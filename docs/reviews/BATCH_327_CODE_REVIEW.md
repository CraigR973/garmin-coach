# Batch 327 — Code and architecture review (audit wave #5, R1)

**Date:** 9 Oct 2026 (resumed; a first run on 7 Oct stopped at a usage limit with only this outline on disk)
**Pass:** R1 of the 327–333 wave (`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`)
**Lens:** senior software engineer — module health, error handling and session discipline,
threads, idempotency and races, migrations 031–037, test strength, the API/front-end contract.
**Mode:** read-only. Revert-the-fix experiments ran in a throwaway clone at
`scratchpad/wave5/r1/clone` (gitignored, outside the tracked tree); the shared checkout was not modified.
**Base:** `42a6a98` (production). Wave #4 base: `2178381`.
**Paid Anthropic calls:** none ($0).

## 1. Summary

**Grade: B** (wave #4 gave no letter). Seven findings: 1 High, 1 Med-High, 2 Medium, 3 Low.
The code is sound where wave #4 looked hardest — the morning pipeline has one owner, the threads are safe, the migrations are additive and reversible, and 12 of 12 reverted fixes fail a test (10 locally, 2 in CI) — but its two weakest seams are the ones that cross days or cross a rollback.
1. **Correct and safe — B.** No safety floor is broken in code; the High (CR327-01) moves a Red easing onto another day, which is the more cautious direction. CR236-01's rollback class returned twice in failure handlers (CR327-02).
2. **Honest with Mark — B−.** Since 8 Oct Saturday's Zwift ride is Thursday's 29-minute Red substitution while Home shows the planned 58-minute Sweet Spot, and nothing in the app notices (CR327-01, `observed`).
3. **Helping him get fitter — B (enabling only, in this lens).** The plan builder and coach offers (323/324) are validated, versioned and tested; Plan No. 3 reaches Zwift only when he accepts it.
4. **Failure noticed — C+.** The delivery mismatch is invisible to app, Craig and Mark; a backstop-morning failure can lose the brief and send Craig a false alert (CR327-02); a red deploy check that means nothing trains Craig to ignore it (CR327-07).
5. **Cheap to run and change — B−.** Service code grew 54% in 38 days to 132 modules; `morning_analysis`/`scheduler` are still the hubs, and Batch 308 is a split of a 446-line function, not a deletion (CR327-03, CR327-04).

## 2. What optimal looks like

**Optimal, in this lens:**
- **One answer to "what is on Zwift for date D".** A morning's easing belongs to its morning; moving a session moves its plan content and any hand edits, never another day's easing; something compares expected with live at least daily. The code already has the comparison (`_proposal_content_matches_workout`); nothing scheduled runs it.
- **Failure handlers that cannot fail.** One session per profile per job iteration, identifiers captured before the `try`, and a test that drives every handler with a real `AsyncSession`.
- **One colour engine, one packet contract.** The graded packet built from an allow-list, the acute rail and shared context as its inputs, no ladder.
- **Writers that refuse cleanly.** A row lock (or advisory lock) on Coach-memory sections so a race is a 409, not a 500.
- **CI that proves what it claims.** Migrations re-applied after the downgrade; deploy freshness by ancestry; the Zod/OpenAPI agreement checked.

**Already near-optimal (protect it):** the worker-thread design since 312; the stored-before-paid-call
morning (302) and the `gradedMorning` contract with optional, string-typed Zod fields; migrations 031–037;
the test suite's strength on the fixes since 1 Sep; the small leaf modules added since wave #4
(`session_recovery`, `serialised_calls`, `retry`, `admin_alerts`, `zwift_rail`, `plan_changes`).

**Smallest set of changes, in order (none needed before 21 Oct):**
1. **Now, Craig's call (no code):** decide what Saturday 10 Oct's Zwift ride should be (CR327-01).
2. **First after the trial, ahead of 308 (about half a day):** hoist the two identifiers and add the
   real-session guard (CR327-02).
3. **308, amended (2–3 days, not 1):** write the graded system prompt out as its own text (it is
   generated from the ladder's today), extract the acute rail, invert the packet to an allow-list, then
   delete (CR327-03).
4. **A new row after G8, or folded into 322 (about a day):** a swap re-pushes a moved session's
   baseline when its live content is a morning transform; `approve_adjustment` stops marking the
   consumed proposal `pushed` (CR327-01).
5. **After G8 (1–2 days):** `services/job_loop.py` for the scheduler's profile loops; move
   `verdict_replay`/`notes_eval` out of `services/` (CR327-04).
6. **Hours each, any later batch:** draft row lock (CR327-05); `none_as_null` (CR327-06); freshness by
   ancestry (CR327-07); `alembic upgrade head` after the downgrade in CI (CR236-18).

## 3. Findings

### CR327-01 — High — a swap carries one morning's Red easing to another day, hides it from Home, and locks that day's own morning out

**Evidence:** `observed` (production rows, 8 Oct), `proved` (the real `ExecutableCoachingService` and
`DailyLoopService` on in-memory SQLite reproduce the production sequence and its end state — origin, `adjustment.verdict`,
which date holds which event, Home's state, the locked-out morning; the durations differ only because the test fixture's
Sweet Spot is not Mark's; `r1/scripts/probe_swap_carries_adjustment.py`,
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
"before 21 Oct?" safety item; it is an honesty one. **Still so at the last read** (`observed`, 9 Oct, late
evening UTC): Saturday's live event (…345) holds `red_substitution`, 1,740 s, verdict Red; no proposal
has been written for 8–11 Oct since 8 Oct 10:07.

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
- **The graded brief's system prompt is built from the ladder's.** `GRADED_SYSTEM_PROMPT =
  _graded_system_prompt(LADDER_SYSTEM_PROMPT)` applies 12 exact-once string replacements at import;
  76% of the graded prompt's 27,179 characters is the ladder prompt's text (`computed` by importing
  both, 9 Oct). 308.1's "delete … its v50 prompt" therefore deletes the graded prompt's source unless
  the graded text is first written out as its own constant, byte-identical (so no version bump), with a
  SHA-256 pin like the ladder's.
- `morning_verdict()` grew from 259 lines (wave #4's `_morning_verdict`) to 446, and its branch count
  (this pass's AST measure) from 69 to 115 — the largest function in the codebase by both measures. It
  holds the acute rail call, the symptom and chest follow-up floors, the ladder's caps and the shared
  context fields.

What it means: Batch 308's row says "delete the ladder's colour path … the acute rail, its floors and
the symptom floors stay". The code makes that a split of a 446-line function, then an inversion of the
packet from deny-list to allow-list, before anything can be deleted. Nothing is wrong today; the risk is
308 being sized as a deletion.

**Fix:** fold into 308 as an amendment: (0) write the graded system prompt out as its own text,
byte-identical and pinned; (1) extract `acute_rail(...)` and the shared context fields
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
id. **Holiday pause and resume (292, #351; `implemented`):** a second Pause is refused with a 409
whenever any window is still open today *or in the future* (`is_active_on` deliberately has no start
bound), and the page shows Resume instead of Pause, so a double tap cannot stack two windows; Resume on
a future window removes it, on a running one shortens it, and restores only rows the pause itself wrote
(`source='holiday_pause'`, still skipped), so a second Resume finds nothing to restore. Every scheduler
reader uses the date-covering helpers, so a future window does not silence today's jobs. Pause leaves
already-delivered Zwift events in place for the away days (they were pushed on 11 Jul and simply went
unridden); that is harmless and consistent with "pushed sessions are never retracted" (R0922-14).
Two concurrent writes to the same Coach-memory section (holiday windows, the plan draft) or the same
chest follow-up day race to a unique index and one gets a 500 rather than a clean refusal — CR327-05's
class, milliseconds wide with one user.

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

Statuses re-verified on `42a6a98` this pass; the shared table's "claimed" rows in this lens are replaced
by what the code shows. Labels: `impl` = read in the code, `proved` = a reverted fix failed a test or a
probe drove the real function, `obs` = production or CI.

**Wave #4 — Batch 236 (19)**

| ID | Status now | Evidence |
|---|---|---|
| CR236-01 rollback expires ORM objects | **Fixed where found; the class is open** | `restore_after_rollback` at 20 correct call sites (impl); two new instances shipped since, both proved to raise (CR327-02) |
| CR236-02 three morning entry points | Fixed | Wake job, backstop, check-in and Retry all construct `MorningBriefPipeline`; the router's private `from src.scheduler import` is gone (impl) |
| CR236-03 isolation tested only on mocks | **Open in substance** | `test_session_recovery.py` drives the helper on a real session (CI); the pipeline's and scheduler's isolation tests still use `AsyncMock`/`MagicMock`, which is why CR327-02 shipped (impl, proved) |
| CR236-04 post-activity services 68–78% alike | Fixed (shell shared) | `PostActivityReadRunner`; the three remaining services 62–65% line-similar (computed) |
| CR236-05 free-text `workout_type` | Fixed | `workout_categories.WORKOUT_TYPE_CATEGORY` mirrors `workoutTypes.ts`, pinned on both sides (`test_workout_categories.py`, `workoutCategories.test.ts`) (impl) |
| CR236-06 transport exception as control flow | Fixed | `GenerationRequestInProgress(Exception)`, one 409 handler (impl) |
| CR236-07 261-line central verdict | **Shipped, then regrown** | Moved to `morning_verdict.py`; the function is now 446 lines, 115 branches (computed; CR327-03) |
| CR236-08 offline Alembic schema | Fixed | `version_table_schema="coach"` on both paths of `migrations/env.py` (impl; offline SQL in `r1/mig_*.sql`) |
| CR236-09 router as serialiser | Fixed | Router 335 lines; serialisers in `daily_loop_envelope` (1,218) (impl) |
| CR236-10 `scheduler.py` an application | **Open; trigger fired 4 Sep, nothing scheduled** | 2,368 lines, 34 service imports; 12 commits since (computed). CR327-04 gives the smallest fix |
| CR236-11 2,230-line `DashboardPage.tsx` | Deferred, trigger not met | 2,300 lines; 15 commits since, none large (+130/−60) (computed). Still not worth splitting until a change needs it |
| CR236-12 projection assembly copied | Fixed | `day_context_loaders` is one leaf (impl) |
| CR236-13 `select(Model)` unlinted | Shipped differently, sound | `bulk_history_reads` documented entry point; 280/285 removed the raw-payload readers that mattered (impl, per their close-outs) |
| CR236-14 five orphan backfills in the image | Accepted, still true | The same five modules have 0 references in `src`, `tests` or `scripts`; the two misnamed live ones are unchanged (impl) |
| CR236-15 no Zod/FastAPI agreement check | Accepted, still true | Hand comparison this pass found no mismatch on the changed endpoints (impl); no automated check |
| CR236-16 coverage measured, ignored | Accepted, still true | `ci.yml` still runs `--cov` with no floor (impl) |
| CR236-17 `run_scheduled` docstring drift | Accepted; mostly fixed in passing | 18 of 19 `JOBS` documented; `fan-control` still missing (impl) |
| CR236-18 migration round trip one way | **Accepted, still true** | `ci.yml` runs `upgrade head` then `downgrade base`, never `upgrade head` again (impl). One line; worth doing with any CI touch |
| CR236-19 duplicated `except`, duck-typed reason | Fixed | One recorder; `isinstance(exc, AnthropicApiError)` (impl) |

**Later reviews, in this lens**

| ID | Status now | Evidence |
|---|---|---|
| 0928-SE-1 verdict pure, table-driven, property-tested | Fixed | `verdict_grading.THRESHOLDS`; reverting 246/303/310's core lines fails 5/2/15 tests (proved) |
| 0928-SE-2 replay a kept tool | Fixed; misplaced | `scripts/replay_verdicts.py` exists (not run this pass); its 1,295-line engine sits in `services/` (CR327-04) |
| 0928-SE-3 shadow before switching | Shipped differently, sound until 308 | The 7–20 Oct side-by-side logs `verdict_engines_compared`; rollback is `config.verdict_engine` (impl) |
| 0928-SE-4 the colour's many consumers | Fixed | Weekly mix takes `session_actions`; the delivery rail and `todays_call` read stored actions via `stored_engine` (impl) |
| 0928-SE-5 flags and answers need a schema change | Fixed | Migrations 033–036 (proved offline) |
| 1001-SE-1 colour exists only if the paid brief succeeds | Fixed | `grade_and_store` before `write_brief`; reverting the `gradedMorning` field fails a Postgres test in CI (proved) |
| 1001-SE-2 weekly mix reads the colour | Fixed | as 0928-SE-4 (impl) |
| 1001-SE-3 rail proposes on rest days and skipped rows | Fixed | `MorningContext.proposal_for` returns nothing on a rest day or a skipped/completed session (impl) |
| 1001-SE-4 a re-save clears a noted symptom | Fixed | `symptoms_answered_at_utc` (035) is the only answer; 6 check-ins with symptoms, 0 answered (obs) |
| 1001-SE-5 rollback no longer exact | Queued (308), still true | `verdict["notesReading"]` is set under either engine (`morning_analysis` after the engine switch) (impl) |
| 1001-SE-6 chat sees a held day as Green | Fixed | `recent_mornings` carries `held` (impl) |
| 1001-SE-8 `updated_at` before `created_at` | Accepted by design | Two `_utcnow` calls; `updated_at_column`'s docstring says "microseconds apart" (impl) |
| 1001-SE-9 CI PostgreSQL 16, production 17 | Open, harmless | CI ran 16.15 on 7 Oct (obs); no 17-only SQL in the tree (impl) |
| R0922-14 a pushed session is never retracted after a Red | Open (Craig's call never recorded) | Unchanged in `regenerate_for_verdict`; CR327-01 adds the converse: a pushed easing can also travel to another day |
| DV-12 swap withheld on an off-the-bike day untested | Queued (321.1), still true | Re-proved 9 Oct: disabling the rule fails 0 of 315 local tests across 10 files, and no skipped test names it |
| DV-15 §4 no longer a model | Queued (308) | Not code; not re-checked |

## 5. G8 and parked rows re-verified

| Row | Verdict | What changed |
|---|---|---|
| **308** the ladder goes | **References hold; under-sized** | `VERDICT_ENGINE` (`config.py:223`, 8 branches in `morning_analysis`), `LADDER_PROMPT_VERSION` v50, `LADDER_ONLY_FIELDS`, `stored_engine` (two readers in `executable_coaching`) all exist. Missing from the row: the graded prompt is generated *from* the ladder prompt (CR327-03), the packet is a deny-list, and four more places name the ladder (`coach_policy.LADDER_MORNING_FLOORS` and its audit test, `coaching_state.LADDER_*_CONSTRAINT`, `todays_call._LADDER_HARD_TYPES`, `verdict_replay`). 308.2 is right that `todays_call` and `stored_engine` must keep reading pre-switch mornings; `_LADDER_HARD_TYPES` is one of the four "hard session" definitions the 6 Oct review counted and should be named as kept, not deleted. Size 2–3 days |
| **311** HRV dip counted twice | Accurate; line drift | `_domains` is at `verdict_grading.py:1070` (row: `:978`); `readiness_confirms_domains` unchanged |
| **316** load-ratio line | Accurate; line drift | `_load` at `:953` (row: `:948`); `acwr_mild` and the recovery-time lines as described |
| **317** Home shows why | Accurate | `mark_facing_summary` at `verdict_grading.py:1412`; `TodaysCallHero.tsx` renders no summary |
| **318** brief leads with the call | Accurate in substance; one ref moved, one count off | `required_morning_output_sections` `:38` holds; the missing-heading warning is now at `morning_analysis.py:1767` (row: `:1727`). The graded prompt has 3 lines naming "Green/Amber/Red" literally (row: four places) and 27 colour words in all; the claim's point stands |
| **319** progress signal | Accurate; one ref moved | `detect_ftp_drift` at `insights.py:334` holds; `atBlockBoundary` is at `schemas.ts:1603` (row: `:1540`) and still no screen reads it |
| **320** tonight's advice | No code references to check | — |
| **321** three small fixes | Accurate; line drift | 321.1's rule is at `morning_analysis.py:1335` (row: `:1301`) and still untested (proved, DV-12 above) |
| **322** record what he rode | Accurate; one more case | CR327-01 shows the version pushed for a date may be another morning's easing; 322.2's "link each ride to the version pushed" would record it, but grading against that version would grade Saturday against Thursday's Red. Grade against the plan row's own easing, not whatever event sits on the date |
| **208** co-resident app | Not code (R2) | — |
| **209** RLS that constrains the app | Accurate | The three new tables (032, 034, 036) declare `RLS_TABLES`; `test_coach_rls_migration.py` passes (4) |
| **210** no connection idles across a model call | **Decayed** | `reviews.py:709` is now `:930`, `generation_requests.py:192` now `:392`; and a third site with the same shape is not named: `trends.py:800` (the 266 trend narratives) holds a transaction-scoped lock across the paid call. Batch 232's amendment (2)–(4) still describes the trade correctly |
| **276** dispute suppresses an input | Accurate; by its own 276.4 it does not run yet | `ConversationLearningProposal` at `models/coaching.py:659` (row: `:651`); `coach.disputes` holds 0 rows (obs, 9 Oct) |

## 6. For reconsideration

**Decision #386's migration rule, "every column but the key nullable", applied to a brand-new table.**
The G8 run's rule (additive and nullable) protects existing rows and a rollback when a column is added
to a table that already holds data. Migration 036 applied it to a table created empty, so
`symptom_follow_ups.user_id` and `subject_date` are nullable, and PostgreSQL treats NULLs as distinct, so
`uq_symptom_follow_ups_user_day` would not stop two rows with a NULL date. No code path writes a NULL
(`DailyLoopService` sets both, `implemented`) and the table holds 0 rows (`observed`, 9 Oct), so
nothing is wrong today and tightening is free now. Proposed amendment: the rule applies to columns added
to existing tables; a new table's identity columns are `NOT NULL`. Only if Craig agrees; no urgency.

Nothing else in this lens argues against a settled decision. Decision #310 (not restructuring Batch 210's
claim-then-work shape) still reads correctly at one user; the third site in section 5 belongs in that
row, not in a reversal.

## 7. Hypotheses (unverified)

1. **Executor saturation.** Garmin, Hive, Piper TTS, the fan and web-push share asyncio's default
   executor (`min(32, cpus + 4)` threads). Several Garmin calls queued on `GARMIN_CALLS` each hold a
   thread while they wait; with a slow Garmin hour (312's open question) this could delay unrelated
   `to_thread` work. Not seen in logs; would show as fan or push latency during a Garmin stall.
2. **A ladder-only field already leaking.** CR327-03's deny-list has no allow-list test; whether any
   field added to `morning_verdict()` since 296 reaches the graded packet unnoticed was not checked
   against stored packets (it would need the `context_packet` JSONB, which this pass did not pull).
3. **Plan No. 3 on an earlier Monday.** Batch 324 lets Mark move the start Monday. If he accepts a
   start before 19 Oct, the new block's dates already carry 11 Jul events; the one-event-per-date rule
   should replace them on reconcile, but this pass did not trace `lock` → reconcile → push (R4's area).
4. **CR327-02 has not fired yet.** 0 occurrences in `job_runs` and `brief_generation_status` since
   1 Sep; how often the ride-changes or drivers step fails on a backstop morning is unknown, so the
   real rate of a lost brief or false alert is unmeasured.

## 8. Limitations

- **No local PostgreSQL:** the clone's full suite ran 2,199 passed, 522 skipped; Postgres-only results
  come from CI on `42a6a98` (2,721 passed, 0 skipped, PostgreSQL 16.15, run 37696581593).
- **Sentry is not readable** from this machine; what reaches Craig was judged from code, `job_runs`
  and two days of Railway logs.
- **The 6 Oct invariant harness was not re-run.** Since `44274a1` the verdict engine changed only by
  Batch 315 (+15 lines in `verdict_grading`, +19 in `morning_verdict`, both an easing that adds
  caution) and `todays_call.py` is unchanged, so the invariants should hold; that is `implemented`,
  not `proved`.
- **Probes ran on fixtures.** CR327-01 and CR327-02 drive the real services on in-memory SQLite with
  the test suite's workouts and profiles, not Mark's rows; SQLite reproduces `MissingGreenlet` and the
  rail's logic but not PostgreSQL locking, so CR327-05's races are `implemented` only.
- **Not traced:** Plan No. 3's accept → materialise → Zwift path end to end; the coach offer's
  apply route under two tabs beyond the revision check (its tests are Postgres-only and read, not run);
  coverage figures (CR236-16).
- **No `railway run` probe** was needed this pass; no paid call was made ($0).

## 9. Probe log

All read-only. Sizes are the returned payload.

| When (UTC) | What | Result |
|---|---|---|
| 9 Oct 09:12 | `gh run list` / `gh run view --log` on `main` (CI 37696581593; freshness 37696731669, 37696909541) | pytest 2,721 passed, 0 skipped; freshness failure text |
| 9 Oct 09:13 | `information_schema.columns` for `job_runs` | ~1 KB |
| 9 Oct 09:13 | `job_runs` non-succeeded since 1 Sep, grouped (excl. `egress-budget`) | 11 groups, ~2 KB |
| 9 Oct 09:13 | `job_runs` non-succeeded `morning-sync`/`wake-check`/`activity-poll` rows with counters | ~3.5 KB |
| 9 Oct 09:16–09:18 | `railway logs --service api --since 2d` (one pull of 3,539 lines, kept in `r1/api_2d.log`) | 39 `daily_loop served`, 397 `pydreo` lines |
| 9 Oct 09:18 | `brief_messages` JSON-null vs SQL-NULL counts | 1 row, ~0.7 KB |
| 9 Oct 09:19 | Active bike rows per date with more than one session; 10–11 Jul proposals | ~0.8 KB, ~1.3 KB |
| 9 Oct 09:20 | `manual_entries` 6–9 Oct (no notes text); `analyses` 6–9 Oct (lengths only) | ~2 KB, ~13 KB |
| 9 Oct 09:21 | Row counts: disputes, check-in readings, follow-ups, symptoms answered; Alembic head | 1 row (0, 5, 0, 0, 6, 0, `037`) |
| 9 Oct 14:06 | `brief_generation_status` not ready since 1 Sep; `job_runs` failures and degraded rows | 0 rows; ~1.5 KB; ~2.6 KB |
| 9 Oct 14:08 | `morning-sync` counters since 1 Sep | 1 row (39 runs) |
| 9 Oct 14:08–14:09 | Table and column lists; `planned_workouts` 7–11 Oct; `audit_log` 8 Oct 09:30–10:30; `workout_delivery_proposals` 6–12 Oct | ~1–4.4 KB each; audit 0 rows |
| 9 Oct 14:11 | Three proposals' IR keys, origin, duration | 3 rows, ~1.7 KB |
| 9 Oct 14:13 | Swapped rows whose live IR carries a change | 5 rows, ~1.4 KB |
| 9 Oct 14:15 | `pg_indexes` for seven tables | ~3.9 KB |
| 9 Oct 14:16 | `brief_messages` NULL shapes by column, grouped | ~0.9 KB |
| 9 Oct 14:21 | 2 Aug pushed proposal with 31 Jul–2 Aug verdicts | 1 row, ~1.9 KB |
| 9 Oct ~22:20 | `workout_delivery_proposals` 8–11 Oct created since 8 Oct; live events for 8 and 10 Oct | 1 row; 2 rows |
| Local | Clone full suite; 13 revert-the-fix mutations (12 in `r1/out/mutations.txt`, plus 321.1 on 9 Oct); AST scans (`rollback_scan`, `loop_scan`, `sync_on_loop_scan`, `metrics`); aiosqlite probes (`probe_rollback_class`, `probe_backstop_real_session`, `probe_swap_carries_adjustment`); prompt derivation measure; `alembic --sql` offline 030↔037 | as reported above |

Total production reads well under 1 MB; no JSONB column selected whole except the small `adjustment`
and `delivery` sub-objects.
