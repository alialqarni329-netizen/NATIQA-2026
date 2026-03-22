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

# ─── CORS ──────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://frontend-production-043cd.up.railway.app",
        "http://localhost:3000",
        "https://natiqa.ai",
        "https://www.natiqa.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
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
    error_trace = traceback.format_exc()
    log.error("Unhandled Exception", error=str(exc), path=request.url.path, traceback=error_trace)
    
    # Return error type and message for easier debugging for the user
    response = JSONResponse(
        status_code=500,
        content={
            "detail": "خطأ داخلي في الخادم. يرجى المحاولة لاحقاً.",
            "debug": {
                "error_type": type(exc).__name__,
                "error_msg": str(exc),
                "path": request.url.path
            }
        },
    )
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
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

# ─── Static Files ──────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
