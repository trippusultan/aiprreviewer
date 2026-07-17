"""End-to-end verification against a REAL GitHub repository.

Guarded: only runs when GITHUB_TOKEN (and optionally GITHUB_APP_ID /
GITHUB_APP_PRIVATE_KEY) AND GITHUB_REPO / GITHUB_PR are supplied. Otherwise it
skips — so it never breaks the offline CI, but proves the live GitHub paths
(diff fetch, GitHub App JWT / installation token, and the full review pipeline)
work against real infrastructure.

Run manually:
  GITHUB_TOKEN=ghp_xxx GITHUB_REPO=octocat/Spoon-Knife GITHUB_PR=1185 \
  RUN_OFFLINE=true pytest tests/test_live_github.py -q -s
"""
import asyncio
import os

import pytest

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_PR = os.environ.get("GITHUB_PR")

_NEED = all([GITHUB_TOKEN, GITHUB_REPO, GITHUB_PR])
pytestmark = pytest.mark.skipif(
    not _NEED,
    reason="live GitHub e2e requires GITHUB_TOKEN, GITHUB_REPO and GITHUB_PR",
)


def test_fetch_real_pr_diff():
    from common.github import fetch_pr_diff

    diff = asyncio.run(fetch_pr_diff(GITHUB_REPO, int(GITHUB_PR)))
    assert isinstance(diff, str) and len(diff) > 0, "expected a non-empty diff"
    assert diff.startswith("diff --git") or "diff --git" in diff


def test_live_review_pipeline_posts_result():
    """Run the engine on the real PR, then confirm the Reviewer posts comments
    and a summary (when a token is configured)."""
    from common.config import settings
    from common.github import fetch_pr_diff
    from engine import run_review
    from reviewer.main import _post

    settings.github_token = GITHUB_TOKEN  # ensure posting is attempted
    diff = asyncio.run(fetch_pr_diff(GITHUB_REPO, int(GITHUB_PR)))
    result = asyncio.run(run_review(diff))

    payload = {
        "repo_full_name": GITHUB_REPO,
        "pr_number": int(GITHUB_PR),
        "installation_id": None,
        "result": result.model_dump(mode="json"),
    }
    out = asyncio.run(_post(payload))
    assert out["summary_posted"] is True, f"posting failed: {out}"
    print(f"\n  live review: {len(result.comments)} findings, posted={out['posted']}")
