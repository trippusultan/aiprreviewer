"""GATEWAY SERVICE (FastAPI) — entry point behind the ALB/ingress.

Verifies the GitHub HMAC signature, rejects fakes, and forwards only verified
events to the Webhook service. Mirrors the diagram's Gateway box.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response

from common.config import settings
from common.observability import PR_EVENTS
from common.security import require_github_signature
from common.server import add_landing
from common.observability import instrument

app = FastAPI(title="AI PR Reviewer — Gateway", version="1.0.0")
add_landing(app, "Gateway", "Entry point behind the ALB. Verifies the GitHub HMAC signature and forwards only verified webhook events to the Webhook service.")
instrument(app)

_WEBHOOK = f"{settings.webhook_url}/webhook"


@app.get("/health")
async def health():
    return {"service": "gateway", "status": "ok"}


@app.post("/webhook")
async def inbound(request: Request):
    body = await require_github_signature(request)  # 401 if signature invalid
    event = request.headers.get("X-GitHub-Event", "unknown")
    action = request.headers.get("X-GitHub-Event-Action", "unknown")
    if PR_EVENTS is not None:
        PR_EVENTS.labels(action=action, service="gateway").inc()
    # Forward verified payload downstream (verified only).
    async with httpx.AsyncClient() as client:
        fwd = await client.post(
            _WEBHOOK,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": event,
                "X-GitHub-Event-Action": action,
            },
            timeout=10,
        )
    return Response(content=fwd.content, status_code=fwd.status_code, media_type="application/json")
