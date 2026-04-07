"""initial_schema_all_tables

Revision ID: 0001
Revises:
Create Date: 2026-04-07

Baseline migration — captures the full current schema (14 tables) so
future incremental migrations (alembic revision --autogenerate) have a
starting point. If tables already exist (first deploy that ran
init_db/create_all), run:
    alembic stamp head
to mark this migration as applied without re-executing it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ══════════════════════════════════════════════════════════════════════
# UPGRADE — create all tables from scratch
# ══════════════════════════════════════════════════════════════════════

def upgrade() -> None:

    # ── Enum types ─────────────────────────────────────────────────────
    # Create PostgreSQL ENUM types before the tables that depend on them.

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE documenttype     AS ENUM ('cr', 'freelance');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE subscriptionplan AS ENUM ('FREE', 'TRIAL', 'PRO', 'ENTERPRISE');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE userrole AS ENUM (
                'super_admin', 'admin', 'org_admin',
                'employee', 'hr_analyst', 'analyst', 'viewer'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE approvalstatus   AS ENUM ('pending', 'approved', 'rejected');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE projectstatus    AS ENUM ('active', 'paused', 'done', 'archived', 'processing');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE documentstatus   AS ENUM ('processing', 'ready', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE notificationtype AS ENUM ('info', 'success', 'warning', 'error');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE auditaction AS ENUM (
                'login', 'logout', 'login_failed', 'register', 'email_verify',
                'file_upload', 'file_delete', 'project_create', 'project_delete',
                'query', 'report_generate', 'user_create', 'user_delete',
                'user_approve', 'user_reject', 'settings_change',
                'plan_upgrade', 'plan_downgrade', 'trial_activate', 'trial_expiry',
                'user_invite', 'invite_accept'
            );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN
            CREATE TYPE channeltype AS ENUM ('public', 'private', 'direct');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    # ── organizations ──────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("tax_number", sa.String(100), nullable=True, unique=True),
        sa.Column("document_type", sa.Enum("cr", "freelance", name="documenttype"), nullable=True),
        sa.Column("subscription_plan",
                  sa.Enum("FREE", "TRIAL", "PRO", "ENTERPRISE", name="subscriptionplan"),
                  nullable=False, server_default="FREE"),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_custom_limits", sa.JSON(), nullable=True),
        sa.Column("trial_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── users ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("role",
                  sa.Enum("super_admin", "admin", "org_admin", "employee",
                           "hr_analyst", "analyst", "viewer", name="userrole"),
                  nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allowed_depts", sa.JSON(), nullable=True),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("document_type", sa.Enum("cr", "freelance", name="documenttype"), nullable=True),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("referral_code", sa.String(50), nullable=True, unique=True),
        sa.Column("referred_by", sa.String(50), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("otp_code", sa.String(10), nullable=True),
        sa.Column("otp_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_status",
                  sa.Enum("pending", "approved", "rejected", name="approvalstatus"),
                  nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── refresh_tokens ─────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── projects ───────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status",
                  sa.Enum("active", "paused", "done", "archived", "processing", name="projectstatus"),
                  nullable=False, server_default="active"),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── documents ──────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=True),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("department", sa.String(100), nullable=True, index=True),
        sa.Column("language", sa.String(10), nullable=True, server_default="ar"),
        sa.Column("status",
                  sa.Enum("processing", "ready", "failed", name="documentstatus"),
                  nullable=False, server_default="processing"),
        sa.Column("chunks_count", sa.Integer(), nullable=True),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("ai_metadata", sa.JSON(), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── conversations ──────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── messages ───────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── audit_logs ─────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("action",
                  sa.Enum("login", "logout", "login_failed", "register", "email_verify",
                           "file_upload", "file_delete", "project_create", "project_delete",
                           "query", "report_generate", "user_create", "user_delete",
                           "user_approve", "user_reject", "settings_change",
                           "plan_upgrade", "plan_downgrade", "trial_activate", "trial_expiry",
                           "user_invite", "invite_accept", name="auditaction"),
                  nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False, index=True),
    )

    # ── notifications ──────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("type",
                  sa.Enum("info", "success", "warning", "error", name="notificationtype"),
                  nullable=False, server_default="info"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── project_members ────────────────────────────────────────────────
    op.create_table(
        "project_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── invitations ────────────────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("role",
                  sa.Enum("super_admin", "admin", "org_admin", "employee",
                           "hr_analyst", "analyst", "viewer", name="userrole"),
                  nullable=False, server_default="employee"),
        sa.Column("token", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── channels ───────────────────────────────────────────────────────
    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("channel_type",
                  sa.Enum("public", "private", "direct", name="channeltype"),
                  nullable=False, server_default="public"),
        sa.Column("dm_key", sa.String(80), nullable=True, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── channel_members ────────────────────────────────────────────────
    op.create_table(
        "channel_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── channel_messages ───────────────────────────────────────────────
    op.create_table(
        "channel_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ref_doc_id", sa.String(36), nullable=True),
        sa.Column("ref_project_id", sa.String(36), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reactions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False, index=True),
    )


# ══════════════════════════════════════════════════════════════════════
# DOWNGRADE — drop all tables in reverse dependency order
# ══════════════════════════════════════════════════════════════════════

def downgrade() -> None:
    op.drop_table("channel_messages")
    op.drop_table("channel_members")
    op.drop_table("channels")
    op.drop_table("invitations")
    op.drop_table("project_members")
    op.drop_table("notifications")
    op.drop_table("audit_logs")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("documents")
    op.drop_table("projects")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("organizations")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS channeltype")
    op.execute("DROP TYPE IF EXISTS auditaction")
    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS projectstatus")
    op.execute("DROP TYPE IF EXISTS approvalstatus")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS subscriptionplan")
    op.execute("DROP TYPE IF EXISTS documenttype")
