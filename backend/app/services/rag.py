"""
RAG Service — Document Ingestion + Vector Search + LLM (via Factory)
"""
import io
from pathlib import Path

import asyncio
import logging
from typing import Optional, List, Tuple

import chromadb

from app.core.config import settings
from app.core.security import encrypt_file, decrypt_file
from app.services.llm import get_llm
import structlog

log = structlog.get_logger()


# ─── ChromaDB ────────────────────────────────────────────────────────
def get_chroma_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.VECTOR_DIR)


def get_collection(project_id: str):
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=f"project_{project_id}",
        metadata={"hnsw:space": "cosine"},
    )


# ─── Text Extraction ─────────────────────────────────────────────────
async def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n\n".join(
            page.extract_text() or "" for page in reader.pages
        )

    elif ext in (".docx", ".doc"):
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif ext in (".xlsx", ".xls"):
        import pandas as pd
        try:
            xl = pd.ExcelFile(io.BytesIO(file_bytes))
            all_sheets = []
            for sheet_name in xl.sheet_names:
                try:
                    df = xl.parse(sheet_name)
                    if not df.empty:
                        all_sheets.append(
                            f"--- ورقة: {sheet_name} ---\n{df.to_string(index=False)}"
                        )
                except Exception:
                    continue
            if not all_sheets:
                raise ValueError("الملف فارغ أو تالف")
            return "\n\n".join(all_sheets)
        except Exception as e:
            raise ValueError(f"فشل قراءة ملف Excel: {str(e)}")

    elif ext == ".csv":
        import pandas as pd
        df = pd.read_csv(io.BytesIO(file_bytes))
        return df.to_string(index=False)

    elif ext in (".txt", ".md"):
        return file_bytes.decode("utf-8", errors="ignore")

    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ─── Document Ingestion ──────────────────────────────────────────────
async def ingest_document(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    project_id: str,
    department: str,
    organization_id: Optional[str] = None,
) -> Tuple[int, dict]: # Return chunks count and classification
    log.info("Starting document ingestion", filename=filename, doc_id=doc_id)

    # 1. Extract & Classify
    text = await extract_text(file_bytes, filename)
    if not text.strip():
        raise ValueError("Could not extract text from document")
        
    # Classification logic
    classification = await classify_document_content(text[:1500])
    log.info("Document classified", classification=classification)

    # 2. Split
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", "،", " ", ""],
    )
    chunks = splitter.split_text(text)
    log.info("Text split into chunks", count=len(chunks))

    # 3. Embed
    llm = get_llm()
    collection = get_collection(project_id)

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i: i + batch_size]
        ids = [f"{doc_id}_{i + j}" for j in range(len(batch))]

        # Parallelize embedding calls
        tasks = [llm.embed(chunk) for chunk in batch]
        resps = await asyncio.gather(*tasks)
        embeds = [r.embedding for r in resps]

        collection.add(
            ids=ids,
            embeddings=embeds,
            documents=batch,
            metadatas=[
                {
                    "doc_id": doc_id,
                    "filename": filename,
                    "project_id": project_id,
                    "organization_id": organization_id,
                    "department": department,
                    "chunk_index": i + j,
                    "provider": llm.provider_name,
                    "doc_type": classification.get("document_type"),
                    "priority": classification.get("priority"),
                }
                for j in range(len(batch))
            ],
        )

    # 4. Encrypt & save
    encrypted = encrypt_file(file_bytes)
    save_path = Path(settings.UPLOAD_DIR) / project_id / f"{doc_id}.enc"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    import aiofiles
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(encrypted)

    log.info("Ingestion complete", chunks=len(chunks), provider=llm.provider_name)
    return len(chunks), classification


# ─── Classification Helper ───────────────────────────────────────────
async def classify_document_content(text_sample: str) -> dict:
    """
    Classify a document using AI.
    Returns: { 'document_type': '...', 'summary': '...', 'priority': '...' }
    """
    from app.services.llm.factory import get_llm
    import json
    
    llm = get_llm()
    system_prompt = (
        "You are a document analyzer. "
        "Analyze the provided document text and return a JSON object with: "
        "'document_type' (e.g., Contract, Invoice, Report, Memo, Legal), "
        "'summary' (a concise 1-sentence summary in Arabic), "
        "'priority' (High, Medium, or Low based on business importance). "
        "Return ONLY the JSON object. No markdown, no backticks."
    )
    
    try:
        response = await llm.generate(
            prompt=f"Text sample:\n{text_sample}",
            system=system_prompt,
            temperature=0.0,
            max_tokens=200,
        )
        # Attempt to parse JSON
        content = response.content.strip()
        # Remove potential markdown block markers
        if content.startswith("```"):
            try:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            except IndexError:
                pass
        
        return json.loads(content)
    except Exception as e:
        log.warning("Classification failed", error=str(e))
        return {
            "document_type": "Unknown",
            "summary": "فشل التحليل التلقائي للمستند.",
            "priority": "Low"
        }


# ─── RAG Query ───────────────────────────────────────────────────────
async def query_rag(
    question: str,
    project_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    project_ids: Optional[List[str]] = None,
    top_k: int = 5,
) -> dict:
    import time
    start = time.time()

    llm = get_llm()

    q_embed_resp = await llm.embed(question)
    q_embed = q_embed_resp.embedding

    # 2. Vector Search
    client = get_chroma_client()
    
    # If project_ids is not provided, but project_id is, use it.
    target_projects = project_ids or ([project_id] if project_id else [])
    
    # Simple strategy: Search target project(s). 
    # If organization_id is provided, the caller should have populated project_ids.
    all_docs = []
    all_metas = []
    all_dists = []

    for p_id in target_projects:
        try:
            col = get_collection(p_id)
            n = col.count()
            if n == 0: continue
            
            res = col.query(
                query_embeddings=[q_embed],
                n_results=min(top_k, n),
                include=["documents", "metadatas", "distances"],
            )
            if res["documents"] and res["documents"][0]:
                all_docs.extend(res["documents"][0])
                all_metas.extend(res["metadatas"][0])
                all_dists.extend(res["distances"][0])
        except Exception as e:
            log.warning("Search failed for project", project_id=p_id, error=str(e))

    # Sort results by distance across all projects
    combined = sorted(zip(all_docs, all_metas, all_dists), key=lambda x: x[2])[:top_k]
    
    sources = []
    if not combined:
        context = "لم يتم العثور على سياق ذي صلة في الوثائق. استخدم معلوماتك العامة."
    else:
        context_parts = []
        seen_docs = set()
        for doc, meta, dist in combined:
            fname = meta.get("filename", "مجهول")
            pname = meta.get("project_name", meta.get("project_id", "غير محدد"))
            dept = meta.get("department", "")
            
            context_parts.append(f"[المشروع: {pname} | المصدر: {fname}]\n{doc}")
            
            d_id = meta.get("doc_id")
            if d_id not in seen_docs:
                seen_docs.add(d_id)
                sources.append({
                    "filename": fname,
                    "project_id": meta.get("project_id"),
                    "department": dept,
                    "relevance": round(1 - dist, 3),
                })
        context = "\n\n---\n\n".join(context_parts)

    system_prompt = f"""
أنت مساعد ذكاء اصطناعي محترف للنظام السعودي "ناطقة" (Natiqa).
ساعد المستخدم بناءً على السياق أدناه. إذا لم تجد الإجابة، استخدم معلوماتك العامة مع التنويه بذلك.

السياق:
{context}
    """

    prompt = (
        f"السؤال: {question}\n\n"
        f"أجب بشكل مباشر ودقيق واستشهد بالأرقام."
    )

    llm_resp = await llm.generate(
        prompt=prompt,
        system=system_prompt,
        temperature=0.3,
        max_tokens=2048,
    )

    return {
        "answer":           llm_resp.content,
        "sources":          sources,
        "tokens":           llm_resp.total_tokens,
        "response_time_ms": llm_resp.response_time_ms,
        "provider":         llm.provider_name,
    }


# ─── Delete document vectors ─────────────────────────────────────────
async def delete_document_vectors(doc_id: str, project_id: str):
    collection = get_collection(project_id)
    results = collection.get(where={"doc_id": doc_id})
    if results["ids"]:
        collection.delete(ids=results["ids"])

    enc_path = Path(settings.UPLOAD_DIR) / project_id / f"{doc_id}.enc"
    if enc_path.exists():
        enc_path.unlink()

    log.info("Document deleted", doc_id=doc_id, project_id=project_id)