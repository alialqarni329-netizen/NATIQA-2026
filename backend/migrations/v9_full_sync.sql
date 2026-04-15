-- ═══════════════════════════════════════════════════════════════
--  NATIQA v9 — Full Production Synchronization Script
-- ═══════════════════════════════════════════════════════════════

-- 1. Handle Enums safely
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscriptionplan') THEN
        CREATE TYPE subscriptionplan AS ENUM ('FREE', 'TRIAL', 'PRO', 'ENTERPRISE');
    END IF;
END $$;

-- 2. Add monetization columns to organizations
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_plan subscriptionplan DEFAULT 'FREE' NOT NULL;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS token_balance INTEGER DEFAULT 1000 NOT NULL;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_custom_limits JSON;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_starts_at TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;

-- 3. Add organization_id to projects (Multi-Tenancy Column)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects(organization_id);

-- 4. Backfill existing projects with their owner's organization_id
UPDATE projects
SET organization_id = users.organization_id
FROM users
WHERE projects.owner_id = users.id AND projects.organization_id IS NULL;

-- 5. Handle UserRole enum update for ORG_ADMIN
ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'org_admin';

-- 6. Verification
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('organizations', 'projects')
  AND column_name IN ('token_balance', 'subscription_plan', 'organization_id');
