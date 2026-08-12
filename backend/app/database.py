"""Async SQLAlchemy engine, session factory and declarative base.

The layer is portable across PostgreSQL (asyncpg) and SQLite (aiosqlite) so the
demo runs with zero external services locally, while production uses Postgres.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for all ORM models."""


def _build_engine():
    kwargs: dict = {"echo": False}
    if not settings.is_sqlite:
        # Connection health checks only make sense for a real network DB.
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return create_async_engine(settings.database_url, **kwargs)


engine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncSession:  # FastAPI dependency
    async with AsyncSessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create all tables if they do not yet exist (idempotent).

    For Postgres production deployments prefer Alembic migrations; this helper
    guarantees the schema exists for the demo regardless of the backend.
    """
    # Import models so they are registered on the metadata before create_all.
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
