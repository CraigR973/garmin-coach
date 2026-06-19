"""Mocked-session tests for ``sync_knockout_bracket`` (U13 DB layer).

The pure resolution logic is covered by ``test_knockout_progression``. These
tests pin the thin persistence layer: it must write resolved team ids onto the
right seeded rows, cascade to later rounds as results settle, and stay
idempotent. A mocked ``AsyncSession`` keeps them DB-free.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.match import Match
from src.routers.groups import TeamStanding
from src.services import knockout_advancement
from src.services.knockout_progression import (
    MatchOutcome,
    rank_third_place_teams,
    resolve_bracket,
    stage_for_match_number,
)

_LETTERS = "ABCDEFGHIJKL"


def _standing(
    *, position: int, code: str, points: int, gd: int, gf: int, played: int = 3
) -> TeamStanding:
    return TeamStanding(
        position=position,
        team_id=str(uuid.uuid4()),
        team_name=f"Team {code}",
        team_code=code,
        flag_emoji="🏳",
        played=played,
        won=0,
        drawn=0,
        lost=0,
        gf=gf,
        ga=max(gf - gd, 0),
        gd=gd,
        points=points,
    )


def _twelve_complete_groups() -> dict[str, list[TeamStanding]]:
    out: dict[str, list[TeamStanding]] = {}
    for idx, letter in enumerate(_LETTERS):
        out[letter] = [
            _standing(position=1, code=f"{letter}1", points=9, gd=6, gf=8),
            _standing(position=2, code=f"{letter}2", points=6, gd=2, gf=5),
            _standing(position=3, code=f"{letter}3", points=4 - (idx // 4), gd=3 - idx, gf=4),
            _standing(position=4, code=f"{letter}4", points=0, gd=-7, gf=1),
        ]
    return out


def _seed_ko_match(match_number: int) -> MagicMock:
    m = MagicMock(spec=Match)
    m.match_number = match_number
    m.stage = stage_for_match_number(match_number)
    m.home_team_id = None
    m.away_team_id = None
    m.deleted_at = None
    return m


def _stub_db(ko_matches: list[MagicMock]) -> AsyncMock:
    """AsyncSession whose single execute() returns the seeded KO rows."""
    wrapper = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = ko_matches
    wrapper.scalars.return_value = scalars
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=wrapper)
    db.commit = AsyncMock()
    return db


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    standings: dict[str, list[TeamStanding]],
    outcomes: dict[int, MatchOutcome],
) -> None:
    async def _fake_standings(_db: object) -> dict[str, list[TeamStanding]]:
        return standings

    async def _fake_outcomes(_db: object) -> dict[int, MatchOutcome]:
        return outcomes

    monkeypatch.setattr(knockout_advancement, "_load_group_standings", _fake_standings)
    monkeypatch.setattr(knockout_advancement, "_load_ko_outcomes", _fake_outcomes)


async def test_sync_resolves_r32_from_complete_standings(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = _twelve_complete_groups()
    ranked = rank_third_place_teams(groups)
    ko_matches = [_seed_ko_match(n) for n in range(73, 105)]
    _patch_loaders(monkeypatch, groups, {})

    db = _stub_db(ko_matches)
    updated = await knockout_advancement.sync_knockout_bracket(db)

    by_num = {m.match_number: m for m in ko_matches}
    assert updated == 16  # all 16 R32 rows newly filled
    assert by_num[73].home_team_id == uuid.UUID(groups["A"][0].team_id)
    assert by_num[73].away_team_id == uuid.UUID(ranked[0].team_id)
    assert by_num[80].away_team_id == uuid.UUID(ranked[7].team_id)
    # Later rounds remain unresolved until results settle.
    assert by_num[89].home_team_id is None
    assert by_num[104].home_team_id is None
    db.commit.assert_awaited_once()


async def test_sync_cascades_to_next_round(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = _twelve_complete_groups()
    r32 = resolve_bracket(groups, {})
    # R32 already resolved on the rows; every home team won.
    outcomes = {
        n: MatchOutcome(
            home_team_id=r32[n].home_team_id,
            away_team_id=r32[n].away_team_id,
            home_score=1,
            away_score=0,
        )
        for n in range(73, 89)
    }
    ko_matches: list[MagicMock] = []
    for n in range(73, 105):
        m = _seed_ko_match(n)
        if 73 <= n <= 88:
            m.home_team_id = r32[n].home_team_id
            m.away_team_id = r32[n].away_team_id
        ko_matches.append(m)
    _patch_loaders(monkeypatch, groups, outcomes)

    db = _stub_db(ko_matches)
    updated = await knockout_advancement.sync_knockout_bracket(db)

    by_num = {m.match_number: m for m in ko_matches}
    # Only the 8 R16 rows are newly filled; the already-set R32 rows aren't recounted.
    assert updated == 8
    assert by_num[89].home_team_id == r32[73].home_team_id
    assert by_num[89].away_team_id == r32[74].home_team_id
    assert by_num[96].away_team_id == r32[88].home_team_id
    db.commit.assert_awaited_once()


async def test_sync_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = _twelve_complete_groups()
    r32 = resolve_bracket(groups, {})
    # Rows already carry the resolved R32 teams; nothing new to write.
    ko_matches: list[MagicMock] = []
    for n in range(73, 105):
        m = _seed_ko_match(n)
        if 73 <= n <= 88:
            m.home_team_id = r32[n].home_team_id
            m.away_team_id = r32[n].away_team_id
        ko_matches.append(m)
    _patch_loaders(monkeypatch, groups, {})

    db = _stub_db(ko_matches)
    updated = await knockout_advancement.sync_knockout_bracket(db)

    assert updated == 0
    db.commit.assert_not_awaited()  # no-op runs must not commit


async def test_sync_no_op_before_group_stage_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = _twelve_complete_groups()
    groups["A"][0] = _standing(position=1, code="A1", points=9, gd=6, gf=8, played=2)  # unfinished
    ko_matches = [_seed_ko_match(n) for n in range(73, 105)]
    _patch_loaders(monkeypatch, groups, {})

    db = _stub_db(ko_matches)
    updated = await knockout_advancement.sync_knockout_bracket(db)

    by_num = {m.match_number: m for m in ko_matches}
    # Group A's winner slot and all best-third slots stay unknown; other group
    # winners/runners-up still resolve, so some R32 rows fill.
    assert by_num[73].home_team_id is None  # winner_group_a
    assert by_num[73].away_team_id is None  # best_third_1
    assert updated > 0  # e.g. match 88 (runner-up K vs runner-up L) resolves
