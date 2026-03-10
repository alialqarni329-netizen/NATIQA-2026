-- ============================================================
--  NATIQA Phase 1 B2B -- Database Migration SQL
--  Run:  docker exec -i natiqa_db psql -U natiqa_admin -d natiqa < migrate_phase1.sql
-- ============================================================

\echo '>>> Step 1: Creating ENUM types'

DO $$ BEGIN
    CREATE TYPE documenttype AS ENUM ('cr', 'freelance');
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'documenttype already exists, skipping.';
END $$;

DO $$ BEGIN
    CREATE TYPE approvalstatus AS ENUM ('pending', 'approved', 'rejected');
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'approvalstatus already exists, skipping.';
END $$;

\echo '>>> Step 2: Extending AuditAction ENUM'
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'register';
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'email_verify';
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_approve';
ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_reject';

\echo '>>> Step 3: Adding Phase 1 columns to users table'
ALTER TABLE users ADD COLUMN IF NOT EXISTS business_name    VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS document_type    documenttype;
ALTER TABLE users ADD COLUMN IF NOT EXISTS document_number  VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code    VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by      VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_code         VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_expiry       TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status  approvalstatus NOT NULL DEFAULT 'pending';
ALTER TABLE users ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by      UUID;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at      TIMESTAMPTZ;

\echo '>>> Step 4: Creating indexes'
CREATE INDEX IF NOT EXISTS ix_users_document_number
    ON users(document_number);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code
    ON users(referral_code)
    WHERE referral_code IS NOT NULL;

\echo '>>> Step 5: Back-filling existing users (approved + verified)'
UPDATE users
   SET is_verified     = TRUE,
       approval_status = 'approved'
 WHERE is_verified = FALSE
   AND approval_status = 'pending';

\echo '>>> Step 6: Verification'
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
  AND column_name IN (
      'business_name', 'document_type', 'document_number',
      'referral_code', 'referred_by', 'is_verified',
      'otp_code', 'otp_expiry', 'approval_status',
      'rejection_reason', 'approved_by', 'approved_at'
  )
ORDER BY column_name;

\echo '>>> Migration complete. Users summary:'
SELECT
    COUNT(*)                                              AS total_users,
    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) AS approved,
    SUM(CASE WHEN approval_status = 'pending'  THEN 1 ELSE 0 END) AS pending,
    SUM(CASE WHEN is_verified = TRUE           THEN 1 ELSE 0 END) AS email_verified
FROM users;
