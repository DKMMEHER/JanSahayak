"""
Application configuration using Pydantic Settings.
Loads values from .env file automatically.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Sarvam AI
    sarvam_api_key: str = ""

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./jan_sahayak.db"

    # LangSmith / LangChain Observability
    langsmith_tracing: bool = True
    langsmith_tracing_v2: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "jan-sahayak"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Application
    app_name: str = "Jan Sahayak"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Authentication & JWT
    jwt_secret_key: str = "172e1141c48647f6c9549cf8c8604aae9a1645a38e74161dfed5f7b04517a957"
    jwt_expiry_minutes: int = 1440
    auth_provider: str = "local"  # "local" or "firebase"
    firebase_credentials_path: str = "jansahayak-firebase-credentials.json"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    model_config = {
        "env_file": (".env", "../.env", "../../.env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached singleton of Settings.
    Using lru_cache ensures the .env file is read only once.
    """
    settings = Settings()

    # Enable LangSmith tracing
    settings.langsmith_tracing = True
    settings.langsmith_tracing_v2 = True

    import os
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_TRACING"] = "true"

    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint

        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint

    return settings

