"""
LLM Base Interface — Adapter Pattern
======================================
كل Provider يرث من هذه الـ Abstract Base Class.
منطق العمل في rag.py لا يعرف شيئاً عن Claude أو Ollama —
يتحدث فقط مع LLMBase.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class LLMResponse:
    """الاستجابة الموحّدة من أي Provider."""
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_time_ms: int = 0


@dataclass
class EmbeddingResponse:
    """استجابة التضمين الموحّدة."""
    embedding: list
    model: str
    tokens: int = 0


class LLMBase(ABC):
    """
    Abstract Base — كل LLM Provider يجب أن ينفّذ هذه الوظائف.
    منطق RAG يتحدث مع هذه الـ Interface فقط.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        conversation_history: Optional[List[dict]] = None,
        trust_system: bool = False,
    ) -> LLMResponse:
        """
        توليد نص من prompt.

        المعاملات:
            prompt: رسالة المستخدم الحالية
            system: prompt النظام (سياق الوثائق)
            temperature: درجة الإبداع (0.0 = حتمي، 1.0 = إبداعي)
            max_tokens: الحد الأقصى للرموز
            conversation_history: سجل المحادثة السابقة
                [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
            trust_system: عندما True، لا يُطبَّق Masking على system prompt
                (للبيانات الداخلية المحفوظة في قاعدة البيانات)
        """
        ...

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResponse:
        """تحويل نص إلى embedding vector."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """التحقق من أن الـ Provider يعمل."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """اسم الـ Provider (claude / ollama / openai ...)"""
        ...
