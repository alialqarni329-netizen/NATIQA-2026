-- ═══════════════════════════════════════════════════════════════
--  NATIQA SaaS Platform — Initial Schema (Fresh Build)
--  Run this ONCE on a brand new PostgreSQL database.
--  Database: natiqa  |  User: natiqa_admin
-- ═══════════════════════════════════════════════════════════════

-- ── Extensions ─────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Custom ENUM types ───────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE userrole AS ENUM ('super_admin','admin','hr_analyst','analyst','viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE approvalstatus AS ENUM ('pending','approved','rejected');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE documenttype AS ENUM ('cr','freelance');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE subscriptionplan AS ENUM ('free','trial','pro','enterprise');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE projectstatus AS ENUM ('active','paused','done','archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE documentstatus AS ENUM ('processing','ready','failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE auditaction AS ENUM (
        'login','logout','login_failed','register','email_verify',
        'file_upload','file_delete','project_create','project_delete',
        'query','report_generate','user_create','user_delete',
        'user_approve','user_reject','settings_change',
        'plan_upgrade','plan_downgrade','trial_activate','trial_expiry'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── ORGANIZATIONS ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                        VARCHAR(255) NOT NULL,
    tax_number                  VARCHAR(100) UNIQUE,
    document_type               documenttype,
    subscription_plan           subscriptionplan NOT NULL DEFAULT 'free',
    subscription_expires_at     TIMESTAMPTZ,
    subscription_custom_limits  JSONB,
    trial_starts_at             TIMESTAMPTZ,
    trial_ends_at               TIMESTAMPTZ,
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_organizations_name       ON organizations(name);
CREATE INDEX IF NOT EXISTS ix_organizations_tax_number ON organizations(tax_number);

-- ── USERS ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               VARCHAR(255) NOT NULL UNIQUE,
    full_name           VARCHAR(255) NOT NULL,
    hashed_password     VARCHAR(255) NOT NULL,

    -- Multi-tenancy link
    organization_id     UUID REFERENCES organizations(id) ON DELETE SET NULL,

    -- Role & access
    role                userrole NOT NULL DEFAULT 'analyst',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_depts       JSONB,

    -- B2B identity (mirrors org for fast queries)
    business_name       VARCHAR(255),
    document_type       documenttype,
    document_number     VARCHAR(100),

    -- Marketing
    referral_code       VARCHAR(50) UNIQUE,
    referred_by         VARCHAR(50),

    -- Email verification
    is_verified         BOOLEAN NOT NULL DEFAULT FALSE,
    otp_code            VARCHAR(10),
    otp_expiry          TIMESTAMPTZ,

    -- Admin approval
    approval_status     approvalstatus NOT NULL DEFAULT 'pending',
    rejection_reason    TEXT,
    approved_by         UUID,
    approved_at         TIMESTAMPTZ,

    -- 2FA
    totp_secret         VARCHAR(64),
    totp_enabled        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Brute-force
    failed_logins       INTEGER NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,

    -- Activity
    last_login          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_users_email           ON users(email);
CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users(organization_id);
CREATE INDEX IF NOT EXISTS ix_users_document_number ON users(document_number);
CREATE INDEX IF NOT EXISTS ix_users_referral_code   ON users(referral_code);

-- ── REFRESH TOKENS ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jti         VARCHAR(64) NOT NULL UNIQUE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_jti ON refresh_tokens(jti);

-- ── PROJECTS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    status          projectstatus NOT NULL DEFAULT 'active',
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects(organization_id);

-- ── DOCUMENTS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name        VARCHAR(500) NOT NULL,
    original_name    VARCHAR(500) NOT NULL,
    file_path        VARCHAR(1000) NOT NULL,
    file_size        BIGINT NOT NULL,
    file_hash        VARCHAR(64) NOT NULL,
    department       VARCHAR(100) NOT NULL,
    language         VARCHAR(10) NOT NULL DEFAULT 'ar',
    status           documentstatus NOT NULL DEFAULT 'processing',
    chunks_count     INTEGER NOT NULL DEFAULT 0,
    is_encrypted     BOOLEAN NOT NULL DEFAULT TRUE,
    processing_error TEXT,
    project_id       UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uploaded_by      UUID NOT NULL REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── CONVERSATIONS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(500),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── MESSAGES ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role             VARCHAR(20) NOT NULL,
    content          TEXT NOT NULL,
    sources          JSONB,
    tokens_used      INTEGER NOT NULL DEFAULT 0,
    response_time_ms INTEGER NOT NULL DEFAULT 0,
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── AUDIT LOGS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES users(id),
    action        auditaction NOT NULL,
    resource_type VARCHAR(50),
    resource_id   VARCHAR(100),
    details       JSONB,
    ip_address    VARCHAR(45),
    user_agent    VARCHAR(500),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id    ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs(created_at DESC);

-- ══════════════════════════════════════════════════════════════════
--  SEED: Default Platform Superadmin
--  Password: Admin@2025! (bcrypt hash — change after first login)
-- ══════════════════════════════════════════════════════════════════
INSERT INTO users (
    id, email, full_name, hashed_password,
    role, is_active, is_verified, approval_status
)
VALUES (
    gen_random_uuid(),
    'admin@natiqa.com',
    'Platform Admin',
    -- This is a placeholder hash. Run force_admin.py after boot to set a real bcrypt hash.
    'PLACEHOLDER_RUN_FORCE_ADMIN',
    'super_admin', TRUE, TRUE, 'approved'
)
ON CONFLICT (email) DO NOTHING;

SELECT 'NATIQA SaaS schema initialized successfully.' AS status;
