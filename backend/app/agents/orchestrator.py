"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Agent Orchestrator  (المنسّق المركزي)                        ║
║                                                                          ║
║  نقطة الدخول الوحيدة لكل الطلبات:                                       ║
║                                                                          ║
║   User Input                                                             ║
║       ↓                                                                  ║
║   RouterChain  →  Single / Multi / Workflow                              ║
║       ↓               ↓           ↓                                     ║
║   Agent.run()   Multi.run()   WorkflowEngine                            ║
║       ↓               ↓           ↓                                     ║
║   AuditTrail ←────────────────────┘                                     ║
║       ↓                                                                  ║
║   OrchestratorResult → API Response                                      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

from app.agents.base import AgentResult, AgentType
from app.agents.agents import HRAgent, FinanceAgent, SalesAgent
from app.agents.router import RouterChain, RoutingStrategy, get_router_chain
from app.agents.workflow import WorkflowEngine, WorkflowEvent, get_workflow_engine
from app.agents.audit_trail import (
    AuditAction, AuditCategory, AuditSeverity,
    AuditRecord, get_audit_trail,
)

log = structlog.get_logger()


@dataclass
class OrchestratorResult:
    """النتيجة النهائية للمستخدم."""
    success:       bool
    response:      str
    agent_used:    str
    strategy:      str
    workflow_id:   str | None = None
    audit_id:      str | None = None
    elapsed_ms:    int = 0
    tokens_used:   int = 0
    requires_followup: bool = False
    followup_message:  str | None = None


class AgentOrchestrator:
    """المنسّق المركزي — يُشغَّل كـ Singleton."""

    def __init__(self):
        self._router   = get_router_chain()
        self._workflow = get_workflow_engine()
        self._audit    = get_audit_trail()

    def _make_agent(self, agent_type: AgentType, user_role: str) -> HRAgent | FinanceAgent | SalesAgent:
        if agent_type == AgentType.HR_AGENT:
            return HRAgent(user_role=user_role)
        elif agent_type == AgentType.FINANCE_AGENT:
            return FinanceAgent(user_role=user_role)
        elif agent_type == AgentType.SALES_AGENT:
            return SalesAgent(user_role=user_role)
        else:
            return HRAgent(user_role=user_role)

    async def process(
        self,
        query:       str,
        user_id:     str,
        user_role:   str,
        employee_id: str | None = None,
        ip_address:  str | None = None,
        session_id:  str | None = None,
    ) -> OrchestratorResult:
        t_start = time.time()

        # ── 1. Router ──────────────────────────────────────
        decision = await self._router.route(query, user_role)

        # سجّل قرار الـ Router
        await self._audit.log_router_decision(
            query=query,
            actor_id=user_id,
            actor_role=user_role,
            decision=decision,
        )

        # رفض — خارج النطاق
        if decision.strategy == RoutingStrategy.REJECT:
            await self._audit.log(AuditRecord(
                action=AuditAction.ACCESS_DENIED,
                category=AuditCategory.AUTHORIZATION,
                severity=AuditSeverity.MEDIUM,
                actor_id=user_id,
                actor_role=user_role,
                description=f"طلب خارج نطاق المنصة: {query[:100]}",
                success=False,
                ip_address=ip_address,
            ))
            return OrchestratorResult(
                success=False,
                response="هذا السؤال خارج نطاق اختصاص منصة ناطقة. "
                         "يمكنني مساعدتك في: الإجازات، الميزانية، المبيعات، وطلبات الشراء.",
                agent_used="router",
                strategy="reject",
                elapsed_ms=int((time.time() - t_start) * 1000),
            )

        # ── 2. Single Agent ────────────────────────────────
        if decision.strategy == RoutingStrategy.SINGLE_AGENT:
            agent  = self._make_agent(decision.primary_agent, user_role)
            result = await agent.run(
                query,
                context={"employee_id": employee_id, "user_role": user_role},
            )
            audit_id = await self._audit.log_agent_query(
                actor_id=user_id,
                actor_role=user_role,
                agent_type=decision.primary_agent.value,
                query=query,
                response=result.response,
                tool_calls=[{"tool": tc.tool_name, "status": tc.status.value} for tc in result.tool_calls],
                tokens_used=result.tokens_used,
                elapsed_ms=result.elapsed_ms,
                ip_address=ip_address,
                session_id=session_id,
                masked_fields=result.masked_fields,
            )
            # إذا نتج Workflow من الوكيل (مثل طلب شراء)
            workflow_id = None
            followup    = None
            for tc in result.tool_calls:
                if isinstance(tc.result, dict) and tc.result.get("type") == "budget_approval_request":
                    ev = await self._workflow.trigger_purchase_approval(
                        item=tc.result.get("item", ""),
                        amount=tc.result.get("amount", 0),
                        justification=tc.result.get("justification", ""),
                        requestor_id=user_id,
                        requestor_role=user_role,
                    )
                    workflow_id = ev.event_id
                    followup    = f"تم إنشاء طلب اعتماد {ev.event_id} وإرساله لوكيل المالية."

            return OrchestratorResult(
                success=result.success,
                response=result.response,
                agent_used=decision.primary_agent.value,
                strategy="single_agent",
                workflow_id=workflow_id,
                audit_id=audit_id,
                elapsed_ms=int((time.time() - t_start) * 1000),
                tokens_used=result.tokens_used,
                requires_followup=bool(workflow_id),
                followup_message=followup,
            )

        # ── 3. Orchestrated Workflow ───────────────────────
        if decision.strategy == RoutingStrategy.ORCHESTRATED:
            wf_type = decision.workflow_type or "unknown"

            if wf_type == "purchase_approval_workflow":
                # تشغيل Sales Agent أولاً لجمع التفاصيل
                sales   = self._make_agent(AgentType.SALES_AGENT, user_role)
                s_result = await sales.run(
                    query,
                    context={"employee_id": employee_id, "extract_po": True},
                )
                # استخراج بيانات PO من نتيجة الوكيل
                po_data  = self._extract_po_from_result(s_result, query)
                ev       = await self._workflow.trigger_purchase_approval(**po_data, requestor_id=user_id, requestor_role=user_role)

                await self._audit.log_agent_decision(
                    agent_type="orchestrator",
                    decision=f"purchase_workflow_triggered:{ev.event_id}",
                    context=query,
                    workflow_id=ev.event_id,
                    severity=AuditSeverity.HIGH,
                )

                return OrchestratorResult(
                    success=True,
                    response=(
                        f"✅ تم تلقّي طلب الشراء وإحالته لوكيل المالية للاعتماد.\n\n"
                        f"رقم الطلب: **{ev.event_id}**\n"
                        f"الحالة: قيد المراجعة\n"
                        f"SLA: 48 ساعة\n\n"
                        f"سيصلك إشعار عند صدور القرار."
                    ),
                    agent_used="sales_agent→finance_agent",
                    strategy="orchestrated_workflow",
                    workflow_id=ev.event_id,
                    elapsed_ms=int((time.time() - t_start) * 1000),
                    tokens_used=s_result.tokens_used,
                    requires_followup=True,
                    followup_message=f"تتبع الطلب: GET /api/agents/workflows/{ev.event_id}",
                )

        # ── 4. Multi-Agent (بدون Workflow) ─────────────────
        agents  = [decision.primary_agent] + decision.secondary_agents
        results = await asyncio.gather(*[
            self._make_agent(at, user_role).run(query) for at in agents
        ])

        combined = "\n\n---\n\n".join(
            f"**{at.value}:**\n{r.response}"
            for at, r in zip(agents, results)
        )
        total_tokens = sum(r.tokens_used for r in results)

        return OrchestratorResult(
            success=True,
            response=combined,
            agent_used=" + ".join(a.value for a in agents),
            strategy="multi_agent",
            elapsed_ms=int((time.time() - t_start) * 1000),
            tokens_used=total_tokens,
        )

    def _extract_po_from_result(self, result, fallback_query: str) -> dict:
        """استخراج بيانات طلب الشراء من نتيجة الوكيل."""
        import re
        text  = result.response + " " + fallback_query
        # محاولة استخراج مبلغ
        amounts = re.findall(r'[\d,]+(?:\.\d+)?\s*(?:ريال|SAR|sar)', text)
        amount  = 0.0
        if amounts:
            amount = float(re.sub(r'[^\d.]', '', amounts[0]))
        # محاولة استخراج العنصر
        item_match = re.search(r'(?:شراء|اشتر[ي]|نشتري|purchase)\s+(.{5,60}?)(?:\.|،|$)', text, re.I)
        item = item_match.group(1).strip() if item_match else fallback_query[:80]

        return {
            "item":          item,
            "amount":        amount or 100_000,
            "justification": fallback_query[:300],
        }


_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
