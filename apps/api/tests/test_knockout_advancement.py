"""Unit tests for the pure-function pieces of knockout_advancement."""

from __future__ import annotations

import uuid

import pytest

from src.routers.groups import TeamStanding
from src.services.knockout_advancement import (
    BRACKET_R32,
    assign_r32_slots,
    rank_third_place_teams,
)


def _standing(
    *,
    position: int,
    code: str,
    points: int = 0,
    gd: int = 0,
    gf: int = 0,
    played: int = 3,
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


def _twelve_groups_full_results() -> dict[str, list[TeamStanding]]:
    """Twelve well-formed group standings — group letter chosen so the
    primary key (-pts, -gd, -gf, code) ranks the 3rds in a known order.

    Each group's 3rd team is given pts/gd/gf that vary by group letter
    so we can reason about the cross-group ranking deterministically.
    """
    out: dict[str, list[TeamStanding]] = {}
    for idx, letter in enumerate("ABCDEFGHIJKL"):
        # 1st and 2nd are kept generic.
        first = _standing(position=1, code=f"{letter}1", points=9, gd=5, gf=7)
        second = _standing(position=2, code=f"{letter}2", points=6, gd=2, gf=5)
        # 3rd team: pts decrease by group index so A's 3rd ranks top, L's last.
        third = _standing(
            position=3,
            code=f"{letter}3",
            points=4 - (idx // 4),  # Tiers: A-D=4, E-H=3, I-L=2 pts
            gd=2 - idx,  # GD decreases monotonically with letter
            gf=3,
        )
        fourth = _standing(position=4, code=f"{letter}4", points=0, gd=-7, gf=0)
        out[letter] = [first, second, third, fourth]
    return out


# ---------------------------------------------------------------------------
# rank_third_place_teams
# ---------------------------------------------------------------------------


def test_rank_third_place_teams_returns_eight_in_pts_gd_gf_order() -> None:
    standings = _twelve_groups_full_results()
    ranked = rank_third_place_teams(standings)

    assert len(ranked) == 8
    # Top tier (4 pts): A-D. Within tier, ranked by GD desc — A (2), B (1), C (0), D (-1).
    assert [s.team_code for s in ranked[:4]] == ["A3", "B3", "C3", "D3"]
    # Next tier (3 pts): E-H. Within tier — E (-3) > F (-4) > G (-5) > H (-6).
    assert [s.team_code for s in ranked[4:8]] == ["E3", "F3", "G3", "H3"]


def test_rank_third_place_teams_breaks_pts_tie_with_gd() -> None:
    standings = {
        "A": [
            _standing(position=1, code="A1", points=9),
            _standing(position=2, code="A2", points=6),
            _standing(position=3, code="A3", points=3, gd=-1, gf=2),
        ],
        "B": [
            _standing(position=1, code="B1", points=9),
            _standing(position=2, code="B2", points=6),
            _standing(position=3, code="B3", points=3, gd=2, gf=2),
        ],
        "C": [
            _standing(position=1, code="C1", points=9),
            _standing(position=2, code="C2", points=6),
            _standing(position=3, code="C3", points=3, gd=0, gf=2),
        ],
    }
    ranked = rank_third_place_teams(standings)
    # All three have 3 pts so GD picks: B(2) > C(0) > A(-1).
    assert [s.team_code for s in ranked] == ["B3", "C3", "A3"]


def test_rank_third_place_teams_breaks_pts_and_gd_tie_with_gf() -> None:
    standings = {
        "A": [
            _standing(position=1, code="A1", points=9),
            _standing(position=2, code="A2", points=6),
            _standing(position=3, code="A3", points=3, gd=0, gf=5),
        ],
        "B": [
            _standing(position=1, code="B1", points=9),
            _standing(position=2, code="B2", points=6),
            _standing(position=3, code="B3", points=3, gd=0, gf=2),
        ],
    }
    ranked = rank_third_place_teams(standings)
    assert [s.team_code for s in ranked] == ["A3", "B3"]


def test_rank_third_place_teams_uses_team_code_as_final_tiebreaker() -> None:
    standings = {
        "A": [
            _standing(position=1, code="A1", points=9),
            _standing(position=2, code="A2", points=6),
            _standing(position=3, code="ZZZ", points=3, gd=0, gf=2),
        ],
        "B": [
            _standing(position=1, code="B1", points=9),
            _standing(position=2, code="B2", points=6),
            _standing(position=3, code="AAA", points=3, gd=0, gf=2),
        ],
    }
    ranked = rank_third_place_teams(standings)
    # All else equal → alphabetical by team_code (deterministic).
    assert [s.team_code for s in ranked] == ["AAA", "ZZZ"]


def test_rank_third_place_teams_skips_groups_with_fewer_than_three_rows() -> None:
    standings = {
        "A": [
            _standing(position=1, code="A1", points=9),
            _standing(position=2, code="A2", points=6),
        ],
        "B": [
            _standing(position=1, code="B1", points=9),
            _standing(position=2, code="B2", points=6),
            _standing(position=3, code="B3", points=3),
        ],
    }
    ranked = rank_third_place_teams(standings)
    assert [s.team_code for s in ranked] == ["B3"]


# ---------------------------------------------------------------------------
# assign_r32_slots
# ---------------------------------------------------------------------------


def test_assign_r32_slots_covers_all_32_slots() -> None:
    standings = _twelve_groups_full_results()
    thirds = rank_third_place_teams(standings)
    slots = assign_r32_slots(standings, thirds)

    # 12 winners + 12 runners-up + 8 best thirds = 32 unique team-ids.
    assert len(slots) == 32
    assert len({s.team_id for s in slots.values()}) == 32

    # Every BRACKET_R32 label is resolvable.
    for home_slot, away_slot in BRACKET_R32:
        assert home_slot in slots
        assert away_slot in slots


def test_assign_r32_slots_raises_when_third_place_pool_short() -> None:
    standings = _twelve_groups_full_results()
    with pytest.raises(ValueError, match="ranked third-place"):
        assign_r32_slots(standings, [])


def test_assign_r32_slots_raises_when_group_missing_top_two() -> None:
    standings = _twelve_groups_full_results()
    standings["A"] = standings["A"][:1]  # only the winner present
    thirds = rank_third_place_teams(standings)
    with pytest.raises(ValueError, match="Group A"):
        assign_r32_slots(standings, thirds)


# ---------------------------------------------------------------------------
# Bracket invariants
# ---------------------------------------------------------------------------


def test_bracket_r32_has_sixteen_pairings_and_uses_each_slot_once() -> None:
    assert len(BRACKET_R32) == 16
    flat = [s for pair in BRACKET_R32 for s in pair]
    assert len(flat) == 32
    assert len(set(flat)) == 32

    expected = (
        {f"1{c}" for c in "ABCDEFGHIJKL"}
        | {f"2{c}" for c in "ABCDEFGHIJKL"}
        | {f"T{i}" for i in range(1, 9)}
    )
    assert set(flat) == expected
