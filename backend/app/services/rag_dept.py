"""
╔══════════════════════════════════════════════════════════════════════╗
║  NATIQA — RAG Department Isolation Layer + Conversation Memory       ║
╚══════════════════════════════════════════════════════════════════════╝

إصلاحات v4.2:
- إضافة ذاكرة المحادثة الكاملة (آخر 10 رسائل)
- إصلاح ازدواج التقنيع: السياق الداخلي (وثائق المستخدم) يُرسَل
  بـ trust_system=True فلا يُقنَّع في المحوّل — فقط سؤال المستخدم يُقنَّع
"""
from __future__ import annotations
import time
from typing import List, Optional
import uuid
from sqlalchemy import select
from app.models.models import Project
import structlog

log = structlog.get_logger()

ROLE_DEPT_DEFAULTS: dict[str, list] = {
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
    if role_val in ("admin", "super_admin", "org_admin"):
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
    db,
    top_k: int = 5,
    conversation_history: Optional[List[dict]] = None,
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
        history_msgs=len(conversation_history) if conversation_history else 0,
    )

    llm = get_llm()

    # ── 1. تحديد المشاريع المستهدفة ─────────────────────────────────
    project_ids = [project_id]
    if user.organization_id:
        try:
            res = await db.execute(
                select(Project.id).where(Project.organization_id == user.organization_id)
            )
            project_ids = [str(pid) for pid in res.scalars().all()]
        except Exception as e:
            log.warning("Global Search: project lookup failed", error=str(e))

    # ── 2. تضمين السؤال ─────────────────────────────────────────────
    q_embed_resp = await llm.embed(question)
    q_embed      = q_embed_resp.embedding

    # ── 3. البحث في ChromaDB عبر كل المشاريع ───────────────────────
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
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    all_combined.append((doc, meta, dist))
        except Exception:
            continue

    all_combined = sorted(all_combined, key=lambda x: x[2])[:top_k]

    context_parts: list = []
    sources: list       = []

    if not all_combined:
        log.info("No relevant documents found in any project")
        context = "لم يتم العثور على سياق ذي صلة في الوثائق. استخدم معلوماتك العامة."
        has_docs = False
    else:
        seen_docs = set()
        for doc_text, meta, dist in all_combined:
            doc_id = meta.get("doc_id", "")
            if doc_id in seen_docs: continue
            seen_docs.add(doc_id)

            dept  = meta.get("department", "general")
            p_id  = meta.get("project_id", "unknown")
            fname = meta.get("filename", "ملف")
            context_parts.append(
                f"[المشروع: {p_id} | المصدر: {fname} | القسم: {dept}]\n{doc_text}"
            )
            sources.append({
                "doc_id":     doc_id,
                "project_id": meta.get("project_id"),
                "filename":   fname,
                "department": dept,
                "relevance":  round(1 - float(dist), 3),
            })

        context = "\n\n---\n\n".join(context_parts)
        has_docs = True

    # ── 4. بناء System Prompt (السياق) ──────────────────────────────
    dept_info = f"الأقسام المتاحة: {', '.join(allowed)}" if allowed else "جميع الأقسام"

    system_prompt = f"""أنت مساعد ذكاء اصطناعي محترف للنظام السعودي "ناطقة" (Natiqa).
مهمتك تحليل وثائق المؤسسة والإجابة بدقة واحترافية.

إرشادات:
1. استخدم المعلومات في "السياق" للإجابة بدقة. اذكر الأرقام والتفاصيل بوضوح.
2. إذا وجدت بيانات من مشاريع متعددة، قارن وأبرز الفروق والاتجاهات.
3. إذا لم تجد إجابة في الوثائق، قل ذلك بوضوح ثم استخدم معلوماتك العامة.
4. الإجابة دائماً باللغة العربية بلهجة مهنية رسمية.
5. {dept_info}

السياق (وثائق المؤسسة):
{context}"""

    # ── 5. تقنيع سؤال المستخدم فقط (لا السياق الداخلي) ─────────────
    # trust_system=True: السياق بيانات داخلية لا تُقنَّع في المحوّل
    # المحوّل سيُقنَّع سؤال المستخدم تلقائياً
    # ملاحظة: لا نُقنَّع السياق هنا لأن ذلك كان يسبب:
    #   1. ازدواج التقنيع (rag_dept + adapter)
    #   2. تقنيع أرقام مالية كـ هوية وطنية → كلود لا يستطيع تحليلها
    prompt = (
        f"السؤال: {question}\n\n"
        f"الإجابة (باللغة العربية):"
    )

    # ── 6. استدعاء LLM مع سجل المحادثة ─────────────────────────────
    response = await llm.generate(
        prompt=prompt,
        system=system_prompt,
        temperature=0.1,
        max_tokens=2048,
        conversation_history=conversation_history,
        trust_system=True,   # ← السياق بيانات داخلية موثوقة
    )

    return {
        "answer":              response.content,
        "sources":             sources,
        "tokens":              response.total_tokens,
        "response_time_ms":    int((time.time() - start) * 1000),
        "dept_filter_applied": allowed or "ALL",
        "has_context":         has_docs,
    }


async def get_user_accessible_docs_count(
    project_id: str,
    user,
) -> dict[str, int]:
    from app.services.rag import get_collection

    allowed    = resolve_user_departments(user)
    collection = get_collection(project_id)
    depts      = allowed if allowed else list(ALL_DEPARTMENTS)
    counts: dict = {}

    for dept in depts:
        try:
            result       = collection.get(where={"department": {"$eq": dept}}, include=[])
            counts[dept] = len(result.get("ids", []))
        except Exception:
            counts[dept] = 0

    return counts
