"""
Database Models — SQLAlchemy 2.0 async
═══════════════════════════════════════
SaaS Hybrid Model (Fresh Build):
  • Organization  — one per company, multi-tenancy root
  • User          — linked to Organization via organization_id
  • Project, Document, Conversation, Message — tenant-scoped
  • AuditLog, RefreshToken — platform-wide
"""
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum as PyEnum
import uuid

from sqlalchemy import (
    String, Boolean, DateTime, Integer,
    Text, ForeignKey, Enum, BigInteger, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════

class UserRole(str, PyEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN       = "admin"
    ORG_ADMIN   = "org_admin"
    EMPLOYEE    = "employee"
    HR_ANALYST  = "hr_analyst"
    ANALYST     = "analyst"
    VIEWER      = "viewer"


class ApprovalStatus(str, PyEnum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentType(str, PyEnum):
    CR        = "cr"
    FREELANCE = "freelance"


class SubscriptionPlan(str, PyEnum):
    FREE       = "FREE"
    TRIAL      = "TRIAL"
    PRO        = "PRO"
    ENTERPRISE = "ENTERPRISE"


class ProjectStatus(str, PyEnum):
    ACTIVE     = "active"
    PAUSED     = "paused"
    DONE       = "done"
    ARCHIVED   = "archived"
    PROCESSING = "processing"


class DocumentStatus(str, PyEnum):
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"


class NotificationType(str, PyEnum):
    INFO    = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR   = "error"


class AuditAction(str, PyEnum):
    LOGIN            = "login"
    LOGOUT           = "logout"
    LOGIN_FAILED     = "login_failed"
    REGISTER         = "register"
    EMAIL_VERIFY     = "email_verify"
    FILE_UPLOAD      = "file_upload"
    FILE_DELETE      = "file_delete"
    PROJECT_CREATE   = "project_create"
    PROJECT_DELETE   = "project_delete"
    QUERY            = "query"
    REPORT_GENERATE  = "report_generate"
    USER_CREATE      = "user_create"
    USER_DELETE      = "user_delete"
    USER_APPROVE     = "user_approve"
    USER_REJECT      = "user_reject"
    SETTINGS_CHANGE  = "settings_change"
    PLAN_UPGRADE     = "plan_upgrade"
    PLAN_DOWNGRADE   = "plan_downgrade"
    TRIAL_ACTIVATE   = "trial_activate"
    TRIAL_EXPIRY     = "trial_expiry"
    USER_INVITE      = "user_invite"
    INVITE_ACCEPT    = "invite_accept"


# ══════════════════════════════════════════════════════════════════════
# ORGANIZATION  — SaaS multi-tenancy root (one per company)
# ══════════════════════════════════════════════════════════════════════

class Organization(Base):
    """
    Each company that registers on NATIQA gets one Organization record.
    All Users and Projects belong to an Organization.
    """
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Tax / Commercial registration number
    tax_number: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )
    # Document type: cr (Commercial Register) or freelance certificate
    document_type: Mapped[Optional[DocumentType]] = mapped_column(
        Enum(DocumentType, name="documenttype"), nullable=True
    )

    # Subscription
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, name="subscriptionplan"),
        server_default="FREE",
        default=SubscriptionPlan.FREE,
    )
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subscription_custom_limits: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=None
    )
    token_balance: Mapped[int] = mapped_column(Integer, default=1000) # Default balance for new orgs

    # Trial
    trial_starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_accepted:    Mapped[bool]              = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Relationships ─────────────────────────────────────────────────
    members:  Mapped[List["User"]]    = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[List["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════
# USER
# ══════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email:           Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name:       Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))

    # ── Organization FK (multi-tenancy) ────────────────────────────────
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # ── Role & Access ─────────────────────────────────────────────────
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="userrole"), default=UserRole.ANALYST)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_accepted:    Mapped[bool]              = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    allowed_depts: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True, default=None)

    # ── B2B Identity (mirrors org — kept for fast queries) ────────────
    business_name:   Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    document_type:   Mapped[Optional[DocumentType]] = mapped_column(Enum(DocumentType, name="documenttype"), nullable=True)
    document_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # ── Marketing Attribution ─────────────────────────────────────────
    referral_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    referred_by:   Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ── Email Verification (OTP) ──────────────────────────────────────
    is_verified: Mapped[bool]              = mapped_column(Boolean, default=False)
    otp_code:    Mapped[Optional[str]]     = mapped_column(String(10), nullable=True)
    otp_expiry:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Admin Approval Workflow ───────────────────────────────────────
    approval_status:  Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approvalstatus"), default=ApprovalStatus.PENDING
    )
    rejection_reason: Mapped[Optional[str]]       = mapped_column(Text, nullable=True)
    approved_by:      Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at:      Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True), nullable=True)

    # ── 2FA / TOTP ────────────────────────────────────────────────────
    totp_secret:  Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool]          = mapped_column(Boolean, default=False)

    # ── Brute-force protection ────────────────────────────────────────
    failed_logins: Mapped[int]               = mapped_column(Integer, default=0)
    locked_until:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Activity ──────────────────────────────────────────────────────
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Computed properties ───────────────────────────────────────────
    @property
    def is_admin(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)

    @property
    def can_access_platform(self) -> bool:
        return self.is_active and self.is_verified and self.approval_status == ApprovalStatus.APPROVED

    # ── Relationships ─────────────────────────────────────────────────
    organization:   Mapped[Optional["Organization"]] = relationship(back_populates="members")
    projects:       Mapped[List["Project"]]      = relationship(back_populates="owner")
    audit_logs:     Mapped[List["AuditLog"]]     = relationship(back_populates="user")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(back_populates="user")
    notifications:  Mapped[List["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    project_memberships: Mapped[List["ProjectMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════
# REFRESH TOKEN
# ══════════════════════════════════════════════════════════════════════

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti:        Mapped[str]       = mapped_column(String(64), unique=True, index=True)
    user_id:    Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True))
    revoked:    Mapped[bool]      = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


# ══════════════════════════════════════════════════════════════════════
# PROJECT
# ══════════════════════════════════════════════════════════════════════

class Project(Base):
    __tablename__ = "projects"

    id:          Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name:        Mapped[str]          = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="projectstatus"), default=ProjectStatus.ACTIVE
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id:   Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization:  Mapped[Optional["Organization"]] = relationship(back_populates="projects")
    owner:         Mapped["User"]               = relationship(back_populates="projects")
    documents:     Mapped[List["Document"]]     = relationship(back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members:       Mapped[List["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════
# DOCUMENT
# ══════════════════════════════════════════════════════════════════════

class Document(Base):
    __tablename__ = "documents"

    id:               Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name:        Mapped[str]          = mapped_column(String(500))
    original_name:    Mapped[str]          = mapped_column(String(500))
    file_path:        Mapped[str]          = mapped_column(String(1000))
    file_size:        Mapped[int]          = mapped_column(BigInteger)
    file_hash:        Mapped[str]          = mapped_column(String(64))
    department:       Mapped[str]          = mapped_column(String(100))
    language:         Mapped[str]          = mapped_column(String(10), default="ar")
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="documentstatus"), default=DocumentStatus.PROCESSING
    )
    chunks_count:     Mapped[int]          = mapped_column(Integer, default=0)
    is_encrypted:     Mapped[bool]         = mapped_column(Boolean, default=True)
    ai_metadata:      Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id:       Mapped[uuid.UUID]    = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    uploaded_by:      Mapped[uuid.UUID]    = mapped_column(ForeignKey("users.id"))
    created_at:       Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="documents")


# ══════════════════════════════════════════════════════════════════════
# CONVERSATION
# ══════════════════════════════════════════════════════════════════════

class Conversation(Base):
    __tablename__ = "conversations"

    id:         Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title:      Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    project_id: Mapped[uuid.UUID]    = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id:    Mapped[uuid.UUID]    = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    project:  Mapped["Project"]       = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


# ══════════════════════════════════════════════════════════════════════
# MESSAGE
# ══════════════════════════════════════════════════════════════════════

class Message(Base):
    __tablename__ = "messages"

    id:               Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role:             Mapped[str]          = mapped_column(String(20))
    content:          Mapped[str]          = mapped_column(Text)
    sources:          Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tokens_used:      Mapped[int]          = mapped_column(Integer, default=0)
    response_time_ms: Mapped[int]          = mapped_column(Integer, default=0)
    conversation_id:  Mapped[uuid.UUID]    = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    created_at:       Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ══════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ══════════════════════════════════════════════════════════════════════

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:            Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:       Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action:        Mapped[AuditAction]  = mapped_column(Enum(AuditAction, name="auditaction"))
    resource_type: Mapped[Optional[str]] = mapped_column(String(50),  nullable=True)
    resource_id:   Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details:       Mapped[Optional[dict]] = mapped_column(JSON,       nullable=True)
    ip_address:    Mapped[Optional[str]] = mapped_column(String(45),  nullable=True)
    user_agent:    Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


# ══════════════════════════════════════════════════════════════════════
# NOTIFICATION
# ══════════════════════════════════════════════════════════════════════

class Notification(Base):
    __tablename__ = "notifications"

    id:         Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:    Mapped[uuid.UUID]    = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id:     Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    type:       Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notificationtype"), default=NotificationType.INFO)
    title:      Mapped[str]          = mapped_column(String(255))
    message:    Mapped[str]          = mapped_column(Text)
    is_read:    Mapped[bool]         = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notifications")


# ══════════════════════════════════════════════════════════════════════
# PROJECT MEMBER
# ══════════════════════════════════════════════════════════════════════

class ProjectMember(Base):
    __tablename__ = "project_members"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id:    Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    added_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="members")
    user:    Mapped["User"]    = relationship(back_populates="project_memberships")


# ══════════════════════════════════════════════════════════════════════
# INVITATION
# ══════════════════════════════════════════════════════════════════════

class Invitation(Base):
    """
    Temporary invitation for a user to join an organization.
    """
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="userrole"), default=UserRole.EMPLOYEE)
    token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    inviter: Mapped["User"] = relationship()


# ══════════════════════════════════════════════════════════════════════
# MESSAGING — Internal org communication system
# ══════════════════════════════════════════════════════════════════════

class ChannelType(str, PyEnum):
    PUBLIC  = "public"   # All org members can join
    PRIVATE = "private"  # Invite-only
    DIRECT  = "direct"   # 1:1 — auto-created, not listed in /channels


class Channel(Base):
    """
    A messaging channel (group or DM thread) scoped to an organization.
    Direct messages are stored as DIRECT channels with exactly 2 members.
    """
    __tablename__ = "channels"

    id:              Mapped[uuid.UUID]       = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID]       = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by:      Mapped[uuid.UUID]       = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name:            Mapped[Optional[str]]   = mapped_column(String(200), nullable=True)   # null for DM
    description:     Mapped[Optional[str]]   = mapped_column(String(500), nullable=True)
    channel_type:    Mapped[ChannelType]     = mapped_column(Enum(ChannelType, name="channeltype"), default=ChannelType.PUBLIC)
    # For DM: store sorted pair "uuid1:uuid2" to find/dedup quickly
    dm_key:          Mapped[Optional[str]]   = mapped_column(String(80), nullable=True, unique=True, index=True)
    created_at:      Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())

    members:  Mapped[List["ChannelMember"]]  = relationship(back_populates="channel", cascade="all, delete-orphan")
    messages: Mapped[List["ChannelMessage"]] = relationship(back_populates="channel", cascade="all, delete-orphan",
                                                             order_by="ChannelMessage.created_at")


class ChannelMember(Base):
    """Membership record — who is in a channel."""
    __tablename__ = "channel_members"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    user_id:    Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id",    ondelete="CASCADE"), index=True)
    is_admin:   Mapped[bool]      = mapped_column(Boolean, default=False)
    joined_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Track last seen message for unread count
    last_read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    channel: Mapped["Channel"] = relationship(back_populates="members")
    user:    Mapped["User"]    = relationship()


class ChannelMessage(Base):
    """A single message inside a channel or DM thread."""
    __tablename__ = "channel_messages"

    id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID]      = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    sender_id:  Mapped[uuid.UUID]      = mapped_column(ForeignKey("users.id",    ondelete="CASCADE"), index=True)
    content:    Mapped[str]            = mapped_column(Text, nullable=False)
    # Optional: link message to a document or project for context
    ref_doc_id:     Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    ref_project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # edited / deleted
    edited_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool]               = mapped_column(Boolean, default=False)
    # reactions stored as JSON: {"👍": ["user_id1", ...], "❤️": [...]}
    reactions:  Mapped[Optional[dict]]     = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    channel: Mapped["Channel"] = relationship(back_populates="messages")
    sender:  Mapped["User"]    = relationship()
