-- ═══════════════════════════════════════════════════════════════
--  NATIQA — Migration v7: MVP Organization Management
--  Adds Invitations, Terms Acceptance, and New Roles
-- ═══════════════════════════════════════════════════════════════

BEGIN;

-- 1. Update Enums for new roles and actions
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'userrole'::regtype AND enumlabel = 'org_admin') THEN
        ALTER TYPE userrole ADD VALUE 'org_admin';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'userrole'::regtype AND enumlabel = 'employee') THEN
        ALTER TYPE userrole ADD VALUE 'employee';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'user_invite') THEN
        ALTER TYPE auditaction ADD VALUE 'user_invite';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'auditaction'::regtype AND enumlabel = 'invite_accept') THEN
        ALTER TYPE auditaction ADD VALUE 'invite_accept';
    END IF;
END $$;

-- 2. Add Terms Acceptance to Organizations and Users
ALTER TABLE organizations 
    ADD COLUMN IF NOT EXISTS terms_accepted BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS terms_accepted BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;

-- 3. Create Invitations Table
CREATE TABLE IF NOT EXISTS invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL,
    role            userrole NOT NULL DEFAULT 'employee',
    token           VARCHAR(100) NOT NULL UNIQUE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    invited_by      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_invitations_email           ON invitations(email);
CREATE INDEX IF NOT EXISTS ix_invitations_token           ON invitations(token);
CREATE INDEX IF NOT EXISTS ix_invitations_organization_id ON invitations(organization_id);

COMMIT;

-- Verification
DO $$
DECLARE
    role_exists_1 BOOLEAN;
    role_exists_2 BOOLEAN;
    table_exists BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'userrole'::regtype AND enumlabel = 'org_admin') INTO role_exists_1;
    SELECT EXISTS (SELECT 1 FROM pg_enum WHERE enumtypid = 'userrole'::regtype AND enumlabel = 'employee') INTO role_exists_2;
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'invitations') INTO table_exists;

    IF role_exists_1 AND role_exists_2 AND table_exists THEN
        RAISE NOTICE '✅ Migration v7 تم بنجاح — الأدوار الجديدة والجدول تمت إضافتها';
    ELSE
        RAISE WARNING '⚠️ Migration v7 قد يكون ناقصاً';
    END IF;
END $$;
