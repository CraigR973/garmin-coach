"""Tests for Phase 1.4 seed data — no DB connection required.

Validates that the GROUPS, TEAMS, and MATCHES constants in src.seed are
complete and internally consistent before any database is touched.
"""

from collections import Counter
from datetime import datetime

from src.seed import GROUPS, KNOCKOUT_MATCHES, MATCHES, TEAMS
from src.services.knockout_progression import placeholder_label, stage_for_match_number


def test_twelve_groups() -> None:
    assert GROUPS == list("ABCDEFGHIJKL")


def test_forty_eight_teams() -> None:
    assert len(TEAMS) == 48


def test_four_teams_per_group() -> None:
    counts = Counter(t["group"] for t in TEAMS)
    for g in GROUPS:
        assert counts[g] == 4, f"Group {g} has {counts[g]} teams, expected 4"


def test_all_team_codes_unique() -> None:
    codes = [t["code"] for t in TEAMS]
    assert len(codes) == len(set(codes)), "Duplicate team codes found"


def test_all_team_names_unique() -> None:
    names = [t["name"] for t in TEAMS]
    assert len(names) == len(set(names)), "Duplicate team names found"


def test_each_team_has_required_fields() -> None:
    for team in TEAMS:
        assert team["code"], f"Missing code for {team['name']}"
        assert team["flag_emoji"], f"Missing flag_emoji for {team['name']}"
        assert team["group"] in GROUPS, f"Invalid group {team['group']} for {team['name']}"
        assert isinstance(team["is_host"], bool)


def test_exactly_three_host_teams() -> None:
    hosts = [t for t in TEAMS if t["is_host"]]
    assert len(hosts) == 3
    host_codes = {t["code"] for t in hosts}
    assert host_codes == {"MEX", "CAN", "USA"}


def test_seventy_two_matches() -> None:
    assert len(MATCHES) == 72


def test_match_numbers_sequential() -> None:
    numbers = sorted(m["match_number"] for m in MATCHES)
    assert numbers == list(range(1, 73))


def test_six_matches_per_group() -> None:
    counts = Counter(m["group"] for m in MATCHES)
    for g in GROUPS:
        assert counts[g] == 6, f"Group {g} has {counts[g]} matches, expected 6"


def test_each_match_has_required_fields() -> None:
    team_codes = {t["code"] for t in TEAMS}
    for m in MATCHES:
        assert m["group"] in GROUPS, f"Match {m['match_number']}: invalid group {m['group']}"
        assert m["home"] in team_codes, f"Match {m['match_number']}: unknown home {m['home']}"
        assert m["away"] in team_codes, f"Match {m['match_number']}: unknown away {m['away']}"
        assert m["home"] != m["away"], f"Match {m['match_number']}: home == away"
        assert isinstance(m["kickoff_utc"], datetime)
        assert m["venue"], f"Match {m['match_number']}: missing venue"


def test_home_and_away_teams_in_correct_group() -> None:
    team_group = {t["code"]: t["group"] for t in TEAMS}
    for m in MATCHES:
        assert team_group[m["home"]] == m["group"], (
            f"Match {m['match_number']}: home {m['home']} not in group {m['group']}"
        )
        assert team_group[m["away"]] == m["group"], (
            f"Match {m['match_number']}: away {m['away']} not in group {m['group']}"
        )


def test_each_team_plays_three_matches() -> None:
    play_counts: Counter[str] = Counter()
    for m in MATCHES:
        play_counts[m["home"]] += 1
        play_counts[m["away"]] += 1
    for team in TEAMS:
        assert play_counts[team["code"]] == 3, (
            f"{team['code']} plays {play_counts[team['code']]} matches, expected 3"
        )


def test_each_pair_plays_exactly_once() -> None:
    pairs: set[frozenset[str]] = set()
    for m in MATCHES:
        pair = frozenset([m["home"], m["away"]])
        assert pair not in pairs, (
            f"Duplicate fixture: {m['home']} vs {m['away']} in match {m['match_number']}"
        )
        pairs.add(pair)


def test_group_stage_window() -> None:
    kickoffs = [m["kickoff_utc"] for m in MATCHES]
    assert min(kickoffs) >= datetime(2026, 6, 11)
    assert max(kickoffs) <= datetime(2026, 6, 29)


def test_matchday3_simultaneous_within_group() -> None:
    # Last 24 matches (numbers 49-72) form 12 simultaneous pairs, one per group.
    # Each pair has identical kickoff_utc.
    final_matches = [m for m in MATCHES if m["match_number"] >= 49]
    assert len(final_matches) == 24
    by_group: dict[str, list[dict]] = {}
    for m in final_matches:
        by_group.setdefault(m["group"], []).append(m)
    for g, ms in by_group.items():
        assert len(ms) == 2, f"Group {g} has {len(ms)} final matchday games, expected 2"
        t0, t1 = ms[0]["kickoff_utc"], ms[1]["kickoff_utc"]
        assert t0 == t1, f"Group {g} final matches not simultaneous: {t0} vs {t1}"


# ---------------------------------------------------------------------------
# Knockout skeleton (U13.1) — 32 seeded matches, teams TBD
# ---------------------------------------------------------------------------


def test_thirty_two_knockout_matches() -> None:
    assert len(KNOCKOUT_MATCHES) == 32


def test_full_104_match_calendar() -> None:
    assert len(MATCHES) + len(KNOCKOUT_MATCHES) == 104


def test_knockout_match_numbers_sequential_73_to_104() -> None:
    numbers = sorted(m["match_number"] for m in KNOCKOUT_MATCHES)
    assert numbers == list(range(73, 105))


def test_knockout_round_counts() -> None:
    counts = Counter(m["stage"] for m in KNOCKOUT_MATCHES)
    assert counts == {
        "r32": 16,
        "r16": 8,
        "qf": 4,
        "sf": 2,
        "third_place": 1,
        "final": 1,
    }


def test_each_knockout_match_has_sources_placeholders_and_schedule() -> None:
    ko_venues = {m["venue"] for m in MATCHES}  # KO reuses the group venue pool
    for m in KNOCKOUT_MATCHES:
        mn = m["match_number"]
        assert m["stage"] == stage_for_match_number(mn).value
        assert m["home_source"], f"Match {mn}: missing home_source"
        assert m["away_source"], f"Match {mn}: missing away_source"
        assert m["home_source"] != m["away_source"], f"Match {mn}: home_source == away_source"
        # Display placeholder is derived from the source ref.
        assert m["home_placeholder"] == placeholder_label(m["home_source"])
        assert m["away_placeholder"] == placeholder_label(m["away_source"])
        assert len(m["home_placeholder"]) <= 50 and len(m["away_placeholder"]) <= 50
        assert len(m["home_source"]) <= 32 and len(m["away_source"]) <= 32
        assert isinstance(m["kickoff_utc"], datetime)
        assert m["venue"] in ko_venues, f"Match {mn}: venue {m['venue']!r} not a real 2026 venue"


def test_knockout_window_follows_group_stage() -> None:
    kickoffs = [m["kickoff_utc"] for m in KNOCKOUT_MATCHES]
    # KO starts as the group stage ends (28 Jun) and finishes with the final.
    assert min(kickoffs) >= datetime(2026, 6, 28)
    assert max(kickoffs) <= datetime(2026, 7, 19, 23, 59)
    # The final (104) is the very last match on the calendar.
    final = next(m for m in KNOCKOUT_MATCHES if m["match_number"] == 104)
    assert final["kickoff_utc"] == max(kickoffs)
