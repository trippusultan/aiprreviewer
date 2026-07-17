"""Celery task wrapper for the worker process.

`process_pr` (the pure pipeline) lives in `worker.pipeline` so importing THIS
module is the only thing that wires up Celery/Redis. The Webhook service only
imports `worker.pipeline.process_pr` for the offline fallback, and imports this
module (to call `process_pr_task.delay`) only when a broker is configured.
"""
from __future__ import annotations

from common.config import settings
from celery import Celery

celery_app = Celery(
    "aipr",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Fail fast when the broker/result store is unreachable so callers can
    # fall back to in-process execution instead of blocking on retries.
    broker_connection_max_retries=0,
    broker_connection_retry=False,
    task_publish_retry=False,
    result_backend_max_retries=0,
)

from worker.pipeline import process_pr  # noqa: E402


@celery_app.task(name="process_pr_task", bind=True, max_retries=3)
def process_pr_task(self, payload: dict) -> dict:
    try:
        return asyncio.run(process_pr(payload))
    except Exception as exc:  # pragma: no cover - broker path
        raise self.retry(exc=exc, countdown=10)
