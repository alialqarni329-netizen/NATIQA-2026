"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Agent API Endpoints                                           ║
║                                                                          ║
║  POST /api/agents/chat              ← السؤال الطبيعي (الرئيسي)          ║
║  GET  /api/agents/status            ← حالة جميع الوكلاء                 ║
║                                                                          ║
║  GET  /api/agents/workflows         ← قائمة الـ Workflows               ║
║  GET  /api/agents/workflows/{id}    ← حالة Workflow محدد                ║
║                                                                          ║
║  GET  /api/agents/audit             ← سجل التدقيق (بحث)                ║
║  GET  /api/agents/audit/compliance  ← تقرير الامتثال                   ║
║  GET  /api/agents/audit/{id}/verify ← التحقق من سلامة سجل              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
import structlog

from app.core.dependencies import get_current_user
from app.agents.orchestrator import get_orchestrator
from app.agents.workflow import get_workflow_engine, get_event_bus
from app.agents.audit_trail import (
    AuditAction, AuditCategory, AuditSeverity, get_audit_trail,
)
from app.agents.router import get_router_chain

log = structlog.get_logger()
router = APIRouter(prefix="/api/agents", tags=["agents"])


# ─── Schemas ──────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    query:       str = Field(..., min_length=3, max_length=2000)
    employee_id: Optional[str] = None
    verbose:     bool = False


class AgentChatResponse(BaseModel):
    success:          bool
    response:         str
    agent_used:       str
    strategy:         str
    workflow_id:      Optional[str] = None
    audit_id:         Optional[str] = None
    elapsed_ms:       int
    tokens_used:      int
    requires_followup: bool = False
    followup_message:  Optional[str] = None


# ─── 1. Chat — الواجهة الرئيسية ───────────────────────────

@router.post("/chat", response_model=AgentChatResponse,
             summary="استعلام موجَّه للوكيل المناسب تلقائياً")
async def agent_chat(
    body:    AgentChatRequest,
    request: Request,
    current_user = Depends(get_current_user),
):
    """
    نقطة الدخول الذكية — يُحلَّل السؤال ويوجَّه للوكيل الصحيح.

    **أمثلة:**
    - "كم باقي لديّ من إجازة؟" → HR Agent
    - "ما حالة ميزانية قسم IT؟" → Finance Agent
    - "أريد شراء معدات بـ 200,000 ريال" → Sales → Finance Workflow
    """
    orch   = get_orchestrator()
    result = await orch.process(
        query=body.query,
        user_id=str(current_user.id),
        user_role=current_user.role.value,
        employee_id=body.employee_id,
        ip_address=request.client.host if request.client else None,
        session_id=request.headers.get("X-Session-ID"),
    )
    return AgentChatResponse(**result.__dict__)


# ─── 2. Agent Status ──────────────────────────────────────

@router.get("/status", summary="حالة نظام الوكلاء والـ Router")
async def agents_status(current_user = Depends(get_current_user)):
    router_chain = get_router_chain()
    return {
        "agents": [
            {"name": "hr_agent",      "status": "ready", "tools": 5},
            {"name": "finance_agent", "status": "ready", "tools": 5},
            {"name": "sales_agent",   "status": "ready", "tools": 4},
        ],
        "router": {
            "status": "ready",
            "stats":  router_chain.stats,
        },
        "workflow_engine": "ready",
        "audit_trail":     "active",
    }


# ─── 3. Workflows ─────────────────────────────────────────

@router.get("/workflows", summary="قائمة الـ Workflows المعلّقة")
async def list_workflows(
    workflow_type: Optional[str] = None,
    current_user  = Depends(get_current_user),
):
    _require_roles(current_user, {"admin", "super_admin", "hr_analyst"})
    bus = get_event_bus()

    from app.agents.workflow import WorkflowType
    wf_type = None
    if workflow_type:
        try:
            wf_type = WorkflowType(workflow_type)
        except ValueError:
            raise HTTPException(400, f"نوع workflow غير معروف: {workflow_type}")

    pending = await bus.list_pending(wf_type)
    return {
        "count":     len(pending),
        "workflows": [e.to_dict() for e in pending],
    }


@router.get("/workflows/{event_id}", summary="حالة Workflow محدد")
async def get_workflow_status(
    event_id: str,
    current_user = Depends(get_current_user),
):
    engine = get_workflow_engine()
    result = await engine.get_workflow_status(event_id)

    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ─── 4. Audit Trail ──────────────────────────────────────

@router.get("/audit", summary="بحث في سجل التدقيق")
async def search_audit(
    actor_id:  Optional[str] = None,
    action:    Optional[str] = None,
    category:  Optional[str] = None,
    severity:  Optional[str] = None,
    success:   Optional[bool] = None,
    limit:     int = 50,
    current_user = Depends(get_current_user),
):
    """
    بحث متقدم في سجل التدقيق.
    يتطلب دور `admin` أو `super_admin`.
    """
    _require_roles(current_user, {"admin", "super_admin"})
    audit = get_audit_trail()

    action_enum   = AuditAction(action)     if action   else None
    category_enum = AuditCategory(category) if category else None
    severity_enum = AuditSeverity(severity) if severity else None

    records = await audit.search(
        actor_id=actor_id,
        action=action_enum,
        category=category_enum,
        severity=severity_enum,
        success=success,
        limit=min(limit, 500),
    )
    return {"count": len(records), "records": records}


@router.get("/audit/compliance", summary="تقرير الامتثال")
async def compliance_report(current_user = Depends(get_current_user)):
    """
    تقرير امتثال شامل مع إشارات التحذير.
    يتطلب دور `super_admin`.
    """
    _require_roles(current_user, {"super_admin"})
    audit = get_audit_trail()
    return await audit.get_compliance_summary()


@router.get("/audit/{record_id}/verify", summary="التحقق من سلامة سجل")
async def verify_audit_record(
    record_id: str,
    current_user = Depends(get_current_user),
):
    """
    التحقق من أن سجل التدقيق لم يُعدَّل (HMAC verification).
    يتطلب دور `super_admin`.
    """
    _require_roles(current_user, {"super_admin"})
    audit  = get_audit_trail()
    result = await audit.verify_record_integrity(record_id)
    return result


# ─── Helper ──────────────────────────────────────────────

def _require_roles(user, allowed: set[str]) -> None:
    if user.role.value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"دورك '{user.role.value}' لا يملك صلاحية هذه العملية",
        )
