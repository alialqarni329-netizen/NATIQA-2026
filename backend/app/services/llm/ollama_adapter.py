"""
Ollama Local LLM Adapter — مع دعم المحادثات وتقنيع البيانات
"""
import time
from typing import Optional, List

import httpx

from app.services.llm.base import LLMBase, LLMResponse, EmbeddingResponse
from app.services.llm.masking import mask_sensitive_data, unmask_data
from app.core.config import settings
import structlog

log = structlog.get_logger()


class OllamaAdapter(LLMBase):
    """Adapter لـ Ollama — يعمل محلياً مع Data Masking كطبقة دفاع متعمق."""

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        conversation_history: Optional[List[dict]] = None,
        trust_system: bool = False,
    ) -> LLMResponse:
        start = time.time()
        all_mappings: dict = {}

        # ── تقنيع رسالة المستخدم ─────────────────────────────────────────
        prompt_mask = mask_sensitive_data(prompt)
        masked_prompt = prompt_mask.masked_text
        all_mappings.update(prompt_mask.mappings)

        # ── system prompt ────────────────────────────────────────────────
        masked_system = system
        if system and not trust_system:
            sys_result = mask_sensitive_data(system)
            masked_system = sys_result.masked_text
            all_mappings.update(sys_result.mappings)

        # ── بناء prompt مع التاريخ (Ollama API style) ────────────────────
        # Ollama /api/generate لا يدعم multi-turn مباشرة — نبني السياق يدوياً
        full_prompt = ""
        if conversation_history:
            for msg in conversation_history[-6:]:  # آخر 6 رسائل فقط
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    h_mask = mask_sensitive_data(content)
                    content = h_mask.masked_text
                    all_mappings.update(h_mask.mappings)
                    full_prompt += f"\n\nMustakhdem: {content}"
                elif role == "assistant":
                    full_prompt += f"\n\nNatiqa: {content}"

        full_prompt += f"\n\nMustakhdem: {masked_prompt}\n\nNatiqa:"

        if all_mappings:
            log.info("Ollama: sensitive data masked", fields_masked=len(all_mappings))

        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": full_prompt.strip(),
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
