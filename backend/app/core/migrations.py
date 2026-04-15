"""
migrations.py — Lightweight schema migration system for NATIQA.

Tracks applied migrations in a `schema_versions` table and applies any
missing DDL changes at startup, before SQLAlchemy's create_all() runs.

Design goals:
  • Idempotent — safe to run on every startup.
  • Additive only — never drops or renames existing columns.
  • Raw SQL via conn.exec_driver_sql() for DDL (bypasses ORM reflection).
  • Fully async (SQLAlchemy 2.0 async engine).
"""
import structlog  # type: ignore
from sqlalchemy import text

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Migration registry
# Each entry is (migration_id, description, sql_statement).
# Add new migrations at the END of this list — never reorder or remove.
# ---------------------------------------------------------------------------
_MIGRATIONS: list[tuple[str, str, str]] = [
    (
        "0001_add_token_balance_to_organizations",
        "Add token_balance column (INTEGER DEFAULT 1000) to organizations table",
        "ALTER TABLE organizations ADD COLUMN token_balance INTEGER DEFAULT 1000",
    ),
]


async def apply_migrations(engine) -> None:
    """
    Ensure the schema_versions tracking table exists, then apply every
    migration in _MIGRATIONS that has not yet been recorded.

    This function is intentionally idempotent: running it multiple times
    produces the same result as running it once.

    Args:
        engine: An SQLAlchemy async engine instance.
    """
    log.info("migrations: starting schema migration check")

    async with engine.begin() as conn:
        # ── 1. Bootstrap the tracking table ──────────────────────────────
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_versions (
                id          SERIAL PRIMARY KEY,
                migration_id VARCHAR(200) NOT NULL UNIQUE,
                description  TEXT,
                applied_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        log.info("migrations: schema_versions table ready")

        # ── 2. Fetch already-applied migration IDs ────────────────────────
        rows = await conn.exec_driver_sql(
            "SELECT migration_id FROM schema_versions"
        )
        applied: set[str] = {row[0] for row in rows.fetchall()}
        log.info("migrations: applied migrations found", count=len(applied))

        # ── 3. Apply pending migrations in order ──────────────────────────
        for migration_id, description, sql in _MIGRATIONS:
            if migration_id in applied:
                log.debug("migrations: already applied, skipping", migration_id=migration_id)
                continue

            log.info(
                "migrations: applying migration",
                migration_id=migration_id,
                description=description,
            )

            # Check whether the column already exists in the live DB before
            # running the ALTER TABLE — this guards against the case where
            # the column was added manually outside of this system.
            if migration_id == "0001_add_token_balance_to_organizations":
                col_exists = await _column_exists(conn, "organizations", "token_balance")
                if col_exists:
                    log.info(
                        "migrations: column already present in DB, recording migration without DDL",
                        migration_id=migration_id,
                        table="organizations",
                        column="token_balance",
                    )
                    # Record it so we don't check again on next startup.
                    await conn.exec_driver_sql(
                        "INSERT INTO schema_versions (migration_id, description) VALUES (%s, %s)",
                        (migration_id, description),
                    )
                    continue

            try:
                await conn.exec_driver_sql(sql)
                await conn.exec_driver_sql(
                    "INSERT INTO schema_versions (migration_id, description) VALUES (%s, %s)",
                    (migration_id, description),
                )
                log.info("migrations: migration applied successfully", migration_id=migration_id)
            except Exception as exc:
                log.error(
                    "migrations: migration failed",
                    migration_id=migration_id,
                    error=str(exc),
                )
                raise

    log.info("migrations: all migrations complete")


async def _column_exists(conn, table: str, column: str) -> bool:
    """
    Return True if *column* exists in *table* in the current PostgreSQL schema.
    Uses information_schema for portability.
    """
    result = await conn.exec_driver_sql(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    return result.fetchone() is not None
