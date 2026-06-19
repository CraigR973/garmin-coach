# Code-Quality Audit — World Cup 2026 Prediction League

Final pre-production review. Read-only audit; no source modified.

- Date: 2026-06-08
- Scope: scoring (shared TS + Postgres trigger + backend), match-lock & auto result-fetch scheduler, knockout bracket creation/progression, test coverage, type/lint health, general quality, deps.

---

## Analyzer results

| Analyzer | Result |
|---|---|
| `mypy src` (backend, 62 files) | **PASS** — no issues found |
| `ruff check src` | **PASS** — all checks passed |
| `ruff format --check src` | **PASS** — 62 files already formatted |
| Frontend `tsc --noEmit` | **PASS** — no errors |
| Backend `pytest` | **639 passed, 126 skipped** (DB-backed tests skip locally as designed), 29 warnings |
| `packages/shared` vitest (scoring) | **21 passed** |
| Frontend vitest (full suite) | **FLAKY** — passes in some runs, fails 3–4 tests in others under CPU load (see P1-1) |

Backend type/lint/format health is excellent: zero mypy, ruff, or format issues across the whole tree. Frontend typecheck is clean. The only analyzer concern is frontend test flakiness, detailed below.

---

## P0 — correctness bugs (mis-score / mis-advance / scheduler break)

### P0-1 — Auto result-fetch never resolves the next knockout round's bracket
**Severity: P0**
**Files:** `apps/api/src/services/result_sync.py:98` (`sync_results`), `:237` (`_apply_finished`); contrast `apps/api/src/routers/admin.py:766` (`_maybe_resync_knockout`) called only from `enter_result` (`:851`) and `override_result`.

The seeded knockout skeleton stores placeholder source-refs (`winner_match_73`, etc.) that must be resolved into real team ids by `sync_knockout_bracket()` (`apps/api/src/services/knockout_advancement.py:307`) after each result settles. That resync is wired into the **manual** admin result paths only. The **auto** path (`result_sync.sync_results` → `_apply_finished`) writes the score, fires the DB scoring trigger, and returns — it **never calls `sync_knockout_bracket`**. `grep` confirms the only caller in `src/` is `admin.py:777`.

During the tournament the expected happy path is auto-fetch from football-data.org. When an R32 match auto-completes, the feeding R16 match's `home_team_id`/`away_team_id` stay NULL (still placeholders), so:
- the R16 fixture shows TBD teams indefinitely (until an admin happens to manually enter/override some result, which triggers a full resync), and
- because `_load_ko_outcomes` derives a match's winner from `home_team_id`/`away_team_id`, an unresolved downstream match cannot be scored even after its own result arrives.

This is a tournament-breaking gap on the primary code path.

**Recommended action:** Call `sync_knockout_bracket(session)` inside `sync_results` after the commit when any completed match is a knockout stage (mirror `_maybe_resync_knockout`'s best-effort guard so a resolver failure never aborts the sync). Add a regression test in `test_result_sync.py` that auto-completes an R32 match and asserts the R16 placeholders resolve.

---

## P1 — fix before prod

### P1-1 — Flaky frontend test suite (tight 5s per-test timeout under load)
**Severity: P1**
**Files:** `apps/web/src/test/PredictionsPage.test.tsx` ("renders group tabs A and B after loading", "shows scheduled match inputs as editable"), `DashboardPage.test.tsx:488` ("keeps the compact league rows and preserves delta badges"), `PlayerProfilePage.test.tsx:335` ("includes link back to leagues hub").

Different tests fail across runs (one run failed 4, an isolated re-run failed a different 3; the full-suite background run passed all). The failures are `waitFor`/`findBy` timeouts and text-matcher misses, with whole-file durations of 18–26s and individual tests hitting the 5000ms default `testTimeout` (e.g. "group tabs" consistently runs ~8–10s). This is non-determinism driven by CPU contention from running many heavy suites concurrently, not logic regressions. It undermines the "green CI" signal and risks intermittent CI failures.

**Recommended action:** Raise `testTimeout` in `vitest.config`/`vite.config.ts` for the web app (e.g. 15000ms), and/or reduce vitest worker concurrency in CI. For the brittle text matchers ("Leagues", "↑2"), prefer role/testid queries over exact-text `getByText`. Re-run to confirm determinism.

### P1-2 — football-data 5xx and network errors are not retried; network errors bypass the failure counter
**Severity: P1**
**Files:** `apps/api/src/services/football_data.py:129` (`_get`), `:149` (5xx → immediate `FootballDataServerError`); `apps/api/src/services/result_sync.py:118` (only `FootballDataError` caught).

The retry/backoff loop in `_get` retries **only HTTP 429**. A single transient **5xx** raises `FootballDataServerError` immediately (confirmed by `test_500_raises_server_error`), aborting the entire 5-minute sync cycle. Worse, a transient **network error** (httpx `ConnectError`/`ReadTimeout`) is not an `FootballDataError`, so it is **not caught** in `sync_results` — it propagates out of the job, bypassing `_record_failure`/`_consecutive_failures` and the admin alert path. APScheduler will log it but the consecutive-failure alerting (the "3 strikes → notify admins" mechanism) never engages for the most common real-world failure modes.

**Recommended action:** Retry 5xx with the same backoff the 429 branch uses; wrap httpx transport exceptions (`httpx.TransportError`/`TimeoutException`) and re-raise as `FootballDataError` (or catch `FootballDataError | httpx.HTTPError` in `sync_results`) so all transient failures flow through `_record_failure`.

### P1-3 — Process-local in-memory state in scheduler jobs (lost on restart / wrong under >1 worker)
**Severity: P1**
**Files:** `apps/api/src/services/result_sync.py:76` (`_consecutive_failures`), `apps/api/src/services/notification_triggers.py:360` (`_pick_confirmed_match_player_ids`).

Two scheduler-driven dedup/counter states live as module globals:
- `_consecutive_failures` — resets to 0 on process restart, so the "3 consecutive failures → alert" threshold can be silently dodged by a restart between failures.
- `_pick_confirmed_match_player_ids` — an unbounded in-memory set used to suppress duplicate pick-confirmation notifications. On restart it is empty, so confirmations can re-send; it also grows for the tournament's lifetime and would double-fire under more than one process/worker.

Railway likely runs a single worker today, so impact is limited, but it is fragile for prod and breaks if the deployment ever scales horizontally or restarts mid-incident.

**Recommended action:** Persist the consecutive-failure counter and the pick-confirmation dedup set in the DB (e.g. an existing audit/notification table or a small `scheduler_state` row). At minimum, document the single-worker assumption in the runbook and the deploy config.

---

## P2 — refactor / cleanliness / nice-to-have

### P2-1 — Snapshot fan-out recomputes per-player sums via repeated correlated subqueries
**Severity: P2**
**Files:** `migrations/versions/026_tiebreak_cascade.py:58` (`_PLAYER_TOTALS`), mirrored in `apps/api/src/services/leaderboard.py:65`.

The `player_totals` subquery runs 10 correlated subqueries per profile (3 sums + a 4th re-summing all three for `total_points`, + 5 counts), then the trigger fan-out joins it to every league membership and re-evaluates the whole thing on every result entry. For ~15 players this is fine, but `total_points` needlessly re-sums predictions/knockout/specials a second time rather than adding the three already-computed columns. Pure cleanliness — no correctness impact.

**Recommended action:** Compute `total_points` as `match_points + knockout_winner_points + special_points` in an outer select instead of three more subqueries. Keep the trigger and the Python twin in sync (both files carry a "keep in sync" note).

### P2-2 — `scoreMatchPrediction` carries a now-unused `stage` parameter
**Severity: P2**
**File:** `packages/shared/src/scoring.ts:49` (`_stage` param), and the Postgres `calculate_match_points` (`migrations/versions/021_scoring_knockout_draws.py`) takes a `stage` arg it no longer reads.

Since U21, knockout 90-minute draws score identically to group draws, so `stage` is dead in the scoreline calculation (the comment at `scoring.ts:52` acknowledges this; the SQL function still declares the param for signature compatibility). Harmless but mildly misleading.

**Recommended action:** Leave the SQL signature (changing it churns the trigger), but consider a short comment on the SQL `stage` arg noting it is retained only for signature stability. No action strictly required.

### P2-3 — No scheduler-level test for `sync_results` registration/timezone behavior
**Severity: P2**
**Files:** `apps/api/tests/test_scheduler.py` (9 tests, all for `lock_due_matches`/backup/lifespan), `test_result_sync.py` (covers the service, not the job wiring).

`create_scheduler` registers `sync_results` on a 5-minute interval with `coalesce`/`max_instances=1` but there is no test asserting that job's registration (there is one for the 15s lock job at `test_scheduler.py:208`). The scheduler is correctly pinned to `timezone="UTC"` and all jobs use UTC, which is good; a small registration assertion would lock that in.

**Recommended action:** Add a test asserting the `sync_results` job exists with the expected interval and the cron jobs (`daily_backup` 03:00, `prune_leaderboard_snapshots` 04:00, `daily_prediction_digest` 09:00) are registered in UTC.

---

## Things checked and found healthy (no action)

- **Scoring math (TS + SQL) agree.** `packages/shared/src/scoring.ts` and `calculate_match_points` (mig 021) both use `sign(diff)` for result, total-goals equality for +2, exact for +5, max 10/match; NULL prediction → `no_prediction:true`, NULL actual → zeros. 21 shared scoring tests pass.
- **Knockout winner determination handles draws → penalties** consistently in the SQL trigger (mig 005/012/026), `MatchOutcome.winner_id` (knockout_progression.py:276), and the live projection (scoring.ts:80). A 90-min draw with no/invalid `penalty_winner_id` correctly yields no winner.
- **Trigger ↔ Python twin parity.** The `matches_score_results` trigger (mig 026) and `recompute_leaderboard_snapshot` (leaderboard.py) use the identical merit-cascade RANK (total → exact → result → goals → specials → KO-winner → manual override, NULLS LAST) and the same `_PLAYER_TOTALS` body. Verified in sync.
- **Bracket resolver is pure and idempotent.** `resolve_bracket` (knockout_progression.py:370) only fills slots, never clears; `sync_knockout_bracket` re-writes only on change. Third-place ranking applies FIFA tiebreakers with a deterministic `team_code` last resort.
- **`lock_due_matches` is correct and idempotent** — selects only `scheduled` non-deleted matches with `kickoff_utc <= now`, uses an injectable UTC clock, writes audit + notifications post-commit with per-item try/except.
- **Auto-sync idempotency & race safety** — `_sync_one_match` takes `SELECT ... FOR UPDATE`; `_apply_finished` short-circuits if `result_source is not None`, so it never clobbers a manual/override result. Kickoff drift preserves `original_kickoff_utc`.
- **Timezone handling** — all stored timestamps are naive-UTC; `_strip_tz` normalizes feed datetimes; viewer-local day bounds (leaderboard.py:356, notification_triggers.py:363) use `ZoneInfo` with a UTC fallback on bad IANA strings.
- **Leaderboard queries** — no N+1; `DISTINCT ON (player_id)` with `snapshot_at DESC, id DESC` to break same-transaction ties (backed by `ix_leaderboard_snapshots_league_player_time`); per-stage round leaderboard aggregates in Python over bounded member sets.
- **Exception handling** — broad `except` blocks are all intentional and annotated (`# noqa: BLE001` where used), each logs with `log.exception`/`log.warning`; none silently swallow. No bare `except:`.
- **Migrations** — all 26 have non-stub `downgrade()` functions; the scoring-trigger migrations (005/009/012/021/026) each restore the prior body verbatim on downgrade. Backfills guard the fresh-DB case.
- **TODO/FIXME debt** — none in source. (grep hits are the "TODO" UI domain noun and player surnames like "Todorović".)
- **Logging hygiene** — no secrets/PII logged; ids are stringified UUIDs, scores, counts. Auth/PIN values are never logged.
- **Largest modules** — `admin.py` (1362 lines) is a multi-endpoint router (acceptable); `generate_squads.py` (1420) is generated data. Frontend `PlayerProfilePage.tsx` (765) is the biggest component — large but cohesive.

---

## Dependencies

`pnpm audit` / `pip-audit` were not run in this pass (sandboxed, offline). Recommend running both in CI before promotion:
- `pnpm --dir apps/web audit --audit-level=high`
- `pip-audit` against `apps/api/.venv` (report high/critical only).
No dependency findings are asserted here.
