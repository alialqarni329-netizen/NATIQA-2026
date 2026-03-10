#!/usr/bin/env python3
"""
test_approve_user.py
====================
Temporary admin approval test script for Phase 1.
Shows exactly how approval logic works — mirrors admin_routes.py behaviour.

Usage (inside natiqa_backend container):
  docker exec natiqa_backend python test_approve_user.py

Or pass email directly:
  docker exec natiqa_backend python test_approve_user.py user@company.com
  docker exec natiqa_backend python test_approve_user.py user@company.com reject "Missing docs"
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone


# ── DB connection ────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: Set DATABASE_URL or run inside the backend container.")
    sys.exit(1)

PG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://") \
                      .replace("postgresql+psycopg2://", "postgresql://")

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg not installed.")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────
DIVIDER = "=" * 60

def _print_user(row):
    print(f"  ID:              {row['id']}")
    print(f"  Email:           {row['email']}")
    print(f"  Full Name:       {row['full_name']}")
    print(f"  Business Name:   {row['business_name'] or '—'}")
    print(f"  Document Type:   {row['document_type'] or '—'}")
    print(f"  Document Number: {row['document_number'] or '—'}")
    print(f"  Referral Code:   {row['referral_code'] or '—'}")
    print(f"  Referred By:     {row['referred_by'] or '—'}")
    print(f"  is_verified:     {row['is_verified']}")
    print(f"  is_active:       {row['is_active']}")
    print(f"  approval_status: {row['approval_status']}")
    print(f"  rejection_reason:{row['rejection_reason'] or '—'}")
    print(f"  approved_by:     {row['approved_by'] or '—'}")
    print(f"  approved_at:     {row['approved_at'] or '—'}")
    print(f"  Created At:      {row['created_at']}")


async def show_pending(conn):
    """Show all users pending approval."""
    rows = await conn.fetch("""
        SELECT id, email, full_name, business_name,
               document_type, document_number,
               referral_code, referred_by,
               is_verified, is_active, approval_status,
               rejection_reason, approved_by, approved_at, created_at
        FROM users
        WHERE approval_status = 'pending'
        ORDER BY created_at DESC
    """)
    print(DIVIDER)
    print(f"  PENDING APPROVALS: {len(rows)} user(s)")
    print(DIVIDER)
    for i, row in enumerate(rows, 1):
        print(f"\n  [{i}] {row['email']}")
        _print_user(row)


async def approve_user(conn, email: str, admin_id: uuid.UUID = None):
    """Approve a user — mirrors PATCH /api/admin/users/{id}/approve"""
    admin_id = admin_id or uuid.UUID("00000000-0000-0000-0000-000000000001")  # test admin ID
    now = datetime.now(timezone.utc)

    row = await conn.fetchrow("SELECT id, email, approval_status FROM users WHERE email = $1", email)
    if not row:
        print(f"  ERROR: User {email} not found.")
        return

    if row['approval_status'] == 'approved':
        print(f"  INFO: User {email} is already approved.")
        return

    # This is exactly what admin_routes.py does:
    result = await conn.execute("""
        UPDATE users SET
            approval_status = 'approved',
            is_active       = TRUE,
            approved_by     = $1,
            approved_at     = $2,
            rejection_reason = NULL
        WHERE id = $3
    """, admin_id, now, row['id'])

    # Audit log
    await conn.execute("""
        INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
        VALUES ($1, $2, 'user_approve', 'user', $3, $4::jsonb)
    """,
        uuid.uuid4(),
        admin_id,
        str(row['id']),
        '{"action": "approved", "target_email": "' + email + '"}',
    )

    print(DIVIDER)
    print(f"  APPROVED: {email}")
    print(f"  approved_by: {admin_id}  (test admin)")
    print(f"  approved_at: {now}")
    print(f"  is_active:   TRUE")
    print(f"  User can now login via POST /api/auth/login")
    print(DIVIDER)


async def reject_user(conn, email: str, reason: str, admin_id: uuid.UUID = None):
    """Reject a user — mirrors PATCH /api/admin/users/{id}/reject"""
    admin_id = admin_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(timezone.utc)

    row = await conn.fetchrow("SELECT id, email, approval_status FROM users WHERE email = $1", email)
    if not row:
        print(f"  ERROR: User {email} not found.")
        return

    # Exactly what admin_routes.py does:
    await conn.execute("""
        UPDATE users SET
            approval_status  = 'rejected',
            is_active        = FALSE,
            rejection_reason = $1,
            approved_by      = $2,
            approved_at      = $3
        WHERE id = $4
    """, reason, admin_id, now, row['id'])

    await conn.execute("""
        INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
        VALUES ($1, $2, 'user_reject', 'user', $3, $4::jsonb)
    """,
        uuid.uuid4(),
        admin_id,
        str(row['id']),
        '{"action": "rejected", "reason": "' + reason + '", "target_email": "' + email + '"}',
    )

    print(DIVIDER)
    print(f"  REJECTED: {email}")
    print(f"  Reason:      {reason}")
    print(f"  approved_by: {admin_id}  (test admin)")
    print(f"  User will see 403 on login with reason.")
    print(DIVIDER)


async def show_user(conn, email: str):
    """Show full profile of a user including all Phase 1 fields."""
    row = await conn.fetchrow("""
        SELECT id, email, full_name, business_name,
               document_type, document_number,
               referral_code, referred_by,
               is_verified, is_active, approval_status,
               rejection_reason, approved_by, approved_at, created_at
        FROM users WHERE email = $1
    """, email)
    if not row:
        print(f"  User {email} not found.")
        return
    print(DIVIDER)
    print(f"  USER PROFILE: {email}")
    print(DIVIDER)
    _print_user(row)


async def main():
    args = sys.argv[1:]
    conn = await asyncpg.connect(PG_URL)

    try:
        if not args:
            # Default: show all pending approvals
            await show_pending(conn)
            print()
            print("  Usage:")
            print("    Show pending:  python test_approve_user.py")
            print("    Show user:     python test_approve_user.py user@co.com show")
            print("    Approve:       python test_approve_user.py user@co.com")
            print("    Reject:        python test_approve_user.py user@co.com reject \"reason\"")

        elif len(args) == 1:
            await approve_user(conn, args[0])
            await show_user(conn, args[0])

        elif len(args) == 2 and args[1] == "show":
            await show_user(conn, args[0])

        elif len(args) >= 3 and args[1] == "reject":
            await reject_user(conn, args[0], args[2])
            await show_user(conn, args[0])

        else:
            print("  Invalid arguments. Run without args for usage.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
