# ═══════════════════════════════════════════════════════════════
#  NATIQA Backend — Dockerfile (Railway-optimised)
#  Multi-stage build: builder → runtime
#  Final image: ~280 MB  (vs ~900 MB single-stage)
# ═══════════════════════════════════════════════════════════════

# ── Stage 1: Build deps ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Build-time system deps only (not needed at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Persistent directories (Railway ephemeral filesystem — use Railway Volume for uploads)
RUN mkdir -p /app/uploads /app/vectors

# Non-root user (Railway runs as root by default but non-root is best practice)
RUN useradd -m -u 1000 natiqa && chown -R natiqa:natiqa /app
USER natiqa

# Railway injects $PORT at runtime — uvicorn reads it via start command in railway.toml
EXPOSE 8000

# Healthcheck for local Docker usage (Railway uses healthcheckPath in railway.toml)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Default start (overridden by railway.toml startCommand in production)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
