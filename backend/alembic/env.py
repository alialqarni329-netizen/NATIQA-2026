"""
Alembic async env.py
═══════════════════════════════════════════════════════════════════════
• Uses SQLAlchemy asyncpg driver (postgresql+asyncpg://)
• Reads DATABASE_URL from environment (falls back to alembic.ini)
• Imports all ORM models so autogenerate detects every table
• Supports --sql (offline) and live (online) migration modes

Usage:
  alembic upgrade head
  alembic downgrade -1
  alembic revision --autogenerate -m "add_something"
  alembic history
  alembic current
"""
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Import all models so autogenerate can detect every table ──────────
from app.models.models import Base   # noqa: F401 — side-effect: registers all mappers

# ── Alembic Config ─────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url from environment variable if available
db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    # asyncpg driver required for async migrations
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate
target_metadata = Base.metadata


# ══════════════════════════════════════════════════════════════════════
# Offline mode: generate SQL script without DB connection
# ══════════════════════════════════════════════════════════════════════

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    Generates SQL without needing a DB connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


# ══════════════════════════════════════════════════════════════════════
# Online async mode: connect and migrate
# ══════════════════════════════════════════════════════════════════════

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,            # detect column type changes
        compare_server_default=True,  # detect default changes
        include_schemas=False,
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool — no persistent connections in migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online (live) migrations."""
    asyncio.run(run_async_migrations())


# ── Entry point ────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
