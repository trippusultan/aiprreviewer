"""FastAPI app import + health checks for all five services."""
from fastapi.testclient import TestClient

import gateway.main as gateway_app
import webhook.main as webhook_app
import orchestrator.main as orchestrator_app
import reviewer.main as reviewer_app
import learner.main as learner_app


def test_gateway_imports_and_health():
    with TestClient(gateway_app.app) as c:
        assert c.get("/health").json()["service"] == "gateway"


def test_webhook_imports_and_health():
    with TestClient(webhook_app.app) as c:
        assert c.get("/health").json()["service"] == "webhook"


def test_orchestrator_imports_and_health():
    with TestClient(orchestrator_app.app) as c:
        assert c.get("/health").json()["service"] == "orchestrator"


def test_reviewer_imports_and_health():
    with TestClient(reviewer_app.app) as c:
        assert c.get("/health").json()["service"] == "reviewer"


def test_learner_imports_and_health():
    with TestClient(learner_app.app) as c:
        assert c.get("/health").json()["service"] == "learner"


async def test_reviewer_post_is_safe_without_token():
    # With no GitHub token configured, posting must not raise.
    payload = {
        "repo_full_name": "owner/repo",
        "pr_number": 1,
        "installation_id": None,
        "result": {
            "comments": [],
            "summary": "No issues found.",
            "generated_at": "2026-07-18T00:00:00+00:00",
        },
    }
    with TestClient(reviewer_app.app) as c:
        r = c.post("/post", json=payload)
        assert r.status_code == 200
