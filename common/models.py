"""Pydantic models shared across services."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewCategory(str, Enum):
    STATIC = "static"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    STYLE = "style"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PRContext(BaseModel):
    """Normalised pull-request payload passed through the pipeline."""

    repo_full_name: str
    pr_number: int
    head_sha: str
    base_sha: str
    action: str = "opened"
    title: str = ""
    description: str = ""
    changed_files: list[str] = Field(default_factory=list)
    diff: str = ""
    installation_id: Optional[str] = None


class ReviewComment(BaseModel):
    """A single inline review comment."""

    category: ReviewCategory
    severity: Severity
    file_path: Optional[str] = None
    line: Optional[int] = None
    body: str
    suggestion: Optional[str] = None


class AgentFinding(BaseModel):
    agent: ReviewCategory
    comments: list[ReviewComment] = Field(default_factory=list)
    summary: str = ""
    raw: Any = None


class ReviewResult(BaseModel):
    """Merged output of the multi-agent run."""

    comments: list[ReviewComment] = Field(default_factory=list)
    summary: str = ""
    generated_at: datetime = Field(default_factory=_now)


class ReviewRecord(BaseModel):
    """Persisted row for a completed review."""

    id: Optional[int] = None
    repo_full_name: str
    pr_number: int
    head_sha: str
    status: str = "completed"
    summary: str = ""
    comments: list[ReviewComment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


class LearnedPattern(BaseModel):
    id: Optional[int] = None
    repo_full_name: str
    pattern_type: str  # style | architecture | security | static
    fingerprint: str
    description: str
    occurrences: int = 1
    created_at: datetime = Field(default_factory=_now)
