-- ============================================================
--  NATIQA Phase 2 — Subscription Engine Migration
--  Run: docker exec -i natiqa_db psql -U natiqa_admin -d natiqa < migrate_phase2.sql
--  Safe to re-run (IF NOT EXISTS / IF VALUE NOT EXISTS throughout)
-- ============================================================

\echo '>>> Step 1: Create subscriptionplan ENUM'
DO $$ BEGIN
    CREATE TYPE subscriptionplan AS ENUM ('free', 'pro', 'enterprise');
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'subscriptionplan already exists, skipping.';
END $$;

\echo '>>> Step 2: Extend auditaction ENUM'
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'plan_upgrade';
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'plan_downgrade';

\echo '>>> Step 3: Add subscription columns to users table'
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_plan
        subscriptionplan NOT NULL DEFAULT 'free';

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_custom_limits
        JSONB;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_expires_at
        TIMESTAMPTZ;

\echo '>>> Step 4: Index on subscription_plan for admin queries'
CREATE INDEX IF NOT EXISTS ix_users_subscription_plan
    ON users(subscription_plan);

\echo '>>> Step 5: Back-fill — all existing approved users get free plan'
UPDATE users
   SET subscription_plan = 'free'
 WHERE subscription_plan IS NULL;

\echo '>>> Step 6: Verification'
SELECT
    column_name,
    data_type,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
  AND column_name IN (
      'subscription_plan',
      'subscription_custom_limits',
      'subscription_expires_at'
  )
ORDER BY column_name;

\echo '>>> Step 7: Usage summary by plan'
SELECT
    subscription_plan,
    COUNT(*)             AS total_users,
    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) AS approved,
    SUM(CASE WHEN approval_status = 'pending'  THEN 1 ELSE 0 END) AS pending
FROM users
GROUP BY subscription_plan
ORDER BY subscription_plan;

\echo '>>> Phase 2 migration complete.'
