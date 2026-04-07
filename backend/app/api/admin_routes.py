"""
Admin Routes — Approval Workflow & User Management
═══════════════════════════════════════════════════
File:    app/api/admin_routes.py
Mount:   app/main.py  →  app.include_router(admin_routes.router, prefix="/api")

All routes require is_admin=True (ADMIN or SUPER_ADMIN role).

Routes:
  GET    /api/admin/pending          → قائمة الحسابات التي تنتظر الموافقة
  POST   /api/admin/users/{id}/approve → الموافقة على حساب
  POST   /api/admin/users/{id}/reject  → رفض حساب مع سبب
  GET    /api/admin/users            → قائمة كل المستخدمين مع فلترة
  GET    /api/admin/stats            → إحصائيات المنصة
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, log_audit
from app.models.models import (
    ApprovalStatus, AuditAction, User, UserRole, Organization, Document
)
from app.services.export_service import ExportService

log = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["Admin"])


# ══════════════════════════════════════════════════════════════════════
# GUARD — is_admin check
# ══════════════════════════════════════════════════════════════════════

async def require_admin(
    current: User = Depends(get_current_user),
) -> User:
    """
    تحقق أن المستخدم الحالي هو admin أو super_admin.
    يعتمد على الـ computed property  User.is_admin.
    """
    if not current.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="هذه العملية مخصصة للمسؤولين فقط.",
        )
    return current


# ══════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════

class ApproveUserResponse(BaseModel):
    message:         str
    user_id:         str
    email:           str
    approval_status: str
    approved_by:     str
    approved_at:     str


class RejectRequest(BaseModel):
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="سبب الرفض — سيُرسَل للمستخدم في الإيميل",
    )


class UserSummary(BaseModel):
    id:              str
    email:           str
    full_name:       str
    business_name:   Optional[str]
    document_type:   Optional[str]
    document_number: Optional[str]
    role:            str
    is_active:       bool
    is_verified:     bool
    approval_status: str
    referral_code:   Optional[str]
    referred_by:     Optional[str]
    created_at:      str
    last_login:      Optional[str]
    approved_by:     Optional[str]
    approved_at:     Optional[str]
    rejection_reason: Optional[str]


class OrganizationSummary(BaseModel):
    id:                str
    name:              str
    document_type:     Optional[str]
    document_number:   Optional[str]
    subscription_plan: str
    is_active:         bool
    created_at:        str


def _user_to_summary(u: User) -> UserSummary:
    return UserSummary(
        id              = str(u.id),
        email           = u.email,
        full_name       = u.full_name,
        business_name   = u.business_name,
        document_type   = u.document_type.value if u.document_type else None,
        document_number = u.document_number,
        role            = u.role.value,
        is_active       = u.is_active,
        is_verified     = u.is_verified,
        approval_status = u.approval_status.value,
        referral_code   = u.referral_code,
        referred_by     = u.referred_by,
        created_at      = u.created_at.isoformat() if u.created_at else "",
        last_login      = u.last_login.isoformat() if u.last_login else None,
        approved_by     = str(u.approved_by) if u.approved_by else None,
        approved_at     = u.approved_at.isoformat() if u.approved_at else None,
        rejection_reason = u.rejection_reason,
    )


# ══════════════════════════════════════════════════════════════════════
# ROUTE 1 — PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/pending",
    response_model=List[UserSummary],
    summary="قائمة الحسابات التي تنتظر الموافقة",
    description=(
        "يعرض المستخدمين الذين: "
        "(1) أكملوا التحقق من البريد الإلكتروني "
        "(2) لم يتلقوا قراراً بعد."
    ),
)
async def list_pending_approvals(
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
) -> List[UserSummary]:

    result = await db.execute(
        select(User)
        .where(
            User.approval_status == ApprovalStatus.PENDING,
            User.is_verified == True,  # noqa: E712
        )
        .order_by(User.created_at.asc())   # الأقدم أولاً (FIFO)
    )
    users = result.scalars().all()

    log.info(
        "Admin fetched pending approvals",
        admin_id=str(current.id),
        count=len(users),
    )

    return [_user_to_summary(u) for u in users]


# ══════════════════════════════════════════════════════════════════════
# ROUTE 2 — APPROVE USER
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/users/{user_id}/approve",
    response_model=ApproveUserResponse,
    summary="الموافقة على حساب مستخدم",
)
async def approve_user(
    user_id: str,
    request: Request,
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
) -> ApproveUserResponse:

    target = await _get_user_or_404(db, user_id)

    # ── الحالات التي لا تحتاج تغييراً ───────────────────────────────
    if target.approval_status == ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الحساب موافَق عليه مسبقاً.",
        )

    # ── تطبيق الموافقة ────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    target.approval_status = ApprovalStatus.APPROVED
    target.approved_by     = current.id
    target.approved_at     = now
    target.rejection_reason = None   # إلغاء أي رفض سابق

    await log_audit(
        db,
        AuditAction.USER_APPROVE,
        user_id=current.id,
        resource_type="user",
        resource_id=str(target.id),
        details={
            "target_email":  target.email,
            "business_name": target.business_name,
        },
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(target)

    # ── Send approval notification email ─────────────────────────────
    await _send_approval_email(target.email, target.business_name or target.full_name)
    log.info(
        "Admin approved user",
        admin_id=str(current.id),
        target_user=str(target.id),
        email=target.email,
    )

    return ApproveUserResponse(
        message         = f"تمت الموافقة على حساب {target.email} بنجاح.",
        user_id         = str(target.id),
        email           = target.email,
        approval_status = target.approval_status.value,
        approved_by     = str(current.id),
        approved_at     = now.isoformat(),
    )


# ══════════════════════════════════════════════════════════════════════
# ROUTE 3 — REJECT USER
# ══════════════════════════════════════════════════════════════════════

@router.post(
    "/users/{user_id}/reject",
    summary="رفض حساب مستخدم",
)
async def reject_user(
    user_id: str,
    body:    RejectRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
) -> dict:

    target = await _get_user_or_404(db, user_id)

    if target.approval_status == ApprovalStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الحساب مرفوض مسبقاً.",
        )

    # لا يمكن رفض super_admin
    if target.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن رفض حساب super_admin.",
        )

    now = datetime.now(timezone.utc)
    target.approval_status  = ApprovalStatus.REJECTED
    target.rejection_reason = body.reason
    target.approved_by      = current.id
    target.approved_at      = now

    await log_audit(
        db,
        AuditAction.USER_REJECT,
        user_id=current.id,
        resource_type="user",
        resource_id=str(target.id),
        details={
            "target_email": target.email,
            "reason":       body.reason,
        },
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # ── Send rejection email with reason ──────────────────────────
    await _send_rejection_email(
        target.email,
        target.business_name or target.full_name,
        body.reason,
    )
    log.info(
        "Admin rejected user",
        admin_id=str(current.id),
        target_user=str(target.id),
        email=target.email,
        reason=body.reason,
    )

    return {
        "message":         f"تم رفض حساب {target.email}.",
        "user_id":         str(target.id),
        "approval_status": target.approval_status.value,
        "reason":          body.reason,
    }


# ══════════════════════════════════════════════════════════════════════
# ROUTE 4 — LIST ALL USERS (with filters)
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/users",
    response_model=List[UserSummary],
    summary="قائمة المستخدمين مع فلترة",
)
async def list_users(
    approval_status: Optional[str] = Query(
        None, description="pending | approved | rejected"
    ),
    is_verified: Optional[bool]    = Query(None),
    role:        Optional[str]     = Query(None),
    limit:       int               = Query(50,  ge=1, le=200),
    offset:      int               = Query(0,   ge=0),
    db:          AsyncSession      = Depends(get_db),
    current:     User              = Depends(require_admin),
) -> List[UserSummary]:

    q = select(User)

    if approval_status:
        try:
            status_enum = ApprovalStatus(approval_status)
            q = q.where(User.approval_status == status_enum)
        except ValueError:
            raise HTTPException(400, f"قيمة غير صحيحة: {approval_status}")

    if is_verified is not None:
        q = q.where(User.is_verified == is_verified)

    if role:
        try:
            role_enum = UserRole(role)
            q = q.where(User.role == role_enum)
        except ValueError:
            raise HTTPException(400, f"دور غير صحيح: {role}")

    q = q.order_by(User.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(q)
    return [_user_to_summary(u) for u in result.scalars().all()]


# ══════════════════════════════════════════════════════════════════════
# ROUTE 5 — PLATFORM STATS
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/stats",
    summary="إحصائيات المنصة",
)
async def get_platform_stats(
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
) -> dict:

    # Users
    total_users    = await db.scalar(select(sa_func.count(User.id)))
    pending_users  = await db.scalar(select(sa_func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING))
    
    # Organizations
    total_orgs     = await db.scalar(select(sa_func.count(Organization.id)))
    active_orgs    = await db.scalar(select(sa_func.count(Organization.id)).where(Organization.is_active == True))
    
    # Documents
    total_docs     = await db.scalar(select(sa_func.count(Document.id)))

    return {
        "users": {
            "total": total_users or 0,
            "pending": pending_users or 0,
        },
        "organizations": {
            "total": total_orgs or 0,
            "active": active_orgs or 0,
        },
        "documents": {
            "total": total_docs or 0,
        }
    }


# ══════════════════════════════════════════════════════════════════════
# ROUTE 7 — PROFESSIONAL EXPORTS
# ══════════════════════════════════════════════════════════════════════

@router.get("/export/word")
async def export_word_report(
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    """تصدير تقرير أداء المنصة بصيغة Word"""
    stats = await get_platform_stats(db, current)
    logo_path = "app/static/logo.png"
    
    file_stream = ExportService.generate_word_report(stats, logo_path)
    
    filename = f"Natiqa_Report_{datetime.now().strftime('%Y%m%d')}.docx"
    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/pptx")
async def export_pptx_report(
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    """تصدير عرض تقديمي لنتائج المنصة بصيغة PowerPoint"""
    stats = await get_platform_stats(db, current)
    logo_path = "app/static/logo.png"
    
    file_stream = ExportService.generate_pptx_presentation(stats, logo_path)
    
    filename = f"Natiqa_Presentation_{datetime.now().strftime('%Y%m%d')}.pptx"
    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/powerbi")
async def export_powerbi_feed(
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    """تغذية بيانات متكاملة لـ Power BI (BI-Ready Feed)"""
    stats = await get_platform_stats(db, current)
    
    # Detailed org list for BI
    res = await db.execute(select(Organization))
    orgs = res.scalars().all()
    
    bi_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": stats,
        "organizations": [
            {
                "id": str(o.id),
                "name": o.name,
                "plan": o.subscription_plan.value,
                "active": o.is_active,
                "signup_date": o.created_at.isoformat(),
            } for o in orgs
        ]
    }
    
    return JSONResponse(content=bi_data)


# ══════════════════════════════════════════════════════════════════════
# ROUTE 6 — LIST ORGANIZATIONS
# ══════════════════════════════════════════════════════════════════════

@router.get(
    "/organizations",
    response_model=List[OrganizationSummary],
    summary="قائمة الشركات المسجلة",
)
async def list_organizations(
    limit:   int          = Query(50, ge=1, le=100),
    offset:  int          = Query(0, ge=0),
    db:      AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
) -> List[OrganizationSummary]:

    result = await db.execute(
        select(Organization)
        .order_by(Organization.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    orgs = result.scalars().all()

    return [
        OrganizationSummary(
            id                = str(o.id),
            name              = o.name,
            document_type     = o.document_type.value if o.document_type else None,
            document_number   = getattr(o, "document_number", None) or getattr(o, "tax_number", None),
            subscription_plan = o.subscription_plan.value,
            is_active         = o.is_active,
            created_at        = o.created_at.isoformat(),
        )
        for o in orgs
    ]


# ══════════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════════

async def _get_user_or_404(db: AsyncSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="معرّف المستخدم غير صحيح.",
        )

    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود.",
        )
    return user


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
        log.info("Approval email sent via admin_routes", email=email)
    except Exception as exc:
        log.error("Approval email delivery failed", email=email, error=str(exc))


async def _send_rejection_email(email: str, business_name: str, reason: str) -> None:
    """Send account-rejection notification email via Resend (or log in debug mode)."""
    from app.core.config import settings

    html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>تحديث حالة طلبك في ناطقة</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:'Tajawal',Arial,sans-serif;direction:rtl;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#f1f5f9;min-height:100vh;padding:32px 16px;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="max-width:580px;background:#ffffff;border-radius:16px;
                    overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.12);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1e3a5f 0%,#0f2040 100%);
                     padding:32px 40px;text-align:center;">
            <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">
              ناطقة
            </div>
            <div style="font-size:13px;color:#93c5fd;margin-top:4px;">
              منصة الذكاء الاصطناعي المؤسسي
            </div>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:40px;">
            <h2 style="font-size:22px;color:#1e293b;margin:0 0 16px;">
              مرحباً {business_name}،
            </h2>
            <p style="font-size:16px;color:#475569;line-height:1.7;margin:0 0 24px;">
              شكراً لتسجيلك في منصة ناطقة. بعد مراجعة طلبك، نأسف لإبلاغك
              بأنه لم يتم قبوله في الوقت الحالي.
            </p>
            <div style="background:#fff1f2;border-right:4px solid #f43f5e;
                        border-radius:8px;padding:16px 20px;margin-bottom:24px;">
              <p style="font-size:14px;font-weight:700;color:#be123c;margin:0 0 6px;">
                سبب الرفض:
              </p>
              <p style="font-size:15px;color:#1e293b;margin:0;line-height:1.6;">
                {reason}
              </p>
            </div>
            <p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 24px;">
              إذا كنت تعتقد أن هناك خطأً أو لديك استفسار، يمكنك التواصل معنا
              عبر البريد الإلكتروني للدعم.
            </p>
            <div style="text-align:center;">
              <a href="mailto:support@natiqa.ai"
                 style="display:inline-block;background:#1e3a5f;color:#ffffff;
                        font-size:15px;font-weight:700;padding:14px 32px;
                        border-radius:10px;text-decoration:none;">
                تواصل مع الدعم
              </a>
            </div>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:20px 40px;text-align:center;
                     border-top:1px solid #e2e8f0;">
            <p style="font-size:12px;color:#94a3b8;margin:0;">
              © 2026 ناطقة — جميع الحقوق محفوظة
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    if not settings.ENABLE_REAL_EMAIL:
        log.info(
            "DEBUG REJECTION EMAIL — ENABLE_REAL_EMAIL=False",
            email=email, business_name=business_name, reason=reason,
        )
        return

    if not settings.RESEND_API_KEY:
        log.error("RESEND_API_KEY not set — rejection email not sent", email=email)
        return

    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from":    settings.RESEND_FROM_EMAIL,
            "to":      [email],
            "subject": "تحديث حالة طلبك في ناطقة",
            "html":    html,
        })
        log.info("Rejection email sent via admin_routes", email=email)
    except Exception as exc:
        log.error("Rejection email delivery failed", email=email, error=str(exc))

