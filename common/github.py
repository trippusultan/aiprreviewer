"""GitHub API client: webhook parsing, diff fetch, and GitHub App auth.

Posting is delegated to the Reviewer service, but the diff-fetch + auth
primitives live here so the Orchestrator can reuse them.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
from typing import Optional

import httpx

from common.config import settings
from common.models import PRContext


def parse_webhook(payload: dict) -> Optional[PRContext]:
    """Convert a GitHub webhook payload into a normalised PRContext.

    Returns None for events that are not actionable PR events.
    """
    if "pull_request" not in payload:
        return None
    pr = payload["pull_request"]
    repo = payload.get("repository", {})
    action = payload.get("action", "opened")
    return PRContext(
        repo_full_name=repo.get("full_name", ""),
        pr_number=pr.get("number", 0),
        head_sha=pr.get("head", {}).get("sha", ""),
        base_sha=pr.get("base", {}).get("sha", ""),
        action=action,
        title=pr.get("title", ""),
        description=pr.get("body") or "",
        changed_files=[
            f.get("filename")
            for f in pr.get("files", [])
            if f.get("filename")
        ],
        installation_id=str(payload.get("installation", {}).get("id", "")) or None,
    )


def _load_private_key() -> str:
    if settings.github_app_private_key:
        return settings.github_app_private_key
    if settings.github_app_private_key_path:
        with open(settings.github_app_private_key_path, "r", encoding="utf-8") as fh:
            return fh.read()
    return ""


def generate_app_jwt() -> str:
    """Create a short-lived GitHub App JWT (RS256)."""
    import jwt  # PyJWT

    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    payload = {
        "iat": now - 60,
        "exp": now + 540,
        "iss": settings.github_app_id,
    }
    key = _load_private_key()
    if not key:
        raise RuntimeError("GitHub App private key not configured")
    return jwt.encode(payload, key, algorithm="RS256")


async def get_installation_token(installation_id: str) -> str:
    """Exchange an installation id for an access token via the App JWT."""
    jwt_token = generate_app_jwt()
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(base_url=settings.github_api_url, headers=headers) as client:
        resp = await client.post(
            f"/app/installations/{installation_id}/access_tokens"
        )
        resp.raise_for_status()
        return resp.json()["token"]


async def fetch_pr_diff(ctx: PRContext, token: Optional[str] = None) -> str:
    """Fetch the raw unified diff for a PR via the GitHub API."""
    token = token or settings.github_token
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"Bearer {token}" if token else "",
    }
    headers = {k: v for k, v in headers.items() if v}
    url = f"/repos/{ctx.repo_full_name}/pulls/{ctx.pr_number}"
    async with httpx.AsyncClient(base_url=settings.github_api_url, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
