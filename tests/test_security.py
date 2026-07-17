"""HMAC verification + webhook parsing tests."""
import hmac
import hashlib

from common.security import verify_github_signature
from common.github import parse_webhook


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_valid():
    body = b'{"action":"opened"}'
    assert verify_github_signature(body, _sign(body, "test-secret"))


def test_signature_invalid():
    body = b'{"action":"opened"}'
    bad = _sign(b"tampered", "test-secret")
    assert not verify_github_signature(body, bad)
    assert not verify_github_signature(body, None)


def test_parse_webhook_pr():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
            "title": "Add feature",
            "body": "desc",
            "files": [{"filename": "a.py"}, {"filename": "b.py"}],
        },
        "repository": {"full_name": "owner/repo"},
        "installation": {"id": 99},
    }
    ctx = parse_webhook(payload)
    assert ctx is not None
    assert ctx.pr_number == 42
    assert ctx.head_sha == "abc123"
    assert ctx.repo_full_name == "owner/repo"
    assert ctx.installation_id == "99"
    assert set(ctx.changed_files) == {"a.py", "b.py"}


def test_parse_webhook_non_pr_returns_none():
    assert parse_webhook({"action": "push"}) is None
