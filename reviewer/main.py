"""REVIEWER SERVICE (FastAPI) — posts review output to the PR.

Authenticates with the GitHub App (JWT -> installation token), then posts inline
comments on PR lines and an overall summary review. Mirrors the diagram's
Reviewer box.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from common.config import settings
from common.github import get_installation_token
from common.models import ReviewComment, ReviewResult
from common.server import add_landing
from common.observability import instrument

app = FastAPI(title="AI PR Reviewer — Reviewer", version="1.0.0")
add_landing(app, "Reviewer", "Authenticates with the GitHub App (JWT → installation token) and posts inline comments and an overall summary review back onto the pull request.")
instrument(app)


@app.get("/health")
async def health():
    return {"service": "reviewer", "status": "ok"}


async def _token(installation_id: str | None) -> str | None:
    if installation_id and settings.using_github_app:
        return await get_installation_token(installation_id)
    return settings.github_token or None


async def _post(payload: dict) -> dict:
    result = ReviewResult(**payload["result"])
    repo = payload["repo_full_name"]
    pr = payload["pr_number"]
    token = await _token(payload.get("installation_id"))

    comments = []
    for c in result.comments:
        if c.file_path and c.line:
            comments.append(
                {
                    "path": c.file_path,
                    "line": c.line,
                    "body": f"**[{c.category.value}/{c.severity.value}]** {c.body}"
                    + (f"\n\n```suggestion\n{c.suggestion}\n```" if c.suggestion else ""),
                }
            )
    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(base_url=settings.github_api_url, headers=headers) as client:
            if comments:
                await client.post(
                    f"/repos/{repo}/pulls/{pr}/comments",
                    json={"comments": comments},
                )
            await client.post(
                f"/repos/{repo}/pulls/{pr}/reviews",
                json={"event": "COMMENT", "body": result.summary},
            )
    return {"posted": len(comments), "summary_posted": True}


@app.post("/post")
async def post(payload: dict):
    return await _post(payload)
