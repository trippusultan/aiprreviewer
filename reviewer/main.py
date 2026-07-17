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

    # Split findings into line-anchored (postable as inline comments) and
    # line-less (fold into the summary review, since /comments needs a line).
    inline, line_less = [], []
    for c in result.comments:
        (inline if (c.file_path and c.line) else line_less).append(c)

    posted = 0
    errors = []
    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(base_url=settings.github_api_url, headers=headers) as client:
            # 1) Inline comments — one POST per comment (the GitHub endpoint
            #    /pulls/{n}/comments accepts a SINGLE comment, not a batch).
            for c in inline:
                body = f"**[{c.category.value}/{c.severity.value}]** {c.body}"
                if c.suggestion:
                    body += f"\n\n```suggestion\n{c.suggestion}\n```"
                try:
                    r = await client.post(
                        f"/repos/{repo}/pulls/{pr}/comments",
                        json={"path": c.file_path, "line": c.line, "side": "RIGHT", "body": body},
                    )
                    r.raise_for_status()
                    posted += 1
                except Exception as e:  # best-effort: record, don't abort the run
                    errors.append(str(e))

            # 2) Summary review (optionally carrying line-less findings).
            summary = result.summary
            if line_less:
                extra = "\n\nAdditional notes:\n" + "\n".join(
                    f"- [{c.category.value}/{c.severity.value}] {c.body}" for c in line_less
                )
                summary += extra
            try:
                r = await client.post(
                    f"/repos/{repo}/pulls/{pr}/reviews",
                    json={"event": "COMMENT", "body": summary},
                )
                r.raise_for_status()
                summary_posted = True
            except Exception as e:
                errors.append(str(e))
                summary_posted = False
    else:
        # No token -> cannot post; surface that honestly rather than 200 OK.
        summary_posted = False
        errors.append("no_github_token")

    return {
        "posted": posted,
        "summary_posted": summary_posted,
        "errors": errors,
    }


@app.post("/post")
async def post(payload: dict):
    return await _post(payload)
