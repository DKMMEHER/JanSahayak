"""
Health check router — Verifies the app and its dependencies are running.
"""

from fastapi import APIRouter

from jan_sahayak.config import get_settings
from jan_sahayak.schemas.api import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the application is healthy and running."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        version="0.1.0",
        environment=settings.app_env,
    )
