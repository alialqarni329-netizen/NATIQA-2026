"""
Messaging API — Internal org communication
══════════════════════════════════════════
Channels (groups) + Direct Messages + SSE real-time stream.

Routes:
  GET  /channels                        — list my channels
  POST /channels                        — create a group channel
  GET  /channels/{id}                   — channel detail + members
  PATCH /channels/{id}                  — edit name/description (admin only)
  DELETE /channels/{id}                 — archive channel (admin only)
  POST /channels/{id}/members           — add members
  DELETE /channels/{id}/members/{uid}   — remove member
  GET  /channels/{id}/messages          — paginated messages (before cursor)
  POST /channels/{id}/messages          — send a message
  PATCH /channels/{id}/messages/{mid}   — edit message (sender only)
  DELETE /channels/{id}/messages/{mid}  — soft-delete message (sender / channel-admin)
  POST /channels/{id}/messages/{mid}/react — toggle emoji reaction
  POST /channels/{id}/read              — update last_read_at

  POST /dm/{user_id}                    — get-or-create DM channel with a user
  GET  /dm                              — list all my DM threads

  GET  /events/stream                   — SSE endpoint for real-time messages
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_redis
from app.models.models import (
    Channel, ChannelMember, ChannelMessage, ChannelType,
    Notification, NotificationType, User,
)
from app.services.notifications import create_notification

log = structlog.get_logger()

router = APIRouter(tags=["Messaging"])

# ──────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)
    channel_type: str = Field("public", pattern="^(public|private)$")
    member_ids: List[str] = Field(default_factory=list)


class ChannelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    ref_doc_id: Optional[str] = None
    ref_project_id: Optional[str] = None


class MessageEdit(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ReactionToggle(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=8)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _dm_key(uid1: uuid.UUID, uid2: uuid.UUID) -> str:
    """Deterministic key for a DM pair (sorted)."""
    a, b = sorted([str(uid1), str(uid2)])
    return f"{a}:{b}"


def _fmt_member(cm: ChannelMember) -> dict:
    u = cm.user
    return {
        "user_id": str(cm.user_id),
        "full_name": u.full_name if u else "—",
        "email": u.email if u else "",
        "is_admin": cm.is_admin,
        "joined_at": cm.joined_at.isoformat(),
    }


def _fmt_message(msg: ChannelMessage) -> dict:
    sender = msg.sender
    return {
        "id": str(msg.id),
        "channel_id": str(msg.channel_id),
        "sender_id": str(msg.sender_id),
        "sender_name": sender.full_name if sender else "—",
        "content": "" if msg.is_deleted else msg.content,
        "is_deleted": msg.is_deleted,
        "ref_doc_id": msg.ref_doc_id,
        "ref_project_id": msg.ref_project_id,
        "reactions": msg.reactions or {},
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "created_at": msg.created_at.isoformat(),
    }


def _fmt_channel(ch: Channel, unread: int = 0) -> dict:
    return {
        "id": str(ch.id),
        "name": ch.name,
        "description": ch.description,
        "channel_type": ch.channel_type.value,
        "member_count": len(ch.members),
        "unread": unread,
        "created_at": ch.created_at.isoformat(),
    }


async def _assert_member(
    channel_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    require_admin: bool = False,
) -> ChannelMember:
    res = await db.execute(
        select(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == user_id,
        )
    )
    cm = res.scalar_one_or_none()
    if not cm:
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية الوصول لهذه القناة")
    if require_admin and not cm.is_admin:
        raise HTTPException(status_code=403, detail="هذه العملية تتطلب صلاحية مشرف القناة")
    return cm


async def _publish(redis: aioredis.Redis, org_id: str, event: dict) -> None:
    """Publish a real-time event to the org's Redis channel."""
    try:
        await redis.publish(f"natiqa:org:{org_id}", json.dumps(event, ensure_ascii=False, default=str))
    except Exception as exc:
        log.warning("SSE publish failed", error=str(exc))


# ──────────────────────────────────────────────────────────────────────
# Channel CRUD
# ──────────────────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all non-DM channels the user belongs to."""
    res = await db.execute(
        select(Channel)
        .join(ChannelMember, ChannelMember.channel_id == Channel.id)
        .where(
            ChannelMember.user_id == user.id,
            Channel.channel_type != ChannelType.DIRECT,
            Channel.organization_id == user.organization_id,
        )
        .options(selectinload(Channel.members).selectinload(ChannelMember.user))
        .order_by(Channel.created_at.asc())
    )
    channels = res.scalars().all()

    # Compute unread counts in one pass
    out = []
    for ch in channels:
        my_mem = next((m for m in ch.members if m.user_id == user.id), None)
        if my_mem and my_mem.last_read_at:
            unread_res = await db.execute(
                select(func.count()).select_from(ChannelMessage).where(
                    ChannelMessage.channel_id == ch.id,
                    ChannelMessage.created_at > my_mem.last_read_at,
                    ChannelMessage.sender_id != user.id,
                )
            )
            unread = unread_res.scalar() or 0
        else:
            unread = 0
        out.append({**_fmt_channel(ch, unread), "members": [_fmt_member(m) for m in ch.members]})
    return out


@router.post("/channels", status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    if not user.organization_id:
        raise HTTPException(status_code=400, detail="يجب أن تكون عضواً في منظمة لإنشاء قناة")

    ch = Channel(
        organization_id=user.organization_id,
        created_by=user.id,
        name=body.name,
        description=body.description,
        channel_type=ChannelType(body.channel_type),
    )
    db.add(ch)
    await db.flush()  # get ch.id

    # Add creator as admin member
    db.add(ChannelMember(channel_id=ch.id, user_id=user.id, is_admin=True))

    # Add extra members
    added_ids = {user.id}
    for uid_str in body.member_ids:
        try:
            uid = uuid.UUID(uid_str)
        except ValueError:
            continue
        if uid in added_ids:
            continue
        # Verify member is in same org
        res = await db.execute(select(User).where(User.id == uid, User.organization_id == user.organization_id))
        member = res.scalar_one_or_none()
        if member:
            db.add(ChannelMember(channel_id=ch.id, user_id=uid))
            added_ids.add(uid)
            # Notify them
            await create_notification(db, uid, NotificationType.INFO,
                                      f"دُعيت إلى قناة «{ch.name}»",
                                      f"{user.full_name} أضافك إلى القناة")

    await db.commit()
    await db.refresh(ch)

    await _publish(redis, str(user.organization_id), {
        "type": "channel_created", "channel_id": str(ch.id), "name": ch.name
    })

    log.info("Channel created", channel_id=str(ch.id), name=ch.name, creator=str(user.id))
    return {"id": str(ch.id), "name": ch.name, "channel_type": ch.channel_type.value}


@router.get("/channels/{channel_id}")
async def get_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.id, db)
    res = await db.execute(
        select(Channel)
        .where(Channel.id == channel_id)
        .options(selectinload(Channel.members).selectinload(ChannelMember.user))
    )
    ch = res.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="القناة غير موجودة")
    return {**_fmt_channel(ch), "members": [_fmt_member(m) for m in ch.members]}


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.id, db, require_admin=True)
    res = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = res.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="القناة غير موجودة")

    if body.name is not None:
        ch.name = body.name
    if body.description is not None:
        ch.description = body.description
    await db.commit()
    return {"id": str(ch.id), "name": ch.name}


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.id, db, require_admin=True)
    await db.execute(delete(Channel).where(Channel.id == channel_id))
    await db.commit()


# ──────────────────────────────────────────────────────────────────────
# Channel members
# ──────────────────────────────────────────────────────────────────────

class AddMembers(BaseModel):
    user_ids: List[str]


@router.post("/channels/{channel_id}/members", status_code=status.HTTP_201_CREATED)
async def add_members(
    channel_id: uuid.UUID,
    body: AddMembers,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    cm = await _assert_member(channel_id, user.id, db, require_admin=True)
    res_ch = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = res_ch.scalar_one_or_none()

    added = []
    for uid_str in body.user_ids:
        try:
            uid = uuid.UUID(uid_str)
        except ValueError:
            continue
        # Already member?
        ex = await db.execute(select(ChannelMember).where(
            ChannelMember.channel_id == channel_id, ChannelMember.user_id == uid
        ))
        if ex.scalar_one_or_none():
            continue
        res_u = await db.execute(select(User).where(User.id == uid, User.organization_id == user.organization_id))
        member = res_u.scalar_one_or_none()
        if member:
            db.add(ChannelMember(channel_id=channel_id, user_id=uid))
            added.append(str(uid))
            await create_notification(db, uid, NotificationType.INFO,
                                      f"دُعيت إلى قناة «{ch.name if ch else ''}»",
                                      f"{user.full_name} أضافك إلى القناة")

    await db.commit()
    await _publish(redis, str(user.organization_id), {
        "type": "members_added", "channel_id": str(channel_id), "added": added
    })
    return {"added": added}


@router.delete("/channels/{channel_id}/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    channel_id: uuid.UUID,
    target_user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Allow self-leave or admin removal
    if target_user_id != user.id:
        await _assert_member(channel_id, user.id, db, require_admin=True)
    await db.execute(delete(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == target_user_id,
    ))
    await db.commit()


# ──────────────────────────────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: uuid.UUID,
    before: Optional[str] = Query(None, description="Cursor — load messages before this message ID"),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated message history (newest-first, cursor-based)."""
    await _assert_member(channel_id, user.id, db)

    q = select(ChannelMessage).where(
        ChannelMessage.channel_id == channel_id
    ).options(selectinload(ChannelMessage.sender)).order_by(ChannelMessage.created_at.desc()).limit(limit)

    if before:
        try:
            ref_id = uuid.UUID(before)
            ref_res = await db.execute(select(ChannelMessage.created_at).where(ChannelMessage.id == ref_id))
            ref_ts = ref_res.scalar_one_or_none()
            if ref_ts:
                q = q.where(ChannelMessage.created_at < ref_ts)
        except ValueError:
            pass

    res = await db.execute(q)
    msgs = list(reversed(res.scalars().all()))
    return [_fmt_message(m) for m in msgs]


@router.post("/channels/{channel_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    channel_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    await _assert_member(channel_id, user.id, db)

    msg = ChannelMessage(
        channel_id=channel_id,
        sender_id=user.id,
        content=body.content,
        ref_doc_id=body.ref_doc_id,
        ref_project_id=body.ref_project_id,
    )
    db.add(msg)

    # Update sender's last_read_at
    await db.execute(
        update(ChannelMember)
        .where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user.id)
        .values(last_read_at=datetime.now(timezone.utc))
    )

    await db.flush()
    await db.refresh(msg)

    # Load sender for formatting
    msg_data = {
        "id": str(msg.id),
        "channel_id": str(msg.channel_id),
        "sender_id": str(msg.sender_id),
        "sender_name": user.full_name,
        "content": msg.content,
        "is_deleted": False,
        "ref_doc_id": msg.ref_doc_id,
        "ref_project_id": msg.ref_project_id,
        "reactions": {},
        "edited_at": None,
        "created_at": msg.created_at.isoformat(),
    }

    # Notify other channel members (non-DM: only mention mentions for now)
    res_ch = await db.execute(
        select(Channel).where(Channel.id == channel_id)
        .options(selectinload(Channel.members))
    )
    ch = res_ch.scalar_one_or_none()
    if ch:
        for cm in ch.members:
            if cm.user_id != user.id:
                await create_notification(
                    db, cm.user_id, NotificationType.INFO,
                    f"رسالة جديدة في «{ch.name or 'المحادثة'}»",
                    f"{user.full_name}: {body.content[:80]}{'...' if len(body.content) > 80 else ''}",
                )

    await db.commit()

    # Broadcast via SSE/Redis
    await _publish(redis, str(user.organization_id), {
        "type": "new_message",
        "message": msg_data,
    })

    return msg_data


@router.patch("/channels/{channel_id}/messages/{message_id}")
async def edit_message(
    channel_id: uuid.UUID,
    message_id: uuid.UUID,
    body: MessageEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    res = await db.execute(select(ChannelMessage).where(
        ChannelMessage.id == message_id,
        ChannelMessage.channel_id == channel_id,
    ))
    msg = res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="الرسالة غير موجودة")
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="يمكنك تعديل رسائلك فقط")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="لا يمكن تعديل رسالة محذوفة")

    msg.content = body.content
    msg.edited_at = datetime.now(timezone.utc)
    await db.commit()

    await _publish(redis, str(user.organization_id), {
        "type": "message_edited",
        "message_id": str(message_id),
        "channel_id": str(channel_id),
        "content": body.content,
    })
    return {"id": str(msg.id), "content": msg.content, "edited_at": msg.edited_at.isoformat()}


@router.delete("/channels/{channel_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    channel_id: uuid.UUID,
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    res = await db.execute(select(ChannelMessage).where(
        ChannelMessage.id == message_id,
        ChannelMessage.channel_id == channel_id,
    ))
    msg = res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="الرسالة غير موجودة")

    # Allow sender or channel admin
    if msg.sender_id != user.id:
        await _assert_member(channel_id, user.id, db, require_admin=True)

    msg.is_deleted = True
    msg.content = ""  # wipe content
    await db.commit()

    await _publish(redis, str(user.organization_id), {
        "type": "message_deleted",
        "message_id": str(message_id),
        "channel_id": str(channel_id),
    })


@router.post("/channels/{channel_id}/messages/{message_id}/react")
async def toggle_reaction(
    channel_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ReactionToggle,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    await _assert_member(channel_id, user.id, db)
    res = await db.execute(select(ChannelMessage).where(
        ChannelMessage.id == message_id,
        ChannelMessage.channel_id == channel_id,
    ))
    msg = res.scalar_one_or_none()
    if not msg or msg.is_deleted:
        raise HTTPException(status_code=404, detail="الرسالة غير موجودة")

    reactions: dict = dict(msg.reactions or {})
    uid_str = str(user.id)
    users_list: list = list(reactions.get(body.emoji, []))

    if uid_str in users_list:
        users_list.remove(uid_str)
        if not users_list:
            reactions.pop(body.emoji, None)
        else:
            reactions[body.emoji] = users_list
    else:
        users_list.append(uid_str)
        reactions[body.emoji] = users_list

    msg.reactions = reactions
    await db.commit()

    await _publish(redis, str(user.organization_id), {
        "type": "reaction_update",
        "message_id": str(message_id),
        "channel_id": str(channel_id),
        "reactions": reactions,
    })
    return {"reactions": reactions}


@router.post("/channels/{channel_id}/read")
async def mark_channel_read(
    channel_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cm = await _assert_member(channel_id, user.id, db)
    await db.execute(
        update(ChannelMember)
        .where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user.id)
        .values(last_read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────
# Direct Messages
# ──────────────────────────────────────────────────────────────────────

@router.post("/dm/{target_user_id}")
async def get_or_create_dm(
    target_user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get or create a DM channel between the current user and target_user_id."""
    if target_user_id == user.id:
        raise HTTPException(status_code=400, detail="لا يمكنك إرسال رسالة لنفسك")
    if not user.organization_id:
        raise HTTPException(status_code=400, detail="يجب أن تكون عضواً في منظمة")

    # Verify target is in same org
    res_t = await db.execute(select(User).where(User.id == target_user_id, User.organization_id == user.organization_id))
    target = res_t.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود في منظمتك")

    key = _dm_key(user.id, target_user_id)

    # Find existing DM
    res = await db.execute(select(Channel).where(Channel.dm_key == key))
    ch = res.scalar_one_or_none()

    if not ch:
        ch = Channel(
            organization_id=user.organization_id,
            created_by=user.id,
            channel_type=ChannelType.DIRECT,
            dm_key=key,
            name=None,
        )
        db.add(ch)
        await db.flush()
        db.add(ChannelMember(channel_id=ch.id, user_id=user.id, is_admin=True))
        db.add(ChannelMember(channel_id=ch.id, user_id=target_user_id, is_admin=True))
        await db.commit()
        await db.refresh(ch)

    return {
        "channel_id": str(ch.id),
        "with_user": {
            "id": str(target.id),
            "full_name": target.full_name,
            "email": target.email,
        }
    }


@router.get("/dm")
async def list_dm_threads(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all DM threads for the current user, sorted by latest activity."""
    res = await db.execute(
        select(Channel)
        .join(ChannelMember, ChannelMember.channel_id == Channel.id)
        .where(
            ChannelMember.user_id == user.id,
            Channel.channel_type == ChannelType.DIRECT,
        )
        .options(selectinload(Channel.members).selectinload(ChannelMember.user))
    )
    channels = res.scalars().all()

    out = []
    for ch in channels:
        # Identify the other party
        other = next(
            (m.user for m in ch.members if m.user_id != user.id), None
        )
        my_mem = next((m for m in ch.members if m.user_id == user.id), None)

        # Unread count
        if my_mem and my_mem.last_read_at:
            ur_res = await db.execute(
                select(func.count()).select_from(ChannelMessage).where(
                    ChannelMessage.channel_id == ch.id,
                    ChannelMessage.created_at > my_mem.last_read_at,
                    ChannelMessage.sender_id != user.id,
                )
            )
            unread = ur_res.scalar() or 0
        else:
            unread = 0

        # Last message preview
        lm_res = await db.execute(
            select(ChannelMessage)
            .where(ChannelMessage.channel_id == ch.id)
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
        last_msg = lm_res.scalar_one_or_none()

        out.append({
            "channel_id": str(ch.id),
            "with_user": {
                "id": str(other.id) if other else None,
                "full_name": other.full_name if other else "—",
                "email": other.email if other else "",
            },
            "unread": unread,
            "last_message": {
                "content": (last_msg.content[:80] if last_msg and not last_msg.is_deleted else ("🗑 محذوفة" if last_msg else None)),
                "created_at": last_msg.created_at.isoformat() if last_msg else None,
                "sender_id": str(last_msg.sender_id) if last_msg else None,
            } if last_msg else None,
        })

    # Sort by latest message
    out.sort(key=lambda x: x["last_message"]["created_at"] if x.get("last_message") else "", reverse=True)
    return out


# ──────────────────────────────────────────────────────────────────────
# SSE — Real-time event stream
# ──────────────────────────────────────────────────────────────────────

@router.get("/events/stream")
async def sse_stream(
    user: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Server-Sent Events endpoint.
    Clients connect once; the server pushes new_message / reaction_update /
    message_edited / message_deleted / channel_created events in real-time.
    """
    org_id = str(user.organization_id) if user.organization_id else "global"
    channel_name = f"natiqa:org:{org_id}"

    async def event_generator() -> AsyncIterator[str]:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel_name)
        try:
            # Heartbeat every 20s to keep connection alive
            last_ping = asyncio.get_event_loop().time()
            while True:
                now = asyncio.get_event_loop().time()
                if now - last_ping > 20:
                    yield "event: ping\ndata: {}\n\n"
                    last_ping = now

                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    payload = msg.get("data", "{}")
                    yield f"event: message\ndata: {payload}\n\n"

                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering
            "Connection": "keep-alive",
        },
    )
