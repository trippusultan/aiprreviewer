"""End-to-end integration test over real ASGI transport.

Drives a PR webhook through the pipeline and asserts every stage works:
  - Webhook accepts + enqueues an opened PR
  - Orchestrator runs the 4-agent LangGraph review end-to-end
  - Reviewer accepts the merged result
  - /metrics is exposed (Prometheus)
  - A merged (closed) PR triggers the Learner feedback loop
"""
import hmac
import hashlib

from starlette.testclient import TestClient

import common.config as config
from common.db import connect, dispose
import webhook.main as webhook_app
import orchestrator.main as orchestrator_app
import reviewer.main as reviewer_app
import learner.main as learner_app

OPENED = {
    "action": "opened",
    "pull_request": {
        "number": 11,
        "head": {"sha": "shaHEAD"},
        "base": {"sha": "shaBASE"},
        "title": "add auth",
        "body": "",
        "files": [{"filename": "a.py"}],
    },
    "repository": {"full_name": "acme/flow"},
    "installation": {"id": 1},
}

MERGED = {
    "action": "closed",
    "pull_request": {
        "number": 5,
        "merged": True,
        "head": {"sha": "m1"},
        "base": {"sha": "m0"},
        "title": "x",
        "body": "",
        "files": [],
    },
    "repository": {"full_name": "acme/flow"},
    "installation": {"id": 1},
}


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        config.settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()


async def test_full_review_pipeline():
    await connect()
    wh = TestClient(webhook_app.app)
    orch = TestClient(orchestrator_app.app)
    rev = TestClient(reviewer_app.app)

    # 1) Webhook accepts an opened PR and enqueues.
    r1 = wh.post("/webhook", json=OPENED)
    assert r1.status_code == 200, r1.text
    assert r1.json()["accepted"] is True

    # 2) Orchestrator runs the 4-agent merged review (offline StubLLM).
    r2 = orch.post("/review", json=OPENED)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    cats = {c["category"] for c in data["comments"]}
    assert {"static", "security", "architecture", "style"} <= cats
    assert data["summary"]

    # 3) Reviewer returns a well-formed posting result. Without a GitHub
    #    token configured it cannot actually post, so assert the contract
    #    (posted/summary_posted/errors) rather than a forced success.
    r3 = rev.post(
        "/post",
        json={
            "repo_full_name": "acme/flow",
            "pr_number": 11,
            "installation_id": None,
            "result": data,
        },
    )
    assert r3.status_code == 200
    body3 = r3.json()
    assert "posted" in body3 and "summary_posted" in body3 and "errors" in body3

    # 4) Prometheus /metrics is exposed with our custom counter.
    m = orch.get("/metrics")
    assert m.status_code == 200
    assert "aipr_review_runs_total" in m.text

    await dispose()


async def test_feedback_loop_on_merged_pr():
    await connect()
    wh = TestClient(webhook_app.app)
    lr = TestClient(learner_app.app)

    # Closed + merged -> webhook routes to the Learner feedback path.
    r = wh.post("/webhook", json=MERGED)
    assert r.status_code == 200
    assert r.json()["reason"] == "merged_learn_queued"

    # Learner extracts + stores patterns from a diff.
    lr.post(
        "/learn",
        json={"repo_full_name": "acme/flow", "diff": "except:\n    pass\n# TODO\n"},
    )
    pats = lr.get("/patterns/acme/flow").json()
    assert any(p["description"] for p in pats)
    await dispose()
