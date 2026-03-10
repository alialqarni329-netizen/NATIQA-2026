import sys
sys.path.append('/app')
import asyncio
import structlog
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import User, UserRole, ApprovalStatus
from app.core.security import hash_password
from sqlalchemy import select

log = structlog.get_logger()

async def main():
    log.info("Starting force_admin script...")
    
    admin_email = settings.FIRST_ADMIN_EMAIL
    if not admin_email:
        log.error("FIRST_ADMIN_EMAIL must be set in the environment.")
        return
        
    admin_password = "Admin123!"
    admin_name = settings.FIRST_ADMIN_NAME or "Admin"

    async with AsyncSessionLocal() as session:
        try:
            log.info("Checking for existing user...", email=admin_email)
            result = await session.execute(
                select(User).where(User.email == admin_email)
            )
            existing_user = result.scalar_one_or_none()

            if existing_user:
                log.info("Deleting existing user...", email=admin_email)
                await session.delete(existing_user)
                await session.commit()
                log.info("Existing user deleted.")
                
            log.info("Creating brand new superadmin user...", email=admin_email)
            hashed_pw = hash_password(admin_password)
            new_user = User(
                email=admin_email,
                full_name=admin_name,
                hashed_password=hashed_pw,
                role=UserRole.SUPER_ADMIN,
                is_active=True,
                is_verified=True,
                approval_status=ApprovalStatus.APPROVED
            )
            session.add(new_user)

            await session.commit()
            
            # Fetch it back just to be absolutely sure
            verify_result = await session.execute(
                select(User).where(User.email == admin_email)
            )
            saved_user = verify_result.scalar_one()
            
            log.info("Successfully forced superadmin credentials.", email=admin_email)
            print("\n" + "="*50)
            print("✅ SUCCESS: Superadmin user saved to database")
            print(f"▶ EMAIL: {admin_email}")
            print(f"▶ PASSWORD: {admin_password}")
            print(f"▶ HASHED_PW IN DB: {saved_user.hashed_password}")
            print("="*50 + "\n")
        
        except Exception as e:
            await session.rollback()
            log.error("Failed to create/update superadmin.", error=str(e))
            raise

if __name__ == "__main__":
    asyncio.run(main())
