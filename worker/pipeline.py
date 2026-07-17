"""Pure review-pipeline logic, free of any Celery / Redis import.

Importing this module must NOT touch the broker, so the webhook can run the
pipeline in-process during offline/dev/test without attempting a Redis connection.
The Celery wrapper lives in `worker.tasks`, which imports this module.
"""
from __future__ import annotations

import asyncio

from common.db import connect
from common.github import parse_webhook
from orchestrator.main import _execute
from common.models import PRContext


async def process_pr(payload: dict) -> dict:
    """Run the full review pipeline for a webhook payload."""
    await connect()
    ctx = parse_webhook(payload)
    if ctx is None:
        return {"error": "not_a_pr_event"}
    result = await _execute(ctx)
    return result.model_dump(mode="json")
