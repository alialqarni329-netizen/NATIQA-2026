"""
Claude API Adapter — مع دعم كامل للمحادثات متعددة الأدوار وتقنيع البيانات
"""
import time
import asyncio
from typing import Optional, List

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
        temperature: float = 0.5,
        max_tokens: int = 8192,
        conversation_history: Optional[List[dict]] = None,
        trust_system: bool = False,
    ) -> LLMResponse:
        """
        يُرسل الرسالة لـ Claude مع دعم:
        - conversation_history: سجل المحادثة للذاكرة الكاملة
        - trust_system=True: لا يُقنَّع system prompt (بيانات وثائق داخلية)
        - trust_system=False (default): يُقنَّع كل شيء (للبيانات الخارجية)
        """
        from anthropic import AsyncAnthropic
        import os

        start = time.time()
        salt = settings.ENCRYPTION_KEY[:16]
        all_mappings: dict = {}

        # ── تقنيع رسالة المستخدم الحالية دائماً ────────────────────────
        prompt_mask = mask_sensitive_data(prompt, session_salt=salt)
        masked_prompt = prompt_mask.masked_text
        all_mappings.update(prompt_mask.mappings)

        # ── system prompt: يُقنَّع فقط عند trust_system=False ────────────
        hidden_instruction = (
            "When generating reports, use clear structure with [HEADING], [TABLE], and [SLIDE] tags. "
            "For multi-project data, perform comparative analysis highlighting differences and trends. "
            "Always respond in Arabic unless explicitly asked otherwise."
        )

        masked_system: Optional[str] = None
        if system:
            if trust_system:
                # بيانات داخلية (وثائق المستخدم) — لا تقنيع
                masked_system = f"{system}\n\n{hidden_instruction}"
                log.debug("Claude: system prompt trusted (no masking)", chars=len(system))
            else:
                # بيانات خارجية أو تكامل — تقنيع كامل
                full_system = f"{system}\n\n{hidden_instruction}"
                sys_mask = mask_sensitive_data(full_system, session_salt=salt)
                masked_system = sys_mask.masked_text
                all_mappings.update(sys_mask.mappings)
        else:
            masked_system = hidden_instruction

        # ── بناء سجل المحادثة (multi-turn) ──────────────────────────────
        messages: List[dict] = []

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role not in ("user", "assistant"):
                    continue
                # تقنيع رسائل المستخدم في التاريخ
                if role == "user" and content:
                    h_mask = mask_sensitive_data(content, session_salt=salt)
                    content = h_mask.masked_text
                    all_mappings.update(h_mask.mappings)
                messages.append({"role": role, "content": content})

        # إضافة الرسالة الحالية
        messages.append({"role": "user", "content": masked_prompt})

        # Claude API يتطلب أن يتبادل user/assistant — تحقق من الترتيب
        messages = _ensure_alternating(messages)

        api_key = os.environ.get("ANTHROPIC_API_KEY", settings.CLAUDE_API_KEY)
        client = AsyncAnthropic(api_key=api_key)

        kwargs: dict = {
            "model": settings.CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if masked_system:
            kwargs["system"] = masked_system

        if all_mappings:
            log.debug(
                "Claude: data masking applied",
                fields_masked=len(all_mappings),
                trust_system=trust_system,
            )

        resp = await client.messages.create(**kwargs)

        raw_content = resp.content[0].text

        # ── فك التقنيع على الرد ──────────────────────────────────────────
        content = unmask_data(raw_content, all_mappings) if all_mappings else raw_content

        usage = resp.usage
        return LLMResponse(
            content=content,
            model=settings.CLAUDE_MODEL,
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


def _ensure_alternating(messages: List[dict]) -> List[dict]:
    """
    Claude API يتطلب تبادل صارم user↔assistant.
    يدمج الرسائل المتكررة من نفس الدور إذا لزم الأمر.
    """
    if not messages:
        return messages

    result = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == result[-1]["role"]:
            # دمج رسالتين متتاليتين من نفس الدور
            result[-1] = {
                "role": result[-1]["role"],
                "content": f"{result[-1]['content']}\n\n{msg['content']}",
            }
        else:
            result.append(msg)

    # يجب أن تبدأ بـ user
    if result and result[0]["role"] != "user":
        result.insert(0, {"role": "user", "content": "."})

    return result
