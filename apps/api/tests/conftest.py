"""Shared pytest fixtures.

Tests that require a live Postgres database depend on the ``db_engine``
fixture.  They skip automatically when ``DATABASE_URL`` is not set so the
default unit-test job stays hermetic.  CI provides a Postgres service plus
``alembic upgrade head`` before running these tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Reset in-memory rate-limit storage before every test for hermetic runs."""
    from src.rate_limit import limiter
    from src.services.workload_budget import reset_workload_budgets

    limiter._storage.reset()
    reset_workload_budgets()


DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — Postgres-backed tests skipped")
    engine = create_async_engine(DATABASE_URL, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_conn(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Open a fresh connection per test and roll back on exit.

    Each test runs inside an auto-begun transaction.  Rolling back keeps
    the suite hermetic even when tests insert rows.
    """
    async with db_engine.connect() as conn:
        await conn.execute(text("SET search_path TO coach, public"))
        await conn.execute(text("UPDATE profiles SET deleted_at = now() WHERE deleted_at IS NULL"))
        try:
            yield conn
        finally:
            await conn.rollback()
