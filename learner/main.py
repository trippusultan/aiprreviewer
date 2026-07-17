"""LEARNER SERVICE (FastAPI) — continuously improves reviews from merged PRs.

When a PR is merged, the Webhook/Orchestrator notifies this service. It extracts
frequent issues (style/architecture) and stores repo-specific patterns that the
Orchestrator loads before each future review — closing the self-improving loop
from the diagram's Learner pipeline.
"""
from __future__ import annotations

import re
from collections import Counter

from fastapi import FastAPI

from common.config import settings
from common.db import connect, load_patterns, upsert_pattern
from common.models import LearnedPattern

app = FastAPI(title="AI PR Reviewer — Learner", version="1.0.0")


@app.on_event("startup")
async def _startup():
    await connect()


@app.get("/health")
async def health():
    return {"service": "learner", "status": "ok"}


# Heuristic extractors: pattern_type -> (regex, description template)
_EXTRACTORS = {
    "style": [
        (re.compile(r"^\s*except\s*:"), "Bare except clause"),
        (re.compile(r"print\("), "Use of print() for logging"),
        (re.compile(r"#\s*todo", re.I), "TODO comment left in code"),
    ],
    "architecture": [
        (re.compile(r"^global\s+\w+", re.M), "Module-level global state"),
        (re.compile(r"import\s+os,", re.I), "Multiple imports on one line"),
    ],
}


@app.post("/learn")
async def learn(payload: dict):
    repo = payload.get("repo_full_name", "")
    diff: str = payload.get("diff", "")
    if not repo:
        return {"stored": 0}

    stored = 0
    for ptype, extractors in _EXTRACTORS.items():
        seen = Counter()
        for line in diff.splitlines():
            for rx, desc in extractors:
                if rx.search(line):
                    seen[desc] += 1
        for desc, count in seen.items():
            fp = f"{ptype}:{desc}"
            pat = LearnedPattern(
                repo_full_name=repo,
                pattern_type=ptype,
                fingerprint=fp,
                description=desc,
                occurrences=count,
            )
            await upsert_pattern(pat)
            stored += 1
    return {"stored": stored}


@app.get("/patterns/{repo}")
async def patterns(repo: str):
    rows = await load_patterns(repo)
    return [r.model_dump(mode="json") for r in rows]
