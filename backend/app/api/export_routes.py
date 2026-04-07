"""
Smart Export API Routes
═══════════════════════
POST /export/generate      — upload file + choose format → get generated file
GET  /export/formats       — list supported formats + export types
POST /export/preview       — same as generate but returns base64 for in-browser preview
"""
from __future__ import annotations

import base64
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.core.dependencies import get_current_user
from app.models.models import User
from app.services.llm.factory import get_llm
from app.services.smart_export_service import (
    EXPORT_PROMPTS,
    FILE_EXTENSIONS,
    MIME_TYPES,
    generate_smart_export,
)

log = structlog.get_logger()

router = APIRouter(prefix="/export", tags=["Smart Export"])

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


# ─────────────────────────────────────────────────────────────────────────────
# GET /export/formats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/formats")
async def list_formats(_: User = Depends(get_current_user)):
    """Return all supported output formats and their export types."""
    return {
        "formats": [
            {
                "id":          "excel",
                "label":       "Excel",
                "label_ar":    "إكسل",
                "icon":        "📊",
                "extension":   "xlsx",
                "mime":        MIME_TYPES["excel"],
                "export_types": list(EXPORT_PROMPTS["excel"].keys()),
                "preview":     "table",  # frontend preview mode
                "color":       "#10b981",
            },
            {
                "id":          "word",
                "label":       "Word",
                "label_ar":    "وورد",
                "icon":        "📝",
                "extension":   "docx",
                "mime":        MIME_TYPES["word"],
                "export_types": list(EXPORT_PROMPTS["word"].keys()),
                "preview":     "download",
                "color":       "#3b82f6",
            },
            {
                "id":          "pdf",
                "label":       "PDF",
                "label_ar":    "بي دي إف",
                "icon":        "📄",
                "extension":   "pdf",
                "mime":        MIME_TYPES["pdf"],
                "export_types": list(EXPORT_PROMPTS["pdf"].keys()),
                "preview":     "pdf",
                "color":       "#ef4444",
            },
            {
                "id":          "powerpoint",
                "label":       "PowerPoint",
                "label_ar":    "باور بوينت",
                "icon":        "📑",
                "extension":   "pptx",
                "mime":        MIME_TYPES["powerpoint"],
                "export_types": list(EXPORT_PROMPTS["powerpoint"].keys()),
                "preview":     "download",
                "color":       "#f59e0b",
            },
            {
                "id":          "powerbi",
                "label":       "Power BI",
                "label_ar":    "باور بي آي",
                "icon":        "📈",
                "extension":   "json",
                "mime":        MIME_TYPES["powerbi"],
                "export_types": list(EXPORT_PROMPTS["powerbi"].keys()),
                "preview":     "json",
                "color":       "#f59e0b",
            },
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /export/generate   → streams the file directly
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_export(
    file:          UploadFile = File(...),
    output_format: str        = Form(...),
    export_type:   str        = Form(...),
    user:          User       = Depends(get_current_user),
):
    """
    Analyze the uploaded file with AI and return the generated file for download.
    Streams the binary response so it is memory-efficient.
    """
    if output_format not in MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"صيغة غير مدعومة: {output_format}. الصيغ المتاحة: {list(MIME_TYPES.keys())}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="حجم الملف يتجاوز الحد المسموح (20 MB)",
        )

    filename = file.filename or "document"
    log.info("export: generate request",
             user_id=str(user.id), format=output_format, type=export_type, filename=filename)

    try:
        llm = get_llm()
        buf, mime, out_name = await generate_smart_export(
            file_bytes=file_bytes,
            filename=filename,
            output_format=output_format,
            export_type=export_type,
            llm=llm,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("export: generation failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="فشل توليد الملف. يرجى المحاولة مجدداً.",
        )

    return StreamingResponse(
        buf,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Export-Filename": out_name,
            "X-Export-Format": output_format,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /export/preview   → returns base64 + metadata (for in-browser preview)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_export(
    file:          UploadFile = File(...),
    output_format: str        = Form(...),
    export_type:   str        = Form(...),
    user:          User       = Depends(get_current_user),
):
    """
    Same as /generate but returns base64-encoded file + JSON structure for
    in-browser rendering (Excel table preview, PDF iframe, JSON viewer, etc.)
    """
    if output_format not in MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"صيغة غير مدعومة: {output_format}")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="حجم الملف يتجاوز الحد المسموح (20 MB)")

    filename = file.filename or "document"
    log.info("export: preview request",
             user_id=str(user.id), format=output_format, filename=filename)

    try:
        llm = get_llm()
        buf, mime, out_name = await generate_smart_export(
            file_bytes=file_bytes,
            filename=filename,
            output_format=output_format,
            export_type=export_type,
            llm=llm,
        )
    except Exception as e:
        log.error("export: preview failed", error=str(e))
        raise HTTPException(status_code=500, detail="فشل توليد المعاينة.")

    raw_bytes = buf.read()
    b64 = base64.b64encode(raw_bytes).decode("ascii")

    return {
        "filename":      out_name,
        "format":        output_format,
        "mime":          mime,
        "size_bytes":    len(raw_bytes),
        "base64":        b64,
        "extension":     FILE_EXTENSIONS[output_format],
    }
