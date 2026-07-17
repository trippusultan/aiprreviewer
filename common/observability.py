"""Lightweight observability: Prometheus metrics + optional Langfuse tracing."""
from __future__ import annotations

from common.config import settings

try:
    from prometheus_client import Counter, Histogram

    PR_EVENTS = Counter(
        "aipr_pr_events_total", "GitHub PR events received", ["action", "service"]
    )
    REVIEW_RUNS = Counter("aipr_review_runs_total", "Review runs executed", ["status"])
    AGENT_CALLS = Counter("aipr_agent_calls_total", "Agent LLM calls", ["agent"])
    REVIEW_LATENCY = Histogram(
        "aipr_review_latency_seconds", "End-to-end review latency"
    )
    _PROM_AVAILABLE = True
except Exception:  # pragma: no cover
    _PROM_AVAILABLE = False

    def _noop(*_a, **_k):
        return None

    PR_EVENTS = REVIEW_RUNS = AGENT_CALLS = None
    REVIEW_LATENCY = type("X", (), {"time": lambda self: (lambda *_a, **_k: None)})()


def instrument(app) -> None:
    """Expose Prometheus /metrics on a FastAPI app (idempotent)."""
    if not _PROM_AVAILABLE:
        return
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    except Exception:
        pass


def trace(name: str, **metadata):
    """Emit a Langfuse trace span if configured, otherwise no-op."""
    if not (
        settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        return None
    try:  # pragma: no cover - network dep
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return client.trace(name=name, metadata=metadata)
    except Exception:
        return None
