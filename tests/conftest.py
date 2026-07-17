"""Test fixtures: force offline mode + sqlite in-memory so the whole pipeline
runs deterministically without OpenAI/Redis/Postgres."""
import os

os.environ["RUN_OFFLINE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
os.environ["OPENAI_API_KEY"] = "sk-offline"

import pytest  # noqa: E402

from common.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
async def _db():
    from common.db import connect, dispose

    await connect(settings.database_url)
    yield
    await dispose()
