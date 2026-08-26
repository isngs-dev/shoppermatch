"""Async SQLAlchemy engine, session factory and declarative base.

The layer is portable across PostgreSQL (asyncpg) and SQLite (aiosqlite) so the
demo runs with zero external services locally, while production uses Postgres.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
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
    return create_async_engine(settings.resolved_database_url, **kwargs)


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
        await _retrofit_columns(conn)


# --------------------------------------------------------------------------- #
# Retrofit columns onto tables that already existed before a model gained a
# new column. `create_all()` above only creates missing TABLES, never adds
# columns to ones that already exist — harmless for a brand-new database, but
# on any database that predates a given column (including the live deploy,
# which never runs Alembic — it just starts uvicorn directly) that column
# would otherwise silently never exist, and every read/write through the ORM
# for it would fail. Declare a new nullable column here once and it retrofits
# itself on the next restart, on any database, no separate migration needed.
# --------------------------------------------------------------------------- #
_RETROFIT_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, DDL type fragment — must be valid on both SQLite and
    # Postgres, e.g. "INTEGER", "INTEGER DEFAULT 1", "VARCHAR(255)")
    ("email_automations", "batch_size", "INTEGER"),
    ("email_automations", "total_iterations", "INTEGER DEFAULT 1"),
]


async def _retrofit_columns(conn) -> None:
    def _find_missing(sync_conn) -> list[tuple[str, str, str]]:
        inspector = inspect(sync_conn)
        table_names = set(inspector.get_table_names())
        missing = []
        for table, column, ddl_type in _RETROFIT_COLUMNS:
            if table not in table_names:
                continue  # brand-new DB — create_all() above already covered it
            existing_columns = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing_columns:
                missing.append((table, column, ddl_type))
        return missing

    for table, column, ddl_type in await conn.run_sync(_find_missing):
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
