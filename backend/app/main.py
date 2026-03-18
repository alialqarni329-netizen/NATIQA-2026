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

# ─── CORS (First) ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

@app.options("/{path:path}")
async def options_handler(path: str):
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
        }
    )

# ─── Static Files (Logo, etc) ──────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: HTTPException):
    log.error("404 Error", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=404,
        content={"detail": "رابط غير موجود أو غير صالح", "path": request.url.path},
    )


# ─── Routes ───────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(main_routes.router, prefix="/api")
app.include_router(user_routes.router, prefix="/api")
app.include_router(admin_routes.router, prefix="/api")   # Phase 1: /api/admin/*
app.include_router(admin_portal.router)                   # Phase 2: /admin-portal/*
app.include_router(notification_routes.router, prefix="/api")
app.include_router(integration_routes.router)
app.include_router(integration_routes.router)
app.include_router(agent_routes.router)
app.include_router(erp_routes.router)
app.include_router(org_routes.router, prefix="/api")
app.include_router(analytics_routes.router, prefix="/api")


@app.get("/api/health", tags=["Health"])
async def health(db: AsyncSession = Depends(get_db)):
    """
    Railway health check endpoint.
    Returns 200 when the app is running and DB is reachable.
    Returns 503 if DB is unreachable (Railway will restart the service).
    """
    from sqlalchemy import text
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        log.error("Health check DB failure", error=str(e))
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "status":      "unhealthy",
                "version":     settings.APP_VERSION,
                "database":    "unreachable",
                "environment": settings.ENVIRONMENT,
            }
        )

    return {
        "status":       "ok",
        "version":      settings.APP_VERSION,
        "environment":  settings.ENVIRONMENT,
        "database":     db_status,
        "debug":        settings.DEBUG,
    }
