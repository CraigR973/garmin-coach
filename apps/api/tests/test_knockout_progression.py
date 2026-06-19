"""Unit tests for the pure knockout progression resolver (U13.4)."""

from __future__ import annotations

import uuid

import pytest

from src.models.team import TournamentStage
from src.routers.groups import TeamStanding
from src.services.knockout_advancement import BRACKET_R32  # re-exported, must stay importable
from src.services.knockout_progression import (
    KNOCKOUT_BRACKET,
    MatchOutcome,
    all_groups_complete,
    placeholder_label,
    rank_third_place_teams,
    resolve_bracket,
    resolve_source,
    stage_for_match_number,
)

_LETTERS = "ABCDEFGHIJKL"


def _standing(
    *,
    position: int,
    code: str,
    team_id: uuid.UUID | None = None,
    points: int = 0,
    gd: int = 0,
    gf: int = 0,
    played: int = 3,
) -> TeamStanding:
    return TeamStanding(
        position=position,
        team_id=str(team_id or uuid.uuid4()),
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
    """Twelve fully-played groups with deterministic third-place ranking.

    Third-placed points/GD decrease with the group letter so the eight best
    thirds rank A3 > B3 > … > H3 (I3..L3 drop out).
    """
    out: dict[str, list[TeamStanding]] = {}
    for idx, letter in enumerate(_LETTERS):
        out[letter] = [
            _standing(position=1, code=f"{letter}1", points=9, gd=6, gf=8),
            _standing(position=2, code=f"{letter}2", points=6, gd=2, gf=5),
            _standing(position=3, code=f"{letter}3", points=4 - (idx // 4), gd=3 - idx, gf=4),
            _standing(position=4, code=f"{letter}4", points=0, gd=-7, gf=1),
        ]
    return out


def _tid(s: TeamStanding) -> uuid.UUID:
    return uuid.UUID(s.team_id)


# ---------------------------------------------------------------------------
# Bracket shape
# ---------------------------------------------------------------------------


def test_bracket_covers_all_32_knockout_matches() -> None:
    assert sorted(KNOCKOUT_BRACKET) == list(range(73, 105))
    assert len(KNOCKOUT_BRACKET) == 32


def test_bracket_r32_matches_legacy_pairing() -> None:
    """The seeded R32 sources are derived from BRACKET_R32 — they can't drift."""

    def src(slot: str) -> str:
        kind, rest = slot[0], slot[1:]
        return {
            "1": f"winner_group_{rest.lower()}",
            "2": f"runner_up_group_{rest.lower()}",
            "T": f"best_third_{rest}",
        }[kind]

    for i, (home_slot, away_slot) in enumerate(BRACKET_R32):
        assert KNOCKOUT_BRACKET[73 + i] == (src(home_slot), src(away_slot))


def test_bracket_later_rounds_reference_prior_match_winners() -> None:
    assert KNOCKOUT_BRACKET[89] == ("winner_match_73", "winner_match_74")
    assert KNOCKOUT_BRACKET[96] == ("winner_match_87", "winner_match_88")
    assert KNOCKOUT_BRACKET[97] == ("winner_match_89", "winner_match_90")
    assert KNOCKOUT_BRACKET[101] == ("winner_match_97", "winner_match_98")
    assert KNOCKOUT_BRACKET[102] == ("winner_match_99", "winner_match_100")
    # Third place = the two semi-final losers; final = the two semi-final winners.
    assert KNOCKOUT_BRACKET[103] == ("loser_match_101", "loser_match_102")
    assert KNOCKOUT_BRACKET[104] == ("winner_match_101", "winner_match_102")


def test_every_match_winner_is_consumed_exactly_once_downstream() -> None:
    """Each of matches 73..102 feeds exactly one later slot (single-elimination)."""
    refs: list[str] = []
    for home_src, away_src in KNOCKOUT_BRACKET.values():
        refs.extend([home_src, away_src])
    winner_targets = sorted(
        int(r.removeprefix("winner_match_")) for r in refs if r.startswith("winner_match_")
    )
    # 73..100 feed exactly one slot each; 101 & 102 feed two (final + nothing-
    # else) — they each appear once as winner_match (final) and once as
    # loser_match (third place).
    assert winner_targets == list(range(73, 103))
    loser_targets = sorted(
        int(r.removeprefix("loser_match_")) for r in refs if r.startswith("loser_match_")
    )
    assert loser_targets == [101, 102]


# ---------------------------------------------------------------------------
# stage_for_match_number / placeholder_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("match_number", "stage"),
    [
        (73, TournamentStage.r32),
        (88, TournamentStage.r32),
        (89, TournamentStage.r16),
        (96, TournamentStage.r16),
        (97, TournamentStage.qf),
        (100, TournamentStage.qf),
        (101, TournamentStage.sf),
        (102, TournamentStage.sf),
        (103, TournamentStage.third_place),
        (104, TournamentStage.final),
    ],
)
def test_stage_for_match_number(match_number: int, stage: TournamentStage) -> None:
    assert stage_for_match_number(match_number) == stage


@pytest.mark.parametrize("bad", [1, 72, 105, 0])
def test_stage_for_match_number_rejects_non_knockout(bad: int) -> None:
    with pytest.raises(ValueError, match="knockout match number"):
        stage_for_match_number(bad)


@pytest.mark.parametrize(
    ("source", "label"),
    [
        ("winner_group_a", "Winner Group A"),
        ("runner_up_group_b", "Runner-up Group B"),
        ("best_third_1", "Best 3rd #1"),
        ("winner_match_73", "Winner of Match 73"),
        ("loser_match_101", "Loser of Match 101"),
    ],
)
def test_placeholder_label(source: str, label: str) -> None:
    assert placeholder_label(source) == label


def test_placeholder_label_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source ref"):
        placeholder_label("garbage")


def test_every_bracket_source_has_a_placeholder_label() -> None:
    for home_src, away_src in KNOCKOUT_BRACKET.values():
        assert placeholder_label(home_src)
        assert placeholder_label(away_src)


# ---------------------------------------------------------------------------
# MatchOutcome winner / loser
# ---------------------------------------------------------------------------


def test_match_outcome_home_win() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    o = MatchOutcome(home_team_id=h, away_team_id=a, home_score=2, away_score=1)
    assert o.winner_id == h
    assert o.loser_id == a


def test_match_outcome_away_win() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    o = MatchOutcome(home_team_id=h, away_team_id=a, home_score=0, away_score=3)
    assert o.winner_id == a
    assert o.loser_id == h


def test_match_outcome_draw_decided_on_penalties() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    o = MatchOutcome(
        home_team_id=h, away_team_id=a, home_score=1, away_score=1, penalty_winner_id=a
    )
    assert o.winner_id == a
    assert o.loser_id == h


def test_match_outcome_draw_without_penalty_winner_is_unresolved() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    o = MatchOutcome(home_team_id=h, away_team_id=a, home_score=1, away_score=1)
    assert o.winner_id is None
    assert o.loser_id is None


def test_match_outcome_without_scores_is_unresolved() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    o = MatchOutcome(home_team_id=h, away_team_id=a, home_score=None, away_score=None)
    assert o.winner_id is None
    assert o.loser_id is None


# ---------------------------------------------------------------------------
# resolve_source
# ---------------------------------------------------------------------------


def test_resolve_source_group_winner_and_runner_up() -> None:
    groups = _twelve_complete_groups()
    thirds = rank_third_place_teams(groups)
    assert resolve_source("winner_group_a", groups, thirds, {}) == _tid(groups["A"][0])
    assert resolve_source("runner_up_group_c", groups, thirds, {}) == _tid(groups["C"][1])


def test_resolve_source_group_unresolved_until_group_complete() -> None:
    groups = _twelve_complete_groups()
    groups["A"][3] = _standing(position=4, code="A4", points=0, played=2)  # A not finished
    assert resolve_source("winner_group_a", groups, [], {}) is None
    # Other finished groups still resolve.
    assert resolve_source("winner_group_b", groups, [], {}) == _tid(groups["B"][0])


def test_resolve_source_best_third_uses_ranked_list() -> None:
    groups = _twelve_complete_groups()
    thirds = rank_third_place_teams(groups)
    assert resolve_source("best_third_1", groups, thirds, {}) == _tid(thirds[0])
    assert resolve_source("best_third_8", groups, thirds, {}) == _tid(thirds[7])
    # No 9th best third exists.
    assert resolve_source("best_third_9", groups, thirds, {}) is None
    # Empty ranked list (groups not all complete) → unresolved.
    assert resolve_source("best_third_1", groups, [], {}) is None


def test_resolve_source_match_winner_and_loser() -> None:
    h, a = uuid.uuid4(), uuid.uuid4()
    outcomes = {73: MatchOutcome(home_team_id=h, away_team_id=a, home_score=3, away_score=0)}
    assert resolve_source("winner_match_73", {}, [], outcomes) == h
    assert resolve_source("loser_match_73", {}, [], outcomes) == a
    # Match not yet settled.
    assert resolve_source("winner_match_99", {}, [], outcomes) is None


def test_resolve_source_rejects_unknown_ref() -> None:
    with pytest.raises(ValueError, match="Unknown source ref"):
        resolve_source("nonsense", {}, [], {})


# ---------------------------------------------------------------------------
# all_groups_complete
# ---------------------------------------------------------------------------


def test_all_groups_complete_true_when_every_team_played_three() -> None:
    assert all_groups_complete(_twelve_complete_groups()) is True


def test_all_groups_complete_false_when_a_team_has_a_match_left() -> None:
    groups = _twelve_complete_groups()
    groups["F"][0] = _standing(position=1, code="F1", points=9, played=2)
    assert all_groups_complete(groups) is False


def test_all_groups_complete_false_with_missing_groups() -> None:
    groups = _twelve_complete_groups()
    del groups["L"]
    assert all_groups_complete(groups) is False


# ---------------------------------------------------------------------------
# resolve_bracket — R32 from standings (best-third mapping)
# ---------------------------------------------------------------------------


def test_resolve_bracket_empty_state_resolves_nothing() -> None:
    resolved = resolve_bracket({}, {})
    assert len(resolved) == 32
    assert all(not r.fully_resolved for r in resolved.values())


def test_resolve_bracket_r32_maps_winners_runners_and_best_thirds() -> None:
    groups = _twelve_complete_groups()
    ranked_thirds = rank_third_place_teams(groups)
    resolved = resolve_bracket(groups, {})

    # Matches 73..80: group winner A..H (home) vs best thirds #1..#8 (away).
    for i in range(8):
        letter = _LETTERS[i]
        assert resolved[73 + i].home_team_id == _tid(groups[letter][0])
        assert resolved[73 + i].away_team_id == _tid(ranked_thirds[i])

    # Match 81: winner I vs runner-up A.
    assert resolved[81].home_team_id == _tid(groups["I"][0])
    assert resolved[81].away_team_id == _tid(groups["A"][1])
    # Match 88: runner-up K vs runner-up L.
    assert resolved[88].home_team_id == _tid(groups["K"][1])
    assert resolved[88].away_team_id == _tid(groups["L"][1])

    # Every R32 match is fully resolved; later rounds are still unknown.
    assert all(resolved[n].fully_resolved for n in range(73, 89))
    assert all(not resolved[n].fully_resolved for n in range(89, 105))


def test_resolve_bracket_r32_unresolved_while_one_group_pending() -> None:
    groups = _twelve_complete_groups()
    groups["A"][0] = _standing(position=1, code="A1", points=9, played=2)
    resolved = resolve_bracket(groups, {})
    # Group A not final → its winner slot and ALL best-third slots stay unknown.
    assert resolved[73].home_team_id is None  # winner_group_a
    assert resolved[73].away_team_id is None  # best_third_1 (needs all groups)
    assert resolved[80].away_team_id is None  # best_third_8
    # A fully-finished group unrelated to thirds still resolves its winner.
    assert resolved[88].home_team_id == _tid(groups["K"][1])


# ---------------------------------------------------------------------------
# resolve_bracket — round-to-round advancement
# ---------------------------------------------------------------------------


def _home_wins(resolved: dict[int, object], match_numbers: range) -> dict[int, MatchOutcome]:
    """Build outcomes where the home team wins every given match."""
    outcomes: dict[int, MatchOutcome] = {}
    for n in match_numbers:
        slots = resolved[n]
        outcomes[n] = MatchOutcome(
            home_team_id=slots.home_team_id,  # type: ignore[attr-defined]
            away_team_id=slots.away_team_id,  # type: ignore[attr-defined]
            home_score=1,
            away_score=0,
        )
    return outcomes


def test_resolve_bracket_cascades_through_every_round() -> None:
    groups = _twelve_complete_groups()

    # R32 resolved from standings; home wins all 16.
    r32 = resolve_bracket(groups, {})
    outcomes = _home_wins(r32, range(73, 89))

    # R16 now resolves from R32 winners.
    r16 = resolve_bracket(groups, outcomes)
    assert r16[89].home_team_id == r32[73].home_team_id
    assert r16[89].away_team_id == r32[74].home_team_id
    assert r16[96].home_team_id == r32[87].home_team_id
    assert all(r16[n].fully_resolved for n in range(89, 97))
    outcomes |= _home_wins(r16, range(89, 97))

    # QF.
    qf = resolve_bracket(groups, outcomes)
    assert qf[97].home_team_id == r16[89].home_team_id
    assert qf[97].away_team_id == r16[90].home_team_id
    assert all(qf[n].fully_resolved for n in range(97, 101))
    outcomes |= _home_wins(qf, range(97, 101))

    # SF.
    sf = resolve_bracket(groups, outcomes)
    assert sf[101].home_team_id == qf[97].home_team_id
    assert sf[101].away_team_id == qf[98].home_team_id
    assert sf[102].home_team_id == qf[99].home_team_id
    assert sf[102].away_team_id == qf[100].home_team_id
    outcomes |= _home_wins(sf, range(101, 103))

    # Final + third-place play-off.
    final_round = resolve_bracket(groups, outcomes)
    # Final = the two SF winners (home teams won).
    assert final_round[104].home_team_id == sf[101].home_team_id
    assert final_round[104].away_team_id == sf[102].home_team_id
    # Third place = the two SF losers (the away teams).
    assert final_round[103].home_team_id == sf[101].away_team_id
    assert final_round[103].away_team_id == sf[102].away_team_id
    assert final_round[103].fully_resolved
    assert final_round[104].fully_resolved


def test_resolve_bracket_penalty_winner_advances() -> None:
    groups = _twelve_complete_groups()
    r32 = resolve_bracket(groups, {})
    # Match 73 drawn, decided on penalties for the away team.
    away = r32[73].away_team_id
    outcomes = {
        73: MatchOutcome(
            home_team_id=r32[73].home_team_id,
            away_team_id=away,
            home_score=1,
            away_score=1,
            penalty_winner_id=away,
        ),
        74: MatchOutcome(
            home_team_id=r32[74].home_team_id,
            away_team_id=r32[74].away_team_id,
            home_score=2,
            away_score=0,
        ),
    }
    r16 = resolve_bracket(groups, outcomes)
    assert r16[89].home_team_id == away  # penalty winner advanced
    assert r16[89].away_team_id == r32[74].home_team_id
