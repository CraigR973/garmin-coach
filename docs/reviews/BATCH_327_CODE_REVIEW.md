# Batch 327 — Code and architecture review (audit wave #5, R1)

**Date:** 9 Oct 2026 (resumed; a first run on 7 Oct stopped at a usage limit with only this outline on disk)
**Pass:** R1 of the 327–333 wave (`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`)
**Lens:** senior software engineer — module health, error handling and session discipline,
threads, idempotency and races, migrations 031–037, test strength, the API/front-end contract.
**Mode:** read-only. Revert-the-fix experiments ran in a throwaway clone at
`scratchpad/wave5/r1/clone` (gitignored, outside the tracked tree); the shared checkout was not modified.
**Base:** `42a6a98` (production). Wave #4 base: `2178381`.
**Paid Anthropic calls:** none ($0).

_In progress — sections are filled as the pass runs._

## 1. Summary

## 2. What optimal looks like

## 3. Findings

### CR327-01 — High — a swap carries one morning's Red easing to another day, hides it from Home, and locks that day's own morning out

**Evidence:** `observed` (production rows, 8 Oct), `proved` (the real `ExecutableCoachingService` and
`DailyLoopService` on in-memory SQLite reproduce every production value; `r1/scripts/probe_swap_carries_adjustment.py`,
output in `r1/out/probe_swap.txt`), `implemented` (`swap_day`, `move_event`, `_deliberately_acted`, `daily_loop._deliveries`).

**The live case (lens item 4), reconstructed from the rows.** Event ids were pushed in date order on
11 Jul, so event …345 was Thursday 8 Oct's and …349 Saturday 10 Oct's.
1. 09:40 UTC — the check-in graded 8 Oct Red; the ride-changes step *proposed* a Red recovery
   substitution of Thursday's Sweet Spot (29 min, power capped at 60%).
2. 10:07:01 — Mark tapped Approve. `approve_adjustment` → `_resync_event` updated Thursday's live event
   (…345) in place with the eased ride and wrote that IR onto the July carrier row. The proposal he
   approved is marked `pushed` with no event id (a bookkeeping row; harmless to the rail, which requires
   an event id, but it reads as a delivery).
3. 10:07:10 — Mark tapped Swap (Thursday's Sweet Spot ↔ Saturday's Easy Z2). `swap_day` moves the
   **delivered events with their current content** (`move_event` only rewrites the date) and re-slots
   the **plan rows from the plan's own content**. So Thursday got the unadjusted Easy Z2 (he rode 45 min),
   and Saturday's event …345 now holds "Recovery substitution: Sweet Spot", 1,740 s, `adjustment.verdict`
   Red, while Saturday's plan row reads "Sweet Spot (1 × 30 min @ 89%)", 58 min.

**Is it correct?** No. The easing was a decision about Thursday's morning. Three consequences, each proved:
- **Saturday's trainer and Home disagree.** Home's delivery state for Saturday is `changed: false`,
  `adjustment: null` (only a *pending* proposal sets them); `liveOrigin` is `red_substitution`, which the
  web never renders. Home shows the planned Sweet Spot "in Zwift"; Zwift will serve a 29-minute ride at
  60%.
- **Saturday's own morning cannot fix it.** `_deliberately_acted` treats any pushed proposal with
  `adjustment.changed` as "Mark acted on this ride", and the moved carrier now points at Saturday's
  row. Probe: an Amber Saturday proposes nothing; a Green Saturday changes nothing by design.
- **The same shape has happened before** (computed): of 5 swapped rows whose live IR carries a change,
  one other carries a verdict easing onto a later date (a Red substitution pushed 1 Aug, dated 2 Aug).
  Mark's own edits (interval editor, manual override) also travel with a swap, and should.

The code already disagrees with itself here: `reconcile_deliveries`' own predicate
(`_proposal_content_matches_workout`) treats a `red_substitution` IR that differs from the day's
expected IR as stale and would re-push Saturday's baseline — but reconcile runs only after a plan
change whose window covers the date (plan actions, restructure, block generation); no scheduled job runs it.

**Fix (about a day, one test file):** in `swap_day`, when the moved live IR's origin is a *morning*
transform (the automatic origins `_proposal_content_matches_workout` already names, plus the tired-morning
picks) re-push the moved session's baseline for its new date (the same `_deliver_one` path reconcile uses)
instead of moving the eased IR; keep moving hand edits as now. Have `approve_adjustment` stop marking the
consumed proposal `pushed` (`approved` is the honest status). Test: approve-then-swap, assert the target
date's live IR is `as_planned` and `_deliberately_acted` is false for it. **Where:** a new row after G8
(it touches the delivery rail, not the verdict), or folded into 322.
**Now (not a code change; Craig's call before Sat 10 Oct):** Saturday's Zwift workout is Thursday's eased
version while Home shows the full Sweet Spot. Edit on Saturday's card re-syncs from the plan row (with
Mark's scaling); a plan action covering Saturday would also restore it. Whether to tell Mark, re-push, or
leave the easier ride is Craig's decision. Leaving it is the more cautious state, so this is not a
"before 21 Oct?" safety item; it is an honesty one.

### CR327-02 — Med-High — CR236-01's class came back twice, once inside the function written to fix it

**Evidence:** `proved` (real `AsyncSession` on aiosqlite, both instances; the fix proved in the clone),
`implemented` (the AST scan), `observed` (0 occurrences in `job_runs` / `brief_generation_status` since 1 Sep).

Batch 242 fixed the instances wave #4 listed and added `session_recovery.restore_after_rollback`. It did
not fix the class: no lint, no per-iteration session, no real-session test of a pipeline. Two new
instances have shipped since, each reading an ORM attribute after `session.rollback()` inside the
handler that exists to survive a failure:

1. **`MorningBriefPipeline._isolated`** (Batch 251, 3 Sep) — the PER_STEP handler the 11:00 backstop
   uses. It rolls back, then logs `profile_id=str(profile.id)` *before* calling
   `restore_after_rollback`. The read raises `MissingGreenlet` from inside the handler. The docstring
   says this function is CR236-01's fix.
   - Probe: re-ran `test_per_step_commit_isolates_a_failed_step_and_continues` with one change — a real
     session and a real `Profile` in place of `AsyncMock`/`MagicMock`. The test expects 1 failure, the
     deload step to run, the brief to be written and pushed, drivers cached. With a real session: 2
     failures, no deload, **no brief written**, no ready push, no drivers, the morning marked failed,
     an operator alert, a "call ready" push. Hoisting `profile_id = profile.id` above the `try`
     (two lines, in the clone) restores every expected value.
   - What Mark would see: on a backstop morning (8 of 39 since 1 Sep were written by the backstop),
     any failure in the ride-changes step loses the brief; Home shows the failure card and Retry
     (which works, it runs TERMINAL). The daily drivers precompute runs under the same handler on every
     backstop (39 of 39); a failure there flips a written morning's status to failed and sends Craig a
     false "brief generation failed" alert (Home is unaffected: a written brief outranks the status row).
2. **`scheduler.run_trend_narratives`** (Batch 266, 20 Sep) — after a failed month narrative it rolls
   back and logs `user_id=str(player.id)`. Probe: the job raises `MissingGreenlet`, the season bucket is
   never attempted, the designed `notify_admin_generation_failure` never runs (0 alerts sent);
   `run_tracked_job` records `failed / unhandled_exception` instead of `degraded`.

The AST scan (`r1/scripts/rollback_scan.py`, `loop_scan.py`) finds no other live instance in
`scheduler.py`, `morning_pipeline.py`, `routers/` or `brief_chat.py` (its one rollback reloads with
`session.get`). The 20 `restore_after_rollback` call sites are correct.

**Why the tests missed it:** the pipeline's isolation tests and `test_scheduler.py`'s `_profile()` still
use `AsyncMock()` sessions and `MagicMock()` profiles — CR236-03's exact gap. The one real-session test
(`test_session_recovery.py`) tests the helper, not a caller. The real-Postgres trend-narratives test
covers only the success path.

**Fix (about half a day):** (a) hoist the two identifiers (proved); (b) a pytest guard that drives
`_isolated` and every scheduler profile loop with a real `AsyncSession` and a failing step — SQLite via
aiosqlite (one new dev dependency; this pass loaded it from a scratch folder) is enough to reproduce
`MissingGreenlet`, so it runs locally, not only in CI; (c) optionally
a small AST check in CI (the scan is 30 lines) for "attribute read on a non-local after `rollback()` and
before `restore_after_rollback`". **Where:** before 21 Oct? — it adds no caution and changes no
Mark-facing behaviour on a healthy morning, so it does not meet the bar; first fix after the trial,
ahead of 308 (which edits `morning_analysis`/`morning_verdict`, not this file). The structural fix —
one session per profile in a shared job-loop helper — belongs with CR327-04.

### CR327-03 — Medium — the graded verdict is built by subtracting from the ladder, so Batch 308 is a split, not a deletion

**Evidence:** `implemented` (`morning_verdict.graded_verdict_packet`, `LADDER_ONLY_FIELDS`,
`morning_analysis._graded_verdict`), `computed` (AST metrics, `r1/metrics_old.json` / `metrics_new.json`).

- The ladder's `morning_verdict()` still runs every morning and is the graded engine's input builder:
  `_graded_verdict(..., ladder=verdict)` and `graded_verdict_packet(ladder, graded, ...)` read
  `acutePhysiology`, `isRestDay`, `hasVo2WorkoutToday`, `readinessBaselineTrend`, `restDayReason`,
  `subjectiveScore`, `readinessLevel`, `hrvStatus`, `hrvBelowBaseline` from the ladder's dict.
- The graded packet is "the ladder's packet minus 15 named keys, plus an overlay". It is a deny-list:
  any field added to the ladder reaches the stored packet, the brief and the coach under the graded
  engine unless someone remembers to add it to `LADDER_ONLY_FIELDS`.
- `morning_verdict()` grew from 259 lines (wave #4's `_morning_verdict`) to 446, and its branch count
  (this pass's AST measure) from 69 to 115 — the largest function in the codebase by both measures. It
  holds the acute rail call, the symptom and chest follow-up floors, the ladder's caps and the shared
  context fields.

What it means: Batch 308's row says "delete the ladder's colour path … the acute rail, its floors and
the symptom floors stay". The code makes that a split of a 446-line function, then an inversion of the
packet from deny-list to allow-list, before anything can be deleted. Nothing is wrong today; the risk is
308 being sized as a deletion.

**Fix:** fold into 308 as an amendment: (1) extract `acute_rail(...)` and the shared context fields
from `morning_verdict()` into the graded engine's inputs; (2) build the graded packet from an explicit
allow-list; (3) then delete the ladder's colour path, `LADDER_ONLY_FIELDS`, `LADDER_*` wording constants
and `VERDICT_ENGINE`. A packet-shape snapshot test over the replay's stored mornings is the guard (308.3
already asks old mornings to render and replay). Cost: 308 is closer to 2–3 days than 1.

### CR327-04 — Medium — the service layer grew 54% in 38 days; `scheduler.py` and `morning_analysis.py` are still the hubs

**Evidence:** `computed` (AST metrics over `2178381` and `42a6a98`), `implemented`.

| Measure | 1 Sep (`2178381`) | 9 Oct (`42a6a98`) |
|---|---|---|
| Service modules / non-blank LOC | 92 / 37,104 | 132 / 57,236 |
| `morning_analysis.py` lines / service imports | 3,027 / 30 | 3,478 / 40 |
| `scheduler.py` lines / service imports | 2,247 / 26 | 2,368 / 34 |
| `chat_context.py` / `brief_chat.py` service imports | 8 / 5 | 17 / 13 |
| Functions with branch count ≥ 40 (top three per module) | 2 | 11 |

Which modules pay their way:
- **Earn their place (keep):** the leaves added since — `session_recovery`, `serialised_calls`,
  `retry`, `admin_alerts`, `profile_clock`, `graded_morning`, `day_context_loaders`, `zwift_rail`,
  `symptom_check`, `todays_call`, `plan_changes`, `provenance`. Each is small, single-purpose and
  imported where needed. `morning_pipeline` (991 lines) replaced three entry points (CR236-02) and is
  the right owner; `daily_loop_envelope` took the router's serialisation (CR236-09).
- **Do not pay their way in `services/`:** `verdict_replay` (1,295 lines) and `notes_eval` (391) are
  imported only by `scripts/`; they are kept tools (0928-SE-2) shipped in the API image and counted in
  the service graph. `verdict_grading` imports `verdict_replay` only in a docstring.
- **Hubs:** `morning_analysis` (40 service imports) and `scheduler.py` (34) are where every new rule
  lands. CR236-10's own trigger ("after W10") fired on 4 Sep and nothing was scheduled; the 20 Sep
  regression in CR327-02 (trend narratives) is a scheduler loop written differently from its neighbours.
- **Residual duplication:** the strength, flexibility and walk post-activity services are still 62–65%
  line-similar to each other (68–78% at wave #4; `PostActivityReadRunner` took the shared shell).

**Fix (smallest set, after G8):** (1) a `for_each_active_profile(job, step)` helper in a new
`services/job_loop.py` that opens one session per profile and records the per-profile outcome; move
the scheduler's 15 profile loops onto it (also closes CR327-02's class structurally) — 1–2 days;
(2) move `verdict_replay` and `notes_eval` under `scripts/` or a `tools` package — an hour; (3) do 308
before anything else touches `morning_analysis`. Not worth doing: splitting `DashboardPage.tsx`
(CR236-11) or the three post-activity services until a change needs it.

### CR327-05 — Low — the plan draft has no lock: a same-revision double write fails as a 500, and a decline can be undone by a racing change

**Evidence:** `implemented` (`block_generator.change`, `discard`, `_save_draft`; production index
`uq_knowledge_base_section_version`).

`change()` checks `expected_revision` and then writes a new version with no row lock. Two changes at
the same revision (two tabs, or a builder tap racing an offer's Apply) both pass the check; the unique
index on `(user_id, section, version)` rejects one, which surfaces as an unhandled `IntegrityError`
(a 500), not the 409 "the plan has moved on" the code means to send. A `discard()` that commits
between a racing `change()`'s read and its write leaves the change inserting a fresh *active* draft,
so the declined plan reappears. Both windows are milliseconds with one user; accept-after-decline,
double-tap Accept and stale offers are all handled correctly (`lock` refuses a locked draft;
`offer_is_current` and the revision check mark a stale offer, both pinned by tests).
**Fix:** `SELECT … FOR UPDATE` on the active `generated_block` row in `_load_kb` for the writers (or a
transaction advisory lock on the user and section). An hour. After G8, or with 319.

### CR327-06 — Low — a missing offer is stored as JSON `null`, not SQL NULL

**Evidence:** `observed` (`coach.brief_messages`: 52 rows hold JSON `null` in `proposed_interval_change`
since 18 Sep, 12 also in `proposed_plan_change` since 7 Oct; 0 rows hold a real plan-change offer),
`implemented` (both columns are `JSONB` without `none_as_null`; `BriefChatService` assigns `None`).

Every reader in the app goes through the ORM, which loads JSON `null` as `None`, so nothing Mark sees
is affected (lens item 7 answered: yes, readers treat it as NULL). The trap is ad-hoc SQL:
`proposed_plan_change IS NOT NULL` counts 12 offers where there are none — exactly the query a review
or a Batch 322 measurement would write. **Fix:** `JSONB(none_as_null=True)` on both columns plus a
one-line data fix to SQL NULL (a production write, Craig's go). Fold into any later batch touching chat.

### CR327-07 — Low — the deploy-freshness check reports red when a docs commit follows within its window

**Evidence:** `observed` (Actions run 37696731669: "Production did not reach expected SHA c759ece…
within 900s"; the close-out commit `42a6a98` was pushed about a minute after `c759ece`, so production
went straight to `42a6a98`; the next run, 37696909541, passed).

`scripts/monitor_deploy_freshness.py` requires the exact merged SHA. Every code-then-docs close-out
done in quick succession produces a red check that means nothing, which trains Craig to ignore the one
check whose red would matter. **Fix:** accept any SHA that has the expected one as an ancestor (the
script can call the GitHub compare API, or CI can pass `git rev-list` output). An hour. After G8.

### Measured and sound — no finding

**Tests: would they fail if the fix were reverted? (lens item 6; `proved`)** Twelve reverts in the
throwaway clone, each restored afterwards (`r1/scripts/mutations.py`, output `r1/out/mutations.txt`).
Local runs skip Postgres tests; CI on `main` at `42a6a98` ran **2,721 passed, 0 skipped** on
PostgreSQL 16.15 (local: 2,199 passed, 522 skipped — the same 2,721).

| Fix reverted (core line) | Local result | Judgement |
|---|---|---|
| 242 `restore_after_rollback` made a no-op | 1 fails (the helper's own log test) | Caught in CI by the real-session test; **callers not covered** (CR327-02) |
| 246 +7 bpm resting-HR floor → +70 | 5 fail | Pinned |
| 248 timeout / transport classified "other" | 2 fail | Pinned |
| 291 `admin_alert` tag not set | 7 fail | Pinned |
| 302 `gradedMorning` never served | 0 fail, 26 skip | Caught in CI only (`test_on_postgres_the_daily_loop_serves_a_morning_without_its_brief`, read) |
| 303 no easy days after a fever | 2 fail | Pinned |
| 310 holiday catch-up off | 15 fail | Pinned |
| 312 Garmin/Hive back on the event loop | 7 fail | Pinned |
| 315 no chest follow-up | 4 fail | Pinned |
| 324 draft revision check removed | 0 fail, 10 skip | Caught in CI only (`test_on_postgres_a_change_versions_the_draft`, read) |
| 324 offer always "current" | 1 fails | Pinned at the function; the Apply route's tests are Postgres-only |
| 326 paused account read as fine | 5 fail | Pinned |

Ten of twelve fail locally, two in CI only; none passes everywhere. The one class no test guards is
the one wave #4 named: ORM state after a rollback in a real session (CR327-02), and the delivery rail's
cross-day behaviour (CR327-01: no test swaps a session whose live event carries an easing). No
PostgreSQL 16-vs-17 sensitive SQL was found (no `MERGE`, `JSON_TABLE`, SQL/JSON functions or
`pg_stat_io`; the storage meter's `pg_database_size` over `pg_database` behaves the same).

**Threads since Batch 312 (lens item 3; `implemented`, `proved` by 312's own tests above).** Near-optimal.
- Every Garmin and Hive call runs in a worker thread (`retry_sync` → `asyncio.to_thread`, or a direct
  `to_thread`); an AST scan of every `async def` finds no synchronous client method called on the loop
  (`r1/scripts/sync_on_loop_scan.py`).
- One process-wide `threading.RLock` per service (`GARMIN_CALLS`, `HIVE_CALLS`), taken inside the worker
  thread, never on the loop; re-entrant because `fetch_*` calls `login`. The two locks never nest, so
  no deadlock. The lazily-built `garminconnect` client is mutated only under the lock.
- A hung call is bounded by the libraries' own timeouts (`garminconnect` 15–30 s per request plus its
  bounded retries; `pyhiveapi` 10 s); `to_thread` cannot be cancelled, so a hang holds its executor
  thread and its lock until that timeout — acceptable at this cadence.
- `release_connection` commits (never rolls back) before each external call, so no pooled connection
  sits idle in a transaction across a Garmin call; all five call sites have it. The exceptions are the
  outdoor Garmin upload inside a plan action's transaction and the async intervals.icu calls (20 s
  timeout) — both short and rare.
- Residual: Garmin, Hive, Piper TTS, the fan and web-push all share asyncio's default executor
  (`min(32, cpus + 4)` threads); several Garmin calls queued on the lock could occupy it. Not seen;
  noted under Hypotheses.

**Idempotency and races (lens item 4; `implemented`).** Apart from CR327-01 and CR327-05: re-grading a
morning and several check-ins a day serialise on `morning_lease_scope` (302's artifact scope, pinned);
`regenerate_for_verdict` is idempotent per workout, version and transform through its audit tag;
accept-after-decline returns 404, double-tap Accept 409, a stale or other-tab offer is marked stale
with his words; the delivery rail resolves one live event per date by newest `created_at` with an event
id. Holiday pause and resume (292) was not re-traced this pass (see Limitations).

**Migrations 031–037 (lens item 5; `proved` offline with `alembic upgrade 030:037 --sql` and
`downgrade 037:030 --sql`; CI runs upgrade head → downgrade base on every push).** All seven are
additive: two JSONB columns on `brief_messages`, two columns and a CHECK on `manual_entries`, three new
tables with RLS enabled where `auth` exists. Every downgrade is the exact inverse; the downgrades of
032, 034 and 036 drop tables holding Mark's disputes, notes readings and chest follow-up answers (stated
in each docstring). Indexes match the readers (`user_id, subject_date`; `user_id, created_at`; the
`manual_entry_id, notes_sha256` unique key that makes a re-read idempotent). One oddity: 036 creates a
brand-new table with every column nullable, including `user_id` and `subject_date`, which also lets
NULLs slip past its unique key — see For reconsideration.

**Front end against the API contract (lens item 7; `implemented`).** Near-optimal for everything
changed since 1 Sep. The new Zod fields are `.nullable().optional()` (`gradedMorning`, `nextPlan`,
`zwiftRail`, `todaysCall`, `proposedPlanChange`), and the fields a server may extend are plain strings
rather than enums (`zwiftRail.state`, `todaysCall.reading`/`look`), each with a comment saying why — the
302 `gradedMorning` lesson was learned. A key-by-key comparison of `ZwiftRailOut` and `BriefMessageOut`
with their Zod schemas finds no mismatch; the plan-change offer statuses the server writes
(`proposed`, `applied`, `stale`, `unavailable`) are exactly the Zod union. `todaysCall` is typed
`dict[str, Any]` on the server but always built by `TodaysCall.to_packet()`. Still missing: any
automated check (CR236-15), and a parse failure still shows Mark raw `ZodError` text (UX241-03, R7's).

## 4. Follow-through

## 5. G8 and parked rows re-verified

## 6. For reconsideration

## 7. Hypotheses

## 8. Limitations

## 9. Probe log
