-- ═══════════════════════════════════════════════════════════════
--  NATIQA v9 — Token Monetization & ORG_ADMIN Role
-- ═══════════════════════════════════════════════════════════════

-- 1. Add token_balance to organizations
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS token_balance INTEGER DEFAULT 1000;

-- 2. Add ORG_ADMIN to userrole enum (if not exists)
-- Note: PostgreSQL doesn't support IF NOT EXISTS for ENUM values directly in a simple way
-- We use a DO block to safely add it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = 'userrole' AND e.enumlabel = 'org_admin') THEN
        ALTER TYPE userrole ADD VALUE 'org_admin';
    END IF;
END
$$;
