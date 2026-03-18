"""
╔══════════════════════════════════════════════════════════════════════╗
║  NATIQA — RAG Department Isolation Layer                            ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import time
from typing import List, Optional
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
    top_k: int = 5,
) -> dict:
    from app.services.rag import get_collection
    from app.services.llm import get_llm
    from app.services.llm.masking import mask_sensitive_data, unmask_data

    start   = time.time()
    allowed = resolve_user_departments(user)
    where_filter = build_dept_where_filter(allowed)

    log.info(
        "RAG scoped query",
        project_id=project_id,
        allowed_depts=allowed or "ALL",
        question_preview=question[:60],
    )

    llm = get_llm()

    # ── 1. Embed question ─────────────────────────────────────────────
    q_embed_resp = await llm.embed(question)
    q_embed      = q_embed_resp.embedding

    # ── 2. Scoped ChromaDB query ──────────────────────────────────────
    collection = get_collection(project_id)
    n          = collection.count()

    # if n == 0:
    #     return {
    #         "answer": "قاعدة المعرفة فارغة. يرجى رفع ملفات أولاً.",
    #         "sources": [], "tokens": 0,
    #         "response_time_ms": int((time.time() - start) * 1000),
    #         "dept_filter_applied": allowed,
    #     }

    query_kwargs = dict(
        query_embeddings=[q_embed],
        n_results=min(top_k, n),
        include=["documents", "metadatas", "distances"],
    )
    if where_filter:
        query_kwargs["where"] = where_filter

    try:
        results = collection.query(**query_kwargs)
    except Exception as e:
        log.warning("ChromaDB where-filter failed, falling back", error=str(e))
        results = collection.query(
            query_embeddings=[q_embed],
            n_results=min(top_k * 3, n),
            include=["documents", "metadatas", "distances"],
        )
        if results["documents"] and allowed:
            fd, fm, fdist = [], [], []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                if meta.get("department") in allowed:
                    fd.append(doc)
                    fm.append(meta)
                    fdist.append(dist)
            results["documents"][0] = fd[:top_k]
            results["metadatas"][0]  = fm[:top_k]
            results["distances"][0]  = fdist[:top_k]

    context_parts: list[str] = []
    sources: list[dict]      = []

    if not results["documents"] or not results["documents"][0]:
        log.info("No relevant documents found in ChromaDB")
        # continue to prompt anyway
        context = "No relevant context found in the project's documents. Use your general knowledge."
    else:
        # ── 3. Build context ──────────────────────────────────────────────
        raw_docs  = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        seen: set                = set()

        for doc_text, meta, dist in zip(raw_docs, metas, distances):
            doc_id = meta.get("doc_id", "")
            if doc_id in seen:
                continue
            seen.add(doc_id)
            dept = meta.get("department", "general")
            context_parts.append(
                f"[المصدر: {meta.get('filename','ملف')} | القسم: {dept}]\n{doc_text}"
            )
            sources.append({
                "doc_id":     doc_id,
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
2. إذا لم تجد الإجابة في السياق المزود، يمكنك الإجابة بناءً على معلوماتك العامة كخبير في الأنظمة السعودية، ولكن يجب أن توضح للمستخدم أنك تستخدم معلوماتك العامة لعدم توفر تفاصيل كافية في المستندات المرفوعة حالياً.
3. التزم دائماً بلهجة مهنية رسمية باللغة العربية.
4. إذا كان السؤال خارج نطاق العمل أو الأنظمة، اعتذر بلباقة وركز على دورك كخبير "ناطقة".

السياق (الوثائق المرفوعة):
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