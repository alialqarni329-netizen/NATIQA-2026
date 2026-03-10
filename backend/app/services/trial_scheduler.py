"""
app/services/trial_scheduler.py
══════════════════════════════════════════════════════════════════════
Golden Trial — Nightly Background Jobs

Two APScheduler jobs registered in main.py:

  • expire_trials()        — runs daily at 00:05 UTC
    Finds users whose trial_ends_at < NOW and whose plan is still 'free'
    (meaning they never paid). Clears their trial_ends_at to prevent
    re-triggering and logs a TRIAL_EXPIRY audit record.

  • send_trial_reminders() — runs daily at 09:00 UTC
    Finds users whose trial expires in the next 24-48 hours (day 13)
    and sends the "Trial Ending Soon" email.

Design decisions:
  • Idempotent — jobs skip users already processed.
  • Graceful — errors in one user don't abort the whole batch.
  • Minimal coupling — imports are lazy to avoid circular imports.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger()

TRIAL_DURATION_DAYS = 15


# ══════════════════════════════════════════════════════════════════════
# JOB 1 — Expire trials nightly at 00:05 UTC
# ══════════════════════════════════════════════════════════════════════

async def expire_trials() -> None:
    """
    Cleans up expired Golden Trials.

    Logic:
      - SELECT users WHERE trial_ends_at < NOW AND trial_ends_at IS NOT NULL
      - Skip any user who paid (subscription_plan != 'free') — don't downgrade
      - Clear trial_ends_at → prevents re-trigger on the next nightly run
      - Write TRIAL_EXPIRY audit record
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import User, AuditAction, ApprovalStatus
    from app.core.dependencies import log_audit
    from sqlalchemy import select

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(User).where(
                    User.trial_ends_at.isnot(None),
                    User.trial_ends_at < now,
                    User.approval_status == ApprovalStatus.APPROVED,
                )
            )
            expired_users = result.scalars().all()

            count = 0
            for user in expired_users:
                # Don't downgrade a user who already paid for PRO/Enterprise
                if str(user.subscription_plan) in ("pro", "enterprise"):
                    # They paid — just clear the trial timestamp to stop re-evaluation
                    user.trial_ends_at = None
                    await db.flush()
                    continue

                # Free user — trial over, no change to plan (stays FREE)
                user.trial_ends_at = None   # prevents re-trigger

                await log_audit(
                    db,
                    AuditAction.TRIAL_EXPIRY,
                    user_id=user.id,
                    resource_type="user",
                    resource_id=str(user.id),
                    details={
                        "email":         user.email,
                        "business_name": user.business_name,
                        "plan":          str(user.subscription_plan),
                        "expired_at":    now.isoformat(),
                    },
                )
                count += 1

            await db.commit()
            log.info("Trial expiry job complete", expired=count, checked=len(expired_users))

        except Exception as exc:
            await db.rollback()
            log.error("expire_trials job failed", error=str(exc))


# ══════════════════════════════════════════════════════════════════════
# JOB 2 — Day-13 reminder at 09:00 UTC
# ══════════════════════════════════════════════════════════════════════

async def send_trial_reminders() -> None:
    """
    Sends a "Trial Ending Soon" reminder to users on Day 13
    (trial expires within 24–48 hours from now).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import User, ApprovalStatus
    from app.core.config import settings
    from app.core.emails import get_trial_reminder_email_template
    from sqlalchemy import select

    now  = datetime.now(timezone.utc)
    lo   = now + timedelta(hours=24)   # ends in 24h
    hi   = now + timedelta(hours=48)   # ends in 48h

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(User).where(
                    User.trial_ends_at.isnot(None),
                    User.trial_ends_at >= lo,
                    User.trial_ends_at <= hi,
                    User.approval_status == ApprovalStatus.APPROVED,
                )
            )
            users = result.scalars().all()

            sent = 0
            for user in users:
                days_left = max(1, (user.trial_ends_at - now).days)
                try:
                    await _send_reminder(
                        email=user.email,
                        business_name=user.business_name or user.full_name,
                        days_left=days_left,
                        settings=settings,
                        get_template=get_trial_reminder_email_template,
                    )
                    sent += 1
                except Exception as exc:
                    log.error("Trial reminder email failed",
                              email=user.email, error=str(exc))

            log.info("Trial reminder job complete", sent=sent, eligible=len(users))

        except Exception as exc:
            log.error("send_trial_reminders job failed", error=str(exc))


async def _send_reminder(
    email: str,
    business_name: str,
    days_left: int,
    settings,
    get_template,
) -> None:
    html = get_template(business_name, days_left)

    if not settings.ENABLE_REAL_EMAIL:
        log.info("DEBUG TRIAL REMINDER — ENABLE_REAL_EMAIL=False",
                 email=email, days_left=days_left)
        return

    if not settings.RESEND_API_KEY:
        log.error("RESEND_API_KEY not set — trial reminder not sent", email=email)
        return

    import resend
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send({
        "from":    settings.RESEND_FROM_EMAIL,
        "to":      [email],
        "subject": f"⏳ تجربتك الذهبية تنتهي خلال {days_left} {'يوم' if days_left == 1 else 'أيام'} — ناطقة",
        "html":    html,
    })
    log.info("Trial reminder sent", email=email, days_left=days_left)


# ══════════════════════════════════════════════════════════════════════
# SCHEDULER REGISTRATION  (called from main.py lifespan)
# ══════════════════════════════════════════════════════════════════════

def create_scheduler():
    """
    Builds and returns a configured AsyncIOScheduler.
    Register in main.py::lifespan() — start on startup, shutdown on teardown.

    Usage in main.py:
        from app.services.trial_scheduler import create_scheduler
        scheduler = create_scheduler()

        @asynccontextmanager
        async def lifespan(app):
            await init_db()
            scheduler.start()
            yield
            scheduler.shutdown(wait=False)
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone="UTC")

    # Expire trials — 00:05 UTC every day
    scheduler.add_job(
        expire_trials,
        trigger=CronTrigger(hour=0, minute=5),
        id="golden_trial_expiry",
        replace_existing=True,
        misfire_grace_time=3600,    # run within 1h if missed
    )

    # Day-13 reminder — 09:00 UTC every day
    scheduler.add_job(
        send_trial_reminders,
        trigger=CronTrigger(hour=9, minute=0),
        id="golden_trial_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    log.info("Golden Trial scheduler configured",
             jobs=["golden_trial_expiry (00:05 UTC)",
                   "golden_trial_reminder (09:00 UTC)"])
    return scheduler
