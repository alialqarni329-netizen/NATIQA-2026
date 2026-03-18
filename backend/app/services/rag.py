"""
RAG Service — Document Ingestion + Vector Search + LLM (via Factory)
"""
import io
from pathlib import Path

import asyncio
import aiofiles
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
) -> int:
    log.info("Starting document ingestion", filename=filename, doc_id=doc_id)

    # 1. Extract
    text = await extract_text(file_bytes, filename)
    if not text.strip():
        raise ValueError("Could not extract text from document")

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
                    "department": department,
                    "chunk_index": i + j,
                    "provider": llm.provider_name,
                }
                for j in range(len(batch))
            ],
        )

    # 4. Encrypt & save
    encrypted = encrypt_file(file_bytes)
    save_path = Path(settings.UPLOAD_DIR) / project_id / f"{doc_id}.enc"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(encrypted)

    log.info("Ingestion complete", chunks=len(chunks), provider=llm.provider_name)
    return len(chunks)


# ─── RAG Query ───────────────────────────────────────────────────────
async def query_rag(
    question: str,
    project_id: str,
    top_k: int = 5,
) -> dict:
    import time
    start = time.time()

    llm = get_llm()

    q_embed_resp = await llm.embed(question)
    q_embed = q_embed_resp.embedding

    collection = get_collection(project_id)
    n = collection.count()

    results = collection.query(
        query_embeddings=[q_embed],
        n_results=min(top_k, n),
        include=["documents", "metadatas", "distances"],
    )

    sources = []
    if not results["documents"] or not results["documents"][0]:
        context = "No relevant context found. Use general knowledge."
    else:
        context_parts = []
        seen: set = set()
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        for doc, meta, dist in zip(docs, metas, distances):
            fname = meta.get("filename", "مجهول")
            dept = meta.get("department", "")
            context_parts.append(f"[المصدر: {fname}]\n{doc}")
            if fname not in seen:
                seen.add(fname)
                sources.append({
                    "filename": fname,
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