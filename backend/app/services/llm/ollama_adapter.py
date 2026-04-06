"""
Ollama Local LLM Adapter
==========================
يُنفّذ LLMBase باستخدام Ollama (Local LLM).

ملاحظة أمنية: على الرغم من أن Ollama يعمل محلياً، نُطبّق Data Masking
كطبقة دفاع متعمق (Defense-in-Depth) لضمان عدم تخزين أي بيانات حساسة
في سجلات Ollama أو ذاكرة النموذج عند إعادة تحميله.
"""
import time
from typing import Optional

import httpx

from app.services.llm.base import LLMBase, LLMResponse, EmbeddingResponse
from app.services.llm.masking import mask_sensitive_data, unmask_data
from app.core.config import settings
import structlog

log = structlog.get_logger()


class OllamaAdapter(LLMBase):
    """Adapter لـ Ollama — يعمل محلياً مع Data Masking كطبقة أمان إضافية."""

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        session_salt: str = "",
    ) -> LLMResponse:
        start = time.time()

        # ── Data Masking (Defense-in-Depth) ──────────────────────────────
        mask_result = mask_sensitive_data(prompt, session_salt=session_salt)
        masked_prompt = mask_result.masked_text
        if mask_result.count > 0:
            log.info(
                "Ollama: sensitive data masked before local inference",
                fields_masked=mask_result.count,
            )

        masked_system = system
        system_mappings: dict = {}
        if system:
            sys_result = mask_sensitive_data(system, session_salt=session_salt)
            masked_system = sys_result.masked_text
            system_mappings = sys_result.mappings

        all_mappings = {**mask_result.mappings, **system_mappings}

        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": masked_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
            },
        }
        if masked_system:
            payload["system"] = masked_system

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_response = data.get("response", "").strip()

        # ── Unmasking: استعادة القيم الأصلية للمستخدم ───────────────────
        final_response = unmask_data(raw_response, all_mappings) if all_mappings else raw_response

        prompt_t = data.get("prompt_eval_count", 0)
        comp_t   = data.get("eval_count", 0)

        return LLMResponse(
            content=final_response,
            model=settings.OLLAMA_MODEL,
            prompt_tokens=prompt_t,
            completion_tokens=comp_t,
            total_tokens=prompt_t + comp_t,
            response_time_ms=int((time.time() - start) * 1000),
        )

    async def embed(self, text: str) -> EmbeddingResponse:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_URL}/api/embeddings",
                json={
                    "model": settings.OLLAMA_EMBED_MODEL,
                    "prompt": text,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return EmbeddingResponse(
            embedding=data["embedding"],
            model=settings.OLLAMA_EMBED_MODEL,
            tokens=len(text.split()),
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
