"""Test fixtures: force offline mode + a file-based sqlite DB.

We deliberately avoid `:memory:` here: Starlette's TestClient runs each
request in its own asyncio event loop, and an in-memory + StaticPool engine
is bound to a single loop, so a second loop would open a fresh empty DB and
lose the tables. A temp *file* DB is shared across loops, which makes the
end-to-end HTTP tests deterministic without a real Postgres.
"""
import os
import tempfile

os.environ["RUN_OFFLINE"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./aipr_test.db"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
os.environ["OPENAI_API_KEY"] = "sk-offline"

import pytest  # noqa: E402

from common.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
async def _db():
    from common.db import connect, dispose

    await connect()
    yield
    await dispose()
