"""
Notification Service — Manage user alerts and real-time triggers.
"""
from __future__ import annotations
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Notification, NotificationType

log = structlog.get_logger()

async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    type: NotificationType,
    title: str,
    message: str,
    org_id: uuid.UUID | None = None,
) -> Notification:
    """
    Create a new notification for a specific user.
    """
    notif = Notification(
        user_id=user_id,
        org_id=org_id,
        type=type,
        title=title,
        message=message,
        is_read=False
    )
    db.add(notif)
    await db.flush()  # get ID
    log.info("notification_created", user_id=str(user_id), type=type.value, title=title)
    return notif
