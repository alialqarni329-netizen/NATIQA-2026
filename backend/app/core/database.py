from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker  # type: ignore
from sqlalchemy.pool import NullPool  # type: ignore
from app.core.config import settings  # type: ignore
from app.models.models import Base  # type: ignore
from app.models import SubscriptionPlan
import structlog  # type: ignore

log = structlog.get_logger()

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create tables (models v1 + v2) and seed initial admin user."""
    # استيراد كل النماذج لضمان إنشاء جداولها
    from app.models import models      # noqa: F401

    async with engine.begin() as conn:
        # إنشاء جداول models.py
        await conn.run_sync(Base.metadata.create_all)

    log.info("Database tables created (v1 + v2)")
    await seed_admin()


async def seed_admin():
    """Create first admin if not exists."""
    from app.models.models import User, UserRole  # type: ignore
    from app.core.security import hash_password  # type: ignore
    from sqlalchemy import select  # type: ignore

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(User).where(User.email == settings.FIRST_ADMIN_EMAIL)
        )
        if existing.scalar_one_or_none():
            return

        from app.models.models import ApprovalStatus
        admin = User(
            email=settings.FIRST_ADMIN_EMAIL,
            full_name=settings.FIRST_ADMIN_NAME,
            hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
            approval_status=ApprovalStatus.APPROVED,
            subscription_plan=SubscriptionPlan.FREE,
        )
        session.add(admin)
        await session.commit()
        log.info("Admin user created", email=settings.FIRST_ADMIN_EMAIL)
