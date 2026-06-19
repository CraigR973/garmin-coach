"""Shared pytest fixtures.

Tests that require a live Postgres database depend on the ``db_engine``
fixture. They skip automatically when ``DATABASE_URL`` is not set so the
default unit-test job stays hermetic. CI provides a Postgres service plus
``alembic upgrade head`` before running these tests.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

# M2 default league slug — tests that exercise the scoring trigger or
# /api/v1/leaderboard need the default league to exist so the trigger
# has memberships to fan out to and the endpoint has rows to read.
DEFAULT_TEST_LEAGUE_SLUG = "steele-spreadsheet"
DEFAULT_TEST_LEAGUE_NAME = "The Steele Spreadsheet"


async def ensure_default_league_membership(
    conn: AsyncConnection,
    profile_id: uuid.UUID | str,
    *,
    role: str = "player",
) -> uuid.UUID:
    """Idempotently create the default league and add ``profile_id`` to it.

    Returns the league id. Safe to call from many test helpers in the same
    transaction; the slug UNIQUE makes league creation a no-op after the
    first call and the ``(league_id, player_id)`` UNIQUE makes the
    membership insert a no-op after the first call per profile.

    The new M2 scoring trigger fans snapshots out per active
    league_membership, so every profile that needs to appear in a
    snapshot must hold a row here.
    """
    league_id = (
        await conn.execute(
            text(
                """
                INSERT INTO leagues (id, slug, name, created_by)
                VALUES (gen_random_uuid(), :slug, :name, :p)
                ON CONFLICT (slug) DO UPDATE SET slug = excluded.slug
                RETURNING id
                """
            ),
            {
                "slug": DEFAULT_TEST_LEAGUE_SLUG,
                "name": DEFAULT_TEST_LEAGUE_NAME,
                "p": str(profile_id),
            },
        )
    ).scalar_one()
    await conn.execute(
        text(
            """
            INSERT INTO league_memberships (id, league_id, player_id, role)
            VALUES (gen_random_uuid(), :l, :p, CAST(:r AS league_member_role))
            ON CONFLICT (league_id, player_id) DO NOTHING
            """
        ),
        {"l": league_id, "p": str(profile_id), "r": role},
    )
    return league_id


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Reset in-memory rate-limit storage before every test for hermetic runs."""
    from src.rate_limit import limiter

    limiter._storage.reset()


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

    Each test runs inside an auto-begun transaction. Rolling back keeps
    the test suite hermetic even when tests insert rows (phase 1.6
    trigger tests rely on this).

    Pre-existing committed profiles (e.g. the admin seeded in production)
    are soft-deleted within the transaction so they don't inflate trigger-
    driven leaderboard snapshot counts. The rollback restores them.
    """
    async with db_engine.connect() as conn:
        await conn.execute(text("UPDATE profiles SET deleted_at = now() WHERE deleted_at IS NULL"))
        try:
            yield conn
        finally:
            await conn.rollback()
