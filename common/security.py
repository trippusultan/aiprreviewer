"""HMAC-SHA256 signature verification for GitHub webhooks."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, Request, status

from common.config import settings


def verify_github_signature(payload: bytes, signature_header: str | None) -> bool:
    """Return True when ``signature_header`` is a valid SHA256 HMAC of ``payload``."""
    secret = settings.github_webhook_secret.encode()
    if not signature_header:
        return False
    parts = signature_header.split("=", 1)
    if len(parts) != 2 or parts[0] not in ("sha256", "sha1"):
        return False
    algo = hashlib.sha256 if parts[0] == "sha256" else hashlib.sha1
    expected = hmac.new(secret, payload, algo).hexdigest()
    return hmac.compare_digest(parts[1], expected)


async def require_github_signature(request: Request) -> bytes:
    """FastAPI dependency: read body, verify HMAC, return raw bytes or 401."""
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256") or request.headers.get(
        "X-Hub-Signature"
    )
    # In offline/dev mode with no secret divergence we still require *a* header
    # when a real secret is configured.
    if settings.github_webhook_secret and settings.github_webhook_secret != "dev-secret":
        if not verify_github_signature(body, sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )
    return body
