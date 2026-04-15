"""
Analytics Routes — Performance Tracking & Visual Data Aggregation
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.models import (
    User, UserRole, Organization, Document, Invitation, Project, ProjectStatus
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# ── Helpers ──────────────────────────────────────────────────────────

def get_time_range(days: Optional[int]) -> datetime:
    if not days:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(days=days)

# ── Routes ───────────────────────────────────────────────────────────

@router.get("/summary")
async def get_analytics_summary(
    days: Optional[int] = Query(30, description="Last N days for time-series"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user)
):
    """
    Consolidated analytics for the dashboard.
    Strict tenant isolation: 
    - Admin/SuperAdmin sees global.
    - Org-Admin sees their organization's data.
    """
    is_admin = current.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)
    org_id = current.organization_id
    
    start_date = get_time_range(days)

    # ── Multi-tenancy: stats are shared for the organization ──────────
    # Defensive Check: Does Project.organization_id exist in DB?
    try:
        await db.execute(select(Project.organization_id).limit(1))
        has_org_col = True
    except Exception:
        log.warning("Project.organization_id column missing in analytics - falling back to owner_id")
        has_org_col = False
        await db.rollback()

    # 1. Summary Cards
    # ────────────────────────────────────────────────────────────────
    # Base filters for Multi-Tenancy
    if is_admin:
        p_filter = True
    elif has_org_col and org_id:
        p_filter = (Project.organization_id == org_id)
    else:
        p_filter = (Project.owner_id == current.id)

    # Projects
    project_q = select(func.count(Project.id)).where(p_filter)
    total_projects = await db.scalar(project_q)

    # Files (Documents)
    doc_q = select(func.count(Document.id), func.sum(Document.file_size)).join(Project).where(p_filter)
    doc_res = (await db.execute(doc_q)).fetchone()
    # Ensure aggregates are always numeric (no None/NaN propagation)
    if doc_res:
        total_files = int(doc_res[0] or 0)
        total_storage = int(doc_res[1] or 0)
    else:
        total_files = 0
        total_storage = 0

    # Employees / Users
    user_q = select(func.count(User.id))
    if org_id:
        user_q = user_q.where(User.organization_id == org_id)
    total_employees = await db.scalar(user_q)

    # 2. Line Chart: Growth of Files (over time)
    # ────────────────────────────────────────────────────────────────
    growth_q = select(
        func.date_trunc('day', Document.created_at).label('day'),
        func.count(Document.id).label('count')
    ).join(Project).where(p_filter, Document.created_at >= start_date)
    
    growth_q = growth_q.group_by('day').order_by('day')
    growth_res = (await db.execute(growth_q)).all()
    
    # Dates returned as ISO strings for frontend charts
    growth_data = []
    for r in growth_res:
        day = getattr(r, "day", None)
        if day is None:
            continue
        if isinstance(day, datetime):
            date_str = day.date().isoformat()
        else:
            date_str = str(day)
        growth_data.append({"date": date_str, "count": int(getattr(r, "count", 0) or 0)})

    # 3. Bar Chart: Active Users vs Pending Invitations
    # ────────────────────────────────────────────────────────────────
    if is_admin:
        u_filter = True
        i_filter = True
    elif org_id:
        u_filter = (User.organization_id == org_id)
        i_filter = (Invitation.organization_id == org_id)
    else:
        u_filter = (User.id == current.id)
        i_filter = (Invitation.invited_by == current.id)

    active_users_q = select(func.count(User.id)).where(u_filter, User.is_active == True)
    pending_inv_q = select(func.count(Invitation.id)).where(i_filter, Invitation.accepted_at == None)
        
    active_users = await db.scalar(active_users_q)
    pending_invs = await db.scalar(pending_inv_q)
    
    user_inv_stats = [
        {"name": "المستخدمين النشطين", "value": active_users or 0},
        {"name": "دعوات معلقة", "value": pending_invs or 0}
    ]

    # 4. Pie Chart: File Type Distribution
    # ────────────────────────────────────────────────────────────────
    dist_q = select(
        func.lower(func.reverse(func.split_part(func.reverse(Document.file_name), '.', 1))).label('ext'),
        func.count(Document.id).label('count')
    ).join(Project).where(p_filter)
    
    dist_q = dist_q.group_by('ext')
    dist_res = (await db.execute(dist_q)).all()
    
    # Map extensions to friendly labels
    mapping = {'pdf': 'PDF', 'docx': 'Word', 'doc': 'Word', 'pptx': 'PowerPoint', 'ppt': 'PowerPoint', 'xlsx': 'Excel', 'xls': 'Excel', 'csv': 'Excel', 'txt': 'نصي'}
    formatted_dist = {}
    for r in dist_res:
        ext = getattr(r, "ext", "") or ""
        label = mapping.get(ext, 'أخرى')
        formatted_dist[label] = formatted_dist.get(label, 0) + (getattr(r, "count", 0) or 0)
    
    pie_data = [{"name": k, "value": v} for k, v in formatted_dist.items()]

    return {
        "cards": {
            "total_employees": total_employees or 0,
            "total_files": total_files or 0,
            "storage_used": total_storage or 0,
            "active_projects": total_projects or 0
        },
        "growth": growth_data,
        "user_stats": user_inv_stats,
        "file_distribution": pie_data,
        "is_global": is_admin
    }
