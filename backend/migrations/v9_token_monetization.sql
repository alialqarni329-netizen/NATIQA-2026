-- ═══════════════════════════════════════════════════════════════
--  NATIQA v9 — Token Monetization, ORG_ADMIN Role & Multi-Tenancy Fix
-- ═══════════════════════════════════════════════════════════════

-- 1. Add token_balance to organizations
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS token_balance INTEGER DEFAULT 1000;

-- 2. Add ORG_ADMIN to userrole enum (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = 'userrole' AND e.enumlabel = 'org_admin') THEN
        ALTER TYPE userrole ADD VALUE 'org_admin';
    END IF;
END
$$;

-- 3. Add organization_id to projects (Missing Multi-Tenancy Column)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects(organization_id);

-- 4. Backfill existing projects with their owner's organization_id
UPDATE projects
SET organization_id = users.organization_id
FROM users
WHERE projects.owner_id = users.id AND projects.organization_id IS NULL;
