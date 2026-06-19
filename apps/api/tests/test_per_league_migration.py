"""Phase M2 — migration 012 schema coverage.

Tests run inside the ``db_conn`` fixture (auto-rolled back). They assume
``alembic upgrade head`` has been applied by CI before pytest runs, so
the new columns / indexes / FKs from migration 012 are visible.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def _scalar(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar_one()


async def _fetchall(conn: AsyncConnection, sql: str, **params: Any) -> list[Any]:
    result = await conn.execute(text(sql), params)
    return list(result.mappings().all())


async def test_alembic_revision_at_least_012(db_conn: AsyncConnection) -> None:
    rev = await _scalar(db_conn, "SELECT version_num FROM alembic_version")
    assert rev >= "012"


async def test_leaderboard_snapshots_has_league_id_not_null(
    db_conn: AsyncConnection,
) -> None:
    rows = await _fetchall(
        db_conn,
        """
        SELECT column_name, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'leaderboard_snapshots' AND column_name = 'league_id'
        """,
    )
    assert len(rows) == 1
    assert rows[0]["is_nullable"] == "NO"


async def test_invites_has_league_id_not_null(db_conn: AsyncConnection) -> None:
    rows = await _fetchall(
        db_conn,
        """
        SELECT column_name, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'invites' AND column_name = 'league_id'
        """,
    )
    assert len(rows) == 1
    assert rows[0]["is_nullable"] == "NO"


async def test_leaderboard_snapshots_league_index_exists(
    db_conn: AsyncConnection,
) -> None:
    row = await _scalar(
        db_conn,
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'leaderboard_snapshots'
          AND indexname = 'ix_leaderboard_snapshots_league_player_time'
        """,
    )
    assert row == "ix_leaderboard_snapshots_league_player_time"


async def test_leaderboard_snapshots_league_fk_targets_leagues(
    db_conn: AsyncConnection,
) -> None:
    row = await _scalar(
        db_conn,
        """
        SELECT confrelid::regclass::text
        FROM pg_constraint
        WHERE conname = 'fk_leaderboard_snapshots_league_id'
        """,
    )
    assert row == "leagues"


async def test_invites_league_fk_targets_leagues(db_conn: AsyncConnection) -> None:
    row = await _scalar(
        db_conn,
        """
        SELECT confrelid::regclass::text
        FROM pg_constraint
        WHERE conname = 'fk_invites_league_id'
        """,
    )
    assert row == "leagues"
