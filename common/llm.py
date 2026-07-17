"""LLM abstraction: provider-agnostic client or a deterministic stub for offline runs.

Supported providers (set LLM_PROVIDER in .env):
  * "openai-compatible" (default) — OpenAI and ANY OpenAI-compatible endpoint:
    OpenRouter, Groq, DeepSeek, Together, Ollama, vLLM, Azure OpenAI, etc.
    Configure via LLM_BASE_URL + LLM_API_KEY + LLM_MODEL.
  * "anthropic" — Anthropic Claude (claude-3-5-sonnet, etc).
  * offline — no key/endpoint needed; the StubLLM produces a valid structured
    review so the whole pipeline runs without network access (pytest, demos).

The StubLLM lets the entire review pipeline execute end-to-end without any
network/API key — essential for local verification.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from common.config import settings
from common.models import ReviewCategory


class BaseLLM(ABC):
    @abstractmethod
    async def complete(self, system: str, user: str) -> str:
        ...


class OpenAICompatibleLLM(BaseLLM):
    """OpenAI and every OpenAI-compatible API (OpenRouter, Groq, DeepSeek,
    Together, Ollama, vLLM, Azure). Just point LLM_BASE_URL at it."""

    def __init__(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key or "not-needed",
            base_url=settings.llm_base_url or None,
        )
        self._model = settings.llm_model

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


class AnthropicLLM(BaseLLM):
    """Native Anthropic Claude client (no OpenAI shim required)."""

    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.llm_api_key)
        self._model = settings.llm_model or "claude-3-5-sonnet-latest"

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        return _extract_json(text)


def _extract_json(text: str) -> str:
    """Pull the first {...} JSON object out of a model response."""
    try:
        return json.dumps(json.loads(text))
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else "{}"


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
    """Select an LLM by LLM_PROVIDER. Falls back to StubLLM when offline,
    unconfigured, or when the provider's optional SDK is not installed — so the
    pipeline never hard-fails on a missing dependency."""
    if settings.run_offline:
        return StubLLM()
    provider = (settings.llm_provider or "openai-compatible").lower()
    if provider == "anthropic":
        if not settings.llm_api_key or settings.llm_api_key.startswith("sk-offline"):
            return StubLLM()
        try:
            return AnthropicLLM()
        except ModuleNotFoundError:
            return StubLLM()
    # openai-compatible (default): valid if a key OR a custom base URL is set.
    if settings.llm_api_key and not settings.llm_api_key.startswith("sk-offline"):
        try:
            return OpenAICompatibleLLM()
        except ModuleNotFoundError:
            return StubLLM()
    if settings.llm_base_url and settings.llm_base_url != "https://api.openai.com/v1":
        try:
            return OpenAICompatibleLLM()  # e.g. Ollama / vLLM with no key
        except ModuleNotFoundError:
            return StubLLM()
    return StubLLM()
