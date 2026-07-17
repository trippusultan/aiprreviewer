"""Verify the ephemeral e2e test's GITHUB ORCHESTRATION against a local mock
GitHub API (no real token / network needed). This proves the test's call
sequence, base64 file upload, PR-number extraction, review-post assertions
and repo teardown are all correct. The real LLM/network path is exercised only
in the dispatched CI job (which supplies a real token + key)."""
import asyncio
import base64
import os
import threading

import httpx
import pytest
from fastapi import FastAPI, Request
import uvicorn

import tests.test_live_e2e_ephemeral as e2e


# ---- local mock of the GitHub REST surface the test uses ----
app = FastAPI()
STATE = {"repos": {}, "seq": 0}


@app.get("/user")
def user():
    return {"login": "fakeuser"}


@app.post("/user/repos")
async def create_repo(req: Request):
    body = await req.json()
    name = body["name"]
    STATE["repos"][name] = {"files": {}, "refs": {}, "prs": [], "deleted": False}
    return {"name": name}


@app.get("/repos/{owner}/{repo}/git/ref/heads/{branch}")
def get_ref(owner, repo, branch):
    r = STATE["repos"][repo]
    if "main" not in r["refs"]:
        r["refs"]["main"] = "BASESHA"
    return {"object": {"sha": r["refs"]["main"]}}


@app.post("/repos/{owner}/{repo}/git/refs")
async def create_ref(owner, repo, req: Request):
    body = await req.json()
    STATE["repos"][repo]["refs"][body["ref"].split("/")[-1]] = body["sha"]
    return {"ref": body["ref"], "object": {"sha": body["sha"]}}


@app.put("/repos/{owner}/{repo}/contents/{path:path}")
async def put_content(owner, repo, path, req: Request):
    body = await req.json()
    STATE["repos"][repo]["files"][path] = base64.b64decode(body["content"]).decode()
    return {"content": {"path": path}}


@app.post("/repos/{owner}/{repo}/pulls")
async def create_pr(owner, repo, req: Request):
    body = await req.json()
    STATE["seq"] += 1
    pr = {"number": STATE["seq"], "title": body["title"], "head": body["head"], "base": body["base"]}
    STATE["repos"][repo]["prs"].append(pr)
    return pr


@app.get("/repos/{owner}/{repo}/pulls")
def list_prs(owner, repo):
    return STATE["repos"][repo]["prs"]


@app.get("/repos/{owner}/{repo}/pulls/{n}/comments")
def pr_comments(owner, repo, n):
    return STATE["repos"][repo].get("_comments", [])


@app.get("/repos/{owner}/{repo}/pulls/{n}/reviews")
def pr_reviews(owner, repo, n):
    return STATE["repos"][repo].get("_reviews", [])


@app.delete("/repos/{owner}/{repo}")
def delete_repo(owner, repo):
    STATE["repos"][repo]["deleted"] = True
    return {"deleted": True}


def _run_mock():
    uvicorn.run(app, host="127.0.0.1", port=8771, log_level="warning")


@pytest.fixture(scope="module")
def mock_github():
    t = threading.Thread(target=_run_mock, daemon=True)
    t.start()
    # patch the test's httpx client base_url to the mock
    orig = e2e._api
    e2e._api = lambda: httpx.Client(
        base_url="http://127.0.0.1:8771",
        headers={"Authorization": "Bearer fake", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    yield "http://127.0.0.1:8771"
    e2e._api = orig


def test_ephemeral_e2e_against_mock(mock_github, monkeypatch):
    # Force RUN_OFFLINE so the engine uses StubLLM (no real LLM needed) and the
    # test's fetch_pr_diff hits our mock via common.github (patch base url).
    monkeypatch.setenv("RUN_OFFLINE", "true")
    monkeypatch.setenv("LIVE_E2E_TOKEN", "fake")

    # Route common.github + reviewer httpx at the mock GitHub.
    import common.github as gh

    monkeypatch.setattr(gh.settings, "github_api_url", "http://127.0.0.1:8771")

    # Make fetch_pr_diff return a real diff-shaped string (it takes a PRContext).
    async def fake_diff(ctx, token=None):
        return (
            "diff --git a/sample.py b/sample.py\n"
            "@@ -0,0 +1,3 @@\n+SECRET = 'super-secret-key'\n"
            "+def process(req):\n+    try:\n+        pass\n+    except:\n+        pass\n"
        )

    monkeypatch.setattr(gh, "fetch_pr_diff", fake_diff)

    # Capture reviewer posts to validate assertions + populate mock state.
    import reviewer.main as rv

    posted = {}

    async def fake_post(payload):
        repo = payload["repo_full_name"]
        # mark that comments/reviews were "posted"
        r = STATE["repos"][repo.split("/")[-1]]
        r.setdefault("_comments", []).append({"id": 1})
        r.setdefault("_reviews", []).append({"id": 1, "body": payload["result"]["summary"]})
        return {"posted": 1, "summary_posted": True, "errors": []}

    monkeypatch.setattr(rv, "_post", fake_post)

    # Run the test function directly (it's normally skipped without token; we
    # set the token via monkeypatch so it executes).
    e2e.test_ephemeral_repo_full_review_pipeline()

    # Verify teardown happened.
    assert any(r.get("deleted") for r in STATE["repos"].values()), "ephemeral repo was NOT deleted"
    print("\n  mock e2e: orchestration + teardown verified; repo deleted =", any(r["deleted"] for r in STATE["repos"].values()))
