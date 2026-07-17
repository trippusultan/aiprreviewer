"""ORCHESTRATOR SERVICE (FastAPI) — drives the review run.

Flow (per diagram): Fetch Code Diff -> Load Repo Patterns -> LangGraph Review ->
hand merged result to the Reviewer service. Exposes /review for direct calls and
/review/async for the worker.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException

from common.config import settings
from common.db import connect, load_patterns, save_review
from common.github import fetch_pr_diff, get_installation_token, parse_webhook
from common.models import PRContext, ReviewRecord, ReviewResult
from common.observability import REVIEW_RUNS, REVIEW_LATENCY
from engine import run_review
from common.server import add_landing

app = FastAPI(title="AI PR Reviewer — Orchestrator", version="1.0.0")
add_landing(app, "Orchestrator", "Drives the review: fetches the code diff, loads repo-specific learned patterns, runs the LangGraph multi-agent engine, and hands the merged result to the Reviewer.")


@app.on_event("startup")
async def _startup():
    await connect()


@app.get("/health")
async def health():
    return {"service": "orchestrator", "status": "ok"}


async def _execute(ctx: PRContext) -> ReviewResult:
    with REVIEW_LATENCY.time() if REVIEW_LATENCY is not None else _nullctx():  # type: ignore
        token = None
        if ctx.installation_id and settings.using_github_app:
            token = await get_installation_token(ctx.installation_id)
        diff = await fetch_pr_diff(ctx, token) if (token or settings.github_token) else (
            ctx.diff or _demo_diff()
        )
        patterns = await load_patterns(ctx.repo_full_name)
        hints = [p.description for p in patterns]
        result = await run_review(diff, hints)
        await save_review(
            ReviewRecord(
                repo_full_name=ctx.repo_full_name,
                pr_number=ctx.pr_number,
                head_sha=ctx.head_sha,
                status="completed",
                summary=result.summary,
                comments=result.comments,
                created_at=result.generated_at,
            )
        )
        # Hand off to the Reviewer service (best-effort).
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{settings.reviewer_url}/post",
                    json={
                        "repo_full_name": ctx.repo_full_name,
                        "pr_number": ctx.pr_number,
                        "installation_id": ctx.installation_id,
                        "result": result.model_dump(mode="json"),
                    },
                    timeout=20,
                )
        except Exception:
            pass
        if REVIEW_RUNS is not None:
            REVIEW_RUNS.labels(status="completed").inc()
        return result


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _demo_diff() -> str:
    return "diff --git a/main.py b/main.py\n@@\n+password = 'hunter2'\n+global state\n"


@app.post("/review")
async def review(payload: dict):
    ctx = parse_webhook(payload)
    if ctx is None:
        raise HTTPException(status_code=400, detail="not_a_pr_event")
    result = await _execute(ctx)
    return result.model_dump(mode="json")
