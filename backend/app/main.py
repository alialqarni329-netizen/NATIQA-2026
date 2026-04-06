"""
NATIQA Platform — FastAPI Application Entry Point
"""
import structlog  # type: ignore
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # type: ignore
from fastapi.responses import JSONResponse  # type: ignore
from slowapi import Limiter, _rate_limit_exceeded_handler  # type: ignore
from slowapi.util import get_remote_address  # type: ignore
from slowapi.errors import RateLimitExceeded  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore

from app.core.config import settings  # type: ignore
from app.core.database import init_db, get_db
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from app.api import auth, main_routes  # type: ignore
from app.api import integration_routes  # type: ignore
from app.api import agent_routes  # type: ignore
from app.api import user_routes  # type: ignore
from app.api import erp_routes  # type: ignore
from app.api import admin_routes   # type: ignore  ← Phase 1 B2B admin approval
from app.api import admin_portal   # type: ignore  ← Phase 2 Admin Dashboard UI
from app.api import notification_routes
from app.api import org_routes, analytics_routes
from app.api import metrics_routes      # type: ignore  ← Prometheus monitoring
from app.api import messaging_routes    # type: ignore  ← Internal messaging
from app.services.trial_scheduler import create_scheduler  # type: ignore  ← Phase 3 Golden Trial

log = structlog.get_logger()
_scheduler = create_scheduler()   # Golden Trial nightly jobs

# ─── Rate limiter ──────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])



# ─── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting NATIQA Platform", version=settings.APP_VERSION)
    await init_db()
    _scheduler.start()
    log.info("Golden Trial scheduler started")
    yield
    _scheduler.shutdown(wait=False)
    log.info("Shutting down NATIQA Platform")


# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ─── CORS ─ يُقرأ من .env عبر settings.cors_origins_list ──────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

# ─── Exception Handlers with CORS support ──────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    response = JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers or {}
    )
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    import uuid as _uuid
    error_trace = traceback.format_exc()
    error_id = _uuid.uuid4().hex[:12]
    log.error(
        "Unhandled Exception",
        error_id=error_id,
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        traceback=error_trace,
    )
    # في الإنتاج: لا نكشف تفاصيل الخطأ — نرجع error_id فقط للمتابعة
    content: dict = {"detail": "خطأ داخلي في الخادم. يرجى المحاولة لاحقاً.", "error_id": error_id}
    if settings.DEBUG:
        content["debug"] = {
            "error_type": type(exc).__name__,
            "error_msg": str(exc),
            "path": request.url.path,
        }
    response = JSONResponse(status_code=500, content=content)
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: HTTPException):
    log.error("404 Error", path=request.url.path, method=request.method)
    response = JSONResponse(
        status_code=404,
        content={"detail": "رابط غير موجود أو غير صالح", "path": request.url.path},
    )
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


# ─── Routes ───────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(main_routes.router, prefix="/api")
app.include_router(user_routes.router, prefix="/api")
app.include_router(admin_routes.router, prefix="/api")   # Phase 1: /api/admin/*
app.include_router(admin_portal.router)                   # Phase 2: /admin-portal/*
app.include_router(notification_routes.router, prefix="/api")
app.include_router(integration_routes.router, prefix="/api")
app.include_router(agent_routes.router, prefix="/api")
app.include_router(erp_routes.router, prefix="/api")
app.include_router(org_routes.router, prefix="/api")
app.include_router(analytics_routes.router, prefix="/api")
app.include_router(metrics_routes.router, prefix="/api")
app.include_router(messaging_routes.router, prefix="/api")

# ─── Static Files ──────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/api/health", tags=["Health"])
async def health(db: AsyncSession = Depends(get_db)):
    """
    Railway health check endpoint.
    Returns 200 when app, DB, and Redis are all reachable.
    Returns 503 if any critical dependency is unreachable.
    """
    from sqlalchemy import text
    import time

    checks: dict = {}
    healthy = True

    # ── Database check ────────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        await db.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        log.error("Health check DB failure", error=str(e))
        checks["database"] = {"status": "unreachable", "error": str(e) if settings.DEBUG else "unreachable"}
        healthy = False

    # ── Redis check ───────────────────────────────────────────────────
    try:
        t0 = time.monotonic()
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await _redis.ping()
        await _redis.aclose()
        checks["redis"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        log.error("Health check Redis failure", error=str(e))
        checks["redis"] = {"status": "unreachable", "error": str(e) if settings.DEBUG else "unreachable"}
        healthy = False

    payload = {
        "status":      "ok" if healthy else "degraded",
        "version":     settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "checks":      checks,
    }

    if not healthy:
        return JSONResponse(status_code=503, content={**payload, "status": "unhealthy"})

    return payload
