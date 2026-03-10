"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NATIQA — Router Chain  (موجّه الوكلاء الذكي)                          ║
║                                                                          ║
║  يحدد الوكيل المناسب لكل سؤال بطبقتين:                                 ║
║                                                                          ║
║  الطبقة 1 — Fast Router (بدون LLM، < 5ms):                             ║
║    Keyword Scoring + Pattern Matching                                    ║
║    إذا confidence > 0.75 → يوجّه مباشرةً                               ║
║                                                                          ║
║  الطبقة 2 — LLM Router (إذا كان السؤال غامضاً، < 500ms):              ║
║    LLM يختار الوكيل الأنسب من قائمة مختصرة                              ║
║                                                                          ║
║  Multi-Agent Routing:                                                    ║
║    إذا كان السؤال يحتاج أكثر من وكيل → Orchestrator يتولى              ║
║    مثال: "هل يمكنني الموافقة على طلب الشراء وتقديم إجازة في نفس اليوم؟"║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from app.agents.base import AgentType

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
#  1. Route Decision
# ═══════════════════════════════════════════════════════════

class RoutingStrategy(str, Enum):
    SINGLE_AGENT  = "single_agent"   # وكيل واحد يكفي
    MULTI_AGENT   = "multi_agent"    # يحتاج تنسيق بين وكلاء
    ORCHESTRATED  = "orchestrated"   # workflow كامل عبر Redis
    REJECT        = "reject"         # خارج نطاق النظام


@dataclass
class RouteDecision:
    primary_agent:   AgentType
    strategy:        RoutingStrategy
    confidence:      float                        # 0.0 → 1.0
    secondary_agents: list[AgentType] = field(default_factory=list)
    requires_workflow: bool = False               # يُشغّل Celery task
    workflow_type:   str | None = None            # purchase_approval / leave_cascade ...
    routing_reason:  str = ""
    routing_method:  str = "keyword"              # keyword | llm | pattern
    elapsed_ms:      int = 0


# ═══════════════════════════════════════════════════════════
#  2. Keyword Scoring Engine
# ═══════════════════════════════════════════════════════════

# قواميس الكلمات المفتاحية لكل وكيل — مرتّبة بالأهمية
AGENT_KEYWORDS: dict[AgentType, dict[str, float]] = {

    AgentType.HR_AGENT: {
        # وزن عالٍ — أسئلة حصرية HR
        "إجازة":       3.0, "إجازتي":     3.0, "رصيد الإجازة": 3.5,
        "leave":       3.0, "vacation":   3.0, "sick leave":    3.5,
        "طلب إجازة":   3.5, "أيام الإجازة": 3.0,
        "موظف":        2.0, "employee":   2.0, "الموارد البشرية": 2.5,
        "hr":          2.0, "إجازة سنوية": 3.5, "إجازة مرضية": 3.5,
        "headcount":   2.0, "عدد الموظفين": 2.0,
        "استئذان":     2.5, "غياب":        2.0,
        # وزن منخفض — مشترك
        "القسم":       0.5, "الفريق":     0.5,
    },

    AgentType.FINANCE_AGENT: {
        # وزن عالٍ
        "ميزانية":     3.5, "budget":     3.5, "إنفاق":       3.0,
        "مصروفات":     3.0, "expenses":   3.0, "فاتورة":      3.0,
        "invoice":     3.0, "طلب شراء":   3.0, "purchase order": 3.5,
        "po":          2.5, "مالية":       3.0, "finance":     3.0,
        "cost center": 3.0, "مركز تكلفة": 3.0,
        "ميزانية سنوية": 3.5, "المصروف":  3.0, "المتبقي":     2.5,
        "اعتماد مالي": 3.5, "موافقة مالية": 3.5,
        # وزن متوسط
        "تقرير مالي": 2.5, "الحسابات":   2.0, "sar":         1.5,
        "ريال":        1.5, "مليون":      1.0, "ألف":         0.5,
    },

    AgentType.SALES_AGENT: {
        # وزن عالٍ
        "مبيعات":      3.5, "sales":      3.5, "هدف المبيعات": 3.5,
        "عميل":        3.0, "client":     3.0, "صفقة":         3.0,
        "deal":        3.0, "pipeline":   3.5, "خط المبيعات":  3.5,
        "إيرادات":     3.0, "revenue":    3.0, "فرصة بيعية":   3.0,
        "opportunity": 3.0, "أداء المبيعات": 3.5,
        # وزن متوسط
        "عرض سعر":    2.5, "proposal":   2.5, "تفاوض":        2.0,
        "negotiation": 2.0, "account":   2.0,
    },
}

# أنماط تتطلب Multi-Agent أو Workflow
MULTI_AGENT_PATTERNS = [
    # طلب شراء من المبيعات → موافقة المالية
    (
        re.compile(r'(طلب شراء|purchase order|اشتر[ي]|نحتاج|نشتري).{0,50}(اعتماد|موافق|approve)', re.I),
        RoutingStrategy.ORCHESTRATED,
        "purchase_approval_workflow",
        [AgentType.SALES_AGENT, AgentType.FINANCE_AGENT],
    ),
    # إجازة + تحقق من ميزانية الاستبدال
    (
        re.compile(r'(إجازة|leave).{0,30}(ميزانية|budget|تكلفة)', re.I),
        RoutingStrategy.MULTI_AGENT,
        None,
        [AgentType.HR_AGENT, AgentType.FINANCE_AGENT],
    ),
    # تقرير شامل عن القسم
    (
        re.compile(r'(تقرير شامل|full report|كامل).{0,50}(قسم|department)', re.I),
        RoutingStrategy.MULTI_AGENT,
        None,
        [AgentType.HR_AGENT, AgentType.FINANCE_AGENT, AgentType.SALES_AGENT],
    ),
]

# أنماط خارج النطاق (ترفض)
OUT_OF_SCOPE_PATTERNS = [
    re.compile(r'\b(weather|طقس|اخبار|news|رياضة|sports)\b', re.I),
    re.compile(r'\b(hack|اختر[ق]|bypass|تجاوز الصلاحيات)\b', re.I),
]


# ═══════════════════════════════════════════════════════════
#  3. Fast Router (Layer 1)
# ═══════════════════════════════════════════════════════════

class FastRouter:
    """
    توجيه سريع بدون LLM.
    يعمل في < 5ms ويكفي لـ 85%+ من الأسئلة.
    """

    CONFIDENCE_THRESHOLD = 0.65   # ما دون هذا → يذهب لـ LLM Router

    def route(self, query: str) -> RouteDecision | None:
        """
        يعود بـ RouteDecision إذا كان واثقاً،
        أو None إذا أراد تصعيد للـ LLM Router.
        """
        t_start  = time.time()
        q_lower  = query.lower()

        # ── 1. فحص Out-of-Scope أولاً ─────────────────────
        for pattern in OUT_OF_SCOPE_PATTERNS:
            if pattern.search(query):
                return RouteDecision(
                    primary_agent=AgentType.ROUTER,
                    strategy=RoutingStrategy.REJECT,
                    confidence=0.99,
                    routing_reason="السؤال خارج نطاق منصة ناطقة",
                    routing_method="pattern",
                    elapsed_ms=int((time.time() - t_start) * 1000),
                )

        # ── 2. فحص Multi-Agent Patterns ────────────────────
        for pattern, strategy, wf_type, agents in MULTI_AGENT_PATTERNS:
            if pattern.search(query):
                return RouteDecision(
                    primary_agent=agents[0],
                    strategy=strategy,
                    confidence=0.90,
                    secondary_agents=agents[1:],
                    requires_workflow=(strategy == RoutingStrategy.ORCHESTRATED),
                    workflow_type=wf_type,
                    routing_reason=f"نمط مُعرَّف: {wf_type or 'multi_agent'}",
                    routing_method="pattern",
                    elapsed_ms=int((time.time() - t_start) * 1000),
                )

        # ── 3. Keyword Scoring ─────────────────────────────
        scores: dict[AgentType, float] = {at: 0.0 for at in AGENT_KEYWORDS}

        for agent_type, keywords in AGENT_KEYWORDS.items():
            for kw, weight in keywords.items():
                if kw.lower() in q_lower:
                    scores[agent_type] += weight

        total = sum(scores.values())
        if total == 0:
            return None   # لا يوجد إشارة واضحة → تصعيد للـ LLM

        # تطبيع الـ scores
        norm_scores = {at: s / total for at, s in scores.items()}
        best_agent  = max(norm_scores, key=lambda k: norm_scores[k])
        confidence  = min(norm_scores[best_agent] * 1.4, 1.0)  # تضخيم خفيف

        if confidence < self.CONFIDENCE_THRESHOLD:
            return None   # غير واثق → تصعيد

        return RouteDecision(
            primary_agent=best_agent,
            strategy=RoutingStrategy.SINGLE_AGENT,
            confidence=confidence,
            routing_reason=f"keyword match — best: {best_agent.value} ({confidence:.2f})",
            routing_method="keyword",
            elapsed_ms=int((time.time() - t_start) * 1000),
        )


# ═══════════════════════════════════════════════════════════
#  4. LLM Router (Layer 2)
# ═══════════════════════════════════════════════════════════

ROUTER_SYSTEM_PROMPT = """
أنت موجّه ذكي لنظام وكلاء متخصصين في منصة ناطقة.

الوكلاء المتاحون:
- hr_agent: كل ما يخص الموارد البشرية، الإجازات، بيانات الموظفين
- finance_agent: الميزانية، المصروفات، طلبات الشراء، الفواتير
- sales_agent: أداء المبيعات، العملاء، Pipeline، الفرص البيعية

أجب بـ JSON فقط بهذا الشكل بلا أي نص آخر:
{
  "agent": "hr_agent | finance_agent | sales_agent",
  "confidence": 0.0-1.0,
  "reason": "سبب قصير"
}
"""


class LLMRouter:
    """
    توجيه بمساعدة LLM للأسئلة الغامضة.
    يستهلك tokens لكنه أكثر دقةً للأسئلة المعقدة.
    """

    async def route(self, query: str) -> RouteDecision:
        import json as json_mod
        t_start = time.time()

        try:
            from app.services.llm.factory import get_llm
            llm = get_llm()

            resp = await llm.generate(
                prompt=f"السؤال: {query}\n\nحدد الوكيل المناسب وأجب بـ JSON فقط.",
                system=ROUTER_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=150,
            )

            # تنظيف JSON
            text = resp.content.strip()
            text = re.sub(r'```json|```', '', text).strip()
            data = json_mod.loads(text)

            agent_map = {
                "hr_agent":      AgentType.HR_AGENT,
                "finance_agent": AgentType.FINANCE_AGENT,
                "sales_agent":   AgentType.SALES_AGENT,
            }
            agent_type = agent_map.get(data.get("agent", ""), AgentType.HR_AGENT)

            return RouteDecision(
                primary_agent=agent_type,
                strategy=RoutingStrategy.SINGLE_AGENT,
                confidence=float(data.get("confidence", 0.7)),
                routing_reason=data.get("reason", "LLM routing"),
                routing_method="llm",
                elapsed_ms=int((time.time() - t_start) * 1000),
            )

        except Exception as e:
            log.warning("LLM router failed, defaulting to HR", error=str(e))
            # Fallback: أكثر الوكلاء شيوعاً
            return RouteDecision(
                primary_agent=AgentType.HR_AGENT,
                strategy=RoutingStrategy.SINGLE_AGENT,
                confidence=0.40,
                routing_reason=f"LLM routing failed — fallback: {e}",
                routing_method="fallback",
                elapsed_ms=int((time.time() - t_start) * 1000),
            )


# ═══════════════════════════════════════════════════════════
#  5. Router Chain (الجمع بين الطبقتين)
# ═══════════════════════════════════════════════════════════

class RouterChain:
    """
    السلسلة الكاملة:
    Query → FastRouter → (if ambiguous) → LLMRouter → RouteDecision

    يُسجّل كل توجيه في Audit Trail.
    """

    def __init__(self):
        self._fast_router = FastRouter()
        self._llm_router  = LLMRouter()
        self._stats = {"fast": 0, "llm": 0, "fallback": 0, "total": 0}

    async def route(
        self,
        query:    str,
        user_role: str = "analyst",
        context:  dict | None = None,
    ) -> RouteDecision:
        """
        توجيه السؤال للوكيل المناسب.

        1. FastRouter: < 5ms بدون LLM
        2. LLMRouter: إذا كان السؤال غامضاً
        """
        self._stats["total"] += 1
        t_start = time.time()

        # ── المحاولة الأولى: Fast ──────────────────────────
        decision = self._fast_router.route(query)

        if decision is not None:
            self._stats["fast"] += 1
            log.info(
                "router_fast",
                agent=decision.primary_agent.value,
                confidence=round(decision.confidence, 2),
                strategy=decision.strategy.value,
            )
            return decision

        # ── المحاولة الثانية: LLM ─────────────────────────
        self._stats["llm"] += 1
        decision = await self._llm_router.route(query)
        decision.elapsed_ms = int((time.time() - t_start) * 1000)

        log.info(
            "router_llm",
            agent=decision.primary_agent.value,
            confidence=round(decision.confidence, 2),
            elapsed_ms=decision.elapsed_ms,
        )
        return decision

    @property
    def stats(self) -> dict:
        """إحصاءات التوجيه (مفيد للمراقبة)."""
        t = self._stats["total"] or 1
        return {
            **self._stats,
            "fast_pct": round(self._stats["fast"] / t * 100, 1),
            "llm_pct":  round(self._stats["llm"]  / t * 100, 1),
        }


# Singleton
_router_chain: RouterChain | None = None


def get_router_chain() -> RouterChain:
    global _router_chain
    if _router_chain is None:
        _router_chain = RouterChain()
    return _router_chain
