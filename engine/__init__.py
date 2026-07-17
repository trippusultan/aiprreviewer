"""LangGraph multi-agent review engine.

Builds a graph with four parallel reviewer agents (Static, Security, Architecture,
Style), merges their findings, de-duplicates, and returns a structured
ReviewResult. Designed to run offline with the StubLLM or online with OpenAI.
"""
from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from common.config import settings
from common.llm import get_llm
from common.models import (
    AgentFinding,
    ReviewCategory,
    ReviewComment,
    ReviewResult,
    Severity,
)
from common.observability import AGENT_CALLS, trace
from engine.prompts import (
    ARCHITECTURE_PROMPT,
    MERGE_PROMPT,
    SECURITY_PROMPT,
    STATIC_PROMPT,
    STYLE_PROMPT,
)

_AGENTS = {
    ReviewCategory.STATIC: STATIC_PROMPT,
    ReviewCategory.SECURITY: SECURITY_PROMPT,
    ReviewCategory.ARCHITECTURE: ARCHITECTURE_PROMPT,
    ReviewCategory.STYLE: STYLE_PROMPT,
}


class ReviewState(TypedDict, total=False):
    diff: str
    patterns: list  # learned style/architecture hints (strings)
    # Four agents write to `findings` in parallel; the reducer accumulates them.
    findings: Annotated[list[AgentFinding], operator.add]
    result: ReviewResult


def _parse_comments(raw: str):
    try:
        data = json.loads(raw)
    except Exception:
        return [], ""
    comments = []
    for c in data.get("comments", []):
        try:
            comments.append(ReviewComment(**c))
        except Exception:
            continue
    return comments, data.get("summary", "")


async def _run_agent(state: ReviewState, category: ReviewCategory) -> AgentFinding:
    llm = get_llm()
    prompt = _AGENTS[category]
    extra = ""
    if state.get("patterns"):
        extra = "\nRepo-specific learned guidance:\n" + "\n".join(
            f"- {p}" for p in state["patterns"][:10]
        )
    user = f"{state['diff']}\n{extra}"
    raw = await llm.complete(prompt, user)
    if AGENT_CALLS is not None:
        AGENT_CALLS.labels(agent=category.value).inc()
    comments, summary = _parse_comments(raw)
    return AgentFinding(agent=category, comments=comments, summary=summary, raw=raw)


# LangGraph node wrappers (sync signature, async body via asyncio.run guard)
async def static_node(state: ReviewState) -> ReviewState:
    f = await _run_agent(state, ReviewCategory.STATIC)
    return {"findings": [f]}


async def security_node(state: ReviewState) -> ReviewState:
    f = await _run_agent(state, ReviewCategory.SECURITY)
    return {"findings": [f]}


async def architecture_node(state: ReviewState) -> ReviewState:
    f = await _run_agent(state, ReviewCategory.ARCHITECTURE)
    return {"findings": [f]}


async def style_node(state: ReviewState) -> ReviewState:
    f = await _run_agent(state, ReviewCategory.STYLE)
    return {"findings": [f]}


async def merge_node(state: ReviewState) -> ReviewState:
    findings = state.get("findings", [])
    all_comments: list[ReviewComment] = []
    summaries = []
    for f in findings:
        all_comments.extend(f.comments)
        if f.summary:
            summaries.append(f.summary)
    merged = _dedupe(all_comments)
    llm = get_llm()
    payload = json.dumps(
        [
            {"agent": f.agent.value, "comments": [c.model_dump() for c in f.comments]}
            for f in findings
        ]
    )
    raw = await llm.complete(
        MERGE_PROMPT, f"Findings:\n{payload}"
    )
    summary_text = _overall_summary(summaries, merged)
    try:
        m = json.loads(raw)
        if isinstance(m, dict) and m.get("summary"):
            summary_text = m["summary"]
    except Exception:
        pass
    return {"result": ReviewResult(comments=merged, summary=summary_text)}


def _dedupe(comments: list[ReviewComment]) -> list[ReviewComment]:
    seen = set()
    out = []
    for c in comments:
        key = (c.file_path, c.line, c.body.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    # Cap to configured maximum to keep PR comments readable.
    return out[: settings.reviewer_max_comments]


def _overall_summary(summaries: list[str], comments: list[ReviewComment]) -> str:
    by_sev = {}
    for c in comments:
        by_sev[c.severity.value] = by_sev.get(c.severity.value, 0) + 1
    sev_line = ", ".join(f"{k}: {v}" for k, v in sorted(by_sev.items())) or "no issues"
    return "Multi-agent review complete — " + sev_line + "."


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("static", static_node)
    g.add_node("security", security_node)
    g.add_node("architecture", architecture_node)
    g.add_node("style", style_node)
    g.add_node("merge", merge_node)
    g.add_edge(START, "static")
    g.add_edge(START, "security")
    g.add_edge(START, "architecture")
    g.add_edge(START, "style")
    g.add_edge("static", "merge")
    g.add_edge("security", "merge")
    g.add_edge("architecture", "merge")
    g.add_edge("style", "merge")
    g.add_edge("merge", END)
    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def run_review(diff: str, patterns: list | None = None) -> ReviewResult:
    """Public entry point used by the Orchestrator."""
    trace("review_run", diff_len=len(diff))
    graph = get_graph()
    result = await graph.ainvoke(
        {"diff": diff, "patterns": patterns or [], "findings": [], "result": None}
    )
    return result["result"]
