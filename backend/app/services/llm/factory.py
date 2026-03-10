"""
LLM Factory
=============
نقطة التحكم الوحيدة لاختيار الـ Provider.
منطق العمل في rag.py يستدعي get_llm() فقط —
لا يعرف شيئاً عن Claude أو Ollama.

التحكم عبر .env:
    LLM_PROVIDER=claude   ← Anthropic Claude API (مع Masking تلقائي)
    LLM_PROVIDER=ollama   ← Ollama محلي (بدون Masking — لا حاجة له)
"""
from app.services.llm.base import LLMBase
from app.core.config import settings
import structlog

log = structlog.get_logger()

# Singleton — instance واحد طوال عمر التطبيق
_instance: LLMBase | None = None


def get_llm() -> LLMBase:
    """
    يُرجع instance واحد من الـ Provider المختار.
    استبدال الـ Provider = تغيير سطر واحد في .env:
        LLM_PROVIDER=claude  →  LLM_PROVIDER=ollama
    """
    global _instance

    if _instance is not None:
        return _instance

    provider = settings.LLM_PROVIDER.lower().strip()

    if provider == "claude":
        from app.services.llm.claude_adapter import ClaudeAdapter
        _instance = ClaudeAdapter()
        log.info(
            "LLM Provider initialized",
            provider="Claude API",
            model=settings.CLAUDE_MODEL,
            masking="enabled",
        )

    elif provider == "ollama":
        from app.services.llm.ollama_adapter import OllamaAdapter
        _instance = OllamaAdapter()
        log.info(
            "LLM Provider initialized",
            provider="Ollama (local)",
            model=settings.OLLAMA_MODEL,
            masking="not needed — fully local",
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider}'. "
            "Valid options: claude | ollama"
        )

    return _instance


def reset_llm():
    """
    يُعيد تهيئة الـ Provider.
    مفيد عند تغيير الإعدادات بدون إعادة تشغيل.
    """
    global _instance
    _instance = None
    log.info("LLM Provider reset")
