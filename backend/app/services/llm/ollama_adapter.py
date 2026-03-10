"""
Ollama Local LLM Adapter
==========================
يُنفّذ LLMBase باستخدام Ollama (Local LLM).
لا Masking مطلوب — كل شيء يعمل محلياً على الخادم.
"""
import time
import asyncio
from typing import Optional

import httpx

from app.services.llm.base import LLMBase, LLMResponse, EmbeddingResponse
from app.core.config import settings
import structlog

log = structlog.get_logger()


class OllamaAdapter(LLMBase):
    """Adapter لـ Ollama — يعمل محلياً بالكامل بدون أي API خارجي."""

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        start = time.time()

        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
            },
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        prompt_t = data.get("prompt_eval_count", 0)
        comp_t   = data.get("eval_count", 0)

        return LLMResponse(
            content=data.get("response", "").strip(),
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
