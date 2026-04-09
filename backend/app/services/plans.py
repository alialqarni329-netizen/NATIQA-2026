"""
app/services/plans.py
══════════════════════════════════════════════════════════════════════
Subscription Plans Engine — Single Source of Truth
Phase 2 Business Logic Layer

Plans:
  FREE       → 3 docs, 5 MB/file, 20 AI queries/day
  PRO        → 100 docs, 50 MB/file, unlimited AI
  ENTERPRISE → Custom limits stored per-user in DB

Usage counters live in two places:
  • Redis  — daily AI query counter (fast, auto-expires at midnight UTC)
  • DB     — document count (accurate, durable)

Rule:  Redis is checked FIRST (fast path).
       DB is the fallback and the source of truth for billing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

import structlog
import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# ── Sentinel for "unlimited" ──────────────────────────────────────────
UNLIMITED = -1


class SubscriptionPlan(str, PyEnum):
    FREE       = "FREE"
    PRO        = "PRO"
    ENTERPRISE = "ENTERPRISE"
    TRIAL      = "TRIAL"


@dataclass(frozen=True)
class PlanLimits:
    """Immutable limit spec for a single plan tier."""
    plan:               SubscriptionPlan
    max_documents:      int            # UNLIMITED = -1
    max_file_size_mb:   int            # per upload
    max_ai_queries_day: int            # UNLIMITED = -1
    display_name:       str
    description:        str
    features:           tuple[str, ...] = field(default_factory=tuple)

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def allows_documents(self, current_count: int) -> bool:
        if self.max_documents == UNLIMITED:
            return True
        return current_count < self.max_documents

    def allows_ai_query(self, queries_today: int) -> bool:
        if self.max_ai_queries_day == UNLIMITED:
            return True
        return queries_today < self.max_ai_queries_day

    def allows_file_size(self, size_bytes: int) -> bool:
        return size_bytes <= self.max_file_size_bytes


# ── Plan registry ─────────────────────────────────────────────────────
PLANS: dict[SubscriptionPlan, PlanLimits] = {
    SubscriptionPlan.FREE: PlanLimits(
        plan               = SubscriptionPlan.FREE,
        max_documents      = 3,
        max_file_size_mb   = 5,
        max_ai_queries_day = 20,
        display_name       = "مجاني",
        description        = "للأفراد والتجربة",
        features           = (
            "3 مستندات كحد أقصى",
            "5 ميغابايت لكل ملف",
            "20 سؤال ذكاء اصطناعي يومياً",
            "مشاريع غير محدودة",
        ),
    ),
    SubscriptionPlan.PRO: PlanLimits(
        plan               = SubscriptionPlan.PRO,
        max_documents      = 100,
        max_file_size_mb   = 50,
        max_ai_queries_day = UNLIMITED,
        display_name       = "احترافي",
        description        = "للفرق والشركات الناشئة",
        features           = (
            "100 مستند",
            "50 ميغابايت لكل ملف",
            "أسئلة ذكاء اصطناعي غير محدودة",
            "أولوية في المعالجة",
            "دعم فني متميز",
        ),
    ),
    SubscriptionPlan.ENTERPRISE: PlanLimits(
        plan               = SubscriptionPlan.ENTERPRISE,
        max_documents      = UNLIMITED,
        max_file_size_mb   = 500,
        max_ai_queries_day = UNLIMITED,
        display_name       = "مؤسسي",
        description        = "للمؤسسات الكبيرة",
        features           = (
            "مستندات غير محدودة",
            "500 ميغابايت لكل ملف",
            "ذكاء اصطناعي غير محدود",
            "حدود مخصصة",
            "مدير حساب مخصص",
            "SLA 99.9%",
        ),
    ),
}


def get_plan(plan: SubscriptionPlan) -> PlanLimits:
    return PLANS[plan]


# ══════════════════════════════════════════════════════════════════════
# GOLDEN TRIAL ENGINE
# ══════════════════════════════════════════════════════════════════════

TRIAL_DURATION_DAYS = 15

# Trial grants identical limits to PRO
TRIAL_PLAN = PlanLimits(
    plan               = SubscriptionPlan.PRO,
    max_documents      = 100,
    max_file_size_mb   = 50,
    max_ai_queries_day = UNLIMITED,
    display_name       = "تجربة ذهبية 15 يوماً",
    description        = "جميع مزايا الخطة الاحترافية مجاناً",
    features           = (
        "100 مستند",
        "50 ميغابايت لكل ملف",
        "أسئلة ذكاء اصطناعي غير محدودة",
        "وصول كامل لمدة 15 يوماً",
    ),
)


def is_in_trial_period(user) -> bool:
    """
    Returns True when the user currently has an active Golden Trial.
    Pure Python — no DB/Redis access. Safe to call everywhere.
    """
    if not getattr(user, "organization", None):
        return False
    if user.organization.trial_starts_at is None or user.organization.trial_ends_at is None:
        return False
    now = datetime.now(timezone.utc)
    # Ensure timezone-aware comparison
    starts = user.organization.trial_starts_at
    ends   = user.organization.trial_ends_at
    if starts.tzinfo is None:
        from datetime import timezone as _tz
        starts = starts.replace(tzinfo=_tz.utc)
    if ends.tzinfo is None:
        from datetime import timezone as _tz
        ends = ends.replace(tzinfo=_tz.utc)
    return starts <= now <= ends


def trial_days_remaining(user) -> int:
    """
    Returns the number of full calendar days left in the trial.
    Returns 0 if the trial is inactive or has expired.
    """
    if not is_in_trial_period(user):
        return 0
    if not getattr(user, "organization", None):
        return 0
    ends = user.organization.trial_ends_at
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=timezone.utc)
    delta = ends - datetime.now(timezone.utc)
    return max(0, delta.days)


def get_effective_plan(user) -> tuple[SubscriptionPlan, PlanLimits]:
    """
    The canonical way to resolve a user's current plan and limits.

    Priority (highest → lowest):
      1. Active Golden Trial  →  PRO limits (TRIAL_PLAN)
      2. Paid subscription    →  user.organization.subscription_plan
      3. Default              →  FREE

    Usage:
        plan_enum, limits = get_effective_plan(user)
        await UsageTracker.check_upload(user_id, size, plan_enum, db, redis,
                                        custom_limits=user.organization.subscription_custom_limits)
    """
    if is_in_trial_period(user):
        return SubscriptionPlan.PRO, TRIAL_PLAN

    if not getattr(user, "organization", None):
        return SubscriptionPlan.FREE, get_plan(SubscriptionPlan.FREE)

    plan_val = user.organization.subscription_plan
    if hasattr(plan_val, "value"):
        plan_str = plan_val.value
    else:
        plan_str = str(plan_val) if plan_val else "FREE"

    plan_enum = SubscriptionPlan(plan_str.upper())
    return plan_enum, get_plan(plan_enum)




# ── Redis key helpers ─────────────────────────────────────────────────
def _ai_counter_key(user_id: str) -> str:
    """Daily AI query counter — auto-expires at midnight UTC."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"usage:ai:{user_id}:{today}"


def _doc_cache_key(user_id: str) -> str:
    """Cached document count — invalidated on upload/delete."""
    return f"usage:docs:{user_id}"


# ── Seconds until midnight UTC (for Redis TTL) ────────────────────────
def _seconds_until_midnight_utc() -> int:
    now  = datetime.now(timezone.utc)
    next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    next_midnight += timedelta(days=1)
    return max(1, int((next_midnight - now).total_seconds()))


# ══════════════════════════════════════════════════════════════════════
# USAGE TRACKER  — the public interface used by routes
# ══════════════════════════════════════════════════════════════════════

class UsageTracker:
    """
    Stateless utility.  All methods are async and accept injected
    db + redis sessions — no hidden globals, fully testable.
    """

    # ── Document count ────────────────────────────────────────────────

    @staticmethod
    async def get_document_count(
        user_id: str,
        db: AsyncSession,
        redis: aioredis.Redis,
    ) -> int:
        """
        Returns the number of documents owned by this user.
        Checks Redis cache first; falls back to DB and re-populates cache.
        Cache TTL: 5 minutes.  Invalidated on upload/delete via
        invalidate_doc_cache().
        """
        cache_key = _doc_cache_key(user_id)
        cached = await redis.get(cache_key)
        if cached is not None:
            return int(cached)

        from app.models.models import Document, Project
        import uuid as _uuid
        count = await db.scalar(
            select(func.count())
            .select_from(Document)
            .join(Project, Document.project_id == Project.id)
            .where(Project.owner_id == _uuid.UUID(user_id))
        )
        count = count or 0
        await redis.setex(cache_key, 300, str(count))   # 5-min cache
        return count

    @staticmethod
    async def invalidate_doc_cache(user_id: str, redis: aioredis.Redis) -> None:
        await redis.delete(_doc_cache_key(user_id))

    # ── AI query counter ──────────────────────────────────────────────

    @staticmethod
    async def get_ai_queries_today(
        user_id: str,
        redis: aioredis.Redis,
    ) -> int:
        val = await redis.get(_ai_counter_key(user_id))
        return int(val) if val else 0

    @staticmethod
    async def increment_ai_counter(
        user_id: str,
        redis: aioredis.Redis,
    ) -> int:
        """Atomically increment and return new count."""
        key = _ai_counter_key(user_id)
        count = await redis.incr(key)
        if count == 1:
            # First query today — set expiry to midnight UTC
            await redis.expire(key, _seconds_until_midnight_utc())
        return count

    # ── Enforcement: upload ───────────────────────────────────────────

    @staticmethod
    async def check_upload(
        user_id: str,
        file_size_bytes: int,
        plan: SubscriptionPlan,
        db: AsyncSession,
        redis: aioredis.Redis,
        custom_limits: Optional[dict] = None,
    ) -> None:
        """
        Raise HTTP 403 if the user has exceeded any upload limit.
        Call this BEFORE saving the file.

        custom_limits (Enterprise): dict with keys
          max_documents, max_file_size_mb (optional overrides)
        """
        from fastapi import HTTPException

        limits = get_plan(plan)

        # ── 1. File size ─────────────────────────────────────────────
        effective_max_mb = (
            custom_limits.get("max_file_size_mb", limits.max_file_size_mb)
            if custom_limits else limits.max_file_size_mb
        )
        max_bytes = effective_max_mb * 1024 * 1024
        if file_size_bytes > max_bytes:
            raise HTTPException(
                status_code=403,
                detail="عذراً، لقد وصلت للحد الأقصى المسموح به في باقتك الحالية. اشترك في الباقة الاحترافية للحصول على مساحة أكبر.",
            )

        # ── 2. Document count ────────────────────────────────────────
        effective_max_docs = (
            custom_limits.get("max_documents", limits.max_documents)
            if custom_limits else limits.max_documents
        )
        if effective_max_docs != UNLIMITED:
            current = await UsageTracker.get_document_count(user_id, db, redis)
            if current >= effective_max_docs:
                raise HTTPException(
                    status_code=403,
                    detail="عذراً، لقد وصلت للحد الأقصى المسموح به في باقتك الحالية. اشترك في الباقة الاحترافية للحصول على مساحة أكبر.",
                )

        log.debug("upload_check_passed",
                  user_id=user_id, plan=plan, size_bytes=file_size_bytes)

    # ── Enforcement: AI query ─────────────────────────────────────────

    @staticmethod
    async def check_ai_query(
        user_id: str,
        plan: SubscriptionPlan,
        redis: aioredis.Redis,
        custom_limits: Optional[dict] = None,
    ) -> None:
        """
        Raise HTTP 403 if the user has exceeded today's AI query limit.
        Call this BEFORE dispatching to the LLM.
        """
        from fastapi import HTTPException

        limits = get_plan(plan)
        effective_max = (
            custom_limits.get("max_ai_queries_day", limits.max_ai_queries_day)
            if custom_limits else limits.max_ai_queries_day
        )
        if effective_max == UNLIMITED:
            return

        today_count = await UsageTracker.get_ai_queries_today(user_id, redis)
        if today_count >= effective_max:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Limit reached. Please upgrade your plan. "
                    f"You have used {today_count}/{effective_max} AI queries today. "
                    f"Limit resets at midnight UTC."
                ),
            )

        log.debug("ai_query_check_passed",
                  user_id=user_id, plan=plan, today=today_count)

    @staticmethod
    async def deduct_tokens(
        organization_id: str,
        tokens: int,
        db: AsyncSession,
    ) -> int:
        """
        Deduct tokens from the organization's balance in real-time.
        Returns the new balance.
        """
        from app.models.models import Organization
        import uuid as _uuid
        from fastapi import HTTPException

        res = await db.execute(
            select(Organization).where(Organization.id == _uuid.UUID(organization_id))
        )
        org = res.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        if org.token_balance < tokens:
             log.warning("Insufficient tokens", org_id=organization_id, balance=org.token_balance, requested=tokens)
             # Option: allow negative or raise error.
             # Requirement says "calculate and deduct", usually implies enforcement.
             raise HTTPException(
                 status_code=403,
                 detail="رصيد التوكنات غير كافٍ. يرجى شحن الرصيد لمتابعة استخدام المحادثة."
             )

        org.token_balance -= tokens
        await db.flush()
        log.info("Tokens deducted", org_id=organization_id, deducted=tokens, new_balance=org.token_balance)
        return org.token_balance

    # ── Usage summary (for /me and admin portal) ──────────────────────

    @staticmethod
    async def get_usage_summary(
        user_id: str,
        plan: SubscriptionPlan,
        db: AsyncSession,
        redis: aioredis.Redis,
        custom_limits: Optional[dict] = None,
    ) -> dict:
        limits       = get_plan(plan)
        doc_count    = await UsageTracker.get_document_count(user_id, db, redis)
        ai_today     = await UsageTracker.get_ai_queries_today(user_id, redis)

        max_docs = (
            custom_limits.get("max_documents", limits.max_documents)
            if custom_limits else limits.max_documents
        )
        max_ai = (
            custom_limits.get("max_ai_queries_day", limits.max_ai_queries_day)
            if custom_limits else limits.max_ai_queries_day
        )

        return {
            "plan":               plan.value,
            "plan_display":       limits.display_name,
            "documents": {
                "used":  doc_count,
                "limit": max_docs if max_docs != UNLIMITED else None,
                "pct":   round(doc_count / max_docs * 100, 1)
                         if max_docs not in (UNLIMITED, 0) else 0,
            },
            "ai_queries_today": {
                "used":  ai_today,
                "limit": max_ai if max_ai != UNLIMITED else None,
                "pct":   round(ai_today / max_ai * 100, 1)
                         if max_ai not in (UNLIMITED, 0) else 0,
            },
            "limits": {
                "max_file_size_mb":   limits.max_file_size_mb,
                "max_documents":      max_docs,
                "max_ai_queries_day": max_ai if max_ai != UNLIMITED else "unlimited",
            },
        }
