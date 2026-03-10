-- migrate_trial.sql — Golden Trial DB Migration
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS trial_starts_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS trial_ends_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_trial_ends_at
  ON users (trial_ends_at)
  WHERE trial_ends_at IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
    WHERE enumlabel = 'trial_activate'
      AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'auditaction')
  ) THEN
    ALTER TYPE auditaction ADD VALUE 'trial_activate';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
    WHERE enumlabel = 'trial_expiry'
      AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'auditaction')
  ) THEN
    ALTER TYPE auditaction ADD VALUE 'trial_expiry';
  END IF;
END
$$;
