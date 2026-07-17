"""Celery worker + task definitions (QUEUE & WORKER in the diagram).

The Webhook service enqueues `process_pr_task`. The worker runs the
Orchestrator review pipeline asynchronously. Redis is the broker; when the
broker is unavailable (offline mode) callers fall back to `process_pr`
directly.
"""
from __future__ import annotations

from celery import Celery

from common.config import settings

celery_app = Celery(
    "aipr",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])


async def process_pr(payload: dict) -> dict:
    """Run the full pipeline for a webhook payload (called by the worker)."""
    from common.db import connect
    from common.github import parse_webhook
    from orchestrator.main import _execute

    await connect()
    ctx = parse_webhook(payload)
    if ctx is None:
        return {"error": "not_a_pr_event"}
    result = await _execute(ctx)
    return result.model_dump(mode="json")


@celery_app.task(name="process_pr_task", bind=True, max_retries=3)
def process_pr_task(self, payload: dict) -> dict:
    import asyncio

    try:
        return asyncio.run(process_pr(payload))
    except Exception as exc:  # pragma: no cover - broker path
        raise self.retry(exc=exc, countdown=10)
