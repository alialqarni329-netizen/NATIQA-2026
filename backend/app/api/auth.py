"""
app/api/auth.py  —  Authentication API
Phase 1 B2B additions: /register, /verify-email, /resend-otp
Existing: /login (hardened), /refresh, /logout, /2fa/setup, /2fa/verify, /me
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
import qrcode
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_redis, log_audit
from app.core.security import (
    create_access_token, create_refresh_token, decode_token,
    generate_totp_secret, get_totp_uri, hash_password,
    verify_password, verify_totp,
)
from app.models.models import (
    ApprovalStatus, AuditAction, DocumentType,
    Organization, RefreshToken, User, UserRole,
)

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Constants ─────────────────────────────────────────────────────────
MAX_FAILED_LOGINS      = 5
LOCK_DURATION_MINUTES  = 30
OTP_LENGTH             = 6
OTP_TTL_MINUTES        = 15
OTP_REDIS_PREFIX       = "otp:"
OTP_MAX_ATTEMPTS       = 5
OTP_LOCK_PREFIX        = "otp_lock:"
REGISTER_RATE_PER_HOUR = 5

# ── Free email domain blocklist (O(1) lookup) ─────────────────────────
_CONSUMER_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "hotmail.fr",
    "live.com", "live.co.uk", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "yahoo.com", "yahoo.co.uk", "yahoo.fr", "yahoo.de", "ymail.com",
    "proton.me", "protonmail.com",
    "aol.com", "aim.com",
    "mail.com", "email.com",
    "inbox.com", "gmx.com", "gmx.net",
    "zoho.com", "tutanota.com", "fastmail.com",
    "hushmail.com", "maktoob.com",
})


def _is_business_email(email: str) -> bool:
    return email.split("@")[-1].lower().strip() not in _CONSUMER_DOMAINS


def _generate_otp() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(OTP_LENGTH))


def _hash_otp(plain: str) -> str:
    """SHA-256 hash — stored in DB. Never store plaintext OTP in DB."""
    return hashlib.sha256(plain.encode()).hexdigest()


def _verify_otp_hash(plain: str, stored_hash: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return secrets.compare_digest(_hash_otp(plain), stored_hash)


def _generate_referral_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "NAT-" + "".join(secrets.choice(chars) for _ in range(length))


async def _unique_referral_code(db: AsyncSession) -> str:
    for _ in range(10):
        code   = _generate_referral_code()
        result = await db.execute(select(User).where(User.referral_code == code))
        if not result.scalar_one_or_none():
            return code
    return _generate_referral_code(length=12)


async def _store_otp(redis: aioredis.Redis, email: str, otp: str) -> None:
    """Store plaintext OTP in Redis with TTL (fast lookup path)."""
    await redis.setex(f"{OTP_REDIS_PREFIX}{email.lower()}", OTP_TTL_MINUTES * 60, otp)


async def _get_otp(redis: aioredis.Redis, email: str) -> Optional[str]:
    return await redis.get(f"{OTP_REDIS_PREFIX}{email.lower()}")


async def _delete_otp(redis: aioredis.Redis, email: str) -> None:
    await redis.delete(f"{OTP_REDIS_PREFIX}{email.lower()}")


async def _check_otp_rate_limit(redis: aioredis.Redis, email: str) -> None:
    lock_key    = f"{OTP_LOCK_PREFIX}{email.lower()}"
    attempt_key = f"otp_attempts:{email.lower()}"
    if await redis.get(lock_key):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait 30 minutes.")
    attempts = await redis.incr(attempt_key)
    if attempts == 1:
        await redis.expire(attempt_key, 1800)
    if attempts >= OTP_MAX_ATTEMPTS:
        await redis.setex(lock_key, 1800, "1")
        raise HTTPException(status_code=429, detail="Too many attempts. Wait 30 minutes.")


async def _send_otp_email(email: str, otp: str, business_name: str) -> None:
    """
    Send an OTP verification email to the given address.

    Behaviour is controlled by two settings:
      ENABLE_REAL_EMAIL=False  → writes rendered HTML to debug_emails.html for local preview
      ENABLE_REAL_EMAIL=True   → sends via Resend.com API using RESEND_API_KEY
    """
    from app.core.config import settings
    from app.core.emails import get_welcome_email_template

    html = get_welcome_email_template(business_name, otp)

    if not settings.ENABLE_REAL_EMAIL:
        # ── Debug mode — dump to local file for visual preview ─────────
        try:
            with open("debug_emails.html", "w", encoding="utf-8") as f:
                f.write(html)
            log.warning(
                "DEBUG EMAIL — written to debug_emails.html (ENABLE_REAL_EMAIL=False)",
                email=email, otp=otp,
            )
        except OSError as exc:
            log.error("Failed to write debug_emails.html", error=str(exc))
        return

    # ── Live mode — send via Resend SDK ────────────────────────────────
    if not settings.RESEND_API_KEY:
        log.error(
            "ENABLE_REAL_EMAIL=True but RESEND_API_KEY is empty — OTP not sent",
            email=email,
        )
        return

    try:
        import resend  # noqa: PLC0415 — lazy import to keep startup light
        resend.api_key = settings.RESEND_API_KEY
        response = resend.Emails.send({
            "from":    settings.RESEND_FROM_EMAIL,
            "to":      [email],
            "subject": f"رمز التحقق من ناطقة: {otp}",
            "html":    html,
        })
        log.info("OTP email sent via Resend", email=email, resend_id=response.get("id"))
    except Exception as exc:  # pragma: no cover
        # Never let email failure block registration — log and continue.
        log.error("Resend email delivery failed", email=email, error=str(exc))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEMAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RegisterRequest(BaseModel):
    email:           EmailStr
    full_name:       str = Field(..., min_length=2, max_length=100)
    password:        str = Field(..., min_length=8)
    business_name:   str = Field(..., min_length=2, max_length=255)
    document_type:   DocumentType = Field(..., description="cr | freelance")
    document_number: str = Field(..., min_length=5, max_length=100,
                                 description="CR number or Freelance cert — REQUIRED")
    referred_by:     Optional[str] = Field(None, max_length=50)
    terms_accepted:  bool          = Field(..., description="Must be True to proceed")

    @field_validator("email")
    @classmethod
    def must_be_business_email(cls, v: str) -> str:
        if not _is_business_email(v):
            raise ValueError(
                "Personal email addresses (Gmail, Outlook, Yahoo, etc.) are not accepted. "
                "Please use your corporate email."
            )
        return v.lower().strip()

    @field_validator("document_number")
    @classmethod
    def clean_document_number(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-]", "", v.strip())
        if not cleaned:
            raise ValueError("document_number cannot be empty.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        errors = []
        if not re.search(r"[A-Za-z]", v): errors.append("one letter")
        if not re.search(r"\d", v):        errors.append("one digit")
        if errors:
            raise ValueError(f"Password must contain: {', '.join(errors)}.")
        return v


class RegisterResponse(BaseModel):
    message:   str
    user_id:   str
    email:     str
    next_step: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp:   str = Field(..., min_length=6, max_length=6)


class ResendOtpRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email:     EmailStr
    password:  str
    totp_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user:          dict


class RefreshRequest(BaseModel):
    refresh_token: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /auth/register
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/register", status_code=201, response_model=RegisterResponse)
async def register(
    body:    RegisterRequest,
    request: Request,
    db:      AsyncSession   = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    """
    B2B self-service registration.
    - Corporate email only (Gmail/Outlook/Yahoo blocked)
    - document_number REQUIRED (HTTP 422 if empty or missing)
    - referred_by validated + saved (Amjad referral system)
    - OTP sent to email (MOCK until Resend.com is wired)
    - Account starts: is_active=False, is_verified=False, approval_status=PENDING
    """
    ip = request.client.host if request.client else "unknown"

    # Rate limit: 5 registrations per IP per hour
    rl_key   = f"reg_rl:{ip}"
    attempts = await redis.incr(rl_key)
    if attempts == 1:
        await redis.expire(rl_key, 3600)
    if attempts > REGISTER_RATE_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try in 1 hour.")

    # ── Terms Acceptance Check ───────────────────────────────────────
    if not body.terms_accepted:
        raise HTTPException(
            status_code=400,
            detail="يجب الموافقة على الشروط والسياسات للمتابعة"
        )

    # Duplicate email
    if (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    # Duplicate document_number
    if (await db.execute(
        select(User).where(User.document_number == body.document_number)
    )).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This document number is already registered.")

    # Validate referral code (Amjad marketing system)
    if body.referred_by:
        ref = await db.execute(select(User).where(User.referral_code == body.referred_by))
        if not ref.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Referral code '{body.referred_by}' is invalid.")

    # Generate unique referral code for new user
    referral_code = await _unique_referral_code(db)

    # ── Create Organization (one per company) ──────────────────────────
    org = Organization(
        name            = body.business_name,
        document_type   = body.document_type,
        document_number = body.document_number,
        terms_accepted  = True,
        terms_accepted_at = datetime.now(timezone.utc),
    )
    db.add(org)
    await db.flush()  # get org.id before commit

    # Generate OTP — Redis (plaintext TTL) + DB (SHA-256 hash fallback)
    otp        = _generate_otp()
    otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    await _store_otp(redis, body.email, otp)

    from app.core.security import hash_password as hp
    user = User(
        email           = body.email,
        full_name       = body.full_name,
        hashed_password = hp(body.password),
        role            = UserRole.ANALYST,
        is_active       = False,
        organization_id = org.id,
        business_name   = body.business_name,
        document_type   = body.document_type,
        document_number = body.document_number,
        referral_code   = referral_code,
        referred_by     = body.referred_by,
        is_verified     = False,
        otp_code        = _hash_otp(otp),
        otp_expiry      = otp_expiry,
        terms_accepted  = True,
        terms_accepted_at = datetime.now(timezone.utc),
        approval_status = ApprovalStatus.PENDING,
    )
    db.add(user)

    await log_audit(
        db, AuditAction.REGISTER, user_id=None,
        details={"email": body.email, "business": body.business_name,
                 "doc_type": body.document_type.value, "referred_by": body.referred_by},
        ip_address=ip,
    )
    await db.commit()
    await db.refresh(user)

    await _send_otp_email(body.email, otp, body.business_name)
    log.info("New B2B registration", user_id=str(user.id), email=body.email)

    return RegisterResponse(
        message   = "Registration successful. An OTP has been sent to your email address.",
        user_id   = str(user.id),
        email     = user.email,
        next_step = "POST /api/auth/verify-email with your 6-digit OTP code.",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /auth/verify-email
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/verify-email")
async def verify_email(
    body:  VerifyEmailRequest,
    db:    AsyncSession   = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    await _check_otp_rate_limit(redis, body.email)

    user = (await db.execute(
        select(User).where(User.email == body.email.lower())
    )).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Email not registered.")
    if user.is_verified:
        return {"message": "Email already verified.", "status": user.approval_status.value}

    # OTP check: Redis (fast path) → DB hash (fallback)
    stored_plain = await _get_otp(redis, body.email)
    if stored_plain:
        otp_ok = secrets.compare_digest(body.otp, stored_plain)
    elif user.otp_code and user.otp_expiry and user.otp_expiry > datetime.now(timezone.utc):
        otp_ok = _verify_otp_hash(body.otp, user.otp_code)
    else:
        raise HTTPException(status_code=400, detail="OTP expired. Request a new one.")

    if not otp_ok:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")

    user.is_verified = True
    user.otp_code    = None
    user.otp_expiry  = None

    await log_audit(db, AuditAction.EMAIL_VERIFY, user_id=user.id,
                    details={"email": user.email})
    await db.commit()
    await _delete_otp(redis, body.email)

    return {
        "message":   "Email verified. Your account is pending admin approval.",
        "verified":  True,
        "status":    user.approval_status.value,
        "next_step": "Wait for admin approval — you will be notified by email.",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /auth/resend-otp
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/resend-otp")
async def resend_otp(
    body:    ResendOtpRequest,
    request: Request,
    db:      AsyncSession   = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    key   = f"resend_rl:{body.email.lower()}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 300)
    if count > 3:
        raise HTTPException(status_code=429, detail="Wait 5 minutes before resending.")

    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()

    if not user or user.is_verified:
        return {"message": "If the account exists and is unverified, a new OTP has been sent."}

    otp        = _generate_otp()
    otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    await _store_otp(redis, body.email, otp)
    user.otp_code   = _hash_otp(otp)
    user.otp_expiry = otp_expiry
    await db.commit()

    await _send_otp_email(body.email, otp, user.business_name or user.full_name)
    return {"message": "A new OTP has been sent to your email.", "expires_in": f"{OTP_TTL_MINUTES} minutes"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POST /auth/login  — ⚠️ AUTH BYPASS ACTIVE (DEV ONLY)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/login", response_model=TokenResponse)
async def login(
    body:    LoginRequest,
    request: Request,
    db:      AsyncSession   = Depends(get_db),
    redis:   aioredis.Redis = Depends(get_redis),
):
    # ⚠️ DEV BYPASS — skip all auth checks, return fake token
    # TODO: remove before going to production
    return TokenResponse(
        access_token  = "dev-bypass-access-token",
        refresh_token = "dev-bypass-refresh-token",
        user = {
            "id":            "c2853f49-bca3-46fc-a755-9abd2d6e759f",
            "email":         "ali_boss@natiqa.com",
            "full_name":     "Ali Boss",
            "role":          "super_admin",
            "is_admin":      True,
            "business_name": "Natiqa",
            "totp_enabled":  False,
            "trial": {
                "active":         True,
                "days_remaining": 15,
                "ends_at":        None,
                "just_activated": True,
            },
        },
    )

    # ── Lookup user ──────────────────────────────────────────────────
    ip   = request.client.host if request.client else "unknown"
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()

    async def fail(msg: str = "Invalid email or password") -> None:
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_DURATION_MINUTES)
            await db.commit()
        raise HTTPException(status_code=401, detail=msg)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # ── Phase 1 Gates ────────────────────────────────────────────────
    if not user.is_verified:
        raise HTTPException(status_code=403,
            detail="Email not verified. Check your inbox or request a new OTP.")
    if user.approval_status == ApprovalStatus.PENDING:
        raise HTTPException(status_code=403,
            detail="Your account is pending admin approval. You will be notified by email.")
    if user.approval_status == ApprovalStatus.REJECTED:
        raise HTTPException(status_code=403,
            detail="Your account was not approved. Contact support.")
    # ────────────────────────────────────────────────────────────────

    if not user.is_active:
        await fail()
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=403,
            detail=f"Account locked until {user.locked_until.strftime('%H:%M')}. Contact admin.")
    if not verify_password(body.password, user.hashed_password):
        await fail()

    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(status_code=200, detail={"require_2fa": True})
        if not verify_totp(user.totp_secret, body.totp_code):
            await fail("Invalid 2FA code")

    user.failed_logins = 0
    user.locked_until  = None
    user.last_login    = datetime.now(timezone.utc)

    # ── Golden Trial Activation (first login after approval) ──────────
    trial_activated = False
    if (
        user.approval_status == ApprovalStatus.APPROVED
        and user.trial_starts_at is None
        and str(user.subscription_plan) == "free"
    ):
        now_utc = datetime.now(timezone.utc)
        user.trial_starts_at = now_utc
        user.trial_ends_at   = now_utc + timedelta(days=15)
        trial_activated = True
        log.info("Golden Trial activated", user_id=str(user.id), email=user.email,
                 trial_ends_at=user.trial_ends_at.isoformat())

    access_token      = create_access_token(str(user.id), extra={"role": user.role.value, "email": user.email})
    refresh_token_str = create_refresh_token(str(user.id))
    rt_payload        = decode_token(refresh_token_str)
    db.add(RefreshToken(jti=rt_payload["jti"], user_id=user.id,
                        expires_at=datetime.fromtimestamp(rt_payload["exp"], tz=timezone.utc)))
    await db.commit()
    if trial_activated:
        await log_audit(db, AuditAction.TRIAL_ACTIVATE, user_id=user.id, ip_address=ip,
                        details={"trial_ends_at": user.trial_ends_at.isoformat()})
    await log_audit(db, AuditAction.LOGIN, user_id=user.id, ip_address=ip)
    await db.commit()

    # ── Build trial_info for the frontend banner ───────────────────────
    from app.services.plans import is_in_trial_period, trial_days_remaining
    in_trial = is_in_trial_period(user)
    trial_info = {
        "active":         in_trial,
        "days_remaining": trial_days_remaining(user) if in_trial else 0,
        "ends_at":        user.trial_ends_at.isoformat() if user.trial_ends_at else None,
        "just_activated": trial_activated,
    }

    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token_str,
        user={
            "id":            str(user.id),
            "email":         user.email,
            "full_name":     user.full_name,
            "role":          user.role.value,
            "is_admin":      user.is_admin,
            "business_name": user.business_name,
            "totp_enabled":  user.totp_enabled,
            "trial":         trial_info,
        },
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REFRESH / LOGOUT / 2FA / ME
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    rt = (await db.execute(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))).scalar_one_or_none()
    if not rt or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")
    rt.revoked = True
    user = (await db.execute(select(User).where(User.id == rt.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    new_access = create_access_token(str(user.id), extra={"role": user.role.value, "email": user.email})
    new_ref    = create_refresh_token(str(user.id))
    nrp        = decode_token(new_ref)
    db.add(RefreshToken(jti=nrp["jti"], user_id=user.id,
                        expires_at=datetime.fromtimestamp(nrp["exp"], tz=timezone.utc)))
    await db.commit()
    return TokenResponse(access_token=new_access, refresh_token=new_ref,
        user={"id": str(user.id), "email": user.email, "full_name": user.full_name,
              "role": user.role.value, "totp_enabled": user.totp_enabled})


@router.post("/logout")
async def logout(request: Request, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db), redis: aioredis.Redis = Depends(get_redis)):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        payload = decode_token(header[7:])
        if payload:
            ttl = payload["exp"] - int(datetime.now(timezone.utc).timestamp())
            if ttl > 0:
                await redis.setex(f"blacklist:{header[7:23]}", ttl, "1")
    await log_audit(db, AuditAction.LOGOUT, user_id=user.id)
    await db.commit()
    return {"detail": "Logged out successfully"}


@router.post("/2fa/setup")
async def setup_2fa(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    secret = generate_totp_secret()
    uri    = get_totp_uri(secret, user.email)
    qr     = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    user.totp_secret = secret
    await db.commit()
    return {"secret": secret, "qr_code": f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"}


@router.post("/2fa/verify")
async def verify_2fa_setup(code: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA not initialized. Call /2fa/setup first.")
    if not verify_totp(user.totp_secret, code):
        raise HTTPException(status_code=400, detail="Invalid code")
    user.totp_enabled = True
    await db.commit()
    return {"detail": "2FA enabled successfully"}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id":              str(user.id),
        "email":           user.email,
        "full_name":       user.full_name,
        "role":            user.role.value,
        "is_admin":        user.is_admin,
        "business_name":   user.business_name,
        "document_type":   user.document_type.value if user.document_type else None,
        "approval_status": user.approval_status.value,
        "is_verified":     user.is_verified,
        "referral_code":   user.referral_code,
        "referred_by":     user.referred_by,
        "totp_enabled":    user.totp_enabled,
        "last_login":      user.last_login.isoformat() if user.last_login else None,
        "subscription_plan":       str(user.subscription_plan or "free"),
        "subscription_expires_at": user.subscription_expires_at.isoformat()
                                     if user.subscription_expires_at else None,
    }
