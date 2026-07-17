"""LLM abstraction: real OpenAI client or a deterministic stub for offline runs.

The StubLLM lets the entire review pipeline execute end-to-end without any
network/API key — essential for local verification (pytest).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from common.config import settings
from common.models import ReviewCategory


class BaseLLM(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str) -> str:
        ...


class OpenAILLM(BaseLLM):
    def __init__(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
        self._model = settings.openai_model

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""


class StubLLM(BaseLLM):
    """Deterministic, offline-safe LLM. Produces a valid structured review.

    It inspects the user prompt for obvious patterns so the output is at least
    plausibly tied to the input (e.g. flags a clear ``password =`` assignment as
    a security issue). This makes the offline pipeline behave believably in demos
    and tests without a network call.
    """

    async def complete(self, system: str, user: str) -> str:
        agent = _detect_agent(system)
        comments = _generate(agent, user)
        payload = {
            "comments": [c.model_dump(mode="json") for c in comments],
            "summary": _summary(agent, comments),
        }
        return json.dumps(payload)


def _detect_agent(system: str) -> ReviewCategory:
    s = system.lower()
    if "security" in s:
        return ReviewCategory.SECURITY
    if "architecture" in s:
        return ReviewCategory.ARCHITECTURE
    if "style" in s:
        return ReviewCategory.STYLE
    return ReviewCategory.STATIC


def _generate(agent: ReviewCategory, user: str):
    from common.models import ReviewComment, Severity

    sample = _first_file(user)
    out = []
    if agent == ReviewCategory.SECURITY and "password" in user.lower():
        out.append(
            ReviewComment(
                category=agent,
                severity=Severity.HIGH,
                file_path=sample,
                line=1,
                body="Avoid hard-coding credentials. Use a secrets manager or environment variable.",
                suggestion="SECRET = os.environ['API_SECRET']",
            )
        )
    if agent == ReviewCategory.STYLE and "    " in user:
        out.append(
            ReviewComment(
                category=agent,
                severity=Severity.LOW,
                file_path=sample,
                line=1,
                body="Inconsistent indentation detected. Use 4 spaces consistently.",
            )
        )
    if agent == ReviewCategory.STATIC and "except:" in user:
        out.append(
            ReviewComment(
                category=agent,
                severity=Severity.MEDIUM,
                file_path=sample,
                line=1,
                body="Bare `except:` swallows all exceptions. Catch specific exceptions.",
            )
        )
    if agent == ReviewCategory.ARCHITECTURE and "global " in user.lower():
        out.append(
            ReviewComment(
                category=agent,
                severity=Severity.MEDIUM,
                file_path=sample,
                line=1,
                body="Module-level global state reduces testability. Consider dependency injection.",
            )
        )
    if not out:
        out.append(
            ReviewComment(
                category=agent,
                severity=Severity.INFO,
                file_path=sample,
                body=f"{agent.value.title()} review found no blocking issues in the provided diff.",
            )
        )
    return out


def _first_file(user: str) -> str | None:
    for line in user.splitlines():
        if line.strip().startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 2:
                return parts[2].lstrip("a/").lstrip("b/")
    return None


def _summary(agent: ReviewCategory, comments) -> str:
    n = len(comments)
    if n == 0:
        return f"{agent.value.title()} agent: no findings."
    return f"{agent.value.title()} agent raised {n} observation(s)."


def get_llm() -> BaseLLM:
    if settings.run_offline or not settings.openai_api_key.startswith("sk-"):
        return StubLLM()
    return OpenAILLM()
