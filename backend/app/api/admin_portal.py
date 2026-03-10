"""
app/api/admin_portal.py
══════════════════════════════════════════════════════════════════════
Admin Portal Backend — Data API + HTML Interface
Mounted at: /admin-portal  (served by FastAPI, no separate process)

Endpoints:
  GET  /admin-portal              → Full HTML dashboard (SPA-style)
  GET  /admin-portal/api/stats    → Platform-wide KPI summary
  GET  /admin-portal/api/users    → Paginated user table
  POST /admin-portal/api/users/{id}/approve  → One-click approve
  POST /admin-portal/api/users/{id}/reject   → One-click reject
  POST /admin-portal/api/users/{id}/plan     → Change subscription plan
  GET  /admin-portal/api/marketing           → Amjad referral stats
  GET  /admin-portal/api/usage/{id}          → Per-user usage detail

All data API routes require:
  • Valid JWT (Authorization: Bearer <token>)
  • role = ADMIN or SUPER_ADMIN

The HTML dashboard calls these APIs via fetch() — the JWT is stored
in sessionStorage and injected on each request.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_redis, log_audit
from app.models.models import (
    ApprovalStatus, AuditAction, AuditLog, Document,
    Message, Project, SubscriptionPlan, User, UserRole,
)
from app.services.plans import UsageTracker, get_plan, PLANS, UNLIMITED

log = structlog.get_logger()

router = APIRouter(prefix="/admin-portal", tags=["Admin Portal"])

# ── Admin guard ───────────────────────────────────────────────────────
async def _require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


# ══════════════════════════════════════════════════════════════════════
# HTML DASHBOARD  (served at GET /admin-portal)
# ══════════════════════════════════════════════════════════════════════

@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard():
    """Serve the single-page admin portal."""
    return HTMLResponse(content=_ADMIN_HTML)


# ══════════════════════════════════════════════════════════════════════
# DATA API
# ══════════════════════════════════════════════════════════════════════

@router.get("/api/stats")
async def platform_stats(
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Platform-wide KPI summary.
    Cached in Redis for 60 seconds — safe for repeated dashboard polls.
    """
    cache_key = "admin:stats"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # User counts
    total_users   = await db.scalar(select(func.count()).select_from(User))
    pending       = await db.scalar(select(func.count()).select_from(User).where(User.approval_status == ApprovalStatus.PENDING))
    approved      = await db.scalar(select(func.count()).select_from(User).where(User.approval_status == ApprovalStatus.APPROVED))
    rejected      = await db.scalar(select(func.count()).select_from(User).where(User.approval_status == ApprovalStatus.REJECTED))

    # Plan breakdown
    plan_rows = await db.execute(
        select(User.subscription_plan, func.count().label("cnt"))
        .group_by(User.subscription_plan)
    )
    plans = {r.subscription_plan: r.cnt for r in plan_rows}

    # Content counts
    total_docs  = await db.scalar(select(func.count()).select_from(Document))
    total_msgs  = await db.scalar(select(func.count()).select_from(Message))

    # New users last 7 days
    from datetime import timedelta
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_7d = await db.scalar(
        select(func.count()).select_from(User).where(User.created_at >= week_ago)
    )

    # Top referrers
    ref_rows = await db.execute(
        select(User.referral_code, func.count(User.referred_by).label("referrals"))
        .where(User.referred_by.isnot(None))
        .group_by(User.referral_code)
        .order_by(text("referrals DESC"))
        .limit(5)
    )

    data = {
        "users": {
            "total":    total_users or 0,
            "pending":  pending or 0,
            "approved": approved or 0,
            "rejected": rejected or 0,
            "new_7d":   new_7d or 0,
        },
        "plans": {
            "free":       plans.get("free", 0),
            "pro":        plans.get("pro", 0),
            "enterprise": plans.get("enterprise", 0),
        },
        "content": {
            "documents": total_docs or 0,
            "messages":  total_msgs or 0,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.setex(cache_key, 60, json.dumps(data))
    return data


@router.get("/api/users")
async def list_users(
    page:     int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    status:   Optional[str] = Query(None),
    plan:     Optional[str] = Query(None),
    search:   Optional[str] = Query(None),
    admin:    User = Depends(_require_admin),
    db:       AsyncSession = Depends(get_db),
):
    """Paginated user list with filters. Used by the admin table."""
    q = select(User).order_by(User.created_at.desc())

    if status:
        try:
            q = q.where(User.approval_status == ApprovalStatus(status))
        except ValueError:
            pass

    if plan:
        try:
            q = q.where(User.subscription_plan == SubscriptionPlan(plan))
        except ValueError:
            pass

    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        q = q.where(
            or_(
                User.email.ilike(like),
                User.full_name.ilike(like),
                User.business_name.ilike(like),
                User.document_number.ilike(like),
            )
        )

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows  = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    users = rows.scalars().all()

    return {
        "total":    total or 0,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, ((total or 0) + per_page - 1) // per_page),
        "users": [_serialize_user(u) for u in users],
    }


class ApproveRejectBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class PlanChangeBody(BaseModel):
    plan:           SubscriptionPlan
    custom_limits:  Optional[dict] = None
    expires_at:     Optional[str]  = None   # ISO-8601


@router.post("/api/users/{user_id}/approve")
async def approve_user(
    user_id: uuid.UUID,
    body:    ApproveRejectBody = ApproveRejectBody(),
    admin:   User = Depends(_require_admin),
    db:      AsyncSession = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    user = await _get_target_user(user_id, db)
    if user.approval_status == ApprovalStatus.APPROVED:
        return {"message": "Already approved.", "user": _serialize_user(user)}

    user.approval_status = ApprovalStatus.APPROVED
    user.is_active        = True
    user.approved_by      = admin.id
    user.approved_at      = datetime.now(timezone.utc)
    user.rejection_reason = None

    await log_audit(db, AuditAction.USER_APPROVE, user_id=admin.id,
                    resource_type="user", resource_id=str(user_id),
                    details={"target_email": user.email})
    await db.commit()
    await db.refresh(user)
    await _bust_stats_cache(redis)

    # ── Send approval notification email ─────────────────────────────
    await _send_approval_email(user.email, user.business_name or user.full_name)

    log.info("user_approved", target=user.email, by=admin.email)
    return {"message": f"User {user.email} approved.", "user": _serialize_user(user)}


@router.post("/api/users/{user_id}/reject")
async def reject_user(
    user_id: uuid.UUID,
    body:    ApproveRejectBody,
    admin:   User = Depends(_require_admin),
    db:      AsyncSession = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    if not body.reason:
        raise HTTPException(status_code=422, detail="Rejection reason is required.")
    user = await _get_target_user(user_id, db)

    user.approval_status  = ApprovalStatus.REJECTED
    user.is_active         = False
    user.approved_by       = admin.id
    user.approved_at       = datetime.now(timezone.utc)
    user.rejection_reason  = body.reason

    await log_audit(db, AuditAction.USER_REJECT, user_id=admin.id,
                    resource_type="user", resource_id=str(user_id),
                    details={"target_email": user.email, "reason": body.reason})
    await db.commit()
    await db.refresh(user)
    await _bust_stats_cache(redis)

    log.info("user_rejected", target=user.email, by=admin.email, reason=body.reason)
    return {"message": f"User {user.email} rejected.", "user": _serialize_user(user)}


@router.post("/api/users/{user_id}/plan")
async def change_plan(
    user_id: uuid.UUID,
    body:    PlanChangeBody,
    admin:   User = Depends(_require_admin),
    db:      AsyncSession = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    user     = await _get_target_user(user_id, db)
    old_plan = user.subscription_plan

    user.subscription_plan          = body.plan
    user.subscription_custom_limits = body.custom_limits
    user.subscription_expires_at    = (
        datetime.fromisoformat(body.expires_at) if body.expires_at else None
    )

    action = (
        AuditAction.PLAN_UPGRADE
        if _plan_rank(body.plan) > _plan_rank(old_plan)
        else AuditAction.PLAN_DOWNGRADE
    )
    await log_audit(db, action, user_id=admin.id,
                    resource_type="user", resource_id=str(user_id),
                    details={
                        "target_email": user.email,
                        "from": old_plan,
                        "to":   body.plan.value,
                        "custom_limits": body.custom_limits,
                    })
    await db.commit()
    await db.refresh(user)
    await _bust_stats_cache(redis)
    # Invalidate doc cache so new limits take effect immediately
    await UsageTracker.invalidate_doc_cache(str(user_id), redis)

    log.info("plan_changed", target=user.email, from_plan=old_plan,
             to_plan=body.plan.value, by=admin.email)
    return {"message": f"Plan changed from {old_plan} → {body.plan.value}.",
            "user": _serialize_user(user)}


@router.get("/api/marketing")
async def marketing_stats(
    admin: User = Depends(_require_admin),
    db:    AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Amjad's referral stats.
    For each referral code: owner info + count of users they referred.
    """
    cache_key = "admin:marketing"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Users who have referred at least one person
    ref_rows = await db.execute(
        select(
            User.referral_code,
            User.full_name,
            User.email,
            User.business_name,
            User.created_at,
            func.count().over(
                partition_by=User.referral_code
            ).label("dummy"),  # placeholder for subquery
        )
        .where(User.referral_code.isnot(None))
        .order_by(User.created_at.desc())
    )

    # Better: direct aggregation
    agg = await db.execute(
        select(
            User.referred_by.label("code"),
            func.count().label("total_referrals"),
            func.sum(
                func.cast(
                    User.subscription_plan == "pro",
                    type_=__import__("sqlalchemy").Integer
                )
            ).label("pro_referrals"),
        )
        .where(User.referred_by.isnot(None))
        .group_by(User.referred_by)
        .order_by(text("total_referrals DESC"))
    )
    referral_counts = {r.code: {"total": r.total_referrals, "pro": r.pro_referrals or 0}
                       for r in agg}

    # Owners of each referral code
    code_owners = await db.execute(
        select(User)
        .where(User.referral_code.in_(list(referral_counts.keys())))
    )
    owners = {u.referral_code: u for u in code_owners.scalars()}

    stats = []
    for code, counts in sorted(referral_counts.items(),
                                 key=lambda x: x[1]["total"], reverse=True):
        owner = owners.get(code)
        stats.append({
            "referral_code":   code,
            "owner_name":      owner.full_name if owner else "—",
            "owner_email":     owner.email if owner else "—",
            "owner_business":  owner.business_name if owner else "—",
            "total_referrals": counts["total"],
            "pro_upgrades":    counts["pro"],
            "conversion_pct":  round(counts["pro"] / counts["total"] * 100, 1)
                               if counts["total"] else 0,
        })

    # Summary totals
    total_referred = sum(s["total_referrals"] for s in stats)
    total_codes    = len(stats)

    data = {
        "summary": {
            "active_referral_codes": total_codes,
            "total_referred_users":  total_referred,
        },
        "leaderboard": stats,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.setex(cache_key, 120, json.dumps(data))
    return data


@router.get("/api/usage/{user_id}")
async def user_usage(
    user_id: uuid.UUID,
    admin:   User = Depends(_require_admin),
    db:      AsyncSession = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    user = await _get_target_user(user_id, db)
    plan = SubscriptionPlan(user.subscription_plan or "free")
    summary = await UsageTracker.get_usage_summary(
        user_id=str(user_id),
        plan=plan,
        db=db,
        redis=redis,
        custom_limits=user.subscription_custom_limits,
    )
    return {"user": _serialize_user(user), "usage": summary}


# ── Helpers ───────────────────────────────────────────────────────────

async def _get_target_user(user_id: uuid.UUID, db: AsyncSession) -> User:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    return u


async def _bust_stats_cache(redis: aioredis.Redis) -> None:
    await redis.delete("admin:stats", "admin:marketing")


def _plan_rank(plan) -> int:
    return {"free": 0, "pro": 1, "enterprise": 2}.get(str(plan), 0)


def _serialize_user(u: User) -> dict:
    return {
        "id":                 str(u.id),
        "email":              u.email,
        "full_name":          u.full_name,
        "business_name":      u.business_name,
        "document_type":      u.document_type.value if u.document_type else None,
        "document_number":    u.document_number,
        "referral_code":      u.referral_code,
        "referred_by":        u.referred_by,
        "role":               u.role.value,
        "is_active":          u.is_active,
        "is_verified":        u.is_verified,
        "approval_status":    u.approval_status.value,
        "rejection_reason":   u.rejection_reason,
        "subscription_plan":  str(u.subscription_plan or "free"),
        "subscription_expires_at": u.subscription_expires_at.isoformat()
                                   if u.subscription_expires_at else None,
        "last_login":         u.last_login.isoformat() if u.last_login else None,
        "created_at":         u.created_at.isoformat(),
    }


async def _send_approval_email(email: str, business_name: str) -> None:
    """Send account-approved notification email via Resend (or log in debug mode)."""
    from app.core.config import settings
    from app.core.emails import get_approval_email_template

    html = get_approval_email_template(business_name)

    if not settings.ENABLE_REAL_EMAIL:
        log.info(
            "DEBUG APPROVAL EMAIL — ENABLE_REAL_EMAIL=False",
            email=email, business_name=business_name,
        )
        return

    if not settings.RESEND_API_KEY:
        log.error("RESEND_API_KEY not set — approval email not sent", email=email)
        return

    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from":    settings.RESEND_FROM_EMAIL,
            "to":      [email],
            "subject": "تمت الموافقة على حسابك في ناطقة ✔️",
            "html":    html,
        })
        log.info("Approval email sent", email=email)
    except Exception as exc:
        log.error("Approval email delivery failed", email=email, error=str(exc))


# ══════════════════════════════════════════════════════════════════════
# ADMIN PORTAL HTML
# Full single-page dashboard served inline — no separate static server
# ══════════════════════════════════════════════════════════════════════

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ناطقة — لوحة الإدارة</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/alpinejs/3.13.5/cdn.min.js" defer></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --ink:       #0A0E1A;
    --ink-2:     #1C2333;
    --ink-3:     #2D3548;
    --surface:   #F4F5F8;
    --surface-2: #EBEDF2;
    --border:    #D6DAE6;
    --accent:    #1A56DB;
    --accent-2:  #1345B7;
    --green:     #0B7A4A;
    --green-bg:  #D1FAE5;
    --amber:     #92400E;
    --amber-bg:  #FEF3C7;
    --red:       #991B1B;
    --red-bg:    #FEE2E2;
    --purple:    #5B21B6;
    --purple-bg: #EDE9FE;
    --gold:      #B45309;
    --gold-bg:   #FEF3C7;
    --mono:      'IBM Plex Mono', monospace;
    --sans:      'IBM Plex Sans Arabic', sans-serif;
    --radius:    10px;
    --shadow:    0 1px 3px rgba(0,0,0,.08), 0 4px 12px rgba(0,0,0,.05);
    --shadow-lg: 0 4px 20px rgba(0,0,0,.12);
    --transition: 150ms cubic-bezier(.4,0,.2,1);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--sans);
    background: var(--surface);
    color: var(--ink);
    min-height: 100vh;
    font-size: 14px;
    line-height: 1.6;
  }

  /* ── Layout ── */
  .shell { display: flex; min-height: 100vh; }

  .sidebar {
    width: 240px;
    flex-shrink: 0;
    background: var(--ink);
    color: #CBD5E1;
    display: flex;
    flex-direction: column;
    position: fixed;
    top: 0; right: 0; bottom: 0;
    overflow-y: auto;
    z-index: 100;
  }

  .sidebar-logo {
    padding: 24px 20px 20px;
    border-bottom: 1px solid var(--ink-3);
    display: flex; align-items: center; gap: 10px;
  }

  .sidebar-logo .wordmark {
    font-size: 18px; font-weight: 700; color: #FFF; letter-spacing: -.5px;
  }
  .sidebar-logo .badge {
    font-size: 10px; font-weight: 600; color: var(--accent);
    background: rgba(26,86,219,.18); border-radius: 4px; padding: 2px 6px;
    font-family: var(--mono);
  }

  .nav { padding: 12px 0; flex: 1; }
  .nav-section { padding: 16px 20px 4px; font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px; color: #475569; }

  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 20px; cursor: pointer;
    color: #94A3B8; font-size: 13.5px; font-weight: 500;
    transition: all var(--transition); border-right: 3px solid transparent;
    text-decoration: none;
  }
  .nav-item:hover { background: var(--ink-2); color: #E2E8F0; }
  .nav-item.active { background: var(--ink-2); color: #FFF;
    border-right-color: var(--accent); }
  .nav-item .icon { width: 18px; height: 18px; opacity: .7; }
  .nav-item.active .icon { opacity: 1; }

  .sidebar-footer {
    padding: 16px 20px; border-top: 1px solid var(--ink-3);
    font-size: 12px; color: #475569;
  }
  .sidebar-footer .admin-name { color: #CBD5E1; font-weight: 600; }

  /* ── Main area ── */
  .main { margin-right: 240px; min-height: 100vh; display: flex; flex-direction: column; }

  .topbar {
    background: #FFF; border-bottom: 1px solid var(--border);
    padding: 0 28px; height: 60px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 50;
    box-shadow: 0 1px 0 var(--border);
  }

  .topbar-title { font-size: 16px; font-weight: 700; color: var(--ink); }
  .topbar-subtitle { font-size: 12px; color: #64748B; }

  .topbar-right { display: flex; align-items: center; gap: 12px; }

  .content { padding: 28px; flex: 1; }

  /* ── Login screen ── */
  .login-screen {
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, var(--ink) 0%, var(--ink-3) 100%);
  }
  .login-card {
    background: #FFF; border-radius: 16px; padding: 40px;
    width: 380px; box-shadow: var(--shadow-lg);
  }
  .login-card h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
  .login-card p  { color: #64748B; margin-bottom: 28px; font-size: 13px; }

  /* ── KPI cards ── */
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }

  .kpi-card {
    background: #FFF; border-radius: var(--radius); padding: 20px;
    box-shadow: var(--shadow); border: 1px solid var(--border);
    display: flex; flex-direction: column; gap: 8px;
  }
  .kpi-label { font-size: 12px; font-weight: 600; color: #64748B;
    text-transform: uppercase; letter-spacing: .5px; }
  .kpi-value { font-size: 28px; font-weight: 700; color: var(--ink);
    font-family: var(--mono); line-height: 1; }
  .kpi-sub   { font-size: 12px; color: #64748B; }
  .kpi-icon  { width: 36px; height: 36px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center; }

  /* ── Section cards ── */
  .card {
    background: #FFF; border-radius: var(--radius);
    box-shadow: var(--shadow); border: 1px solid var(--border);
    overflow: hidden; margin-bottom: 20px;
  }
  .card-header {
    padding: 16px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .card-title { font-size: 14px; font-weight: 700; color: var(--ink); }
  .card-body  { padding: 20px; }

  /* ── Table ── */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    padding: 10px 14px; text-align: right;
    font-size: 11px; font-weight: 700; color: #64748B;
    text-transform: uppercase; letter-spacing: .6px;
    background: var(--surface); border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tbody tr { border-bottom: 1px solid var(--surface-2); transition: background var(--transition); }
  tbody tr:hover { background: var(--surface); }
  tbody tr:last-child { border-bottom: none; }
  tbody td { padding: 12px 14px; font-size: 13px; vertical-align: middle; }

  /* ── Badges ── */
  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 9px; border-radius: 99px; font-size: 11px; font-weight: 600;
    white-space: nowrap;
  }
  .badge-pending    { background: var(--amber-bg);  color: var(--amber); }
  .badge-approved   { background: var(--green-bg);  color: var(--green); }
  .badge-rejected   { background: var(--red-bg);    color: var(--red); }
  .badge-free       { background: var(--surface-2); color: #475569; }
  .badge-pro        { background: var(--purple-bg); color: var(--purple); }
  .badge-enterprise { background: var(--gold-bg);   color: var(--gold); }
  .badge-cr         { background: #DBEAFE; color: #1E40AF; }
  .badge-freelance  { background: #FCE7F3; color: #9D174D; }

  /* ── Buttons ── */
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 7px; font-size: 12.5px; font-weight: 600;
    cursor: pointer; border: 1px solid transparent; transition: all var(--transition);
    font-family: var(--sans); white-space: nowrap;
  }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .btn-primary   { background: var(--accent);  color: #FFF; border-color: var(--accent); }
  .btn-primary:hover:not(:disabled)  { background: var(--accent-2); }
  .btn-success   { background: var(--green);   color: #FFF; }
  .btn-success:hover:not(:disabled)  { background: #065F46; }
  .btn-danger    { background: var(--red);     color: #FFF; }
  .btn-danger:hover:not(:disabled)   { background: #7F1D1D; }
  .btn-ghost     { background: transparent; color: #475569; border-color: var(--border); }
  .btn-ghost:hover:not(:disabled)    { background: var(--surface); }
  .btn-sm        { padding: 4px 10px; font-size: 11.5px; border-radius: 5px; }
  .btn-xs        { padding: 3px 8px;  font-size: 11px;   border-radius: 4px; }

  /* ── Forms ── */
  .form-group { margin-bottom: 16px; }
  label { display: block; font-size: 12.5px; font-weight: 600; color: #374151; margin-bottom: 6px; }
  input, select, textarea {
    width: 100%; padding: 9px 12px; border: 1px solid var(--border);
    border-radius: 7px; font-size: 13.5px; font-family: var(--sans);
    background: #FFF; color: var(--ink); transition: border-color var(--transition);
    outline: none;
  }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(26,86,219,.1); }
  textarea { resize: vertical; min-height: 80px; }

  /* ── Filter bar ── */
  .filter-bar {
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 14px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .filter-bar input, .filter-bar select { max-width: 180px; }
  .filter-bar input[type=search] { max-width: 240px; }

  /* ── Pagination ── */
  .pagination { display: flex; gap: 4px; align-items: center; padding: 12px 16px;
    border-top: 1px solid var(--border); justify-content: flex-end; }
  .page-btn {
    min-width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
    border: 1px solid var(--border); border-radius: 6px; font-size: 12px; font-weight: 600;
    cursor: pointer; background: #FFF; transition: all var(--transition);
  }
  .page-btn:hover { background: var(--surface); }
  .page-btn.active { background: var(--accent); color: #FFF; border-color: var(--accent); }
  .page-info { font-size: 12px; color: #64748B; margin-left: 12px; }

  /* ── Modal ── */
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,.45);
    display: flex; align-items: center; justify-content: center;
    z-index: 200; padding: 16px;
  }
  .modal {
    background: #FFF; border-radius: 14px; width: 440px; max-width: 100%;
    box-shadow: var(--shadow-lg); overflow: hidden;
  }
  .modal-header {
    padding: 18px 22px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .modal-title { font-size: 15px; font-weight: 700; }
  .modal-body  { padding: 22px; }
  .modal-footer { padding: 16px 22px; border-top: 1px solid var(--border);
    display: flex; gap: 8px; justify-content: flex-end; }

  /* ── Toast ── */
  .toast-stack { position: fixed; bottom: 24px; left: 24px; z-index: 300;
    display: flex; flex-direction: column; gap: 8px; }
  .toast {
    padding: 12px 16px; border-radius: 8px; font-size: 13px; font-weight: 500;
    box-shadow: var(--shadow-lg); display: flex; align-items: center; gap: 8px;
    animation: slideIn .2s ease-out; min-width: 260px;
  }
  .toast-ok  { background: var(--green-bg);  color: var(--green); border: 1px solid #6EE7B7; }
  .toast-err { background: var(--red-bg);    color: var(--red);   border: 1px solid #FCA5A5; }
  @keyframes slideIn { from { transform: translateX(-20px); opacity: 0; } }

  /* ── Referral leaderboard ── */
  .lb-row {
    display: flex; align-items: center; padding: 12px 16px;
    border-bottom: 1px solid var(--surface-2); gap: 14px;
  }
  .lb-rank { font-family: var(--mono); font-weight: 700; font-size: 14px;
    width: 28px; color: #94A3B8; }
  .lb-rank.gold   { color: #B45309; }
  .lb-rank.silver { color: #64748B; }
  .lb-rank.bronze { color: #92400E; }
  .lb-avatar {
    width: 36px; height: 36px; border-radius: 50%; background: var(--accent);
    color: #FFF; display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; flex-shrink: 0;
  }
  .lb-info { flex: 1; min-width: 0; }
  .lb-name { font-weight: 600; font-size: 13.5px; }
  .lb-code { font-family: var(--mono); font-size: 11px; color: #64748B; }
  .lb-count { text-align: left; }
  .lb-count .num  { font-family: var(--mono); font-weight: 700; font-size: 18px; color: var(--ink); }
  .lb-count .sub  { font-size: 11px; color: #64748B; }
  .lb-bar { width: 100px; height: 6px; background: var(--surface-2); border-radius: 99px; overflow: hidden; }
  .lb-bar-fill { height: 100%; background: var(--accent); border-radius: 99px; transition: width .5s ease; }

  /* ── Plan selector ── */
  .plan-options { display: flex; gap: 10px; margin: 12px 0; }
  .plan-opt {
    flex: 1; padding: 12px; border: 2px solid var(--border); border-radius: 8px;
    cursor: pointer; text-align: center; transition: all var(--transition);
  }
  .plan-opt.selected { border-color: var(--accent); background: #EFF6FF; }
  .plan-opt .plan-name { font-weight: 700; font-size: 13px; }
  .plan-opt .plan-price { font-size: 11px; color: #64748B; margin-top: 3px; }

  /* ── Misc ── */
  .empty { text-align: center; padding: 48px; color: #94A3B8; }
  .empty svg { margin-bottom: 12px; opacity: .3; }
  .empty p { font-size: 14px; }
  .divider { height: 1px; background: var(--border); margin: 16px 0; }
  .text-mono { font-family: var(--mono); }
  .truncate { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .spinner { display: inline-block; width: 18px; height: 18px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin .7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-overlay {
    display: flex; align-items: center; justify-content: center; min-height: 160px;
    flex-direction: column; gap: 12px; color: #64748B; font-size: 13px;
  }

  /* ── Responsive ── */
  @media (max-width: 1024px) {
    .kpi-grid { grid-template-columns: repeat(2,1fr); }
  }
  @media (max-width: 768px) {
    .sidebar { transform: translateX(100%); }
    .main { margin-right: 0; }
  }
</style>
</head>
<body>

<div x-data="adminApp()" x-init="init()">

  <!-- ── Login Screen ─────────────────────────────────────────── -->
  <div x-show="!authed" class="login-screen" x-cloak style="display:flex">
    <div class="login-card">
      <h1>ناطقة</h1>
      <p>لوحة تحكم المسؤولين — أدخل بيانات الدخول</p>
      <div class="form-group">
        <label>البريد الإلكتروني</label>
        <input type="email" x-model="creds.email" @keyup.enter="login()"
               placeholder="admin@company.com" autocomplete="email">
      </div>
      <div class="form-group">
        <label>كلمة المرور</label>
        <input type="password" x-model="creds.password" @keyup.enter="login()"
               placeholder="••••••••" autocomplete="current-password">
      </div>
      <div x-show="loginErr" class="badge badge-rejected" style="margin-bottom:12px;border-radius:6px;padding:8px 12px;font-size:12px" x-text="loginErr"></div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;padding:11px"
              @click="login()" :disabled="loginLoading">
        <span x-show="loginLoading" class="spinner" style="width:16px;height:16px;border-color:#fff3;border-top-color:#fff"></span>
        <span x-show="!loginLoading">دخول</span>
      </button>
    </div>
  </div>

  <!-- ── App Shell ─────────────────────────────────────────────── -->
  <div x-show="authed" class="shell" x-cloak>

    <!-- Sidebar -->
    <nav class="sidebar">
      <div class="sidebar-logo">
        <div>
          <div class="wordmark">ناطقة</div>
          <div class="badge">ADMIN</div>
        </div>
      </div>
      <div class="nav">
        <div class="nav-section">الرئيسية</div>
        <a class="nav-item" :class="{active: tab==='dashboard'}" @click="tab='dashboard'; loadStats()">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>
          لوحة البيانات
        </a>
        <div class="nav-section">إدارة</div>
        <a class="nav-item" :class="{active: tab==='users'}" @click="tab='users'; loadUsers()">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
          المستخدمون
          <span x-show="stats.users && stats.users.pending > 0"
                class="badge badge-pending"
                style="margin-right:auto;font-size:10px;padding:2px 7px"
                x-text="stats.users.pending + ' معلّق'"></span>
        </a>
        <a class="nav-item" :class="{active: tab==='marketing'}" @click="tab='marketing'; loadMarketing()">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z"/></svg>
          إحصائيات التسويق
        </a>
      </div>
      <div class="sidebar-footer">
        <div class="admin-name" x-text="currentUser.full_name || '—'"></div>
        <div x-text="currentUser.email || ''"></div>
      </div>
    </nav>

    <!-- Main -->
    <div class="main">

      <!-- Topbar -->
      <div class="topbar">
        <div>
          <div class="topbar-title" x-text="tabTitles[tab] || 'الإدارة'"></div>
          <div class="topbar-subtitle" x-text="new Date().toLocaleDateString('ar-SA', {weekday:'long', year:'numeric', month:'long', day:'numeric'})"></div>
        </div>
        <div class="topbar-right">
          <button class="btn btn-ghost btn-sm" @click="refreshCurrent()">
            <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            تحديث
          </button>
          <button class="btn btn-ghost btn-sm" @click="logout()">خروج</button>
        </div>
      </div>

      <!-- ── Golden Trial Banner ─────────────────────────────── -->
      <!-- Shown for all users whose trial.active === true -->
      <div x-show="currentUser.trial && currentUser.trial.active && !trialBannerDismissed"
           x-transition:enter="transition ease-out duration-300"
           x-transition:enter-start="opacity-0 -translate-y-2"
           x-transition:enter-end="opacity-100 translate-y-0"
           style="background:linear-gradient(90deg,#92400e,#d97706,#f59e0b,#d97706,#92400e);
                  background-size:200% auto;
                  animation:goldShimmer 4s linear infinite;
                  padding:10px 24px;
                  display:flex;
                  align-items:center;
                  justify-content:center;
                  gap:12px;
                  font-size:13px;
                  font-weight:600;
                  color:#fff;
                  position:relative;
                  box-shadow:0 2px 8px rgba(180,83,9,.35);">
        <span style="font-size:16px;">⭐</span>
        <span>
          أنت في التجربة الذهبية المجانية —
          <span :style="'color:' + (currentUser.trial.days_remaining <= 3 ? '#fca5a5' : '#fef9c3')"
                x-text="currentUser.trial.days_remaining + ' يوم متبقٍ'"></span>.
          <a href="#" style="color:#fef08a; text-decoration:underline; margin-right:8px;">
            ترقّ لـ Pro للاحتفاظ بمزاياك الآن ←
          </a>
        </span>
        <button @click="trialBannerDismissed = true; sessionStorage.setItem('trialDismissed','1')"
                style="position:absolute;left:16px;background:transparent;border:none;color:#fff;cursor:pointer;font-size:18px;line-height:1;padding:2px 6px;border-radius:4px;opacity:.75;"
                title="إخفاء">×</button>
      </div>
      <style>
        @keyframes goldShimmer {
          0%   { background-position: 0    center; }
          100% { background-position: 200% center; }
        }
      </style>

      <!-- ── Content ────────────────────────────────────────── -->
      <div class="content">

        <!-- ── Dashboard ── -->
        <div x-show="tab==='dashboard'">
          <div class="kpi-grid">
            <div class="kpi-card">
              <div style="display:flex;justify-content:space-between">
                <div class="kpi-label">إجمالي المستخدمين</div>
                <div class="kpi-icon" style="background:#EFF6FF">
                  <svg width="18" height="18" fill="none" stroke="#1A56DB" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
                </div>
              </div>
              <div class="kpi-value" x-text="stats.users ? stats.users.total : '—'"></div>
              <div class="kpi-sub"><span x-text="stats.users ? stats.users.new_7d : 0"></span> جديد هذا الأسبوع</div>
            </div>
            <div class="kpi-card">
              <div style="display:flex;justify-content:space-between">
                <div class="kpi-label">بانتظار الموافقة</div>
                <div class="kpi-icon" style="background:#FEF3C7">
                  <svg width="18" height="18" fill="none" stroke="#92400E" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                </div>
              </div>
              <div class="kpi-value" style="color:#92400E" x-text="stats.users ? stats.users.pending : '—'"></div>
              <div class="kpi-sub" style="cursor:pointer;color:#1A56DB" @click="tab='users'; statusFilter='pending'; loadUsers()">عرض الطلبات ←</div>
            </div>
            <div class="kpi-card">
              <div style="display:flex;justify-content:space-between">
                <div class="kpi-label">مستخدمو Pro</div>
                <div class="kpi-icon" style="background:#EDE9FE">
                  <svg width="18" height="18" fill="none" stroke="#5B21B6" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"/></svg>
                </div>
              </div>
              <div class="kpi-value" style="color:#5B21B6" x-text="stats.plans ? stats.plans.pro : '—'"></div>
              <div class="kpi-sub">من أصل <span x-text="stats.users ? stats.users.approved : 0"></span> معتمد</div>
            </div>
            <div class="kpi-card">
              <div style="display:flex;justify-content:space-between">
                <div class="kpi-label">المستندات</div>
                <div class="kpi-icon" style="background:#D1FAE5">
                  <svg width="18" height="18" fill="none" stroke="#0B7A4A" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                </div>
              </div>
              <div class="kpi-value" style="color:#0B7A4A" x-text="stats.content ? stats.content.documents : '—'"></div>
              <div class="kpi-sub"><span x-text="stats.content ? stats.content.messages : 0"></span> رسالة ذكاء اصطناعي</div>
            </div>
          </div>

          <!-- Plan distribution -->
          <div class="card">
            <div class="card-header">
              <div class="card-title">توزيع خطط الاشتراك</div>
            </div>
            <div class="card-body" style="display:flex;gap:24px;flex-wrap:wrap">
              <template x-for="[k,label,cls] in [['free','مجاني','badge-free'],['pro','احترافي','badge-pro'],['enterprise','مؤسسي','badge-enterprise']]">
                <div style="flex:1;min-width:140px;text-align:center;padding:16px;background:var(--surface);border-radius:8px">
                  <div class="kpi-value" x-text="stats.plans ? (stats.plans[k] || 0) : '—'"></div>
                  <div style="margin-top:6px"><span class="badge" :class="cls" x-text="label"></span></div>
                </div>
              </template>
            </div>
          </div>
        </div>

        <!-- ── Users Tab ── -->
        <div x-show="tab==='users'">
          <div class="card">
            <div class="filter-bar">
              <input type="search" placeholder="بحث بالاسم أو البريد أو رقم الوثيقة..."
                     x-model="search" @input.debounce.400ms="loadUsers()" style="max-width:260px">
              <select x-model="statusFilter" @change="loadUsers()">
                <option value="">كل الحالات</option>
                <option value="pending">معلّق</option>
                <option value="approved">معتمد</option>
                <option value="rejected">مرفوض</option>
              </select>
              <select x-model="planFilter" @change="loadUsers()">
                <option value="">كل الخطط</option>
                <option value="free">مجاني</option>
                <option value="pro">احترافي</option>
                <option value="enterprise">مؤسسي</option>
              </select>
              <div style="margin-right:auto;font-size:12px;color:#64748B">
                <span x-text="usersMeta.total || 0"></span> مستخدم
              </div>
            </div>

            <div class="table-wrap">
              <div x-show="usersLoading" class="loading-overlay">
                <div class="spinner" style="width:28px;height:28px"></div>
                <span>جار التحميل...</span>
              </div>
              <table x-show="!usersLoading">
                <thead>
                  <tr>
                    <th>المستخدم</th>
                    <th>المنشأة</th>
                    <th>وثيقة التسجيل</th>
                    <th>الإحالة</th>
                    <th>الخطة</th>
                    <th>الحالة</th>
                    <th>تاريخ التسجيل</th>
                    <th>إجراءات</th>
                  </tr>
                </thead>
                <tbody>
                  <template x-for="u in users" :key="u.id">
                    <tr>
                      <td>
                        <div style="font-weight:600" x-text="u.full_name"></div>
                        <div style="font-size:11.5px;color:#64748B" x-text="u.email"></div>
                      </td>
                      <td class="truncate" x-text="u.business_name || '—'"></td>
                      <td>
                        <div x-show="u.document_type">
                          <span class="badge" :class="'badge-' + u.document_type" x-text="u.document_type === 'cr' ? 'سجل تجاري' : 'عمل حر'"></span>
                          <div class="text-mono" style="font-size:11px;color:#475569;margin-top:4px" x-text="u.document_number || ''"></div>
                        </div>
                        <span x-show="!u.document_type" style="color:#CBD5E1">—</span>
                      </td>
                      <td>
                        <div x-show="u.referred_by">
                          <div style="font-size:11px;color:#64748B">جاء عبر</div>
                          <div class="text-mono" style="font-size:11.5px;font-weight:600" x-text="u.referred_by"></div>
                        </div>
                        <span x-show="!u.referred_by" style="color:#CBD5E1">—</span>
                      </td>
                      <td>
                        <span class="badge" :class="'badge-' + (u.subscription_plan || 'free')"
                              x-text="{'free':'مجاني','pro':'احترافي','enterprise':'مؤسسي'}[u.subscription_plan] || u.subscription_plan">
                        </span>
                      </td>
                      <td>
                        <span class="badge" :class="'badge-' + u.approval_status"
                              x-text="{'pending':'معلّق','approved':'معتمد','rejected':'مرفوض'}[u.approval_status] || u.approval_status">
                        </span>
                      </td>
                      <td style="font-size:12px;color:#64748B">
                        <span x-text="new Date(u.created_at).toLocaleDateString('ar-SA')"></span>
                      </td>
                      <td>
                        <div style="display:flex;gap:5px;flex-wrap:wrap">
                          <button x-show="u.approval_status !== 'approved'"
                                  class="btn btn-success btn-xs" @click="openApprove(u)">موافقة</button>
                          <button x-show="u.approval_status !== 'rejected'"
                                  class="btn btn-danger btn-xs" @click="openReject(u)">رفض</button>
                          <button class="btn btn-ghost btn-xs" @click="openPlan(u)">الخطة</button>
                        </div>
                      </td>
                    </tr>
                  </template>
                  <tr x-show="!usersLoading && users.length === 0">
                    <td colspan="8" class="empty"><p>لا يوجد مستخدمون بهذا الفلتر</p></td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Pagination -->
            <div class="pagination" x-show="usersMeta.pages > 1">
              <button class="page-btn" @click="usersPage--; loadUsers()" :disabled="usersPage <= 1">‹</button>
              <template x-for="p in Array.from({length: Math.min(7, usersMeta.pages)}, (_,i) => i + Math.max(1, usersPage-3))" :key="p">
                <button class="page-btn" :class="{active: p===usersPage}" @click="usersPage=p; loadUsers()" x-text="p"></button>
              </template>
              <button class="page-btn" @click="usersPage++; loadUsers()" :disabled="usersPage >= usersMeta.pages">›</button>
              <span class="page-info">صفحة <span x-text="usersPage"></span> من <span x-text="usersMeta.pages"></span></span>
            </div>
          </div>
        </div>

        <!-- ── Marketing Tab ── -->
        <div x-show="tab==='marketing'">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
            <div class="kpi-card">
              <div class="kpi-label">رموز الإحالة النشطة</div>
              <div class="kpi-value" x-text="marketing.summary ? marketing.summary.active_referral_codes : '—'"></div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">إجمالي المستخدمين المُحالين</div>
              <div class="kpi-value" x-text="marketing.summary ? marketing.summary.total_referred_users : '—'"></div>
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div class="card-title">لوحة صدارة الإحالات — أمجد</div>
              <div style="font-size:12px;color:#64748B">مرتّب حسب إجمالي الإحالات</div>
            </div>
            <div x-show="marketingLoading" class="loading-overlay">
              <div class="spinner" style="width:28px;height:28px"></div>
            </div>
            <div x-show="!marketingLoading">
              <template x-for="(item, idx) in (marketing.leaderboard || [])" :key="item.referral_code">
                <div class="lb-row">
                  <div class="lb-rank" :class="idx===0?'gold':idx===1?'silver':idx===2?'bronze':''" x-text="'#'+(idx+1)"></div>
                  <div class="lb-avatar" x-text="(item.owner_name||'?')[0]"></div>
                  <div class="lb-info">
                    <div class="lb-name" x-text="item.owner_name"></div>
                    <div style="display:flex;gap:8px;align-items:center">
                      <span class="lb-code" x-text="item.referral_code"></span>
                      <span style="font-size:11px;color:#94A3B8" x-text="item.owner_email"></span>
                    </div>
                  </div>
                  <div style="display:flex;gap:16px;align-items:center">
                    <div style="text-align:center">
                      <div style="font-family:var(--mono);font-weight:700;font-size:20px" x-text="item.total_referrals"></div>
                      <div style="font-size:11px;color:#64748B">إجمالي</div>
                    </div>
                    <div style="text-align:center">
                      <div style="font-family:var(--mono);font-weight:700;font-size:20px;color:#5B21B6" x-text="item.pro_upgrades"></div>
                      <div style="font-size:11px;color:#64748B">Pro</div>
                    </div>
                    <div style="text-align:center;min-width:60px">
                      <div style="font-family:var(--mono);font-weight:700;font-size:16px;color:#0B7A4A" x-text="item.conversion_pct + '%'"></div>
                      <div style="font-size:11px;color:#64748B">تحويل</div>
                    </div>
                    <div class="lb-bar" x-show="(marketing.leaderboard||[]).length > 0">
                      <div class="lb-bar-fill"
                           :style="'width:' + Math.round(item.total_referrals / Math.max(...(marketing.leaderboard||[{total_referrals:1}]).map(x=>x.total_referrals)) * 100) + '%'">
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <div x-show="!marketingLoading && (marketing.leaderboard||[]).length === 0"
                   class="empty"><p>لا توجد بيانات إحالة بعد</p></div>
            </div>
          </div>
        </div>

      </div><!-- /content -->
    </div><!-- /main -->
  </div><!-- /shell -->

  <!-- ── Approve Modal ── -->
  <div class="modal-backdrop" x-show="modal.approve" x-cloak @click.self="modal.approve=false">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title">الموافقة على المستخدم</div>
        <button class="btn btn-ghost btn-xs" @click="modal.approve=false">✕</button>
      </div>
      <div class="modal-body">
        <p>هل تريد الموافقة على حساب <strong x-text="selectedUser.email"></strong>؟</p>
        <p style="font-size:12px;color:#64748B;margin-top:6px">
          سيتمكن المستخدم من تسجيل الدخول والوصول إلى المنصة.
        </p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" @click="modal.approve=false">إلغاء</button>
        <button class="btn btn-success" @click="doApprove()" :disabled="actionLoading">
          <span x-show="actionLoading" class="spinner" style="width:14px;height:14px;border-color:#fff3;border-top-color:#fff"></span>
          موافقة
        </button>
      </div>
    </div>
  </div>

  <!-- ── Reject Modal ── -->
  <div class="modal-backdrop" x-show="modal.reject" x-cloak @click.self="modal.reject=false">
    <div class="modal">
      <div class="modal-header">
        <div class="modal-title">رفض المستخدم</div>
        <button class="btn btn-ghost btn-xs" @click="modal.reject=false">✕</button>
      </div>
      <div class="modal-body">
        <p>رفض حساب <strong x-text="selectedUser.email"></strong></p>
        <div class="form-group" style="margin-top:14px">
          <label>سبب الرفض <span style="color:red">*</span></label>
          <textarea x-model="rejectReason" placeholder="مثال: وثيقة منتهية الصلاحية، بيانات غير مكتملة..."></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" @click="modal.reject=false">إلغاء</button>
        <button class="btn btn-danger" @click="doReject()" :disabled="actionLoading || !rejectReason.trim()">
          رفض
        </button>
      </div>
    </div>
  </div>

  <!-- ── Plan Modal ── -->
  <div class="modal-backdrop" x-show="modal.plan" x-cloak @click.self="modal.plan=false">
    <div class="modal" style="width:500px">
      <div class="modal-header">
        <div class="modal-title">تغيير خطة الاشتراك</div>
        <button class="btn btn-ghost btn-xs" @click="modal.plan=false">✕</button>
      </div>
      <div class="modal-body">
        <p style="font-size:13px;color:#475569;margin-bottom:14px">
          المستخدم: <strong x-text="selectedUser.email"></strong>
        </p>
        <div class="plan-options">
          <template x-for="[val, label, desc] in [['free','مجاني','3 docs / 5MB / 20 AI'],['pro','احترافي','100 docs / 50MB / ∞ AI'],['enterprise','مؤسسي','حدود مخصصة']]">
            <div class="plan-opt" :class="{selected: newPlan===val}" @click="newPlan=val">
              <div class="plan-name" x-text="label"></div>
              <div class="plan-price" x-text="desc"></div>
            </div>
          </template>
        </div>
        <div x-show="newPlan==='enterprise'" style="margin-top:12px">
          <div class="form-group">
            <label>حد المستندات (اتركه فارغاً للغير محدود)</label>
            <input type="number" x-model="enterpriseLimits.max_documents" placeholder="مثال: 500">
          </div>
          <div class="form-group">
            <label>حجم الملف الأقصى (MB)</label>
            <input type="number" x-model="enterpriseLimits.max_file_size_mb" placeholder="مثال: 200">
          </div>
          <div class="form-group">
            <label>أسئلة AI يومياً (اتركه فارغاً للغير محدود)</label>
            <input type="number" x-model="enterpriseLimits.max_ai_queries_day" placeholder="غير محدود">
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-ghost" @click="modal.plan=false">إلغاء</button>
        <button class="btn btn-primary" @click="doChangePlan()" :disabled="actionLoading">
          حفظ الخطة
        </button>
      </div>
    </div>
  </div>

  <!-- ── Toast stack ── -->
  <div class="toast-stack">
    <template x-for="t in toasts" :key="t.id">
      <div class="toast" :class="t.ok ? 'toast-ok' : 'toast-err'">
        <span x-text="t.ok ? '✓' : '✕'"></span>
        <span x-text="t.msg"></span>
      </div>
    </template>
  </div>

</div><!-- /x-data -->

<script>
function adminApp() {
  return {
    // ── State ─────────────────────────────────────────────────────────
    authed: false,
    token: null,
    currentUser: {},
    creds: { email: '', password: '' },
    loginLoading: false,
    loginErr: '',

    // Golden Trial banner — dismissed per session via sessionStorage
    trialBannerDismissed: !!sessionStorage.getItem('trialDismissed'),

    tab: 'dashboard',
    tabTitles: { dashboard: 'لوحة البيانات', users: 'إدارة المستخدمين', marketing: 'إحصائيات التسويق' },

    stats: {},
    users: [],
    usersMeta: { total: 0, pages: 1 },
    usersPage: 1,
    usersLoading: false,
    statusFilter: '',
    planFilter: '',
    search: '',

    marketing: {},
    marketingLoading: false,

    modal: { approve: false, reject: false, plan: false },
    selectedUser: {},
    rejectReason: '',
    newPlan: 'free',
    enterpriseLimits: {},
    actionLoading: false,

    toasts: [],

    // ── Init ──────────────────────────────────────────────────────────
    init() {
      const saved = sessionStorage.getItem('natiqa_admin_token');
      if (saved) {
        this.token = saved;
        this.authed = true;
        this.loadStats();
        this.fetchMe();
      }
    },

    // ── Auth ──────────────────────────────────────────────────────────
    async login() {
      this.loginLoading = true; this.loginErr = '';
      try {
        const r = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.creds),
        });
        if (!r.ok) { this.loginErr = (await r.json()).detail || 'فشل تسجيل الدخول'; return; }
        const d = await r.json();
        if (!['admin','super_admin'].includes(d.user?.role)) {
          this.loginErr = 'هذه اللوحة مخصصة للمسؤولين فقط.'; return;
        }
        this.token = d.access_token;
        this.currentUser = d.user;
        sessionStorage.setItem('natiqa_admin_token', this.token);
        this.authed = true;
        this.loadStats();
      } catch(e) { this.loginErr = 'خطأ في الاتصال'; }
      finally    { this.loginLoading = false; }
    },

    logout() {
      sessionStorage.removeItem('natiqa_admin_token');
      this.token = null; this.authed = false;
      this.creds = { email:'', password:'' };
    },

    async fetchMe() {
      try {
        const d = await this.api('GET', '/api/auth/me');
        this.currentUser = d;
      } catch {}
    },

    // ── API helper ────────────────────────────────────────────────────
    async api(method, path, body) {
      const opts = {
        method,
        headers: { 'Authorization': 'Bearer ' + this.token, 'Content-Type': 'application/json' },
      };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(path, opts);
      if (r.status === 401) { this.logout(); return null; }
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.detail || 'Server error ' + r.status);
      }
      return r.json();
    },

    // ── Data loaders ──────────────────────────────────────────────────
    async loadStats() {
      try { this.stats = await this.api('GET', '/admin-portal/api/stats') || {}; }
      catch(e) { this.toast(false, e.message); }
    },

    async loadUsers() {
      this.usersLoading = true;
      try {
        const qs = new URLSearchParams({
          page: this.usersPage,
          per_page: 25,
          ...(this.statusFilter && { status: this.statusFilter }),
          ...(this.planFilter   && { plan:   this.planFilter }),
          ...(this.search       && { search: this.search }),
        });
        const d = await this.api('GET', '/admin-portal/api/users?' + qs);
        if (d) { this.users = d.users; this.usersMeta = d; }
      } catch(e) { this.toast(false, e.message); }
      finally    { this.usersLoading = false; }
    },

    async loadMarketing() {
      this.marketingLoading = true;
      try { this.marketing = await this.api('GET', '/admin-portal/api/marketing') || {}; }
      catch(e) { this.toast(false, e.message); }
      finally  { this.marketingLoading = false; }
    },

    refreshCurrent() {
      if (this.tab==='dashboard')  this.loadStats();
      if (this.tab==='users')      this.loadUsers();
      if (this.tab==='marketing')  this.loadMarketing();
    },

    // ── Modals ────────────────────────────────────────────────────────
    openApprove(u) { this.selectedUser = u; this.modal.approve = true; },
    openReject(u)  { this.selectedUser = u; this.rejectReason = ''; this.modal.reject = true; },
    openPlan(u)    {
      this.selectedUser = u;
      this.newPlan = u.subscription_plan || 'free';
      this.enterpriseLimits = {};
      this.modal.plan = true;
    },

    // ── Actions ───────────────────────────────────────────────────────
    async doApprove() {
      this.actionLoading = true;
      try {
        await this.api('POST', `/admin-portal/api/users/${this.selectedUser.id}/approve`, {});
        this.toast(true, `تمت الموافقة على ${this.selectedUser.email}`);
        this.modal.approve = false;
        await this.loadUsers(); await this.loadStats();
      } catch(e) { this.toast(false, e.message); }
      finally    { this.actionLoading = false; }
    },

    async doReject() {
      this.actionLoading = true;
      try {
        await this.api('POST', `/admin-portal/api/users/${this.selectedUser.id}/reject`,
                       { reason: this.rejectReason });
        this.toast(true, `تم رفض ${this.selectedUser.email}`);
        this.modal.reject = false;
        await this.loadUsers(); await this.loadStats();
      } catch(e) { this.toast(false, e.message); }
      finally    { this.actionLoading = false; }
    },

    async doChangePlan() {
      this.actionLoading = true;
      const body = {
        plan: this.newPlan,
        custom_limits: this.newPlan === 'enterprise' ? {
          ...(this.enterpriseLimits.max_documents   && { max_documents: +this.enterpriseLimits.max_documents }),
          ...(this.enterpriseLimits.max_file_size_mb && { max_file_size_mb: +this.enterpriseLimits.max_file_size_mb }),
          ...(this.enterpriseLimits.max_ai_queries_day && { max_ai_queries_day: +this.enterpriseLimits.max_ai_queries_day }),
        } : null,
      };
      try {
        await this.api('POST', `/admin-portal/api/users/${this.selectedUser.id}/plan`, body);
        this.toast(true, `تم تغيير الخطة إلى ${this.newPlan}`);
        this.modal.plan = false;
        await this.loadUsers(); await this.loadStats();
      } catch(e) { this.toast(false, e.message); }
      finally    { this.actionLoading = false; }
    },

    // ── Toast ──────────────────────────────────────────────────────────
    toast(ok, msg) {
      const id = Date.now();
      this.toasts.push({ id, ok, msg });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3500);
    },
  };
}
</script>
</body>
</html>"""
