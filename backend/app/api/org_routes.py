"""
Organization Management Routes — Team Management & Invitations
"""
from __future__ import annotations

import secrets
import structlog
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, log_audit
from app.core.security import hash_password
from app.models.models import (
    User, UserRole, Organization, Invitation, AuditAction, ApprovalStatus
)
from app.core.config import settings

log = structlog.get_logger()
router = APIRouter(prefix="/org", tags=["Organization Management"])

# ── Dependencies ──────────────────────────────────────────────────────

async def require_org_admin(current: User = Depends(get_current_user)) -> User:
    if current.role != UserRole.ORG_ADMIN and not current.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذه العملية مخصصة لمدير المؤسسة فقط."
        )
    return current

# ── Schemas ──────────────────────────────────────────────────────────

class InviteRequest(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.EMPLOYEE

class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8)

class UserSummary(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str

class InvitationSummary(BaseModel):
    email: str
    org_name: str
    token: str

# ── Routes ───────────────────────────────────────────────────────────

@router.post("/invite", status_code=201)
async def invite_user(
    body: InviteRequest,
    current: User = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Invite a new member to the organization.
    """
    # Check if user already exists
    existing_user = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="هذا البريد الإلكتروني مسجل مسبقاً في المنصة.")

    # Check for pending invitation
    existing_invite = await db.execute(
        select(Invitation).where(
            Invitation.email == body.email.lower(),
            Invitation.organization_id == current.organization_id,
            Invitation.accepted_at == None
        )
    )
    if existing_invite.scalar_one_or_none():
        # Could resend or just error
        raise HTTPException(status_code=400, detail="توجد دعوة معلقة لهذا البريد بالفعل.")

    # Create invitation
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    
    invite = Invitation(
        email=body.email.lower(),
        role=body.role,
        token=token,
        organization_id=current.organization_id,
        invited_by=current.id,
        expires_at=expires_at
    )
    db.add(invite)
    
    # Send Email
    from app.core.emails import get_invitation_email_template
    org = await db.get(Organization, current.organization_id)
    invite_url = f"{settings.FRONTEND_URL}/accept-invitation?token={token}"
    html = get_invitation_email_template(org.name, invite_url)
    
    # Reuse email sending logic (Mock for now if ENABLE_REAL_EMAIL=False)
    if not settings.ENABLE_REAL_EMAIL:
        log.info("DEBUG INVITE EMAIL", email=body.email, url=invite_url)
        with open("debug_invite.html", "w", encoding="utf-8") as f:
            f.write(html)
    else:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": settings.RESEND_FROM_EMAIL,
            "to": [body.email],
            "subject": f"دعوة للانضمام إلى {org.name} في ناطقة",
            "html": html
        })

    await log_audit(db, AuditAction.USER_INVITE, user_id=current.id, details={"invited_email": body.email})
    await db.commit()
    
    return {"message": "تم إرسال الدعوة بنجاح."}

@router.get("/team", response_model=List[UserSummary])
async def get_team(
    current: User = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all users in the current organization. (Tenant Isolation)
    """
    result = await db.execute(
        select(User).where(User.organization_id == current.organization_id).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    
    return [
        UserSummary(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at.isoformat()
        ) for u in users
    ]

@router.get("/invitations/{token}", response_model=InvitationSummary)
async def get_invitation(token: str, db: AsyncSession = Depends(get_db)):
    """
    Public endpoint to check invitation details.
    """
    invite = (await db.execute(
        select(Invitation).where(Invitation.token == token, Invitation.accepted_at == None)
    )).scalar_one_or_none()
    
    if not invite or invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="الدعوة غير موجودة أو انتهت صلاحيتها.")
    
    org = await db.get(Organization, invite.organization_id)
    
    return InvitationSummary(
        email=invite.email,
        org_name=org.name,
        token=token
    )

@router.post("/accept-invitation")
async def accept_invitation(body: AcceptInviteRequest, db: AsyncSession = Depends(get_db)):
    """
    Public endpoint to accept invitation and create account.
    """
    invite = (await db.execute(
        select(Invitation).where(Invitation.token == body.token, Invitation.accepted_at == None)
    )).scalar_one_or_none()
    
    if not invite or invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="الدعوة غير موجودة أو انتهت صلاحيتها.")
    
    # Create user
    new_user = User(
        email=invite.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        organization_id=invite.organization_id,
        role=invite.role,
        is_active=True,
        is_verified=True, # Invited users are automatically verified
        approval_status=ApprovalStatus.APPROVED # Invited users are auto-approved by their org-admin
    )
    db.add(new_user)
    
    # Mark invite as accepted
    invite.accepted_at = datetime.now(timezone.utc)
    
    await log_audit(db, AuditAction.INVITE_ACCEPT, user_id=None, details={"email": invite.email})
    await db.commit()
    
    return {"message": "تم إنشاء الحساب بنجاح. يمكنك الآن تسجيل الدخول."}
