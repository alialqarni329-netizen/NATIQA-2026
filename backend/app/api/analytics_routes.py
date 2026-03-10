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
    org_id = current.organization_id if not is_admin else None
    
    start_date = get_time_range(days)

    # 1. Summary Cards
    # ────────────────────────────────────────────────────────────────
    # Projects
    project_q = select(func.count(Project.id))
    if org_id:
        project_q = project_q.where(Project.organization_id == org_id)
    total_projects = await db.scalar(project_q)

    # Files (Documents)
    doc_q = select(func.count(Document.id), func.sum(Document.file_size))
    if org_id:
        # Join with project to filter by org if needed, but Document has no direct org_id.
        # However, Project has organization_id.
        doc_q = doc_q.join(Project).where(Project.organization_id == org_id)
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

    # 2. Line Chart: Growth of Archived Files (over time)
    # ────────────────────────────────────────────────────────────────
    # We'll group archived documents by date (created_at)
    # Documents don't have an "archived" flag, but Projects do.
    # Growth = Files uploaded to active/archived projects over time.
    growth_q = select(
        func.date_trunc('day', Document.created_at).label('day'),
        func.count(Document.id).label('count')
    ).where(Document.created_at >= start_date)
    
    if org_id:
        growth_q = growth_q.join(Project).where(Project.organization_id == org_id)
    
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
    active_users_q = select(func.count(User.id)).where(User.is_active == True)
    pending_inv_q = select(func.count(Invitation.id)).where(Invitation.accepted_at == None)
    
    if org_id:
        active_users_q = active_users_q.where(User.organization_id == org_id)
        pending_inv_q = pending_inv_q.where(Invitation.organization_id == org_id)
        
    active_users = await db.scalar(active_users_q)
    pending_invs = await db.scalar(pending_inv_q)
    
    user_inv_stats = [
        {"name": "المستخدمين النشطين", "value": active_users or 0},
        {"name": "دعوات معلقة", "value": pending_invs or 0}
    ]

    # 4. Pie Chart: File Type Distribution
    # ────────────────────────────────────────────────────────────────
    # We can infer type from file_name extension or just use departmental distribution if requested.
    # The user asked for PDF, Word, PPT distribution.
    dist_q = select(
        func.lower(func.split_part(Document.file_name, '.', -1)).label('ext'),
        func.count(Document.id).label('count')
    )
    if org_id:
        dist_q = dist_q.join(Project).where(Project.organization_id == org_id)
    
    dist_q = dist_q.group_by('ext')
    dist_res = (await db.execute(dist_q)).all()
    
    # Map extensions to friendly labels
    mapping = {'pdf': 'PDF', 'docx': 'Word', 'doc': 'Word', 'pptx': 'PowerPoint', 'ppt': 'PowerPoint', 'xlsx': 'Excel', 'xls': 'Excel'}
    formatted_dist = {}
    for r in dist_res:
        label = mapping.get(r.ext, 'أخرى')
        formatted_dist[label] = formatted_dist.get(label, 0) + r.count
    
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
