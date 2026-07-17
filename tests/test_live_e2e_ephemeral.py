"""Live end-to-end against an EPHEMERAL throwaway GitHub repo.

Unlike test_live_github.py (which points at an EXISTING repo you supply), this
test CREATES its own temporary public repo, opens a PR seeded with intentional
code issues, runs the real review pipeline + Reviewer, asserts that findings
were actually posted to the PR, then DELETES the repo.

It is fully self-contained and idempotent: if it crashes mid-way it still tries
to delete the repo in a finally-block, so no test junk is left behind.

Controlled by env (so it stays skipped in normal CI / offline runs):
  LIVE_E2E_TOKEN        a GitHub PAT with repo scope (REQUIRED)
  LIVE_E2E_LLM_KEY      a real LLM API key (optional; if absent, uses StubLLM
                        so the pipeline still runs but findings are synthetic)
  LIVE_E2E_LLM_BASE     OpenAI-compatible base URL (default OpenAI)
  LIVE_E2E_LLM_MODEL    model id (default gpt-4o-mini)
  LIVE_E2E_REPO_PREFIX  repo name prefix (default "aipr-e2e")

Run manually:
  LIVE_E2E_TOKEN=ghp_xxx LIVE_E2E_LLM_KEY=sk-xxx \
  RUN_OFFLINE=true pytest tests/test_live_e2e_ephemeral.py -q -s
"""
import asyncio
import base64
import os
import random
import string
import time

import pytest
import httpx

TOKEN = os.environ.get("LIVE_E2E_TOKEN")
LLM_KEY = os.environ.get("LIVE_E2E_LLM_KEY")
LLM_BASE = os.environ.get("LIVE_E2E_LLM_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LIVE_E2E_LLM_MODEL", "gpt-4o-mini")
PREFIX = os.environ.get("LIVE_E2E_REPO_PREFIX", "aipr-e2e")

pytestmark = pytest.mark.skipif(
    not TOKEN,
    reason="live ephemeral e2e requires LIVE_E2E_TOKEN (a GitHub PAT with repo scope)",
)


# A tiny repo whose only file has deliberate smells the agents should catch.
SEED_FILE = "sample.py"
SEED_CONTENT = (
    "import os\n"
    "SECRET = 'super-secret-key'\n"  # hard-coded credential (security)
    "\n"
    "def add(a,b):\n"
    "    return a+b\n"
    "\n"
    "def process(req):\n"
    "    try:\n"
    "        return do_work(req)\n"
    "    except:\n"  # bare except (style/robustness)
    "        pass\n"
    "    global counter\n"  # global mutation (architecture)
)


def _api():
    return httpx.Client(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )


def _uniq_repo(owner: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{PREFIX}-{suffix}"


def test_ephemeral_repo_full_review_pipeline():
    from common.config import settings
    from common.github import fetch_pr_diff
    from engine import run_review
    from reviewer.main import _post

    api = _api()
    owner = api.get("/user").json()["login"]
    repo = _uniq_repo(owner)
    full = f"{owner}/{repo}"

    try:
        # 1) Create the throwaway repo.
        r = api.post("/user/repos", json={"name": repo, "private": False, "auto_init": True})
        r.raise_for_status()

        # 2) Push the seed file on a branch + open a PR.
        branch = "feature/seed"
        base_sha = api.get(f"/repos/{full}/git/ref/heads/main").json()["object"]["sha"]
        api.post(
            f"/repos/{full}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        ).raise_for_status()
        # Create/overwrite the file on the branch.
        api.put(
            f"/repos/{full}/contents/{SEED_FILE}",
            json={"message": "add sample", "content": base64.b64encode(SEED_CONTENT.encode()).decode(), "branch": branch},
        ).raise_for_status()
        pr = api.post(
            f"/repos/{full}/pulls",
            json={"title": "Add sample module", "head": branch, "base": "main", "body": "e2e"},
        )
        pr.raise_for_status()
        pr_number = pr.json()["number"]

        # 3) Let GitHub index the diff, then fetch it via our real code path.
        time.sleep(2)
        from common.models import PRContext

        ctx = PRContext(
            repo_full_name=full,
            pr_number=pr_number,
            head_sha="e2e-head",
            base_sha=base_sha,
        )
        diff = asyncio.run(fetch_pr_diff(ctx))
        assert "diff --git" in diff, "diff fetch returned no diff"

        # 4) Run the engine (real LLM if LIVE_E2E_LLM_KEY set, else StubLLM).
        settings.github_token = TOKEN
        if LLM_KEY:
            settings.llm_api_key = LLM_KEY
            settings.llm_base_url = LLM_BASE
            settings.llm_model = LLM_MODEL
            settings.llm_provider = "openai-compatible"
            os.environ["RUN_OFFLINE"] = "false"
        result = asyncio.run(run_review(diff))
        assert result.comments, "engine produced no findings on seeded PR"

        # 5) Post via the Reviewer (real GitHub post comments + summary).
        out = asyncio.run(
            _post(
                {
                    "repo_full_name": full,
                    "pr_number": pr_number,
                    "installation_id": None,
                    "result": result.model_dump(mode="json"),
                }
            )
        )
        assert out["summary_posted"] is True, f"posting failed: {out}"

        # 6) Confirm the PR actually received review comments/threads.
        comments = api.get(f"/repos/{full}/pulls/{pr_number}/comments").json()
        reviews = api.get(f"/repos/{full}/pulls/{pr_number}/reviews").json()
        total = len(comments) + len(reviews)
        assert total >= 1, "no review artifacts appeared on the PR"
        print(f"\n  e2e: {len(result.comments)} findings -> {total} posted to PR {full}#{pr_number}")
    finally:
        # 7) Tear down the throwaway repo no matter what.
        try:
            api.delete(f"/repos/{full}").raise_for_status()
        finally:
            api.close()
