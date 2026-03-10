"""
Auto-Organizer Service
=======================
Upgrades the Chat Interface to act as an intelligent organizer.

When a file is uploaded in chat, this service:
  1. Classifies the file content via LLM into a business category.
  2. Finds an existing project for that category (scoped to the user's
     organization) — or creates a new one.
  3. Builds a bilingual Arabic/English confirmation message.

Multi-tenancy: every DB query is scoped by organization_id when available.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import structlog

log = structlog.get_logger()

# ── Valid categories returned by the LLM classifier ─────────────────────────
VALID_CATEGORIES = frozenset({
    "Legal", "Financial", "HR", "Technical", "Admin", "General"
})

CATEGORY_MAP_AR = {
    "Legal":     "قانوني",
    "Financial": "مالي",
    "HR":        "موارد بشرية",
    "Technical": "تقني",
    "Admin":     "إداري",
    "General":   "عام",
}

# Map category → department value expected by the Document model
CATEGORY_DEPT_MAP = {
    "Legal":     "legal",
    "Financial": "financial",
    "HR":        "hr",
    "Technical": "technical",
    "Admin":     "admin",
    "General":   "general",
}


# ────────────────────────────────────────────────────────────────────────────
# 1. Extract a short text sample from raw bytes (format-aware)
# ────────────────────────────────────────────────────────────────────────────

async def extract_text_sample(raw_bytes: bytes, filename: str, max_chars: int = 1500) -> str:
    """
    Return up to *max_chars* characters of extracted text for classification.
    Handles PDF, DOCX, Excel/CSV, and plain text — all other formats fall
    back to raw UTF-8 decode (best-effort).
    """
    ext = Path(filename).suffix.lower().lstrip(".")

    try:
        if ext == "pdf":
            import fitz  # PyMuPDF (already a project dependency)
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            pages = []
            for i in range(min(3, len(doc))):
                pages.append(doc[i].get_text("text"))
            doc.close()
            return " ".join(pages)[:max_chars]

        if ext in ("docx", "doc"):
            from docx import Document  # python-docx
            d = Document(io.BytesIO(raw_bytes))
            text = " ".join(p.text for p in d.paragraphs if p.text.strip())
            return text[:max_chars]

        if ext in ("xlsx", "xls", "xlsm", "csv"):
            import pandas as pd
            if ext == "csv":
                for enc in ("utf-8", "utf-8-sig", "windows-1256", "latin-1"):
                    try:
                        df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, nrows=20)
                        break
                    except Exception:
                        continue
                else:
                    df = pd.read_csv(io.BytesIO(raw_bytes), encoding="latin-1",
                                     errors="replace", nrows=20)
            else:
                df = pd.read_excel(io.BytesIO(raw_bytes), nrows=20)
            cols = ", ".join(str(c) for c in df.columns.tolist())
            sample_rows = df.head(5).to_string(index=False)
            return f"Columns: {cols}\n{sample_rows}"[:max_chars]

        # Plain text / markdown
        for enc in ("utf-8", "utf-8-sig", "windows-1256", "latin-1"):
            try:
                return raw_bytes.decode(enc)[:max_chars]
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("latin-1", errors="replace")[:max_chars]

    except Exception as exc:
        log.warning("auto_organizer: text extraction failed, using filename only",
                    filename=filename, error=str(exc))
        return filename  # fallback — classifier will still work on filename alone


# ────────────────────────────────────────────────────────────────────────────
# 2. AI Content Classifier
# ────────────────────────────────────────────────────────────────────────────

async def classify_file_content(
    text_sample: str,
    filename: str,
    llm,
) -> str:
    """
    Classify a document into one of the business categories via LLM.

    Returns one of:  Legal | Financial | HR | Technical | Admin | General
    Falls back to "General" on any error.
    """
    system_prompt = (
        "You are a business document classifier. "
        "Your ONLY job is to return exactly ONE word from this list: "
        "Legal, Financial, HR, Technical, Admin, General. "
        "No explanations. No punctuation. No other text."
    )

    user_prompt = (
        f"File name: {filename}\n\n"
        f"Content sample (first 1500 chars):\n{text_sample}\n\n"
        "Respond with exactly one word: "
        "Legal, Financial, HR, Technical, Admin, or General."
    )

    try:
        response = await llm.generate(
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.0,
            max_tokens=10,
        )
        raw = response.content.strip().split()[0]  # take first word
        # Normalize case variants (legal → Legal)
        for cat in VALID_CATEGORIES:
            if raw.lower() == cat.lower():
                log.info("auto_organizer: classified", filename=filename, category=cat)
                return cat
    except Exception as exc:
        log.warning("auto_organizer: LLM classification failed, defaulting to General",
                    filename=filename, error=str(exc))

    return "General"


# ────────────────────────────────────────────────────────────────────────────
# 3. Project resolver — find existing or create new (multi-tenant)
# ────────────────────────────────────────────────────────────────────────────

async def find_or_create_project(
    category: str,
    user,                   # app.models.models.User instance
    db: AsyncSession,
) -> "Project":             # noqa: F821  (forward ref)
    """
    Look for a project whose name == category, scoped to the user's
    organization_id (when set) AND owner_id.

    Creates the project if none exists.
    """
    from app.models.models import Project, ProjectStatus

    project_name = category  # e.g. "Financial"

    # Build query — always scoped to this user
    stmt = select(Project).where(
        Project.owner_id == user.id,
        Project.name == project_name,
    )
    # Extra multi-tenancy filter when org is known
    if user.organization_id:
        stmt = stmt.where(Project.organization_id == user.organization_id)

    result = await db.execute(stmt)
    project = result.scalar_one_or_none()

    if project:
        log.info("auto_organizer: linked to existing project",
                 project_id=str(project.id), name=project_name)
        return project

    # ── Create new project ────────────────────────────────────────────────
    dept_label = CATEGORY_MAP_AR.get(category, category)
    project = Project(
        name=project_name,
        description=f"مشروع {dept_label} — أُنشئ تلقائياً بواسطة المنظّم الذكي",
        owner_id=user.id,
        organization_id=user.organization_id,   # None-safe
        status=ProjectStatus.ACTIVE,
    )
    db.add(project)
    await db.flush()   # get generated UUID before commit
    log.info("auto_organizer: created new project",
             project_id=str(project.id), name=project_name,
             org_id=str(user.organization_id) if user.organization_id else None)
    return project


# ────────────────────────────────────────────────────────────────────────────
# 4. Confirmation message builder
# ────────────────────────────────────────────────────────────────────────────

async def handle_auto_classification(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    project_id: str,
    user_id: str,
    conv_id: str,
):
    """
    Background Task for Auto-Organizer:
      1. Classify file content.
      2. Update Project name & status.
      3. Trigger RAG ingestion.
      4. Update conversation confirmation message.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import Project, ProjectStatus, Document, Message, User
    from app.services.llm.factory import get_llm
    from app.services import rag as rag_service
    import traceback

    log.info("Auto-classification background task started", filename=filename, project_id=project_id)

    async with AsyncSessionLocal() as db:
        try:
            # 1. Classification
            llm = get_llm()
            text_sample = await extract_text_sample(file_bytes, filename)
            category = await classify_file_content(text_sample, filename, llm)
            department = CATEGORY_DEPT_MAP.get(category, "general")

            # 2. Update Project
            res_p = await db.execute(select(Project).where(Project.id == uuid.UUID(project_id)))
            project = res_p.scalar_one_or_none()
            if not project:
                log.error("Project not found for auto-classification", project_id=project_id)
                return

            cat_ar = CATEGORY_MAP_AR.get(category, category)
            project.name = category
            project.description = f"مشروع {cat_ar} — أُنشئ تلقائياً بواسطة المنظّم الذكي"
            project.status = ProjectStatus.ACTIVE

            # 3. Update Document & Trigger Ingestion
            res_d = await db.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
            doc = res_d.scalar_one_or_none()
            if doc:
                doc.department = department
            
            # Flush project/doc updates before ingestion
            await db.flush()

            # Ingestion
            chunks = await rag_service.ingest_document(
                file_bytes=file_bytes,
                filename=filename,
                doc_id=doc_id,
                project_id=project_id,
                department=department,
            )
            
            if doc:
                doc.chunks_count = chunks
                doc.status = DocumentStatus.READY
                doc.file_path = f"{project_id}/{doc_id}.enc"

            # 4. Update Assistant Message
            res_m = await db.execute(
                select(Message)
                .where(Message.conversation_id == uuid.UUID(conv_id), Message.role == "assistant")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            ai_msg = res_m.scalar_one_or_none()
            if ai_msg:
                ai_msg.content = build_confirmation(filename, category, project.name)

            await db.commit()
            log.info("Auto-classification complete", project_id=project_id, category=category)

        except Exception as e:
            tb = traceback.format_exc()
            log.error("Auto-classification failed", project_id=project_id, error=str(e))
            await db.rollback()


def build_confirmation(filename: str, category: str, project_name: str) -> str:
    """
    Return the Arabic/English confirmation message shown in the chat bubble.
    """
    cat_ar = CATEGORY_MAP_AR.get(category, category)
    return (
        f"✅ لقد حللت ملفك **{filename}** وصنّفته ضمن فئة **{cat_ar}** "
        f"وأضفته إلى مشروع **\"{project_name}\"** تلقائياً.\n\n"
        f"_I've analyzed your **{category}** file and added it to your "
        f"**{project_name}** project._"
    )

