"""
Jan Sahayak — Main FastAPI Application Entry Point.

Government Scheme Discovery & Application Assistant powered by Sarvam AI.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from jan_sahayak.config import get_settings
from jan_sahayak.database import close_db, init_db
from jan_sahayak.exceptions import register_exception_handlers
from jan_sahayak.logger import get_logger, setup_logging
from jan_sahayak.routers import auth, chat, health, schemes, voice
from jan_sahayak.limiter import limiter


# Configure centralized logging (called once at startup)
setup_logging(level=logging.INFO)
logger = get_logger("jan_sahayak")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the application."""
    # Startup
    logger.info("🏛️ Jan Sahayak starting up...")
    await init_db()
    logger.info("✅ Database initialized")

    settings = get_settings()
    if settings.sarvam_api_key and settings.sarvam_api_key != "your_sarvam_api_key_here":
        logger.info("✅ Sarvam AI API key configured")
    else:
        logger.warning("⚠️ Sarvam AI API key not set! Set SARVAM_API_KEY in .env")

    tracing_enabled = settings.langsmith_tracing_v2 or settings.langsmith_tracing
    if settings.langsmith_api_key:
        if tracing_enabled:
            logger.info(f"🛠️ LangSmith tracing enabled for project: {settings.langsmith_project}")
        else:
            logger.info("🛠️ LangSmith config found but tracing is disabled (LANGSMITH_TRACING=false)")
    else:
        logger.info("ℹ️ LangSmith tracing is not configured (missing LANGSMITH_API_KEY)")

    logger.info("🚀 Jan Sahayak is ready!")

    yield

    # Shutdown
    logger.info("🏛️ Jan Sahayak shutting down...")
    await close_db()
    logger.info("👋 Goodbye!")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Jan Sahayak API",
        description=(
            "🏛️ Jan Sahayak (जन सहायक) — AI-powered Government Scheme Discovery & "
            "Application Assistant. Helps Indian citizens discover, understand, and apply "
            "for government welfare schemes in their own language using Sarvam AI."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' wss: ws: https:;"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Register custom exception handlers (clean JSON error responses)
    register_exception_handlers(app)


    # SlowAPI Rate Limiter setup
    app.state.limiter = limiter
    
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests. Please wait a moment before trying again.",
                "status_code": 429,
            }
        )

    # Register routers
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(schemes.router)
    app.include_router(chat.router)
    app.include_router(voice.router)

    # Mount Model Context Protocol (MCP) SSE Server
    from jan_sahayak.mcp_server import mcp
    app.mount("/mcp", mcp.sse_app())

    return app



# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "jan_sahayak.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_development,
    )
