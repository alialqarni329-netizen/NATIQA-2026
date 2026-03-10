#!/usr/bin/env python3
"""
migrate_phase1.py
=================
Phase 1 B2B SaaS — Database Migration Runner
Run this INSIDE the natiqa_backend container or from the project root:

  docker exec natiqa_backend python migrate_phase1.py
  -- OR --
  docker exec -i natiqa_db psql -U natiqa_admin -d natiqa < migrate_phase1.sql

Environment variables read from process env (set by docker-compose):
  DATABASE_URL  postgresql+asyncpg://user:pass@host:5432/db
"""
import asyncio
import os
import sys

# ── Detect DATABASE_URL ──────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set.")
    print("  Run inside Docker: docker exec natiqa_backend python migrate_phase1.py")
    sys.exit(1)

# asyncpg needs postgresql:// not postgresql+asyncpg://
PG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://") \
                      .replace("postgresql+psycopg2://", "postgresql://")

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg not installed. Run: pip install asyncpg")
    sys.exit(1)


# ── SQL Statements ───────────────────────────────────────────────────
UPGRADE_STEPS = [
    # 1. New ENUM types
    ("Creating documenttype ENUM",
     """DO $$ BEGIN
         CREATE TYPE documenttype AS ENUM ('cr', 'freelance');
     EXCEPTION WHEN duplicate_object THEN
         RAISE NOTICE 'documenttype already exists, skipping.';
     END $$;"""),

    ("Creating approvalstatus ENUM",
     """DO $$ BEGIN
         CREATE TYPE approvalstatus AS ENUM ('pending', 'approved', 'rejected');
     EXCEPTION WHEN duplicate_object THEN
         RAISE NOTICE 'approvalstatus already exists, skipping.';
     END $$;"""),

    # 2. Extend AuditAction ENUM
    ("Adding register to auditaction",
     "ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'register'"),
    ("Adding email_verify to auditaction",
     "ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'email_verify'"),
    ("Adding user_approve to auditaction",
     "ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_approve'"),
    ("Adding user_reject to auditaction",
     "ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_reject'"),

    # 3. Add B2B columns to users table
    ("Adding business_name column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS business_name VARCHAR(255)"),
    ("Adding document_type column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS document_type documenttype"),
    ("Adding document_number column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS document_number VARCHAR(100)"),
    ("Adding referral_code column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(50)"),
    ("Adding referred_by column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by VARCHAR(50)"),
    ("Adding is_verified column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE"),
    ("Adding otp_code column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_code VARCHAR(64)"),
    ("Adding otp_expiry column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_expiry TIMESTAMPTZ"),
    ("Adding approval_status column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status approvalstatus NOT NULL DEFAULT 'pending'"),
    ("Adding rejection_reason column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS rejection_reason TEXT"),
    ("Adding approved_by column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by UUID"),
    ("Adding approved_at column",
     "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ"),

    # 4. Indexes
    ("Creating index on document_number",
     "CREATE INDEX IF NOT EXISTS ix_users_document_number ON users(document_number)"),
    ("Creating unique index on referral_code",
     "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users(referral_code) WHERE referral_code IS NOT NULL"),

    # 5. Back-fill: all existing admin-created users are already verified & approved
    ("Back-filling existing users to approved+verified",
     """UPDATE users
        SET is_verified     = TRUE,
            approval_status = 'approved'
        WHERE is_verified = FALSE
          AND approval_status = 'pending'"""),
]

VERIFY_SQL = """
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'users'
  AND column_name IN (
      'business_name', 'document_type', 'document_number',
      'referral_code', 'referred_by', 'is_verified',
      'otp_code', 'otp_expiry', 'approval_status',
      'rejection_reason', 'approved_by', 'approved_at'
  )
ORDER BY column_name;
"""


async def run_migration():
    print("=" * 60)
    print("  NATIQA Phase 1 — Database Migration")
    print("=" * 60)
    print(f"  Connecting to: {PG_URL[:40]}...")

    conn = await asyncpg.connect(PG_URL)
    try:
        errors = []
        for label, sql in UPGRADE_STEPS:
            try:
                await conn.execute(sql)
                print(f"  [OK ] {label}")
            except Exception as e:
                print(f"  [ERR] {label}: {e}")
                errors.append((label, str(e)))

        print()
        print("-" * 60)
        print("  VERIFICATION — users table columns:")
        print("-" * 60)
        rows = await conn.fetch(VERIFY_SQL)
        expected = {
            'business_name', 'document_type', 'document_number',
            'referral_code', 'referred_by', 'is_verified',
            'otp_code', 'otp_expiry', 'approval_status',
            'rejection_reason', 'approved_by', 'approved_at'
        }
        found = set()
        for row in rows:
            print(f"    {row['column_name']:<20} {row['data_type']:<25} nullable={row['is_nullable']}")
            found.add(row['column_name'])

        missing = expected - found
        print()
        if missing:
            print(f"  WARNING: Missing columns: {missing}")
        else:
            print("  ALL 12 PHASE 1 COLUMNS PRESENT ✓")

        print()
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        approved = await conn.fetchval("SELECT COUNT(*) FROM users WHERE approval_status = 'approved'")
        print(f"  Users total:    {count}")
        print(f"  Users approved: {approved}")

        if errors:
            print(f"\n  {len(errors)} step(s) had errors — review above")
        else:
            print("\n  Migration completed successfully.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
