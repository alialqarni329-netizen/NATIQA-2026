"""
Projects, Documents, Chat API Routes
"""
import hashlib
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status,
    UploadFile, File, Form, BackgroundTasks
)
from fastapi.responses import StreamingResponse
import io
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from pydantic import BaseModel

import structlog
from app.core.database import get_db
from app.core.dependencies import get_current_user, log_audit

log = structlog.get_logger()
from app.models.models import (
    User, Project, Document, Conversation, Message,
    ProjectStatus, DocumentStatus, AuditAction
)
from app.core.config import settings
from app.services import rag as rag_service
from app.services.plans import SubscriptionPlan, UsageTracker
from app.core.dependencies import get_redis
import redis.asyncio as aioredis
from app.services.notifications import create_notification
from app.models.models import NotificationType, ProjectMember
from app.services.generator import FileGenerator

router = APIRouter()


# ═══════════════════════════════════════════════════
#  PROJECTS
# ═══════════════════════════════════════════════════
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None


@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()

    out = []
    for p in projects:
        doc_count = await db.scalar(
            select(func.count()).select_from(Document).where(Document.project_id == p.id)
        )
        out.append({
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "status": p.status.value,
            "doc_count": doc_count or 0,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        })
    return out


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = Project(
        name=body.name, 
        description=body.description, 
        owner_id=user.id,
        organization_id=user.organization_id
    )
    db.add(p)
    await db.flush()
    await log_audit(db, AuditAction.PROJECT_CREATE, user_id=user.id, resource_id=str(p.id), details={"name": body.name})
    await db.commit()
    await db.refresh(p)
    return {"id": str(p.id), "name": p.name, "description": p.description, "status": p.status.value, "doc_count": 0, "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat()}


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_project(project_id, user, db)
    if body.name: p.name = body.name
    if body.description is not None: p.description = body.description
    if body.status: p.status = body.status
    await db.commit()
    return {"id": str(p.id), "name": p.name, "status": p.status.value}


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_project(project_id, user, db)
    # Delete all document vectors
    docs = await db.execute(select(Document).where(Document.project_id == p.id))
    for doc in docs.scalars():
        await rag_service.delete_document_vectors(str(doc.id), str(p.id))
    await log_audit(db, AuditAction.PROJECT_DELETE, user_id=user.id, resource_id=str(p.id))
    await db.delete(p)
    await db.commit()


async def _get_project(project_id, user, db):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: uuid.UUID,
    user_email: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """إضافة عضو جديد إلى المشروع — مع إشعار."""
    p = await _get_project(project_id, user, db)
    
    # Resolve target user
    res = await db.execute(select(User).where(User.email == user_email))
    target = res.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check if already a member
    existing = await db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == target.id)
    )
    if existing.scalar_one_or_none():
        return {"message": "User already a member"}
        
    member = ProjectMember(project_id=project_id, user_id=target.id)
    db.add(member)
    
    # Trigger notification
    await create_notification(
        db,
        user_id=target.id,
        type=NotificationType.INFO,
        title="مشروع جديد",
        message=f"لقد تمت إضافتك إلى المشروع: {p.name}",
        org_id=user.organization_id
    )
    
    await db.commit()
    return {"message": f"Added {user_email} to project {p.name}"}


# ═══════════════════════════════════════════════════
#  DOCUMENTS
# ═══════════════════════════════════════════════════
@router.get("/projects/{project_id}/documents")
async def list_documents(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(project_id, user, db)
    from app.models.models import UserRole as UR
    from sqlalchemy import and_
    # Build dept filter for non-admin users
    if user.role in (UR.ADMIN, UR.SUPER_ADMIN):
        dept_filter = True  # see all
        result = await db.execute(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
    else:
        _dept_defaults = {"hr_analyst":["hr","admin","general"],"analyst":["general"],"viewer":["general"]}
        allowed = user.allowed_depts or _dept_defaults.get(user.role.value, ["general"])
        result = await db.execute(
            select(Document)
            .where(and_(Document.project_id == project_id, Document.department.in_(allowed)))
            .order_by(Document.created_at.desc())
        )
    docs = result.scalars().all()
    return [
        {
            "id": str(d.id),
            "file_name": d.original_name,
            "department": d.department,
            "status": d.status.value,
            "chunks_count": d.chunks_count,
            "file_size": d.file_size,
            "language": d.language,
            "is_encrypted": d.is_encrypted,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    department: str = Form("general"),
    language: str = Form("ar"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    await _get_project(project_id, user, db)

    # ── Department access enforcement ───────────────────────────────
    # admin/super_admin can upload to any dept; others are restricted
    from app.models.models import UserRole as UR
    if user.role not in (UR.ADMIN, UR.SUPER_ADMIN):
        _dept_defaults = {
            "hr_analyst": ["hr", "admin", "general"],
            "analyst"   : ["general"],
            "viewer"    : ["general"],
        }
        allowed = user.allowed_depts or _dept_defaults.get(user.role.value, ["general"])
        if department not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"ليس لديك صلاحية رفع ملفات في قسم '{department}'"
            )

    # Validate extension
    ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} not allowed")

    # Read file
    file_bytes = await file.read()

    # ── Subscription enforcement (upload) ────────────────────────────
    from app.services.plans import get_effective_plan
    plan_enum, _ = get_effective_plan(user)
    custom = getattr(user.organization, "subscription_custom_limits", None) if getattr(user, "organization", None) else None
    await UsageTracker.check_upload(
        user_id=str(user.id),
        file_size_bytes=len(file_bytes),
        plan=plan_enum,
        db=db,
        redis=redis,
        custom_limits=custom,
    )
    # Legacy hard limit (keeps config-level guard as fallback)
    if len(file_bytes) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")

    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # Check duplicate
    existing = await db.execute(
        select(Document).where(Document.project_id == project_id, Document.file_hash == file_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="File already exists in this project")

    # Create DB record
    doc = Document(
        original_name=file.filename,
        file_name=f"{uuid.uuid4()}{ext}",
        file_path="pending",
        file_size=len(file_bytes),
        file_hash=file_hash,
        department=department,
        language=language,
        status=DocumentStatus.PROCESSING,
        is_encrypted=True,
        project_id=project_id,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()
    doc_id = str(doc.id)
    await db.commit()
    # Invalidate doc-count cache so next check is accurate
    await UsageTracker.invalidate_doc_cache(str(user.id), redis)

    # Process in background
    background_tasks.add_task(
        _process_document,
        file_bytes=file_bytes,
        filename=file.filename,
        doc_id=doc_id,
        project_id=str(project_id),
        department=department,
        user_id=str(user.id),
    )

    await log_audit(db, AuditAction.FILE_UPLOAD, user_id=user.id, resource_id=doc_id, details={"filename": file.filename, "size": len(file_bytes)})
    await db.commit()

    return {"id": doc_id, "status": "processing", "filename": file.filename}


async def _process_document(file_bytes, filename, doc_id, project_id, department, user_id):
    """Background task: ingest and update status with full error visibility."""
    from app.core.database import AsyncSessionLocal
    import traceback

    log.info("Background processing started", filename=filename, doc_id=doc_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
        doc = result.scalar_one_or_none()
        if not doc:
            log.error("Document not found in DB", doc_id=doc_id)
            return
        try:
            chunks_count, classification = await rag_service.ingest_document(
                file_bytes=file_bytes,
                filename=filename,
                doc_id=doc_id,
                project_id=project_id,
                department=department,
            )
            doc.status = DocumentStatus.READY
            doc.chunks_count = chunks_count
            doc.ai_metadata = classification
            doc.file_path = f"{project_id}/{doc_id}.enc"
            log.info("Document processing complete", doc_id=doc_id, chunks=chunks_count)
            
            # NOTIFICATION: SUCCESS
            await create_notification(
                db,
                user_id=uuid.UUID(user_id),
                type=NotificationType.SUCCESS,
                title="تمت معالجة الملف بنجاح",
                message=f"الملف {filename} جاهز للاستخدام في المشروع.",
            )
        except Exception as e:
            tb = traceback.format_exc()
            log.error("Document ingestion failed", filename=filename, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.processing_error = f"{str(e)} | Traceback: {tb[:400]}"
            
            # NOTIFICATION: FAILURE
            await create_notification(
                db,
                user_id=uuid.UUID(user_id),
                type=NotificationType.ERROR,
                title="فشل في معالجة الملف",
                message=f"حدث خطأ أثناء معالجة {filename}. يرجى التحقق من الملف والمحاولة مرة أخرى.",
            )
        await db.commit()


@router.get("/projects/{project_id}/documents/{doc_id}/status")
async def get_document_status(
    project_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حالة معالجة مستند — للـ polling من الواجهة."""
    await _get_project(project_id, user, db)
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": str(doc.id),
        "status": doc.status.value,
        "chunks_count": doc.chunks_count,
        "processing_error": doc.processing_error,
        "file_name": doc.original_name,
    }


@router.delete("/projects/{project_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    project_id: uuid.UUID,
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(project_id, user, db)
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await rag_service.delete_document_vectors(str(doc_id), str(project_id))
    await log_audit(db, AuditAction.FILE_DELETE, user_id=user.id, resource_id=str(doc_id))
    await db.delete(doc)
    await db.commit()


# ═══════════════════════════════════════════════════
#  CHAT / RAG
# ═══════════════════════════════════════════════════
class ChatMessage(BaseModel):
    message: str
    conversation_id: Optional[str] = None


@router.post("/projects/{project_id}/chat")
async def chat(
    project_id: str,
    body: ChatMessage,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="معرّف المشروع غير صالح")

    await _get_project(p_uuid, user, db)

    # Get or create conversation
    conv_id = uuid.UUID(body.conversation_id) if body.conversation_id else None
    if conv_id:
        result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = result.scalar_one_or_none()
    else:
        conv = Conversation(
            project_id=project_id,
            user_id=user.id,
            title=body.message[:80],
        )
        db.add(conv)
        await db.flush()

    # Save user message
    user_msg = Message(
        role="user",
        content=body.message,
        conversation_id=conv.id,
    )
    db.add(user_msg)
    await db.flush()

    # ── Subscription enforcement (AI query) ─────────────────────────
    from app.services.plans import get_effective_plan
    plan_enum, _ = get_effective_plan(user)
    custom = getattr(user.organization, "subscription_custom_limits", None) if getattr(user, "organization", None) else None
    await UsageTracker.check_ai_query(
        user_id=str(user.id),
        plan=plan_enum,
        redis=redis,
        custom_limits=custom,
    )
    # Count the query AFTER the check passes
    await UsageTracker.increment_ai_counter(str(user.id), redis)

    # RAG query — scoped to user's RBAC departments via rag_dept layer
    from app.services.rag_dept import query_rag_scoped
    rag_result = await query_rag_scoped(
        question=body.message,
        project_id=str(project_id),
        user=user,
        db=db,
    )

    # Save assistant message
    ai_msg = Message(
        role="assistant",
        content=rag_result["answer"],
        sources=rag_result["sources"],
        tokens_used=rag_result["tokens"],
        response_time_ms=rag_result["response_time_ms"],
        conversation_id=conv.id,
    )
    db.add(ai_msg)
    await log_audit(db, AuditAction.QUERY, user_id=user.id, resource_id=str(project_id), details={"tokens": rag_result["tokens"]})
    await db.commit()

    return {
        "conversation_id": str(conv.id),
        "answer": rag_result["answer"],
        "sources": rag_result["sources"],
        "tokens": rag_result["tokens"],
        "response_time_ms": rag_result["response_time_ms"],
    }


@router.post("/projects/{project_id}/export")
async def export_report(
    project_id: uuid.UUID,
    format: str = Form("pdf"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تصدير التقرير النهائي بتنسيقات متعددة (PDF, Word, Excel, etc.)"""
    await _get_project(project_id, user, db)

    # Get last assistant message in this project
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.project_id == project_id, Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_msg = result.scalar_one_or_none()
    if not last_msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="لا يوجد تقرير صادر من الذكاء الاصطناعي لتصديره حالياً"
        )

    content = last_msg.content
    gen = FileGenerator()
    
    file_bytes = b""
    media_type = "application/octet-stream"
    ext = format.lower()

    if ext == "pdf":
        file_bytes = gen.to_pdf(content)
        media_type = "application/pdf"
    elif ext == "docx":
        file_bytes = gen.to_docx(content)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == "xlsx":
        file_bytes = gen.to_xlsx(content)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext == "csv":
        file_bytes = gen.to_csv(content)
        media_type = "text/csv"
    elif ext == "pptx":
        file_bytes = gen.to_pptx(content)
        media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif ext == "pbi_csv":
        file_bytes = gen.to_pbi_csv(content)
        media_type = "text/csv"
        ext = "csv" # Download as .csv for Power BI
    else:
        file_bytes = gen.to_txt(content)
        media_type = "text/plain"
        ext = "txt"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=natiqa_report_{project_id}.{ext}"}
    )


@router.get("/projects/{project_id}/conversations")
async def list_conversations(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(project_id, user, db)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.project_id == project_id, Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    return [{"id": str(c.id), "title": c.title, "created_at": c.created_at.isoformat()} for c in convs]


@router.get("/conversations/{conv_id}/messages")
async def get_messages(
    conv_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user.id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "sources": m.sources,
            "created_at": m.created_at.isoformat(),
        }
        for m in msgs.scalars()
    ]


# ═══════════════════════════════════════════════════
#  AUTO-ORGANIZER  — Upload file from chat
# ═══════════════════════════════════════════════════

@router.post("/chat/upload")
async def chat_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Auto-Organizer: upload a file directly from the chat interface.
    """
    from app.services.plans import get_effective_plan
    from app.services.auto_organizer import handle_auto_classification

    # 1. Validate extension
    ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} not allowed")

    file_bytes = await file.read()

    # 2. Quota enforcement
    plan_enum, _ = get_effective_plan(user)
    custom = getattr(user.organization, "subscription_custom_limits", None) if getattr(user, "organization", None) else None
    await UsageTracker.check_upload(
        user_id=str(user.id),
        file_size_bytes=len(file_bytes),
        plan=plan_enum,
        db=db,
        redis=redis,
        custom_limits=custom,
    )
    if len(file_bytes) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)",
        )

    # 3. Project identification — use existing or create a new "Processing" one
    project = None
    if project_id:
        try:
            p_uuid = uuid.UUID(project_id)
            res = await db.execute(select(Project).where(Project.id == p_uuid, Project.owner_id == user.id))
            project = res.scalar_one_or_none()
        except ValueError:
            pass
    
    if not project:
        project = Project(
            name="جاري التصنيف...",
            description="AI is analyzing and classifying your project...",
            owner_id=user.id,
            organization_id=user.organization_id,
            status=ProjectStatus.PROCESSING
        )
        db.add(project)
        await db.flush()

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    
    # 4. Create Document record
    doc = Document(
        original_name=file.filename,
        file_name=f"{uuid.uuid4()}{ext}",
        file_path="pending",
        file_size=len(file_bytes),
        file_hash=file_hash,
        department="general", # Default, will be updated by classifier
        language="ar",
        status=DocumentStatus.PROCESSING,
        is_encrypted=True,
        project_id=project.id,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()
    doc_id = str(doc.id)

    # 5. Conversation + initial user message
    conv_id_uuid = uuid.UUID(conversation_id) if conversation_id else None
    if conv_id_uuid:
        conv_res = await db.execute(select(Conversation).where(Conversation.id == conv_id_uuid))
        conv = conv_res.scalar_one_or_none()
    else:
        conv = None
    if not conv:
        conv = Conversation(project_id=project.id, user_id=user.id, title=f"📎 {file.filename[:60]}")
        db.add(conv)
        await db.flush()

    db.add(Message(role="user", content=f"📎 {file.filename}", conversation_id=conv.id))
    
    # Initial "AI is analyzing" message
    wait_msg = "جاري تحليل وتصنيف مشروعك بالذكاء الاصطناعي... ⏳\n\n_AI is analyzing and classifying your project..._"
    db.add(Message(role="assistant", content=wait_msg, conversation_id=conv.id))

    await db.commit()
    await UsageTracker.invalidate_doc_cache(str(user.id), redis)

    # 6. Trigger background classification and ingestion
    background_tasks.add_task(
        handle_auto_classification,
        file_bytes=file_bytes,
        filename=file.filename,
        doc_id=doc_id,
        project_id=str(project.id),
        user_id=str(user.id),
        conv_id=str(conv.id),
        organization_id=str(user.organization_id) if user.organization_id else None
    )

    return {
        "conversation_id": str(conv.id),
        "answer": wait_msg,
        "project_id": str(project.id),
        "doc_id": doc_id,
        "status": "processing"
    }


# ═══════════════════════════════════════════════════
#  DASHBOARD STATS (real data)
# ═══════════════════════════════════════════════════
@router.get("/dashboard/stats")
async def dashboard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_count = await db.scalar(
        select(func.count()).select_from(Project).where(Project.owner_id == user.id)
    )
    doc_count = await db.scalar(
        select(func.count()).select_from(Document)
        .join(Project, Document.project_id == Project.id)
        .where(Project.owner_id == user.id, Document.status == DocumentStatus.READY)
    )
    total_chunks = await db.scalar(
        select(func.sum(Document.chunks_count))
        .select_from(Document)
        .join(Project, Document.project_id == Project.id)
        .where(Project.owner_id == user.id, Document.status == DocumentStatus.READY)
    )
    query_count = await db.scalar(
        select(func.count()).select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(Project, Conversation.project_id == Project.id)
        .where(Project.owner_id == user.id, Message.role == "user")
    )

    return {
        "projects": project_count or 0,
        "documents": doc_count or 0,
        "total_chunks": total_chunks or 0,
        "total_queries": query_count or 0,
    }
