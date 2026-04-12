"""
╔══════════════════════════════════════════════════════════════════════╗
║  NATIQA — User Management API  (IAM Layer)                           ║
║                                                                      ║
║  POST   /api/users              ← إنشاء موظف جديد       (admin+)   ║
║  GET    /api/users              ← قائمة المستخدمين       (admin+)   ║
║  GET    /api/users/me/perms     ← صلاحياتي               (أي مستخدم)║
║  GET    /api/users/{id}         ← بيانات مستخدم          (admin+)   ║
║  PATCH  /api/users/{id}         ← تحديث اسم/دور/أقسام   (admin+)   ║
║  PATCH  /api/users/{id}/depts   ← تغيير الأقسام فقط      (admin+)   ║
║  DELETE /api/users/{id}         ← تعطيل (soft-delete)    (admin+)   ║
║  POST   /api/users/{id}/reset   ← إعادة تعيين كلمة مرور  (admin+)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin, log_audit
from app.core.security import hash_password
from app.models.models import User, UserRole, AuditAction

router = APIRouter(prefix="/users", tags=["User Management"])

ALL_DEPTS: set[str] = {
    "financial", "hr", "legal", "technical",
    "admin", "sales", "general",
}

ROLE_DEFAULT_DEPTS: dict = {
    UserRole.SUPER_ADMIN : sorted(ALL_DEPTS),
    UserRole.ADMIN       : sorted(ALL_DEPTS),
    UserRole.HR_ANALYST  : ["hr", "admin", "general"],
    UserRole.ANALYST     : ["general"],
    UserRole.VIEWER      : ["general"],
}


def resolve_depts(role, requested):
    if requested is not None:
        valid = sorted(set(requested) & ALL_DEPTS)
        return valid if valid else ROLE_DEFAULT_DEPTS.get(role, ["general"])
    return ROLE_DEFAULT_DEPTS.get(role, ["general"])


def user_to_dict(u: User) -> dict:
    depts = u.allowed_depts
    if not depts:
        depts = ROLE_DEFAULT_DEPTS.get(u.role, ["general"])
    return {
        "id"            : str(u.id),
        "email"         : u.email,
        "full_name"     : u.full_name,
        "role"          : u.role.value,
        "is_active"     : u.is_active,
        "allowed_depts" : depts,
        "created_at"    : u.created_at.isoformat() if u.created_at else None,
        "last_login"    : u.last_login.isoformat() if u.last_login else None,
    }


class CreateUserBody(BaseModel):
    email        : EmailStr
    full_name    : str      = Field(..., min_length=2, max_length=100)
    password     : str      = Field(..., min_length=8)
    role         : UserRole = UserRole.ANALYST
    allowed_depts: Optional[List[str]] = None

    @field_validator("allowed_depts", mode="before")
    @classmethod
    def check_depts(cls, v):
        if v is None:
            return v
        bad = set(v) - ALL_DEPTS
        if bad:
            raise ValueError(f"أقسام غير معروفة: {', '.join(bad)}")
        return list(set(v))


class UpdateUserBody(BaseModel):
    full_name    : Optional[str]       = None
    is_active    : Optional[bool]      = None
    role         : Optional[UserRole]  = None
    allowed_depts: Optional[List[str]] = None

    @field_validator("allowed_depts", mode="before")
    @classmethod
    def check_depts(cls, v):
        if v is None:
            return v
        bad = set(v) - ALL_DEPTS
        if bad:
            raise ValueError(f"أقسام غير معروفة: {', '.join(bad)}")
        return list(set(v))


class ChangeDeptBody(BaseModel):
    allowed_depts: List[str]

    @field_validator("allowed_depts")
    @classmethod
    def check_depts(cls, v):
        bad = set(v) - ALL_DEPTS
        if bad:
            raise ValueError(f"أقسام غير معروفة: {', '.join(bad)}")
        return list(set(v))


class ResetPwBody(BaseModel):
    new_password: str = Field(..., min_length=8)


# ─── GET /users/me/perms ──────────────────────────────────────────────
@router.get("/me/perms", summary="صلاحياتي الحالية")
async def my_permissions(current: User = Depends(get_current_user)):
    depts    = current.allowed_depts or ROLE_DEFAULT_DEPTS.get(current.role, ["general"])
    is_admin = current.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)
    return {
        "role"         : current.role.value,
        "allowed_depts": depts,
        "can_upload"   : current.role != UserRole.VIEWER,
        "can_delete"   : is_admin,
        "can_admin"    : is_admin,
        "see_all_depts": is_admin,
    }


# ─── GET /users ───────────────────────────────────────────────────────
@router.get("", summary="قائمة جميع المستخدمين")
async def list_users(
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [user_to_dict(u) for u in result.scalars().all()]


# ─── POST /users ──────────────────────────────────────────────────────
@router.post("", status_code=201, summary="إنشاء موظف جديد")
async def create_user(
    body   : CreateUserBody,
    request: Request,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    dup = await db.execute(select(User).where(User.email == body.email))
    if dup.scalar_one_or_none():
        raise HTTPException(400, "البريد الإلكتروني مستخدم مسبقاً")

    if body.role == UserRole.SUPER_ADMIN and current.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "إنشاء super_admin يتطلب صلاحية super_admin")

    depts = resolve_depts(body.role, body.allowed_depts)
    user  = User(
        email           = body.email,
        full_name       = body.full_name,
        hashed_password = hash_password(body.password),
        role            = body.role,
        allowed_depts   = depts,
        is_active       = True,
    )
    db.add(user)
    await db.flush()
    await log_audit(
        db, AuditAction.USER_CREATE,
        user_id=current.id, resource_type="user", resource_id=str(user.id),
        details={"email": body.email, "role": body.role.value, "depts": depts},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)


# ─── GET /users/{id} ──────────────────────────────────────────────────
@router.get("/{user_id}", summary="بيانات مستخدم محدد")
async def get_user(
    user_id: str,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "معرّف غير صحيح")
    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    return user_to_dict(user)


# ─── PATCH /users/{id} ────────────────────────────────────────────────
@router.patch("/{user_id}", summary="تحديث بيانات مستخدم")
async def update_user(
    user_id: str,
    body   : UpdateUserBody,
    request: Request,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "معرّف غير صحيح")
    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if user.role == UserRole.SUPER_ADMIN and current.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "لا يمكن تعديل super_admin")

    changes: dict = {}
    if body.full_name is not None:
        user.full_name       = body.full_name
        changes["full_name"] = body.full_name
    if body.is_active is not None:
        user.is_active       = body.is_active
        changes["is_active"] = body.is_active
    if body.role is not None:
        user.role            = body.role
        user.allowed_depts   = resolve_depts(body.role, body.allowed_depts)
        changes["role"]      = body.role.value
        changes["depts"]     = user.allowed_depts
    elif body.allowed_depts is not None:
        user.allowed_depts   = sorted(set(body.allowed_depts) & ALL_DEPTS)
        changes["depts"]     = user.allowed_depts

    if changes:
        await log_audit(
            db, AuditAction.SETTINGS_CHANGE,
            user_id=current.id, resource_type="user", resource_id=user_id,
            details=changes,
            ip_address=request.client.host if request.client else None,
        )
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)


# ─── PATCH /users/{id}/depts ──────────────────────────────────────────
@router.patch("/{user_id}/depts", summary="تعديل الأقسام المسموحة")
async def change_depts(
    user_id: str,
    body   : ChangeDeptBody,
    request: Request,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "معرّف غير صحيح")
    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")

    old_depts          = user.allowed_depts
    user.allowed_depts = sorted(set(body.allowed_depts) & ALL_DEPTS)
    await log_audit(
        db, AuditAction.SETTINGS_CHANGE,
        user_id=current.id, resource_type="user", resource_id=user_id,
        details={"old_depts": old_depts, "new_depts": user.allowed_depts},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(user)
    return user_to_dict(user)


# ─── DELETE /users/{id} ───────────────────────────────────────────────
@router.delete("/{user_id}", status_code=204, summary="تعطيل حساب مستخدم")
async def deactivate_user(
    user_id: str,
    request: Request,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    if user_id == str(current.id):
        raise HTTPException(400, "لا يمكنك تعطيل حسابك الخاص")
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "معرّف غير صحيح")
    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if user.role == UserRole.SUPER_ADMIN and current.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "لا يمكن تعطيل super_admin")

    user.is_active = False
    await log_audit(
        db, AuditAction.USER_DELETE,
        user_id=current.id, resource_type="user", resource_id=user_id,
        details={"email": user.email},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()


# ─── POST /users/{id}/reset ───────────────────────────────────────────
@router.post("/{user_id}/reset", summary="إعادة تعيين كلمة مرور")
async def reset_password(
    user_id: str,
    body   : ResetPwBody,
    request: Request,
    db     : AsyncSession = Depends(get_db),
    current: User         = Depends(require_admin),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(400, "معرّف غير صحيح")
    result = await db.execute(select(User).where(User.id == uid))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")

    user.hashed_password = hash_password(body.new_password)
    user.failed_logins   = 0
    user.locked_until    = None
    await log_audit(
        db, AuditAction.SETTINGS_CHANGE,
        user_id=current.id, resource_type="user", resource_id=user_id,
        details={"action": "password_reset"},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return {"ok": True, "message": "تم تغيير كلمة المرور بنجاح"}
