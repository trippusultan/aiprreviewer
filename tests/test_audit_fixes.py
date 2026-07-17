"""Tests for bugs found during the deep audit + their fixes.

Covers:
  * Reviewer posts inline comments individually to the correct GitHub endpoint
    (POST /pulls/{n}/comments takes ONE comment, not {comments:[...]}).
  * observability._NoOpLatency is a usable context manager when prometheus_client
    is missing (previously `with function:` crashed).
  * db.dispose() resets globals so a later connect() can rebuild the engine.
"""
import asyncio

import httpx
import pytest

import common.config as config
import common.observability as obs
from common.db import connect, dispose, load_patterns


def test_reviewer_posts_each_inline_comment_individually(monkeypatch):
    import reviewer.main as reviewer_app

    # Provide a token so the reviewer actually attempts to post (otherwise it
    # correctly skips with summary_posted=False).
    monkeypatch.setattr(config.settings, "github_token", "ghp_test_token")
    monkeypatch.setattr(config.settings, "github_app_id", "")

    calls = []

    class _Resp:
        def __init__(self, status_code=201):
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("x", request=None, response=self)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            return _Resp(201)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    payload = {
        "repo_full_name": "acme/flow",
        "pr_number": 7,
        "installation_id": None,
        "result": {
            "comments": [
                {
                    "category": "security",
                    "severity": "high",
                    "file_path": "a.py",
                    "line": 12,
                    "body": "hardcoded secret",
                    "suggestion": "use env var",
                },
                {
                    "category": "style",
                    "severity": "low",
                    "file_path": None,
                    "line": None,
                    "body": "line-less note",
                    "suggestion": None,
                },
            ],
            "summary": "looks ok",
            "generated_at": "2026-07-18T00:00:00+00:00",
        },
    }
    out = asyncio.run(reviewer_app._post(payload))
    # 1 inline (has path+line) + 1 review (summary, which also folds the
    # line-less note in). The buggy code would have sent {comments:[...]} to
    # /comments and gotten a 422.
    comment_calls = [c for c in calls if c[0].endswith("/comments")]
    review_calls = [c for c in calls if c[0].endswith("/reviews")]
    assert len(comment_calls) == 1, f"expected 1 inline comment POST, got {calls}"
    assert comment_calls[0][1] == {
        "path": "a.py",
        "line": 12,
        "side": "RIGHT",
        "body": "**[security/high]** hardcoded secret\n\n```suggestion\nuse env var\n```",
    }, "inline comment payload shape is wrong"
    assert len(review_calls) == 1, "expected exactly one summary review POST"
    assert out["posted"] == 1
    assert out["summary_posted"] is True


def test_observability_noop_latency_is_context_manager():
    # The no-op latency object must support `with .time():` even without
    # prometheus_client (previously it returned a bare function and crashed).
    noop = obs._NoOpLatency()
    with noop.time():
        pass
    # And the module-level REVIEW_LATENCY is never None (Histogram or no-op).
    assert obs.REVIEW_LATENCY is not None


def test_dispose_then_reconnect_rebuilds_engine():
    async def _run():
        await connect("sqlite+aiosqlite:///./aipr_audit.db")
        await dispose()  # must reset globals
        await connect("sqlite+aiosqlite:///./aipr_audit.db")
        rows = await load_patterns("acme/flow")
        assert rows == []
        await dispose()

    asyncio.run(_run())
