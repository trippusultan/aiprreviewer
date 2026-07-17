"""Centralised configuration loaded from environment (.env supported)."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_TRUE = {"1", "true", "yes", "on"}


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in _TRUE


class Settings:
    """Runtime settings. Read once; mutate is unnecessary."""

    def __init__(self) -> None:
        self.service_name: str = _env("SERVICE_NAME", "aipr")
        self.run_offline: bool = _bool("RUN_OFFLINE", True)
        self.log_level: str = _env("LOG_LEVEL", "INFO")

        # LLM
        self.openai_api_key: str = _env("OPENAI_API_KEY", "sk-offline")
        self.openai_model: str = _env("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_base_url: str = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")

        # GitHub
        self.github_api_url: str = _env("GITHUB_API_URL", "https://api.github.com")
        self.github_webhook_secret: str = _env("GITHUB_WEBHOOK_SECRET", "dev-secret")
        self.github_token: str = _env("GITHUB_TOKEN", "")
        self.github_app_id: str = _env("GITHUB_APP_ID", "")
        self.github_app_client_id: str = _env("GITHUB_APP_CLIENT_ID", "")
        self.github_app_private_key: str = _env("GITHUB_APP_PRIVATE_KEY", "")
        self.github_app_private_key_path: str = _env("GITHUB_APP_PRIVATE_KEY_PATH", "")

        # Persistence
        self.database_url: str = _env(
            "DATABASE_URL", "sqlite+aiosqlite:///./aipr.db"
        )

        # Queue
        self.redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
        self.celery_broker_url: str = _env(
            "CELERY_BROKER_URL", "redis://localhost:6379/0"
        )
        self.celery_result_backend: str = _env(
            "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"
        )

        # Service discovery
        self.gateway_url: str = _env("GATEWAY_URL", "http://localhost:8000")
        self.webhook_url: str = _env("WEBHOOK_URL", "http://localhost:8001")
        self.orchestrator_url: str = _env("ORCHESTRATOR_URL", "http://localhost:8002")
        self.reviewer_url: str = _env("REVIEWER_URL", "http://localhost:8003")
        self.learner_url: str = _env("LEARNER_URL", "http://localhost:8004")

        # Tuning
        self.reviewer_max_comments: int = int(_env("REVIEWER_MAX_COMMENTS", "30"))

        # Observability
        self.langfuse_public_key: str = _env("LANGFUSE_PUBLIC_KEY", "")
        self.langfuse_secret_key: str = _env("LANGFUSE_SECRET_KEY", "")
        self.langfuse_host: str = _env("LANGFUSE_HOST", "https://cloud.langfuse.com")

    @property
    def using_github_app(self) -> bool:
        return bool(self.github_app_id and (self.github_app_private_key or self.github_app_private_key_path))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
