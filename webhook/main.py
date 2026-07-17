"""WEBHOOK SERVICE (FastAPI) — receives verified events from the Gateway.

Parse PR -> deduplicate by SHA -> store metadata -> push to Redis/Celery queue.
Mirrors the diagram's Webhook box (Parse PR / Deduplicate / Store Metadata ->
PostgreSQL).
"""
from __future__ import annotations

import hashlib
import json
from fastapi import FastAPI, Request

from common.config import settings
from common.github import parse_webhook
from common.observability import PR_EVENTS
from common.db import connect, save_review
from common.models import PRContext

app = FastAPI(title="AI PR Reviewer — Webhook", version="1.0.0")

_SEEN: set[str] = set()  # in-process dedup cache (Redis-backed in prod)


@app.on_event("startup")
async def _startup():
    await connect()


@app.get("/health")
async def health():
    return {"service": "webhook", "status": "ok"}


def _dedupe_key(ctx: PRContext) -> str:
    return hashlib.sha256(
        f"{ctx.repo_full_name}:{ctx.pr_number}:{ctx.head_sha}".encode()
    ).hexdigest()


@app.post("/webhook")
async def inbound(request: Request):
    payload = await request.json()
    if PR_EVENTS is not None:
        PR_EVENTS.labels(action=payload.get("action", "?"), service="webhook").inc()

    ctx = parse_webhook(payload)
    if ctx is None:
        return {"accepted": False, "reason": "not_a_pr_event"}

    key = _dedupe_key(ctx)
    if key in _SEEN:
        return {"accepted": False, "reason": "duplicate_sha"}
    _SEEN.add(key)

    # Enqueue async processing job (Celery). Falls back to immediate no-op if
    # broker is offline in dev.
    try:
        from worker.tasks import process_pr_task

        process_pr_task.delay(payload)
    except Exception:
        # Broker not available (offline) — schedule via in-process loop instead.
        import asyncio
        from worker.tasks import process_pr

        asyncio.create_task(process_pr(payload))

    return {"accepted": True, "repo": ctx.repo_full_name, "pr": ctx.pr_number}
