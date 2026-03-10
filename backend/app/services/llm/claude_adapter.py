"""
Claude API Adapter
"""
import time
import asyncio
from typing import Optional

import httpx

from app.services.llm.base import LLMBase, LLMResponse, EmbeddingResponse
from app.services.llm.masking import mask_sensitive_data, unmask_data
from app.core.config import settings
import structlog

log = structlog.get_logger()


class ClaudeAdapter(LLMBase):

    BASE_URL = "https://api.anthropic.com/v1"

    def __init__(self):
        self._embed_fn = None

    @property
    def provider_name(self) -> str:
        return "claude"

    def _headers(self) -> dict:
        return {
            "x-api-key": settings.CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _get_embed_fn(self):
        if self._embed_fn is None:
            from chromadb.utils import embedding_functions
            self._embed_fn = embedding_functions.DefaultEmbeddingFunction()
            log.info("Embedding initialized", model="chromadb-default")
        return self._embed_fn

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        from anthropic import AsyncAnthropic
        start = time.time()
        salt = settings.ENCRYPTION_KEY[:16]

        prompt_mask = mask_sensitive_data(prompt, session_salt=salt)
        masked_prompt = prompt_mask.masked_text
        all_mappings = dict(prompt_mask.mappings)

        masked_system = None
        if system:
            sys_mask = mask_sensitive_data(system, session_salt=salt)
            masked_system = sys_mask.masked_text
            all_mappings.update(sys_mask.mappings)

        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", settings.CLAUDE_API_KEY)
        client = AsyncAnthropic(api_key=api_key)

        kwargs = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": masked_prompt}],
        }
        if masked_system:
            kwargs["system"] = masked_system

        resp = await client.messages.create(**kwargs)
        
        raw_content = resp.content[0].text
        content = unmask_data(raw_content, all_mappings)

        usage = resp.usage
        return LLMResponse(
            content=content,
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens,
            response_time_ms=int((time.time() - start) * 1000),
        )

    async def embed(self, text: str) -> EmbeddingResponse:
        embed_fn = self._get_embed_fn()
        result = await asyncio.to_thread(embed_fn, [text])
        return EmbeddingResponse(
            embedding=result[0],
            model="chromadb-default",
            tokens=len(text.split()),
        )

    async def health_check(self) -> bool:
        if not settings.CLAUDE_API_KEY:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
