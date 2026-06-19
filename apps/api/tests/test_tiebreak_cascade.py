"""U38 — merit-cascade tiebreaking (DB-backed).

These exercise the scoring trigger / recompute helper rewritten in migration
026. Two players level on ``total_points`` must be separated, in order, by:

    exact scores → correct results → correct goals
    → specials correct → knockout-winner picks correct

and a genuine tie on *every* axis must share a rank (flagged for admin
settlement), broken only by an explicit admin manual order.

Like the other ``db_conn`` suites these run against a migrated Postgres (CI),
and are skipped locally where no database is configured.

A useful invariant while reading the fixtures: scoreline match points satisfy
``match_points = 5·exact + 3·result + 2·goals`` exactly. So two players level on
points *and* exact *and* result are automatically level on goals — the goals
axis only ever separates players when knockout/special points break that parity.
The goals fixture below does exactly that.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.database import get_db
from src.main import app
from src.routers.leagues import require_league_member
from tests.conftest import ensure_default_league_membership
from tests.test_leaderboard import _db_with, _league, _make_requester
from tests.test_scoring_trigger import (
    _enter_result,
    _exec,
    _fetchall,
    _insert_group,
    _insert_knockout_prediction,
    _insert_match,
    _insert_prediction,
    _insert_profile,
    _insert_team,
)

SLUG = "test-league"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_special(
    conn: AsyncConnection,
    *,
    player_id: uuid.UUID,
    prediction_type: str,
    points_awarded: int,
) -> None:
    """Insert an already-graded special prediction (bypasses the award flow).

    ``points_awarded > 0`` marks a correct special; the snapshot trigger sums
    these into ``special_points`` and counts the correct ones.
    """
    await _exec(
        conn,
        """
        INSERT INTO special_predictions (id, player_id, prediction_type, points_awarded)
        VALUES (gen_random_uuid(), :p, CAST(:t AS special_prediction_type), :pts)
        """,
        p=player_id,
        t=prediction_type,
        pts=points_awarded,
    )


async def _snaps_for_match(conn: AsyncConnection, match_id: uuid.UUID) -> dict[str, Any]:
    """Latest snapshot per player from the trigger fired by ``match_id``.

    Keyed by display_name. The trigger sums *all* of a player's points (not just
    the triggering match), so this row carries complete current totals/counts.
    """
    rows = await _fetchall(
        conn,
        """
        SELECT p.display_name AS name, s.rank, s.total_points,
               s.match_points, s.knockout_winner_points, s.special_points,
               s.exact_count, s.correct_result_count, s.correct_goals_count,
               s.specials_correct_count, s.ko_winner_correct_count
        FROM leaderboard_snapshots s JOIN profiles p ON p.id = s.player_id
        WHERE s.triggered_by_match_id = :m
        """,
        m=match_id,
    )
    return {r["name"]: r for r in rows}


# ---------------------------------------------------------------------------
# U38.1 — aggregate correctness
# ---------------------------------------------------------------------------


async def test_snapshot_stores_tiebreak_counts(db_conn: AsyncConnection) -> None:
    """The snapshot persists exact/result/goals/specials/ko-winner counts."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Agg Home", "AGH")
    away = await _insert_team(db_conn, g, "Agg Away", "AGA")
    alice = await _insert_profile(db_conn, "agg_alice")

    # Two group matches (actual 3-0 each) + one r16 knockout (home win).
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    m2 = await _insert_match(
        db_conn, stage="group", match_number=2, home_team_id=home, away_team_id=away, group_id=g
    )
    ko = await _insert_match(
        db_conn, stage="r16", match_number=3, home_team_id=home, away_team_id=away
    )

    # m1: exact 3-0 → exact+result+goals. m2: 2-1 → result+goals (no exact).
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=3, away=0)
    await _insert_prediction(db_conn, player_id=alice, match_id=m2, home=2, away=1)
    await _insert_knockout_prediction(
        db_conn, player_id=alice, match_id=ko, predicted_winner_id=home
    )
    await _insert_special(
        db_conn, player_id=alice, prediction_type="tournament_winner", points_awarded=20
    )

    await _enter_result(db_conn, m1, 3, 0)
    await _enter_result(db_conn, m2, 3, 0)
    await _enter_result(db_conn, ko, 2, 1)  # last → authoritative snapshot

    snap = (await _snaps_for_match(db_conn, ko))["agg_alice"]
    assert snap["exact_count"] == 1  # m1 only
    assert snap["correct_result_count"] == 2  # m1 + m2
    assert snap["correct_goals_count"] == 2  # m1 + m2
    assert snap["specials_correct_count"] == 1
    assert snap["ko_winner_correct_count"] == 1
    # match 10 (m1) + 5 (m2) + ko 10 + special 20 = 45
    assert snap["total_points"] == 45
    # identity holds for the scoreline portion: 5*1 + 3*2 + 2*2 = 15
    assert snap["match_points"] == 15


# ---------------------------------------------------------------------------
# U38.2 — the cascade separates at each level
# ---------------------------------------------------------------------------


async def test_cascade_exact_separates_equal_points(db_conn: AsyncConnection) -> None:
    """Level on points, more exacts wins (exact is the first tiebreaker)."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Ex Home", "EXH")
    away = await _insert_team(db_conn, g, "Ex Away", "EXA")
    alice = await _insert_profile(db_conn, "ex_alice")
    bob = await _insert_profile(db_conn, "ex_bob")
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    m2 = await _insert_match(
        db_conn, stage="group", match_number=2, home_team_id=home, away_team_id=away, group_id=g
    )
    # alice: m1 exact (10) + m2 zero → 10, exact=1. bob: two result+goals (5+5) → 10, exact=0.
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=3, away=0)  # exact
    await _insert_prediction(db_conn, player_id=alice, match_id=m2, home=0, away=2)  # 0 pts
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=2, away=1)  # result+goals
    await _insert_prediction(db_conn, player_id=bob, match_id=m2, home=2, away=1)  # result+goals

    await _enter_result(db_conn, m1, 3, 0)
    await _enter_result(db_conn, m2, 3, 0)

    snaps = await _snaps_for_match(db_conn, m2)
    assert snaps["ex_alice"]["total_points"] == snaps["ex_bob"]["total_points"] == 10
    assert snaps["ex_alice"]["exact_count"] == 1
    assert snaps["ex_bob"]["exact_count"] == 0
    assert snaps["ex_alice"]["rank"] == 1
    assert snaps["ex_bob"]["rank"] == 2


async def test_cascade_result_separates_when_exact_tied(db_conn: AsyncConnection) -> None:
    """Level on points and exact (both 0), more correct results wins."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Rs Home", "RSH")
    away = await _insert_team(db_conn, g, "Rs Away", "RSA")
    alice = await _insert_profile(db_conn, "rs_alice")
    bob = await _insert_profile(db_conn, "rs_bob")
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    m2 = await _insert_match(
        db_conn, stage="group", match_number=2, home_team_id=home, away_team_id=away, group_id=g
    )
    m3 = await _insert_match(
        db_conn, stage="group", match_number=3, home_team_id=home, away_team_id=away, group_id=g
    )
    # alice: two result-only (3+3) → 6, result=2. bob: three goals-only (2+2+2) → 6, result=0.
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=2, away=0)  # result only
    await _insert_prediction(db_conn, player_id=alice, match_id=m2, home=2, away=0)  # result only
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=0, away=1)  # goals only
    await _insert_prediction(db_conn, player_id=bob, match_id=m2, home=0, away=1)  # goals only
    await _insert_prediction(db_conn, player_id=bob, match_id=m3, home=0, away=2)  # goals only

    await _enter_result(db_conn, m1, 1, 0)
    await _enter_result(db_conn, m2, 1, 0)
    await _enter_result(db_conn, m3, 2, 0)

    snaps = await _snaps_for_match(db_conn, m3)
    assert snaps["rs_alice"]["total_points"] == snaps["rs_bob"]["total_points"] == 6
    assert snaps["rs_alice"]["exact_count"] == snaps["rs_bob"]["exact_count"] == 0
    assert snaps["rs_alice"]["correct_result_count"] == 2
    assert snaps["rs_bob"]["correct_result_count"] == 0
    assert snaps["rs_alice"]["rank"] == 1
    assert snaps["rs_bob"]["rank"] == 2


async def test_cascade_goals_separates_when_points_exact_result_tied(
    db_conn: AsyncConnection,
) -> None:
    """Goals breaks a tie only when ko/special points offset the score identity.

    alice: five goals-only scorelines → 10 match pts, goals=5, exact=result=0.
    bob:   one correct r16 knockout pick → 10 ko pts, every scoreline count 0.
    Level on points/exact/result; alice's extra goals win before ko is reached.
    """
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Gl Home", "GLH")
    away = await _insert_team(db_conn, g, "Gl Away", "GLA")
    alice = await _insert_profile(db_conn, "gl_alice")
    bob = await _insert_profile(db_conn, "gl_bob")

    last_group: uuid.UUID | None = None
    for n in range(5):
        gm = await _insert_match(
            db_conn,
            stage="group",
            match_number=10 + n,
            home_team_id=home,
            away_team_id=away,
            group_id=g,
        )
        # actual 2-0, predict 0-2 → goals (total 2==2), wrong result, not exact → 2 pts.
        await _insert_prediction(db_conn, player_id=alice, match_id=gm, home=0, away=2)
        await _enter_result(db_conn, gm, 2, 0)
        last_group = gm

    ko = await _insert_match(
        db_conn, stage="r16", match_number=20, home_team_id=home, away_team_id=away
    )
    await _insert_knockout_prediction(db_conn, player_id=bob, match_id=ko, predicted_winner_id=home)
    await _enter_result(db_conn, ko, 2, 1)  # home win → bob's pick correct (10)

    assert last_group is not None
    snaps = await _snaps_for_match(db_conn, ko)
    assert snaps["gl_alice"]["total_points"] == snaps["gl_bob"]["total_points"] == 10
    assert snaps["gl_alice"]["exact_count"] == snaps["gl_bob"]["exact_count"] == 0
    assert snaps["gl_alice"]["correct_result_count"] == snaps["gl_bob"]["correct_result_count"] == 0
    assert snaps["gl_alice"]["correct_goals_count"] == 5
    assert snaps["gl_bob"]["correct_goals_count"] == 0
    assert snaps["gl_alice"]["rank"] == 1
    assert snaps["gl_bob"]["rank"] == 2


async def test_cascade_specials_separate_when_scorelines_tied(
    db_conn: AsyncConnection,
) -> None:
    """Level on every scoreline axis, more correct specials wins (before ko)."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Sp Home", "SPH")
    away = await _insert_team(db_conn, g, "Sp Away", "SPA")
    alice = await _insert_profile(db_conn, "sp_alice")
    bob = await _insert_profile(db_conn, "sp_bob")
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    sf = await _insert_match(
        db_conn, stage="sf", match_number=2, home_team_id=home, away_team_id=away
    )
    # Identical scorelines (both exact on m1 → 10, exact=result=goals=1).
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=3, away=0)
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=3, away=0)
    # alice: correct special (20). bob: correct sf knockout pick (20). Totals tie at 30.
    await _insert_special(
        db_conn, player_id=alice, prediction_type="tournament_winner", points_awarded=20
    )
    await _insert_knockout_prediction(db_conn, player_id=bob, match_id=sf, predicted_winner_id=home)

    await _enter_result(db_conn, m1, 3, 0)
    await _enter_result(db_conn, sf, 2, 1)  # bob's sf pick correct (20)

    snaps = await _snaps_for_match(db_conn, sf)
    assert snaps["sp_alice"]["total_points"] == snaps["sp_bob"]["total_points"] == 30
    for axis in ("exact_count", "correct_result_count", "correct_goals_count"):
        assert snaps["sp_alice"][axis] == snaps["sp_bob"][axis] == 1
    assert snaps["sp_alice"]["specials_correct_count"] == 1
    assert snaps["sp_bob"]["specials_correct_count"] == 0
    assert snaps["sp_alice"]["rank"] == 1
    assert snaps["sp_bob"]["rank"] == 2


async def test_cascade_ko_winner_separates_when_specials_tied(
    db_conn: AsyncConnection,
) -> None:
    """Level up to specials count, more correct knockout-winner picks wins.

    Both have one correct special, but of different value (15 vs 20); alice's
    extra correct r32 pick (5) restores the points tie and wins at the last axis.
    """
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Ko Home", "KOH")
    away = await _insert_team(db_conn, g, "Ko Away", "KOA")
    alice = await _insert_profile(db_conn, "ko_alice")
    bob = await _insert_profile(db_conn, "ko_bob")
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    r32 = await _insert_match(
        db_conn, stage="r32", match_number=2, home_team_id=home, away_team_id=away
    )
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=3, away=0)
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=3, away=0)
    # alice: golden_boot (15) + correct r32 pick (5) = 20 of non-scoreline points.
    # bob:   tournament_winner (20). Both specials_correct = 1; totals tie at 30.
    await _insert_special(
        db_conn, player_id=alice, prediction_type="golden_boot", points_awarded=15
    )
    await _insert_knockout_prediction(
        db_conn, player_id=alice, match_id=r32, predicted_winner_id=home
    )
    await _insert_special(
        db_conn, player_id=bob, prediction_type="tournament_winner", points_awarded=20
    )

    await _enter_result(db_conn, m1, 3, 0)
    await _enter_result(db_conn, r32, 1, 0)  # alice's r32 pick correct (5)

    snaps = await _snaps_for_match(db_conn, r32)
    assert snaps["ko_alice"]["total_points"] == snaps["ko_bob"]["total_points"] == 30
    for axis in ("exact_count", "correct_result_count", "correct_goals_count"):
        assert snaps["ko_alice"][axis] == snaps["ko_bob"][axis] == 1
    assert (
        snaps["ko_alice"]["specials_correct_count"]
        == snaps["ko_bob"]["specials_correct_count"]
        == 1
    )
    assert snaps["ko_alice"]["ko_winner_correct_count"] == 1
    assert snaps["ko_bob"]["ko_winner_correct_count"] == 0
    assert snaps["ko_alice"]["rank"] == 1
    assert snaps["ko_bob"]["rank"] == 2


# ---------------------------------------------------------------------------
# U38.2 / U38.4 — genuine all-axis tie shares a rank, broken only by an override
# ---------------------------------------------------------------------------


async def test_all_axis_tie_shares_rank(db_conn: AsyncConnection) -> None:
    """Identical on every axis → shared rank (no timing/alphabetical break)."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Tie Home", "TIH")
    away = await _insert_team(db_conn, g, "Tie Away", "TIA")
    alice = await _insert_profile(db_conn, "tie_alice")
    bob = await _insert_profile(db_conn, "tie_bob")
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    # Both predict the exact same scoreline → identical on every axis.
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=2, away=1)
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=2, away=1)

    await _enter_result(db_conn, m1, 2, 1)

    snaps = await _snaps_for_match(db_conn, m1)
    assert snaps["tie_alice"]["rank"] == snaps["tie_bob"]["rank"] == 1


async def test_admin_override_breaks_all_axis_tie(db_conn: AsyncConnection) -> None:
    """An admin manual order separates an otherwise-exact tie on recompute."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Ov Home", "OVH")
    away = await _insert_team(db_conn, g, "Ov Away", "OVA")
    alice = await _insert_profile(db_conn, "ov_alice")
    bob = await _insert_profile(db_conn, "ov_bob")
    league_id = await ensure_default_league_membership(db_conn, alice)
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=2, away=1)
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=2, away=1)
    await _enter_result(db_conn, m1, 2, 1)

    # Tied before the override.
    snaps = await _snaps_for_match(db_conn, m1)
    assert snaps["ov_alice"]["rank"] == snaps["ov_bob"]["rank"] == 1

    # Admin pins bob ahead of alice, then we recompute via the same helper the
    # admin endpoint uses.
    await _exec(
        db_conn,
        """
        INSERT INTO leaderboard_tiebreak_overrides (id, league_id, player_id, manual_order)
        VALUES (gen_random_uuid(), :l, :b, 1), (gen_random_uuid(), :l, :a, 2)
        """,
        l=league_id,
        a=alice,
        b=bob,
    )
    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    try:
        from src.services.leaderboard import recompute_leaderboard_snapshot

        await recompute_leaderboard_snapshot(session, triggered_by_match_id=None)
        await session.flush()
    finally:
        await session.close()

    ranked = await _fetchall(
        db_conn,
        """
        SELECT p.display_name AS name, s.rank
        FROM leaderboard_snapshots s JOIN profiles p ON p.id = s.player_id
        WHERE s.league_id = :l AND s.triggered_by_match_id IS NULL
        """,
        l=league_id,
    )
    by_name = {r["name"]: r["rank"] for r in ranked}
    assert by_name["ov_bob"] == 1
    assert by_name["ov_alice"] == 2


# ---------------------------------------------------------------------------
# U38.3 — the same order drives snapshots, history, and the endpoint
# ---------------------------------------------------------------------------


async def test_rank_consistent_across_snapshot_history_and_endpoint(
    db_conn: AsyncConnection,
) -> None:
    """Snapshot rank, history rank, and the leaderboard payload never disagree."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Cs Home", "CSH")
    away = await _insert_team(db_conn, g, "Cs Away", "CSA")
    alice = await _insert_profile(db_conn, "cs_alice")
    bob = await _insert_profile(db_conn, "cs_bob")
    league_id = await ensure_default_league_membership(db_conn, alice)
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    m2 = await _insert_match(
        db_conn, stage="group", match_number=2, home_team_id=home, away_team_id=away, group_id=g
    )
    # Level on points (10 each) but alice has the only exact → alice ranks first.
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=3, away=0)  # exact
    await _insert_prediction(db_conn, player_id=alice, match_id=m2, home=0, away=2)  # 0
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=2, away=1)  # 5
    await _insert_prediction(db_conn, player_id=bob, match_id=m2, home=2, away=1)  # 5
    await _enter_result(db_conn, m1, 3, 0)
    await _enter_result(db_conn, m2, 3, 0)

    snaps = await _snaps_for_match(db_conn, m2)
    assert snaps["cs_alice"]["rank"] == 1
    assert snaps["cs_bob"]["rank"] == 2

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    app.dependency_overrides[get_db] = _db_with(session)
    app.dependency_overrides[require_league_member] = lambda: (
        _make_requester(),
        _league(league_id),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            board = (await client.get(f"/api/v1/leagues/{SLUG}/leaderboard")).json()
            history = (await client.get(f"/api/v1/leagues/{SLUG}/leaderboard/history")).json()
    finally:
        app.dependency_overrides.clear()
        await session.close()

    board_rank = {e["player_name"]: e["rank"] for e in board}
    assert board_rank["cs_alice"] == 1
    assert board_rank["cs_bob"] == 2
    # The leaderboard payload also carries the tiebreak counts that justify it.
    alice_entry = next(e for e in board if e["player_name"] == "cs_alice")
    assert alice_entry["exact_count"] == 1
    assert alice_entry["tied"] is False

    # History's latest snapshot rank per player agrees with the table.
    for entry in history:
        latest = entry["snapshots"][-1]
        assert latest["rank"] == board_rank[entry["player_name"]]


@pytest.mark.asyncio
async def test_endpoint_marks_all_axis_tie(db_conn: AsyncConnection) -> None:
    """A genuine tie surfaces as ``tied=true`` with a shared rank in the payload."""
    g = await _insert_group(db_conn, "A")
    home = await _insert_team(db_conn, g, "Fl Home", "FLH")
    away = await _insert_team(db_conn, g, "Fl Away", "FLA")
    alice = await _insert_profile(db_conn, "fl_alice")
    bob = await _insert_profile(db_conn, "fl_bob")
    league_id = await ensure_default_league_membership(db_conn, alice)
    m1 = await _insert_match(
        db_conn, stage="group", match_number=1, home_team_id=home, away_team_id=away, group_id=g
    )
    await _insert_prediction(db_conn, player_id=alice, match_id=m1, home=2, away=1)
    await _insert_prediction(db_conn, player_id=bob, match_id=m1, home=2, away=1)
    await _enter_result(db_conn, m1, 2, 1)

    session = AsyncSession(bind=db_conn, expire_on_commit=False)
    app.dependency_overrides[get_db] = _db_with(session)
    app.dependency_overrides[require_league_member] = lambda: (
        _make_requester(),
        _league(league_id),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            board = (await client.get(f"/api/v1/leagues/{SLUG}/leaderboard")).json()
    finally:
        app.dependency_overrides.clear()
        await session.close()

    tied = {e["player_name"]: e["tied"] for e in board}
    ranks = {e["player_name"]: e["rank"] for e in board}
    assert tied["fl_alice"] is True
    assert tied["fl_bob"] is True
    assert ranks["fl_alice"] == ranks["fl_bob"] == 1
