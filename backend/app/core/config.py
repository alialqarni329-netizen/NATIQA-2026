from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):

    # ── App ───────────────────────────────────────────────────
    APP_NAME:    str  = "ناطقة — NATIQA Enterprise AI"
    APP_VERSION: str  = "4.1.0"
    ENVIRONMENT: str  = "production"
    DEBUG:       bool = False

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY:                    str = "CHANGE_ME_IN_ENV"
    ENCRYPTION_KEY:                str = "CHANGE_ME_IN_ENV"
    ACCESS_TOKEN_EXPIRE_MINUTES:   int = 60
    REFRESH_TOKEN_EXPIRE_DAYS:     int = 7
    ALGORITHM:                     str = "HS256"

    # ── Rate Limiting ─────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE:       int = 60
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5

    # ── Database ──────────────────────────────────────────────
    # Railway Postgres plugin sets DATABASE_URL automatically.
    # asyncpg requires postgresql+asyncpg:// scheme.
    # If Railway gives postgresql:// we normalise it in the property below.
    DATABASE_URL: str = "postgresql+asyncpg://natiqa_admin:password@db:5432/natiqa"

    @property
    def async_database_url(self) -> str:
        """Ensure scheme is always postgresql+asyncpg:// regardless of source."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # ── Redis ─────────────────────────────────────────────────
    # Railway Redis plugin sets REDIS_URL automatically.
    REDIS_URL: str = "redis://redis:6379/0"

    # ── CORS ──────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,https://frontend-production-043cd.up.railway.app,https://natiqa.ai"
    FRONTEND_URL: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    # ── LLM Provider ──────────────────────────────────────────
    LLM_PROVIDER:       str = "claude"
    CLAUDE_API_KEY:     str = ""
    CLAUDE_MODEL:       str = "claude-3-5-sonnet-20241022"
    OLLAMA_URL:         str = "http://ollama:11434"
    OLLAMA_MODEL:       str = "qwen2.5:7b"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"

    # ── Email — OTP delivery ──────────────────────────────────
    # RESEND_API_KEY : your Resend.com secret key
    # ENABLE_REAL_EMAIL : False → write to debug_emails.html (local preview)
    #                     True  → send via Resend API
    RESEND_API_KEY:    str  = ""
    RESEND_FROM_EMAIL: str  = "verify@natiqa.ai"
    ENABLE_REAL_EMAIL: bool = False

    @property
    def email_enabled(self) -> bool:
        """True only when both the key is set AND live mode is enabled."""
        return bool(self.RESEND_API_KEY) and self.ENABLE_REAL_EMAIL

    # ── File Storage ──────────────────────────────────────────
    UPLOAD_DIR:           str       = "/app/uploads"
    VECTOR_DIR:           str       = "/app/vectors"
    MAX_FILE_SIZE_MB:     int       = 50
    ALLOWED_EXTENSIONS:   List[str] = [
        ".pdf", ".docx", ".doc",
        ".xlsx", ".xls", ".csv",
        ".txt", ".md",
    ]

    # ── First Admin ───────────────────────────────────────────
    FIRST_ADMIN_EMAIL:    str = "admin@natiqa.local"
    FIRST_ADMIN_PASSWORD: str = "Admin@2025!"
    FIRST_ADMIN_NAME:     str = "مدير النظام"

    class Config:
        env_file      = ".env"
        case_sensitive = True
        extra          = "ignore"


settings = Settings()
