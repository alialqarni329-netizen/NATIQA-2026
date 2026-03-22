"""
╔══════════════════════════════════════════════════════════════════════╗
║  NATIQA — RAG Department Isolation Layer                            ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import time
from typing import List, Optional
import uuid
from sqlalchemy import select
from app.models.models import Project
import structlog

log = structlog.get_logger()

ROLE_DEPT_DEFAULTS: dict[str, list[str]] = {
    "super_admin": None,
    "admin":       None,
    "hr_analyst":  ["hr", "admin", "general"],
    "analyst":     ["general"],
    "viewer":      ["general"],
}

ALL_DEPARTMENTS = {
    "financial", "hr", "legal", "technical",
    "sales", "admin", "general",
}


def resolve_user_departments(user) -> Optional[List[str]]:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val in ("admin", "super_admin"):
        return None
    depts = user.allowed_depts
    if not depts:
        depts = ROLE_DEPT_DEFAULTS.get(role_val, ["general"])
    return sorted(set(depts) & ALL_DEPARTMENTS) or ["general"]


def build_dept_where_filter(allowed_depts: Optional[List[str]]) -> Optional[dict]:
    if allowed_depts is None:
        return None
    if len(allowed_depts) == 1:
        return {"department": {"$eq": allowed_depts[0]}}
    return {"department": {"$in": allowed_depts}}


async def query_rag_scoped(
    question: str,
    project_id: str,
    user,
    db, # Add db session for multi-project lookup
    top_k: int = 5,
) -> dict:
    from app.services.rag import get_collection
    from app.services.llm import get_llm
    from app.services.llm.masking import mask_sensitive_data, unmask_data

    start   = time.time()
    allowed = resolve_user_departments(user)
    where_filter = build_dept_where_filter(allowed)

    log.info(
        "RAG scoped query (Global Search)",
        project_id=project_id,
        allowed_depts=allowed or "ALL",
        org_id=user.organization_id,
    )

    llm = get_llm()

    # ── 1. Determine target projects (Global Search) ──────────────────
    project_ids = [project_id]
    if user.organization_id:
        try:
            res = await db.execute(
                select(Project.id).where(Project.organization_id == user.organization_id)
            )
            project_ids = [str(pid) for pid in res.scalars().all()]
        except Exception as e:
            log.warning("Global Search: project lookup failed", error=str(e))

    # ── 2. Embed question ─────────────────────────────────────────────
    q_embed_resp = await llm.embed(question)
    q_embed      = q_embed_resp.embedding

    # ── 3. Multi-project ChromaDB query ───────────────────────────────
    all_combined = []
    for p_id in project_ids:
        try:
            col = get_collection(p_id)
            n = col.count()
            if n == 0: continue
            
            query_kwargs = dict(
                query_embeddings=[q_embed],
                n_results=min(top_k, n),
                include=["documents", "metadatas", "distances"],
            )
            if where_filter:
                query_kwargs["where"] = where_filter
                
            results = col.query(**query_kwargs)
            if results["documents"] and results["documents"][0]:
                for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
                    all_combined.append((doc, meta, dist))
        except Exception:
            continue

    # Sort and pick top_k
    all_combined = sorted(all_combined, key=lambda x: x[2])[:top_k]

    context_parts: list[str] = []
    sources: list[dict]      = []

    if not all_combined:
        log.info("No relevant documents found in any project")
        context = "لم يتم العثور على سياق ذي صلة في الوثائق. استخدم معلوماتك العامة."
    else:
        seen_docs = set()
        for doc_text, meta, dist in all_combined:
            doc_id = meta.get("doc_id", "")
            if doc_id in seen_docs: continue
            seen_docs.add(doc_id)
            
            dept = meta.get("department", "general")
            p_id = meta.get("project_id", meta.get("project_name", "unknown"))
            context_parts.append(
                f"[المشروع: {p_id} | المصدر: {meta.get('filename','ملف')} | القسم: {dept}]\n{doc_text}"
            )
            sources.append({
                "doc_id":     doc_id,
                "project_id": meta.get("project_id"),
                "filename":   meta.get("filename", "ملف"),
                "department": dept,
                "relevance":  round(1 - float(dist), 3),
            })

        context = "\n\n---\n\n".join(context_parts)

    # ── 4. Mask → LLM → Unmask ───────────────────────────────────────
    mask_ctx      = mask_sensitive_data(context)
    masked_context = mask_ctx.masked_text
    entities       = mask_ctx.mappings

    mask_q         = mask_sensitive_data(question)
    masked_question = mask_q.masked_text

    dept_info = f"الأقسام المتاحة: {', '.join(allowed)}" if allowed else "جميع الأقسام"

    system_prompt = f"""
أنت مساعد ذكاء اصطناعي محترف للنظام السعودي "ناطقة" (Natiqa).
مسؤوليتك هي مساعدة المستخدمين في تحليل الوثائق والبيانات بناءً على المعرفة المتوفرة في المشروع.

إرشادات العمل:
1. استخدم المعلومات المزودة في "السياق" أدناه للإجابة على سؤال المستخدم بدقة.
2. إذا وجدت بيانات من مشاريع متعددة، قم بإجراء تحليل مقارن ووضح الفروق أو الاتجاهات.
3. التزم دائماً بلهجة مهنية رسمية باللغة العربية.

السياق (الوثائق المرفوعة عبر المؤسسة):
{masked_context}
    """

    prompt = (
        f"{dept_info}\n\n"
        f"السؤال: {masked_question}\n\n"
        f"الإجابة (باللغة العربية):"
    )

    # ── 5. LLM call ───────────────────────────────────────────────────
    response = await llm.generate(
        prompt=prompt,
        system=system_prompt,
        temperature=0.1,
        max_tokens=1500,
    )

    answer = unmask_data(response.content, entities)

    return {
        "answer":              answer,
        "sources":             sources,
        "tokens":              response.total_tokens,
        "response_time_ms":    int((time.time() - start) * 1000),
        "dept_filter_applied": allowed or "ALL",
    }


async def get_user_accessible_docs_count(
    project_id: str,
    user,
) -> dict[str, int]:
    from app.services.rag import get_collection

    allowed    = resolve_user_departments(user)
    collection = get_collection(project_id)
    depts      = allowed if allowed else list(ALL_DEPARTMENTS)
    counts: dict[str, int] = {}

    for dept in depts:
        try:
            result       = collection.get(where={"department": {"$eq": dept}}, include=[])
            counts[dept] = len(result.get("ids", []))
        except Exception:
            counts[dept] = 0

    return counts