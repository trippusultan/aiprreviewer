"""WEBHOOK SERVICE (FastAPI) — receives verified events from the Gateway.

Parse PR -> deduplicate by SHA -> store metadata -> push to Redis/Celery queue.
When a PR is *closed+merged*, the diff is also sent to the Learner service so
it can extract recurring patterns and improve future reviews (feedback loop).
Mirrors the diagram's Webhook box (Parse PR / Deduplicate / Store Metadata ->
PostgreSQL) plus the Learner feedback edge.
"""
from __future__ import annotations

import hashlib

import httpx
from fastapi import BackgroundTasks, FastAPI, Request

from common.config import settings
from common.github import fetch_pr_diff, get_installation_token, parse_webhook
from common.observability import PR_EVENTS
from common.db import connect, save_review
from common.models import PRContext
from common.server import add_landing, make_lifespan
from common.observability import instrument

_SEEN: set[str] = set()  # in-process dedup cache (Redis-backed in prod)


async def _startup():
    await connect()


app = FastAPI(title="AI PR Reviewer — Webhook", version="1.0.0", lifespan=make_lifespan(_startup))
add_landing(
    app,
    "Webhook",
    "Receives verified events from the Gateway: parses the PR, de-duplicates by SHA, "
    "stores metadata in PostgreSQL, and enqueues the review job. Merged PRs are "
    "forwarded to the Learner to close the self-improving feedback loop.",
)
instrument(app)

@app.get("/health")
async def health():
    return {"service": "webhook", "status": "ok"}


def _dedupe_key(ctx: PRContext) -> str:
    return hashlib.sha256(
        f"{ctx.repo_full_name}:{ctx.pr_number}:{ctx.head_sha}".encode()
    ).hexdigest()


async def _learn(ctx: PRContext) -> None:
    """Fetch the merged diff and hand it to the Learner service."""
    try:
        token = None
        if ctx.installation_id and settings.using_github_app:
            token = await get_installation_token(ctx.installation_id)
        diff = await fetch_pr_diff(ctx, token) if (token or settings.github_token) else ""
        if not diff:
            return
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.learner_url}/learn",
                json={"repo_full_name": ctx.repo_full_name, "diff": diff},
                timeout=20,
            )
    except Exception:
        # Learner is best-effort; never block the webhook on it.
        pass


@app.post("/webhook")
async def inbound(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    if PR_EVENTS is not None:
        PR_EVENTS.labels(action=payload.get("action", "?"), service="webhook").inc()

    ctx = parse_webhook(payload)
    if ctx is None:
        return {"accepted": False, "reason": "not_a_pr_event"}

    # Feedback loop: closed + merged PR -> Learner extracts patterns.
    if payload.get("action") == "closed" and payload.get("pull_request", {}).get(
        "merged"
    ):
        background_tasks.add_task(_learn, ctx)
        return {"accepted": True, "reason": "merged_learn_queued"}

    key = _dedupe_key(ctx)
    if key in _SEEN:
        return {"accepted": False, "reason": "duplicate_sha"}
    _SEEN.add(key)

    # Enqueue via Celery when a broker is configured (production). Otherwise
    # schedule in-process via FastAPI BackgroundTasks, which Starlette awaits
    # within the request's event loop (no leaked asyncio task at teardown).
    if not settings.run_offline:
        try:
            from worker.tasks import process_pr_task

            process_pr_task.delay(payload)
        except Exception:
            pass  # fall through to in-process below
    from worker.pipeline import process_pr

    background_tasks.add_task(process_pr, payload)

    return {"accepted": True, "repo": ctx.repo_full_name, "pr": ctx.pr_number}
