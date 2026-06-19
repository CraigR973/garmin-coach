#!/usr/bin/env python3
# ruff: noqa: E501
"""Staging smoke test for the World Cup 2026 prediction league.

Exercises the high-risk paths from the R1–R7 pre-launch review end-to-end
against the deployed staging API:

  1. Creates 3 test players via real invites (R1.4 validators exercised)
  2. Each player submits group-stage predictions + 3 specials
  3. Admin enters results for 3 matches  (R5/R6 audit paths)
  4. Verifies leaderboard reflects scoring
  5. **Override** a previously-scored result (R2.1/R2.2 — the trigger-without-WHEN path)
  6. **Cancel** a match that had predictions  (R2.4 — points must zero out)
  7. **Award specials**  (R2.3 — the silent leaderboard-stale bug at tournament end)
  8. Verifies the leaderboard after each mutation
  9. Cleans up unless --keep-data is passed

This script is purely API-driven, but two of the steps need a brief SQL
prep / reset which the human operator (or the Claude Code MCP) runs between
phases. The script pauses with a clear prompt at each handoff. The SQL to
run is printed inline so you can copy/paste it into the Supabase MCP.

USAGE
  ADMIN_PIN=xxxx /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python \\
    apps/api/scripts/staging_smoke.py [--keep-data]

REQUIRED ENV
  ADMIN_PIN   — staging admin PIN for the 'Craig' profile

OPTIONAL ENV
  SMOKE_SUFFIX — string appended to test player names (default: random 4 hex chars).
                 Pass an explicit value if a previous run left state behind so the
                 new run uses the same names and you can finish the cleanup.
  STAGING_BASE — override the staging API URL (default: deployed staging).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

STATE_FILE = Path("/tmp/wc2026_staging_smoke_state.json")


BASE = os.environ.get("STAGING_BASE", "https://wc2026-api-production-333a.up.railway.app/api/v1")
ADMIN_NAME = "Craig"
RUN_SUFFIX = os.environ.get("SMOKE_SUFFIX", secrets.token_hex(2))
PLAYER_NAMES = [f"smoke_{n}_{RUN_SUFFIX}" for n in ("alice", "bob", "charlie")]
PLAYER_PINS = ["1234", "2345", "3456"]
TIMEOUT = 15.0

# Fixed prediction matrices — alice predicts the "exact" score for match 1,
# bob predicts the right result with wrong score, charlie misses entirely.
# Lets us assert specific point totals deterministically after results are entered.
#
#   matches[0]: alice=2-1, bob=1-0, charlie=0-2  | actual will be 2-1
#   matches[1]: alice=1-1, bob=2-2, charlie=3-0  | actual will be 1-1
#   matches[2]: alice=0-0, bob=1-0, charlie=0-3  | actual will be 0-1
#   matches[3..5] no result entered (left scheduled)
PREDICTIONS: list[list[tuple[int, int]]] = [
    [(2, 1), (1, 0), (0, 2)],  # match 0
    [(1, 1), (2, 2), (3, 0)],  # match 1
    [(0, 0), (1, 0), (0, 3)],  # match 2
    [(0, 0), (1, 1), (2, 2)],  # match 3 (no result entered)
    [(1, 0), (1, 1), (0, 0)],  # match 4 (no result entered)
    [(2, 0), (1, 2), (0, 1)],  # match 5 (no result entered)
]

# Actual results we'll enter for matches[0..2]
ACTUAL_RESULTS = [(2, 1), (1, 1), (0, 1)]

# What the override on matches[0] will change the score to
OVERRIDE_RESULT = (3, 0)


# --------------------------------------------------------------------------- helpers


def fail(msg: str, *, code: int = 1) -> None:
    print(f"  \033[31m✗ FAIL: {msg}\033[0m", file=sys.stderr)
    sys.exit(code)


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def info(msg: str) -> None:
    print(f"  · {msg}")


def section(name: str) -> None:
    print(f"\n\033[1m=== {name} ===\033[0m")


def print_human_step(title: str, body: str) -> None:
    print()
    print("\033[33m" + "-" * 72)
    print(f"HUMAN STEP NEEDED — {title}")
    print("-" * 72)
    print(body)
    print("-" * 72 + "\033[0m")


def post(client: httpx.Client, path: str, *, token: str | None = None, json: Any = None) -> Any:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.post(path, headers=headers, json=json)
    if r.status_code >= 400:
        fail(f"POST {path} -> {r.status_code}: {r.text}")
    if r.status_code == 204:
        return None
    return r.json()


def put(client: httpx.Client, path: str, *, token: str | None = None, json: Any = None) -> Any:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.put(path, headers=headers, json=json)
    if r.status_code >= 400:
        fail(f"PUT {path} -> {r.status_code}: {r.text}")
    if r.status_code == 204:
        return None
    return r.json()


def get(client: httpx.Client, path: str, *, token: str | None = None) -> Any:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.get(path, headers=headers)
    if r.status_code >= 400:
        fail(f"GET {path} -> {r.status_code}: {r.text}")
    return r.json()


def delete(client: httpx.Client, path: str, *, token: str | None = None) -> None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.delete(path, headers=headers)
    if r.status_code not in (200, 204, 404):
        fail(f"DELETE {path} -> {r.status_code}: {r.text}")


# --------------------------------------------------------------------------- state


@dataclass
class State:
    admin_token: str = ""
    test_match_ids: list[str] = field(default_factory=list)
    test_match_numbers: list[int] = field(default_factory=list)
    test_match_home_team_ids: list[str] = field(default_factory=list)
    test_match_away_team_ids: list[str] = field(default_factory=list)
    test_match_kickoffs: list[str] = field(default_factory=list)
    player_names: list[str] = field(default_factory=list)  # persisted so suffix is stable
    player_ids: list[str] = field(default_factory=list)
    player_tokens: list[str] = field(default_factory=list)
    team_a: str = ""  # used for tournament_winner specials

    def save(self) -> None:
        STATE_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> State:
        if not STATE_FILE.exists():
            fail(f"no state file at {STATE_FILE} — run `setup` first")
        return cls(**json.loads(STATE_FILE.read_text()))


# --------------------------------------------------------------------------- phases


def phase_login_admin(client: httpx.Client, state: State, admin_pin: str) -> None:
    section("Admin login")
    data = post(
        client,
        "/auth/login",
        json={"display_name": ADMIN_NAME, "pin": admin_pin},
    )
    state.admin_token = data["access_token"]
    ok(f"Logged in as {ADMIN_NAME} (id={data['player']['id'][:8]}…)")


def phase_pick_matches(client: httpx.Client, state: State) -> None:
    section("Pick 6 group-stage matches to test against")
    matches = get(client, "/matches", token=state.admin_token)
    if isinstance(matches, dict):
        matches = matches.get("data") or matches.get("matches") or []
    # Sort by match_number, take the first 6 scheduled group matches.
    scheduled = [m for m in matches if m.get("stage") == "group" and m.get("status") == "scheduled"]
    scheduled.sort(key=lambda m: m["match_number"])
    if len(scheduled) < 6:
        fail(f"need 6 scheduled group matches; found {len(scheduled)}")
    for m in scheduled[:6]:
        state.test_match_ids.append(m["id"])
        state.test_match_numbers.append(m["match_number"])
        # The /matches endpoint returns home_team / away_team as nested objects {id, name, ...}
        state.test_match_home_team_ids.append(m["home_team"]["id"])
        state.test_match_away_team_ids.append(m["away_team"]["id"])
        state.test_match_kickoffs.append(m["kickoff_utc"])
    state.team_a = state.test_match_home_team_ids[0]
    ok(f"Selected matches {state.test_match_numbers}")


def phase_create_players(client: httpx.Client, state: State) -> None:
    section("Create 3 test players via invites")
    state.player_names = list(PLAYER_NAMES)
    for name, pin in zip(state.player_names, PLAYER_PINS):
        invite = post(
            client,
            "/admin/invites",
            token=state.admin_token,
            json={"display_name_hint": name, "expires_in_days": 1},
        )
        joined = post(
            client,
            "/auth/join",
            json={
                "token": invite["token"],
                "display_name": name,
                "pin": pin,
                "timezone": "UTC",
            },
        )
        state.player_ids.append(joined["player"]["id"])
        state.player_tokens.append(joined["access_token"])
        ok(f"Created '{name}' (id={joined['player']['id'][:8]}…)")


def phase_submit_predictions(client: httpx.Client, state: State) -> None:
    section("Submit group-stage predictions")
    for match_idx, match_id in enumerate(state.test_match_ids):
        per_player = PREDICTIONS[match_idx]
        for player_idx, (home, away) in enumerate(per_player):
            put(
                client,
                f"/predictions/{match_id}",
                token=state.player_tokens[player_idx],
                json={"predicted_home": home, "predicted_away": away},
            )
        ok(f"Match #{state.test_match_numbers[match_idx]}: all 3 predictions submitted")


def phase_submit_specials(client: httpx.Client, state: State) -> None:
    section("Submit special predictions")
    # All three players pick the same tournament winner (team_a) so we can assert
    # that after award, every player has special_points >= 20.
    for player_idx, token in enumerate(state.player_tokens):
        put(
            client,
            "/specials/tournament_winner",
            token=token,
            json={"predicted_team_id": state.team_a},
        )
        put(
            client,
            "/specials/top_scoring_team",
            token=token,
            json={"predicted_team_id": state.team_a},
        )
        put(
            client,
            "/specials/golden_boot",
            token=token,
            json={"predicted_player_name": f"Test Striker {player_idx}"},
        )
    ok("All 3 players submitted tournament_winner, top_scoring_team, golden_boot")


def phase_print_sql_lock_matches(state: State) -> None:
    """Print SQL to lock the first 3 test matches by shifting their kickoff to the past."""
    ids_to_lock = state.test_match_ids[:3]
    quoted = ", ".join(f"'{i}'" for i in ids_to_lock)
    sql = textwrap.dedent(
        f"""\
        UPDATE matches
           SET kickoff_utc = (now() at time zone 'utc') - interval '1 minute',
               status = 'locked',
               locked_at = (now() at time zone 'utc') - interval '1 minute'
         WHERE id IN ({quoted});
        """
    )
    print_human_step(
        "Lock the 3 test matches via Supabase MCP",
        f"Run this SQL against the staging Supabase project, then re-invoke the script "
        f"with the `run` subcommand:\n\n{sql}",
    )


def phase_enter_results(client: httpx.Client, state: State) -> None:
    section("Admin enters results for matches 0..2 (triggers scoring + leaderboard)")
    for i in range(3):
        home, away = ACTUAL_RESULTS[i]
        post(
            client,
            f"/admin/results/{state.test_match_ids[i]}",
            token=state.admin_token,
            json={
                "actual_home_score": home,
                "actual_away_score": away,
                "extra_time": False,
                "penalties": False,
                "penalty_winner_id": None,
            },
        )
        ok(f"Match #{state.test_match_numbers[i]}: result entered {home}-{away}")


def phase_verify_scoring(client: httpx.Client, state: State) -> None:
    section("Verify leaderboard after initial scoring")
    lb = _get_leaderboard(client, state)
    expected = {
        # alice predicted (2,1),(1,1),(0,0) — actual (2,1),(1,1),(0,1):
        #   match 1: exact 5 + result 3 + total-goals 2 = 10
        #   match 2: exact 5 + result 3 + total-goals 2 = 10
        #   match 3: alice 0-0 (draw, total 0) vs actual 0-1 (away win, total 1) → 0
        #   alice match_total = 10 + 10 + 0 = 20
        state.player_names[0]: 20,
        # bob predicted (1,0),(2,2),(1,0) — actual (2,1),(1,1),(0,1):
        #   match 1: bob 1-0 vs 2-1: result match (both home wins) → 3; total 1!=3 → 0; = 3
        #   match 2: bob 2-2 vs 1-1: result match (draw) → 3; total 4!=2 → 0; = 3
        #   match 3: bob 1-0 vs 0-1: result mismatch → 0; total 1==1 → 2; = 2
        #   bob match_total = 3 + 3 + 2 = 8
        state.player_names[1]: 8,
        # charlie predicted (0,2),(3,0),(0,3) — actual (2,1),(1,1),(0,1):
        #   match 1: 0-2 vs 2-1: result mismatch → 0; total 2!=3 → 0; = 0
        #   match 2: 3-0 vs 1-1: result mismatch → 0; total 3!=2 → 0; = 0
        #   match 3: 0-3 vs 0-1: result match (both away wins) → 3; total 3!=1 → 0; = 3
        #   charlie match_total = 0 + 0 + 3 = 3
        state.player_names[2]: 3,
    }
    for name, exp in expected.items():
        actual = lb.get(name)
        if actual is None:
            fail(f"player '{name}' missing from leaderboard")
        if actual["total_points"] != exp:
            fail(
                f"player '{name}': expected total_points={exp}, "
                f"got {actual['total_points']} (breakdown {actual})"
            )
        ok(f"{name}: total_points={exp} (match_points={actual['match_points']})")


def phase_override_match(client: httpx.Client, state: State) -> None:
    section("Override result on match 0 (R2.2 — trigger-without-WHEN path)")
    home, away = OVERRIDE_RESULT
    put(
        client,
        f"/admin/results/{state.test_match_ids[0]}",
        token=state.admin_token,
        json={
            "actual_home_score": home,
            "actual_away_score": away,
            "extra_time": False,
            "penalties": False,
            "penalty_winner_id": None,
        },
    )
    ok(f"Match #{state.test_match_numbers[0]} overridden to {home}-{away}")

    lb = _get_leaderboard(client, state)
    # New actual 3-0:
    #   alice 2-1: result match (both home wins) → 3; total 3==3 → 2; exact no → 0; subtotal 5 (was 10)
    #   bob 1-0: result match → 3; total 1 != 3 → 0; exact no → 0; subtotal 3 (was 3, unchanged)
    #   charlie 0-2: result mismatch (loss vs win) → 0; total 2 != 3 → 0; exact no → 0; subtotal 0 (was 0)
    expected = {
        state.player_names[0]: 20 - 10 + 5,  # 15
        state.player_names[1]: 8,  # unchanged
        state.player_names[2]: 3,  # unchanged
    }
    for name, exp in expected.items():
        actual = lb[name]["total_points"]
        if actual != exp:
            fail(f"after override, {name}: expected {exp}, got {actual}")
        ok(f"{name}: total_points={exp}")


def phase_cancel_match(client: httpx.Client, state: State) -> None:
    section("Cancel match 2 (R2.4 — points should zero out)")
    # Match 2 was 0-1 actual. Charlie predicted 0-3 (result match, 3pts), so we expect
    # her total to drop by 3. Alice and bob have 0pts from this match anyway (alice exact
    # on the others; bob got total-goals 2).
    # Wait — bob got match 3 → 0,0,2 = 2 pts. Cancelling removes those 2.
    # Alice: 0 pts from match 2 → no change.
    post(
        client,
        f"/admin/matches/{state.test_match_ids[2]}/cancel",
        token=state.admin_token,
        json={},
    )
    ok(f"Match #{state.test_match_numbers[2]} cancelled")

    lb = _get_leaderboard(client, state)
    expected = {
        state.player_names[0]: 15,  # unchanged
        state.player_names[1]: 8 - 2,  # 6
        state.player_names[2]: 3 - 3,  # 0
    }
    for name, exp in expected.items():
        actual = lb[name]["total_points"]
        if actual != exp:
            fail(f"after cancel, {name}: expected {exp}, got {actual}")
        ok(f"{name}: total_points={exp}")


def phase_award_specials(client: httpx.Client, state: State) -> None:
    section("Award tournament_winner special (R2.3 — leaderboard must update)")
    # All 3 players picked team_a as tournament_winner. Award it.
    post(
        client,
        "/admin/specials/award",
        token=state.admin_token,
        json={"prediction_type": "tournament_winner", "winner_team_id": state.team_a},
    )
    ok("Awarded tournament_winner")

    lb = _get_leaderboard(client, state)
    # Tournament winner = 20 pts.
    expected = {
        state.player_names[0]: 15 + 20,  # 35
        state.player_names[1]: 6 + 20,  # 26
        state.player_names[2]: 0 + 20,  # 20
    }
    for name, exp in expected.items():
        entry = lb[name]
        if entry["special_points"] != 20:
            fail(f"{name}: expected special_points=20, got {entry['special_points']}")
        if entry["total_points"] != exp:
            fail(f"{name}: expected total_points={exp}, got {entry['total_points']}")
        ok(f"{name}: total_points={exp}, special_points=20")


def phase_print_sql_reset_matches(state: State) -> None:
    section("Cleanup prep — print SQL to reset match state")
    ids = state.test_match_ids[:3]
    sql_lines: list[str] = []
    for i, mid in enumerate(ids):
        original = state.test_match_kickoffs[i].rstrip("Z")
        sql_lines.append(
            f"UPDATE matches SET kickoff_utc='{original}', status='scheduled', "
            f"locked_at=NULL, actual_home_score=NULL, actual_away_score=NULL, "
            f"result_source=NULL, result_entered_by=NULL, result_entered_at=NULL, "
            f"extra_time=false, penalties=false, penalty_winner_id=NULL "
            f"WHERE id='{mid}';"
        )
    quoted = ", ".join(f"'{i}'" for i in state.test_match_ids)
    sql_lines.append(
        f"DELETE FROM predictions WHERE match_id IN ({quoted}) "
        f"AND player_id IN (SELECT id FROM profiles WHERE display_name LIKE 'smoke_%');"
    )
    sql_lines.append(
        "DELETE FROM special_predictions "
        "WHERE player_id IN (SELECT id FROM profiles WHERE display_name LIKE 'smoke_%');"
    )
    sql_lines.append(
        "DELETE FROM leaderboard_snapshots "
        "WHERE player_id IN (SELECT id FROM profiles WHERE display_name LIKE 'smoke_%');"
    )
    sql = "\n".join(sql_lines)
    print_human_step(
        "Reset match state + remove test data via Supabase MCP",
        f"Run this SQL against staging, then re-invoke with `teardown`:\n\n{sql}",
    )


def phase_teardown_players(client: httpx.Client, state: State) -> None:
    section("Soft-delete test players")
    for name, pid in zip(state.player_names, state.player_ids):
        delete(client, f"/admin/players/{pid}", token=state.admin_token)
        ok(f"Deleted '{name}'")


# --------------------------------------------------------------------------- leaderboard helper


def _get_leaderboard(client: httpx.Client, state: State) -> dict[str, dict[str, int]]:
    """Return a {display_name: {total_points, match_points, knockout_winner_points, special_points}}
    map for the test players."""
    rows = get(client, "/leaderboard", token=state.admin_token)
    names = set(state.player_names)
    by_name: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["player_name"] in names:
            by_name[row["player_name"]] = {
                "total_points": row["total_points"],
                "match_points": row["match_points"],
                "knockout_winner_points": row["knockout_winner_points"],
                "special_points": row["special_points"],
            }
    return by_name


# --------------------------------------------------------------------------- main


def cmd_setup(args: argparse.Namespace) -> None:
    admin_pin = os.environ.get("ADMIN_PIN") or fail("ADMIN_PIN env var required")
    print("\033[1m=== WC2026 staging smoke — SETUP ===\033[0m")
    print(f"  base       : {BASE}")
    print(f"  run suffix : {RUN_SUFFIX}")
    print(f"  players    : {', '.join(PLAYER_NAMES)}")
    state = State()
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        phase_login_admin(client, state, admin_pin)
        phase_pick_matches(client, state)
        phase_create_players(client, state)
        phase_submit_predictions(client, state)
        phase_submit_specials(client, state)
    state.save()
    ok(f"State persisted to {STATE_FILE}")
    phase_print_sql_lock_matches(state)
    print(f"\nNext: run the printed SQL via the Supabase MCP, then invoke `{sys.argv[0]} run`.")


def cmd_run(args: argparse.Namespace) -> None:
    print("\033[1m=== WC2026 staging smoke — RUN ===\033[0m")
    state = State.load()
    # Re-login as admin since the access token in state may be near-expiry (~24 h
    # TTL but no harm in refreshing for a multi-phase script).
    admin_pin = os.environ.get("ADMIN_PIN") or fail("ADMIN_PIN env var required")
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        phase_login_admin(client, state, admin_pin)
        phase_enter_results(client, state)
        phase_verify_scoring(client, state)
        phase_override_match(client, state)
        phase_cancel_match(client, state)
        phase_award_specials(client, state)
    state.save()  # token may have been refreshed
    section("ALL ASSERTIONS PASSED ✓")
    if args.keep_data:
        print(
            f"\n  --keep-data set; {len(state.player_ids)} test players and 3 modified "
            f"matches remain. Re-invoke with `teardown` (and SMOKE_SUFFIX={RUN_SUFFIX}) "
            f"to clean up."
        )
    else:
        phase_print_sql_reset_matches(state)
        print(
            f"\nNext: run the printed SQL via the Supabase MCP, then invoke "
            f"`{sys.argv[0]} teardown`."
        )


def cmd_teardown(args: argparse.Namespace) -> None:
    print("\033[1m=== WC2026 staging smoke — TEARDOWN ===\033[0m")
    state = State.load()
    admin_pin = os.environ.get("ADMIN_PIN") or fail("ADMIN_PIN env var required")
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        phase_login_admin(client, state, admin_pin)
        phase_teardown_players(client, state)
    STATE_FILE.unlink(missing_ok=True)
    section("Teardown complete ✓")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="phase 1: create players, submit predictions/specials")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run", help="phase 2: enter results, override, cancel, award; verify")
    p_run.add_argument(
        "--keep-data",
        action="store_true",
        help="Skip the reset-SQL prompt — leave test data in place for inspection.",
    )
    p_run.set_defaults(func=cmd_run)

    p_td = sub.add_parser("teardown", help="phase 3: soft-delete test players")
    p_td.set_defaults(func=cmd_teardown)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
