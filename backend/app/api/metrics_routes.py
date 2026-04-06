"""
Metrics & Monitoring Endpoint
================================
يوفّر مقاييس للمراقبة بصيغة Prometheus text format.
محمي بـ Internal-Only header — لا يُعرَّض للإنترنت العام.

الاستخدام:
  GET /api/metrics  →  Prometheus scrape
  GET /api/metrics/summary  →  JSON summary للـ dashboard

الحماية:
  - header: X-Metrics-Token (مشترك مع Prometheus scraper)
  - أو تقييد على مستوى nginx (localhost only)
"""
import time
import psutil
import structlog
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, func, select

from app.core.database import get_db
from app.core.config import settings

log = structlog.get_logger()
router = APIRouter(prefix="/metrics", tags=["Monitoring"])

# ── In-memory counters (reset on restart) ────────────────────────────────
_counters: dict = {
    "requests_total": 0,
    "requests_error": 0,
    "logins_total": 0,
    "logins_failed": 0,
    "documents_processed": 0,
    "llm_calls_total": 0,
    "llm_errors_total": 0,
    "data_masked_fields": 0,
}
_start_time = time.time()


def increment(key: str, value: int = 1) -> None:
    """Thread-safe (GIL-protected) counter increment."""
    _counters[key] = _counters.get(key, 0) + value


def _check_metrics_access(request: Request) -> None:
    """
    يتحقق من صلاحية الوصول للـ metrics.
    في الإنتاج: يُقيَّد عبر nginx على localhost فقط.
    """
    # اقبل من localhost دائماً
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return

    # أو عبر internal header
    metrics_token = getattr(settings, "METRICS_TOKEN", "")
    provided_token = request.headers.get("X-Metrics-Token", "")
    if metrics_token and provided_token == metrics_token:
        return

    # الوصول محظور
    raise HTTPException(status_code=403, detail="Metrics access restricted")


@router.get("", response_class=PlainTextResponse)
async def prometheus_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Prometheus text format metrics.
    يُستخدم مع prometheus.yml:
      scrape_configs:
        - job_name: 'natiqa'
          metrics_path: '/api/metrics'
          static_configs:
            - targets: ['backend:8000']
    """
    _check_metrics_access(request)

    uptime = time.time() - _start_time
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()

    # ── DB stats ──────────────────────────────────────────────────────
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM users"))
        users_count = result.scalar() or 0
    except Exception:
        users_count = -1

    try:
        result = await db.execute(text("SELECT COUNT(*) FROM documents"))
        docs_count = result.scalar() or 0
    except Exception:
        docs_count = -1

    lines = [
        "# HELP natiqa_uptime_seconds Time since last restart",
        "# TYPE natiqa_uptime_seconds gauge",
        f"natiqa_uptime_seconds {uptime:.2f}",
        "",
        "# HELP natiqa_requests_total Total HTTP requests",
        "# TYPE natiqa_requests_total counter",
        f"natiqa_requests_total {_counters.get('requests_total', 0)}",
        "",
        "# HELP natiqa_requests_error_total Total HTTP 5xx errors",
        "# TYPE natiqa_requests_error_total counter",
        f"natiqa_requests_error_total {_counters.get('requests_error', 0)}",
        "",
        "# HELP natiqa_logins_total Total login attempts",
        "# TYPE natiqa_logins_total counter",
        f"natiqa_logins_total {_counters.get('logins_total', 0)}",
        "",
        "# HELP natiqa_logins_failed_total Total failed login attempts",
        "# TYPE natiqa_logins_failed_total counter",
        f"natiqa_logins_failed_total {_counters.get('logins_failed', 0)}",
        "",
        "# HELP natiqa_llm_calls_total Total LLM API calls",
        "# TYPE natiqa_llm_calls_total counter",
        f"natiqa_llm_calls_total {_counters.get('llm_calls_total', 0)}",
        "",
        "# HELP natiqa_data_masked_fields_total Total sensitive fields masked",
        "# TYPE natiqa_data_masked_fields_total counter",
        f"natiqa_data_masked_fields_total {_counters.get('data_masked_fields', 0)}",
        "",
        "# HELP natiqa_cpu_percent Current CPU usage",
        "# TYPE natiqa_cpu_percent gauge",
        f"natiqa_cpu_percent {cpu}",
        "",
        "# HELP natiqa_memory_used_bytes Memory used in bytes",
        "# TYPE natiqa_memory_used_bytes gauge",
        f"natiqa_memory_used_bytes {mem.used}",
        "",
        "# HELP natiqa_memory_total_bytes Total memory in bytes",
        "# TYPE natiqa_memory_total_bytes gauge",
        f"natiqa_memory_total_bytes {mem.total}",
        "",
        "# HELP natiqa_users_total Total registered users",
        "# TYPE natiqa_users_total gauge",
        f"natiqa_users_total {users_count}",
        "",
        "# HELP natiqa_documents_total Total documents in system",
        "# TYPE natiqa_documents_total gauge",
        f"natiqa_documents_total {docs_count}",
        "",
    ]

    return "\n".join(lines)


@router.get("/summary")
async def metrics_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """JSON summary للـ admin dashboard."""
    _check_metrics_access(request)

    uptime = time.time() - _start_time
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()

    return {
        "uptime_seconds": round(uptime),
        "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
        "system": {
            "cpu_percent": cpu,
            "memory_used_mb": round(mem.used / 1024 / 1024),
            "memory_total_mb": round(mem.total / 1024 / 1024),
            "memory_percent": mem.percent,
        },
        "counters": _counters.copy(),
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }
