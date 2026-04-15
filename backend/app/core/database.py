from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker  # type: ignore
from sqlalchemy.pool import NullPool  # type: ignore
from app.core.config import settings  # type: ignore
from app.models.models import Base  # type: ignore
from datetime import datetime, timezone
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
    """Create a default organization and seed the first admin and dev users if they don't exist."""
    from app.models.models import (
        User, UserRole, Organization, DocumentType, 
        ApprovalStatus, SubscriptionPlan
    )
    from app.core.security import hash_password
    from sqlalchemy import select, text
    import uuid as _uuid

    async with AsyncSessionLocal() as session:
        # 0. Gracefully handle schema mismatch (e.g. during migration)
        # Check if subscription_plan column exists in organizations
        try:
            await session.execute(text("SELECT subscription_plan FROM organizations LIMIT 1"))
            schema_ok = True
        except Exception:
            log.warning("Schema mismatch detected in organizations table. Seeding might be incomplete.")
            schema_ok = False
            await session.rollback()

        # 1. Ensure a Default Organization exists
        org_result = await session.execute(
            select(Organization).where(Organization.name == "Natiqa Default")
        )
        org = org_result.scalar_one_or_none()
        
        if not org:
            org_params = {
                "name": "Natiqa Default",
                "tax_number": "DEV-123456789",
                "document_type": DocumentType.CR,
                "is_active": True,
                "terms_accepted": True,
                "terms_accepted_at": datetime.now(timezone.utc)
            }
            if schema_ok:
                org_params["subscription_plan"] = SubscriptionPlan.ENTERPRISE
                org_params["token_balance"] = 1000000 # High balance for default org

            org = Organization(**org_params)
            session.add(org)
            await session.flush()
            log.info("Default Organization created", org_id=str(org.id))
        else:
            # Ensure it has a plan for dev
            if schema_ok and not org.subscription_plan:
                org.subscription_plan = SubscriptionPlan.ENTERPRISE
            await session.flush()

        # 2. Seed First Admin
        existing_admin = await session.execute(
            select(User).where(User.email == settings.FIRST_ADMIN_EMAIL)
        )
        if not existing_admin.scalar_one_or_none():
            admin = User(
                email=settings.FIRST_ADMIN_EMAIL,
                full_name=settings.FIRST_ADMIN_NAME,
                hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                is_verified=True,
                organization_id=org.id,
                approval_status=ApprovalStatus.APPROVED,
                terms_accepted=True,
                terms_accepted_at=datetime.now(timezone.utc)
            )
            session.add(admin)
            log.info("Admin user created", email=settings.FIRST_ADMIN_EMAIL)

        # 3. Seed Dev User (force the fixed UUID)
        _DEV_EMAIL = "ali@natiqa.com"
        _DEV_UUID = _uuid.UUID("c2853f49-bca3-46fc-a755-9abd2d6e759f")
        
        # Check if user with this UUID exists
        dev_by_id = await session.get(User, _DEV_UUID)
        
        if not dev_by_id:
            # Check if email is taken by another ID
            existing_dev_by_email = await session.execute(
                select(User).where(User.email == _DEV_EMAIL)
            )
            old_dev = existing_dev_by_email.scalar_one_or_none()
            if old_dev:
                log.info("Deleting dev user with incorrect UUID", email=_DEV_EMAIL, old_id=str(old_dev.id))
                await session.delete(old_dev)
                await session.flush()
            
            # Create fresh with the correct ID
            dev = User(
                id=_DEV_UUID,
                email=_DEV_EMAIL,
                full_name="Ali (Dev)",
                hashed_password=hash_password("Alluosh2026"),
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                is_verified=True,
                organization_id=org.id,
                approval_status=ApprovalStatus.APPROVED,
                terms_accepted=True,
                terms_accepted_at=datetime.now(timezone.utc),
                referral_code="DEV-ALI-FIXED"
            )
            session.add(dev)
            log.info("Dev user seeded with fixed UUID", email=_DEV_EMAIL)
        else:
            # Ensure it's active and linked to correct org
            dev_by_id.is_active = True
            dev_by_id.is_verified = True
            dev_by_id.approval_status = ApprovalStatus.APPROVED
            dev_by_id.organization_id = org.id
            log.info("Dev user already exists with correct UUID, updated status", email=_DEV_EMAIL)

        await session.commit()
