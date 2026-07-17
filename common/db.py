"""Async persistence layer (SQLAlchemy 2.0). Works with sqlite+aiosqlite offline
or postgresql+asyncpg in production. Tables are created on first ``connect``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
import datetime as dt

from sqlalchemy import (
    ForeignKey,
    String,
    Integer,
    DateTime,
    Text,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.config import settings
from common.models import (
    AgentFinding,
    LearnedPattern,
    ReviewCategory,
    ReviewComment,
    ReviewRecord,
    ReviewResult,
)


class Base(DeclarativeBase):
    pass


class ReviewRow(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    pr_number: Mapped[int] = mapped_column(Integer, index=True)
    head_sha: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    summary: Mapped[str] = mapped_column(Text, default="")
    comments_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[dt] = mapped_column(DateTime)  # type: ignore


class PatternRow(Base):
    __tablename__ = "learned_patterns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    pattern_type: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt] = mapped_column(DateTime)  # type: ignore


def _engine_for(url: str) -> AsyncEngine:
    # In-memory sqlite needs a single shared connection (StaticPool), otherwise
    # each pooled connection gets its own empty DB and tables vanish.
    if url.startswith("sqlite") and ":memory:" in url:
        from sqlalchemy.pool import StaticPool

        return create_async_engine(
            url,
            echo=False,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_async_engine(url, echo=False, pool_pre_ping=True, connect_args=connect_args)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def connect(url: str | None = None) -> None:
    global _engine, _sessionmaker
    # Idempotent: if we already have a session factory, reuse it. Recreating
    # would swap the global engine to a fresh (empty) in-memory DB and wipe
    # tables mid-run (e.g. when a background task also calls connect()).
    if _sessionmaker is not None:
        return
    target = url or settings.database_url
    _engine = _engine_for(target)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    if _engine:
        await _engine.dispose()


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        await connect()
    async with _sessionmaker() as s:
        yield s


async def save_review(record: ReviewRecord) -> ReviewRecord:
    async with session() as s:
        row = ReviewRow(
            repo_full_name=record.repo_full_name,
            pr_number=record.pr_number,
            head_sha=record.head_sha,
            status=record.status,
            summary=record.summary,
            comments_json=ReviewResult(comments=record.comments).model_dump_json(),
            created_at=record.created_at,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        record.id = row.id
        return record


async def load_patterns(repo_full_name: str, pattern_type: str | None = None) -> list[LearnedPattern]:
    async with session() as s:
        stmt = select(PatternRow).where(PatternRow.repo_full_name == repo_full_name)
        if pattern_type:
            stmt = stmt.where(PatternRow.pattern_type == pattern_type)
        rows = (await s.execute(stmt)).scalars().all()
        return [
            LearnedPattern(
                id=r.id,
                repo_full_name=r.repo_full_name,
                pattern_type=r.pattern_type,
                fingerprint=r.fingerprint,
                description=r.description,
                occurrences=r.occurrences,
                created_at=r.created_at,
            )
            for r in rows
        ]


async def upsert_pattern(pattern: LearnedPattern) -> LearnedPattern:
    async with session() as s:
        existing = (
            await s.execute(
                select(PatternRow).where(
                    PatternRow.repo_full_name == pattern.repo_full_name,
                    PatternRow.fingerprint == pattern.fingerprint,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.occurrences += 1
            existing.description = pattern.description
            await s.commit()
            pattern.id = existing.id
            pattern.occurrences = existing.occurrences
        else:
            row = PatternRow(
                repo_full_name=pattern.repo_full_name,
                pattern_type=pattern.pattern_type,
                fingerprint=pattern.fingerprint,
                description=pattern.description,
                occurrences=1,
                created_at=pattern.created_at,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            pattern.id = row.id
        return pattern


def _to_comment(data: dict) -> ReviewComment:
    return ReviewComment(**data)
