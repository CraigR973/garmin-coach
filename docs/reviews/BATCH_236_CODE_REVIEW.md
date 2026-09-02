# Batch 236 — Code & architecture review

**Date:** 2026-09-01
**Pass:** 236 of the 236–241 audit wave (`docs/reviews/BATCH_236-241_AUDIT_SCOPE.md`)
**Lens:** software engineering — module health, the critical path, error handling,
async/session discipline, test quality, dead code, migrations, frontend structure
**Mode:** diagnose-only. No repository code, test, config, schema or production
data was changed. Every experiment below ran against a **copy** of `apps/api`
in the session scratchpad; the repo working tree is byte-identical to `main`.
**Base:** `main` @ `2178381` (`docs: close out batch 233`) — the SHA production serves.
**Scope measured:** `apps/api/src` 55,213 LOC across 86 services / 26 routers /
6 model files; `apps/web/src` 29,127 LOC across 191 TS/TSX files;
`packages/shared/src` 3,194 LOC; 108 backend test files (45,306 LOC);
30 Alembic migrations (`001`–`030`).
**Not in scope:** deployed security/ops posture (Batch 237), prompt and model
behaviour (238), coaching correctness (239), physiology (240), live UX (241).
Where this pass touches those it stops at the code and cross-references.

**Evidence labels** follow the wave convention: `observed` (read the code and
reasoned), `proved` (executed it and watched it happen), `implemented` (changed
something — never used here; this pass is read-only).

---

## Executive summary

**The single most consequential defect in this pass is not a missing feature or a
wrong number. It is that the error handlers themselves raise.**

Batch 189's `CR189-02` found that scheduler jobs continued on a poisoned Session
and recommended rolling back. That remediation landed. But `Session.rollback()`
**expires every object in the identity map** — not just the modified ones, and
regardless of `expire_on_commit=False`, which the app correctly sets
(`database.py:35`). Under an `AsyncSession` the next plain attribute read on an
expired object is IO outside a greenlet, which raises `MissingGreenlet`. So the
line immediately after the rollback —

```python
await session.rollback()
log.info("weekly review delivery deferred to the in-flight holder",
         profile_id=str(profile.id), …)     # scheduler.py:592-597
```

— raises from inside its own `except` clause. **Proved by execution** on a real
`AsyncSession`, including for the primary key (see Verification). The blast
radius is exact and unpleasant: the `except GenerationRequestInProgress` handler
that Batch 232.1 shipped *so that a designed cron overlap would not be recorded
as a failure* now records it as a failure and aborts the job; and the sibling
`except Exception` handler dies before it reaches `record_failure` and
`notify_admin_generation_failure`, so the weekly review's failure turn and the
one broad operator alert Batch 238 credits the scheduler with
(`AI238-03`) are both unreachable on the path that needs them.

The codebase already knows about this. `scheduler.py:294-297` carries the
comment *"Snapshot before the try block: a rollback expires ORM attributes, so
failure logging must not trigger implicit async IO"* and hoists `profile_id =
profile.id` accordingly. **One job out of twenty-four does this.** The insight was
found, fixed locally, and never generalised — which is the shape of most of what
follows.

**Second: the morning brief has three entry points and two incompatible
transaction contracts, and nothing owns the pipeline.** The check-in path runs
everything `commit=False` under one transaction with a single terminal commit
(`routers/daily_loop.py:186-224`); the 11:00 backstop commits each step
independently and rolls back on error (`scheduler.py:1069-1245`); the wake job
does a third thing. The router reaches into the scheduler for a private helper
(`from src.scheduler import _sync_morning_inputs`, `routers/daily_loop.py:192`,
a function-scope import to dodge a cycle). Every morning-path defect the ledger
records — 141, 144, 222, 232.1 — is a drift between these three, and each was
fixed in the copy where it was noticed.

**Third: the test suite is large, fast and well written, and it is systematically
blind to exactly the class above.** `test_scheduler.py` is 1,966 lines; the
morning pipeline's error isolation is exercised entirely against
`session = AsyncMock()` and `profile = MagicMock()` (`test_scheduler.py:65-71`).
A mock session's `rollback()` expires nothing and a `MagicMock` is never in an
identity map, so the ORM behaviour under test is structurally unobservable.
Even the one test written specifically to prove the CR189-02 fix
(`test_scheduler.py:837-869`, a real-Postgres test) passes a `MagicMock` profile.

I ran a small mutation battery against a scratchpad copy of the tree. Two
mutations survived the whole local suite; one of them — deleting the persistence
of the weekly REM experiment assignment that `GET /api/v1/daily-loop` performs —
is **not covered by any test in the repo, local or CI**.

**What holds up.** The gates are real and clean (`1095 passed / 387 expected
PostgreSQL skips` in 77.6s; Ruff clean across `src` + `tests`; mypy strict clean
across 147 files, both proved locally this pass). CI runs `alembic upgrade head`
then `alembic downgrade base` against a fresh Postgres on **every** run, so
migration reversibility on an empty database is continuously proved — a stronger
posture than most projects this size. `services/bulk_history_reads.py` is a
model leaf module: forty lines of code and forty lines of measured reasoning.
And Batch 189's remediation was largely executed — of its 20 findings I could
re-check 14, and **9 are closed**.

**19 findings: 3 High, 9 Medium, 7 Low** (`CR236-01…19`), ranked severe-first.

---

## 236.1 — Re-verification of Batch 189

Checked against code at `2178381`, not against the batch notes.

| ID | Batch 189 finding | Status now | Evidence |
|---|---|---|---|
| CR189-01 | Coach launcher dot hard-coded to `weekly_review` | **Closed** | `CoachLauncher.tsx:84-88` now tests `PROACTIVE_COACH_ORIGIN_KINDS`; `coachOrigin.ts:39` carries `state_change`. |
| CR189-02 | Jobs continue on a poisoned Session | **Closed, and it opened CR236-01** | `_commit_morning_step` (`scheduler.py:910-928`) rolls back and returns a bool; 21 rollback sites now exist. The rollbacks are correct; what follows them is not. |
| CR189-03 | State-change coach unsynchronized | **Closed** | `state_change_coach.py:98-99, 245` take `pg_advisory_xact_lock` on a stable key. |
| CR189-05 | Two definitions of "VO2 today" | **Closed** | `_workout_has_vo2_intensity` (`morning_analysis.py:2821-2825`) delegates to `ir_has_vo2`; the name test survives only as the `HTTPException` fallback. |
| CR189-06 | Migration `022` backfill pairs sessions arbitrarily | **Open, now historical** | The CTE is unchanged at `022_post_activity_generation_status.py:101-197`. It has already run against production, so the remediation owed is a data check, not a code change. |
| CR189-07 | Unbounded scan of evaluation packets | **Closed** | `_previous_experiment_evaluation` (`state_change_coach.py:436-457`) filters and `.limit(1)` in SQL. It still selects the whole `Analysis` row — see CR236-13. |
| CR189-10 | No concurrency test for any lock or lease | **Partly closed** | `test_state_change_coach.py:232` now opens two sessions. `test_generation_requests.py` and `test_reviews.py` remain single-session. |
| CR189-11 | RLS guard test asserts a constant | **Closed** | `test_coach_rls_migration.py` gained `test_every_rls_migration_actually_emits_its_enable_statement`, which parses the migration source. |
| CR189-12 | Advisory lock held across the model call | **Closed by re-design** | Batch 232.1 moved both locks to `pg_try_advisory_xact_lock` (`generation_requests.py:344-348`, `reviews.py:729-737`), so nobody waits. The lock is still held across the call — deliberately, and documented. |
| CR189-13 | Asymmetric ownership predicate in learning joins | **Closed** | `conversation_learning.py:468` and `:759` both carry `Analysis.user_id == user_id`. |
| CR189-14 | Batch 184's "shared" assembly is a copy | **Open, unchanged** | `sleep_projection_context.py:137-204` still duplicates `daily_loop.py:749-815`. `diff` shows **three** differing hunks in 68 lines, two of them cosmetic. See CR236-12. |
| CR189-16 | `state-change` missing from the cron runbook | **Closed** | `docs/runbooks/scheduled-jobs-cron.md:47`. |
| CR189-18 | Prompt bump mid-Sunday yields two turns | **Open** | `reviews.py:738-743` still compares `prompt_version` after the lock. |
| CR189-20 | `run_scheduled.py` exits 0 on failure | **Closed** | `run_scheduled.py:88-90` raises `SystemExit(result.exit_code)`. |

Not re-checked (they belong to 237/238/240 this wave, or need production data):
`CR189-04`, `CR189-08`, `CR189-09`, `CR189-15`, `CR189-17`, `CR189-19`.

---

## 236.2 — Module health

### The god modules, measured

| File | LOC | What it holds | Verdict |
|---|---|---|---|
| `services/morning_analysis.py` | **3,027** | 1 client, 1 service (11 loaders), **60 module-level functions**, 26 sibling-service imports | The whole morning domain in one file |
| `scheduler.py` | **2,247** | 24 job coroutines + the Garmin daily-sync driver + the fan controller + profile-clock helpers; **47 of the codebase's 70 `except Exception`** | An application inside a module |
| `services/executable_coaching.py` | 1,816 | proposal/approval/push/swap lifecycle | Cohesive but large |
| `routers/daily_loop.py` | **1,719** | **45 Pydantic DTOs, 4 routes**, one 165-line `_envelope` | A serialization layer misfiled as a router |
| `services/chronic_patterns.py` | 1,544 | pattern detection + suggestion rendering | Two concerns |
| `services/post_workout_analysis.py` | 1,443 | ride read | See CR236-04 |
| `apps/web/src/pages/DashboardPage.tsx` | **2,230** | **34 components, 10 mutations, 12 `useState`** in one file | See CR236-11 |

**Cyclomatic complexity** (`ruff --select C901`, `max-complexity = 12`, run
isolated so the repo config is untouched) finds 13 functions over the line. The
top one is not close:

```
morning_analysis.py:2543  _morning_verdict            complexity 32   (261 lines)
scheduler.py:1069         run_morning_weather_sync    complexity 16
chronic_patterns.py:1456  _actions_for                complexity 15
```

`_morning_verdict` is the function that decides Green / Amber / Red. It is the
most complex function in the codebase by a factor of two, it takes 12 keyword
arguments, and it is the product.

### Coupling hotspots

`morning_analysis.py` imports **26 sibling services** (`:33-116`). It is the
convergence point for age norms, chronic patterns, coaching state, coverage,
phase, experiments, feedback, generation leases, holidays, insights, learned
context, personal baselines, sleep scoring, standing habits, training week,
verdict scaling, workload budget and workout delivery. Nothing else in the tree
comes close. Fan-in is more even — the most depended-on leaves are
`anthropic_text` (15), `workload_budget` (14), `daily_metric_phase` (13),
`bulk_history_reads` (11) — which is the right shape: small leaves, many callers.

**Where a leaf would pay for itself, in priority order:**

1. **`morning_verdict.py`** — `_morning_verdict` plus the eight predicates it
   calls (`_positive_hrv_evidence`, `_readiness_score_ok`, `_resting_hr_elevated`,
   `_sleep_credit_ceiling`, `_soft_sleep_recovery_override`, `_training_load_cap`,
   `_load_driven_eligibility`, `_hrv_below_baseline`) are already pure functions
   over plain values. Extracting them costs one import and gives the product's
   central decision its own file, its own test module and its own review surface.
2. **`post_activity_generation.py`** — see CR236-04.
3. **`routers/daily_loop_schemas.py`** — 45 DTOs out of the router leaves ~350
   lines of actual HTTP handling.
4. **`scheduler/` as a package** — one module per job family, keeping
   `create_scheduler()` as the registry.
5. **`workout_type` classification** — see CR236-05.

---

## 236.3 — The critical path, end to end

What a new engineer would get wrong, in the order they would hit it.

**There are three entry points, not one.**

| Trigger | Function | What it does |
|---|---|---|
| Wake (Garmin sleep stable) | `run_wake_check` → `run_morning_sync` (`scheduler.py:994`) | Sync inputs, push "good morning". **No generation.** |
| Mark's check-in (primary) | `PUT /daily-loop/{d}/manual-entry` → `BackgroundTasks` → `_generate_brief_after_checkin` (`routers/daily_loop.py:176`) | Sync, presence gate, generate, push, `mark_ready` |
| 11:00 local (backstop) | `run_morning_weather_sync` (`scheduler.py:1069`) | Sync, presence gate, generate, push, verdict proposals, chronic deload, drivers cache |

Five things are counter-intuitive:

1. **The wake job does not generate.** Batch 85 moved generation onto the
   check-in. `run_morning_sync` and `run_morning_weather_sync` are different jobs
   with confusingly adjacent names, and only the second one is exposed to the
   external cron (`run_scheduled.py:63`, as `morning-sync` — which maps to
   `run_morning_weather_sync`, not `run_morning_sync`). `run_morning_sync` is
   reachable **only** from the in-process scheduler.
2. **The two generating paths have opposite transaction contracts.** The router
   path threads `commit=False` through `regenerate_after_morning_checkin`,
   `push_brief_ready` and `mark_ready`, then commits once
   (`routers/daily_loop.py:206-224`) — brief, push audit and ready-status are
   atomic. The backstop commits each step and rolls back on error
   (`scheduler.py:1131-1245`) — a brief can exist with no push. Neither is
   wrong; nothing says which is the contract.
3. **The router imports a private scheduler function at function scope.**
   `routers/daily_loop.py:192`: `from src.scheduler import _sync_morning_inputs`.
   A router depending on the scheduler inverts the intended layering, and the
   local import exists only to break the resulting cycle.
4. **`BriefGenerationStatus` has exactly one writer, and it is the router.**
   `grep` finds `BriefGenerationStatusService` in `routers/daily_loop.py` and
   nowhere else. The backstop never marks generating/ready/failed. This is
   *safe* today only because `_serialize_brief_generation` short-circuits on
   `has_analysis` (`routers/daily_loop.py:1271-1272`) — a good read-time
   defence worth protecting — but it means the state machine has no owner.
5. **Generation runs in a FastAPI `BackgroundTask`**, i.e. in the same worker
   process after the response is flushed. A container restart loses it silently;
   Batch 144's read-time stale-`generating` derivation
   (`routers/daily_loop.py:1275-1276`) is the only backstop.

Downstream of `generate_and_store` the path is clean and worth saying so:
`assemble_context_packet` (`morning_analysis.py:495-842`) builds a packet,
`_morning_verdict` computes the status from that packet, `verdict_scaling`
receives the *already-computed* status as an argument, and the model never sees
the verdict decision. That separation held under Batch 189's scrutiny and still
holds.

---

## 236.4 — Error handling

70 `except Exception` handlers in `apps/api/src`; **47 are in `scheduler.py`**.
That concentration is not itself wrong — per-profile, per-date isolation is the
correct design for a batch job. The problems are what the handlers *do*.

**Class 1 — the handler raises (CR236-01).** 21 rollback sites; one of them
snapshots identifiers first. The rest read ORM attributes after the rollback.

**Class 2 — exceptions as cross-layer control flow (CR236-06).**
`GenerationRequestInProgress` is declared as an **`HTTPException`**
(`generation_requests.py:257`) and raised from two service modules. It travels
through a router (where it means 409), through two scheduler jobs (where it means
"skip") and through an async context manager whose own `except Exception` clause
performs a `session.flush()`. A transport concern is doing domain signalling
across four layers.

**Class 3 — `except Exception` around `session.flush()` in a failure path.**
`claim_generation_request` (`generation_requests.py:366-372`, `:402-409`):

```python
except Exception as exc:
    if claim.row.status != STATUS_FAILED:
        claim.mark_failed(str(getattr(exc, "reason", "generation_error")))
        await session.flush()
    raise
```

If the body failed for a *database* reason, the Session already needs a rollback
and this `flush()` raises `PendingRollbackError` — replacing the real exception
before the caller's `except AnthropicApiError` can classify it, and losing the
failure reason it was trying to record.

**Class 4 — error paths with no test.** `test_scheduler.py` contains no test in
which a real `AsyncSession` rolls back and the loop then continues. Every
"isolates failure" test uses `AsyncMock`.

---

## 236.5 — Async and session discipline

**What is right.** `expire_on_commit=False` (`database.py:35`) is the correct
`AsyncSession` setting and is applied consistently, including in test fixtures.
`prepared_statement_cache_size=0` is correct behind Supavisor and carries a
comment saying why. `bulk_history_reads.py` passes `raiseload=True` on every
projection *specifically* so an unforeseen reader fails loudly instead of
emitting a lazy SELECT — that is exactly the right instinct, and the module's
docstring names `MissingGreenlet` as the failure it is preventing.

**What is wrong.** `expire_on_commit=False` covers commit. Nothing covers
rollback, and rollback is the error path. See CR236-01.

**The identity-map trap named in Batch 235's gotcha is correctly reasoned.**
`bulk_history_reads.py:36-42` explains why `daily_metrics.raw_payload` is not
deferred: `daily_metric_coverage` reads it in the same session that
`morning_analysis` builds the chronic window in. I verified the direction of the
hazard: with `populate_existing=False`, a later full query *does* populate
previously-unloaded attributes, so a deferred-then-full order is safe and merely
forfeits the saving; it is the deferred object escaping to an unforeseen reader
that raises. The module's `raiseload=True` is the right guard for that, and the
one reader of `Sleep.raw_payload` (`bedroom_overnight.extract_hypnogram`) does
sit on its own session. The reasoning holds.

**Read paths that write.** `_envelope` — the serializer for every
`GET /api/v1/daily-loop` — calls
`ExperimentLoopService.ensure_assignment(..., commit=True)`
(`routers/daily_loop.py:1401-1407`). Batch 232 flagged this; it is unchanged and
deliberate ("showing a current-week REM action is the act of issuing it"). It is
correctly serialized — `ensure_assignment` takes a blocking
`pg_advisory_xact_lock` first (`experiment_loop.py:167-171`) — and it fires at
most once per ISO week. It is the *testing* of it that is absent (CR236-03).

---

## 236.6 — Test quality

**The suite is good at what it tests.** 108 files, 45,306 lines, 77.6s wall clock
for 1,095 local tests. Pure reducers are covered densely and specifically:
`test_batch230_reconcilable_figures.py`, `test_driver_levers.py`,
`test_generation_timeout_budgets.py` (which asserts the 600s wall rather than
leaving it in a comment) are all tests that would fail if the behaviour moved.

**Mutation battery.** I copied `apps/api` into the scratchpad, mutated one line
at a time, ran the full local suite, and reverted. Results:

| # | Mutation | Local suite |
|---|---|---|
| M1 | `_morning_verdict` Red sleep floor `< 60` → `< 50` | **6 failed** ✅ |
| M2 | `_morning_verdict` Amber sleep floor `< 74` → `< 70` | **9 failed** ✅ |
| M3 | `claim_generation_request`: never refuse a lost lock | **1 failed** ✅ |
| M4 | `_envelope`: `ensure_assignment(commit=True)` → `commit=False` | **1095 passed** ❌ |
| M5 | Delete the `rollback()` inside `_commit_morning_step` | **1095 passed** ⚠️ |
| M7 | `claim_generation_request`: invert the lease-expiry comparison | **1095 passed** ⚠️ |

M5 and M7 are marked ⚠️ rather than ❌ because both are plausibly caught by the
387 PostgreSQL tests that skip locally —
`test_scheduler.py:837` (`test_poisoned_garmin_step_recovers_session_for_verdict`)
for M5 and `test_generation_requests.py:466`
(`test_expired_or_failed_generation_lease_can_be_reclaimed`) for M7. I did not
have a Postgres to confirm, and say so rather than overclaiming.

**M4 is a genuine hole.** `grep -rn "ensure_assignment" apps/api/tests` returns
only `test_experiment_loop.py`, which exercises the service directly. No test
reaches the router branch, so nothing anywhere — local or CI — notices if
`GET /daily-loop` stops persisting the assignment Mark was actually shown.

**Coverage** (local suite only; CI's figure will be materially higher because
the 387 skips run there). Overall **66%**. Relevant modules:
`scheduler.py` 75.3%, `morning_analysis.py` 75.3%, `routers/daily_loop.py` 71.3%,
`anthropic_text.py` 94.5%, `verdict_scaling.py` 99%. The floor is
`executable_coaching.py` at **17.7%** and `state_change_coach.py` at **34.3%**
— the latter is Batch 189's `CR189-09` still visible in the numbers.
CI runs `pytest --cov` (`ci.yml:81`) with **no `--cov-fail-under`**, so the
number is produced and discarded.

**Batch 238's `AI238-02` (nothing inspects generated output) and `AI238-09` (the
highest-volume paid path records nothing) have a testability consequence worth
stating here:** with no stored artefact and no output assertion, the only
regression detector for the generation layer is a human reading the brief. That
is why the 43%-length regression in the wave's pre-audit finding was noticed by
Craig and not by CI, and it is why the highest-value test in the repo would be a
cheap structural assertion over stored `analyses.output_markdown` rather than
another unit test over a pure function.

---

## 236.7 — Dead and orphaned code

Seven top-level `*_backfill.py` scripts. Reachability, by `grep` over
`apps/api/src`, `apps/api/tests` and `scripts/`:

| Script | Referenced from | Local coverage | Status |
|---|---|---|---|
| `garmin_history_backfill.py` | `services/backup.py`, `tests/test_garmin_history_backfill.py` | 36% | **Live** — it is part of the backup/restore drill |
| `metric_baselines_backfill.py` | `scheduler.py` (the `baseline-refresh` job), `tests/` | covered | **Live** — not a one-off at all; the name is wrong |
| `ride_analysis_backfill.py` | nothing | not measured | Orphan |
| `walk_analysis_backfill.py` | nothing | **0%** | Orphan |
| `strength_analysis_backfill.py` | nothing | **0%** | Orphan |
| `flexibility_analysis_backfill.py` | nothing | **0%** | Orphan |
| `sleep_history_backfill.py` | nothing | **0%** | Orphan, and needs a workbook that is not in the repo |

Five orphans, ~150 lines, all importable from `src` and therefore all inside the
mypy/ruff surface and the deployed image.

---

## 236.8 — Migrations

**30 migrations, `001`–`030`. Every one has a `downgrade()`.** Several are
unusually careful: `023`'s pre-flight `DO $$` block refuses to strand an active
profile; `026` deletes unanchored rows before restoring `NOT NULL`; `028`'s
downgrade drops the wake-phase rows so the old unique constraint can be restored.

**CI proves reversibility on every run.** `ci.yml:83-113` has a dedicated
`migration-check` job that runs `alembic upgrade head` then
`alembic downgrade base` against a fresh Postgres 16. This is a genuinely strong
control and most repositories this size do not have it.

Three gaps:

1. **The round trip is one-way.** `upgrade head` → `downgrade base` is checked;
   `upgrade head` again is not. A downgrade that leaves residue (an orphaned
   index, an un-dropped type) passes today and breaks the first re-apply.
2. **Offline rendering diverges from online application** (CR236-08).
3. **No migration's data statement is tested.** `022`'s ~90-line backfill CTE is
   still the only data-modifying statement in the set and still has no test,
   which is how `CR189-06` survived.

Fresh-database sanity was checked offline: `alembic upgrade base:head --sql`
renders cleanly, 1,309 lines, all 30 revisions, and `001` creates the `coach`
schema before anything references it.

---

## 236.9 — Frontend

**What is right.** Every page that fetches handles both loading and error
(`useQuery` counts against `isLoading`/`isError` counts line up across all 17
pages). There are **two** error boundaries — one app-level (`App.tsx:95`) and one
keyed on `location.pathname` (`Layout.tsx:18`), so a crash in one route does not
strand the shell. Zod parsing happens at the query boundary in 30 files
(`useDailyLoop.ts:23`, `CheckInPage.tsx:129`, …), which means API drift surfaces
as a caught parse error rather than an `undefined` deep in a render. The
persisted-cache allow-list (`queryClient.ts:13`) is one key, deliberately.

**What is not.** `DashboardPage.tsx` is 2,230 lines holding 34 components, 10
`useMutation`s and 12 `useState`s; its test file is another 2,014. The components
inside it (`WorkoutRow`, `PostRideCheckInForm`, `RideIntervalTable`,
`CompletedRideLogForm`, …) are ordinary reusable components that happen to live
in a page file, and several duplicate patterns that already exist in
`components/`.

**Duplicated contract knowledge.** The zod mirror in `packages/shared` is the
right home and is used properly — I diffed `dailyLoopSchema`'s 24 top-level keys
against the FastAPI `DailyLoopData` model's 24 properties and they agree exactly.
But that agreement is maintained by hand: nothing compares the generated OpenAPI
document to the schemas (CR236-15). And one piece of *domain* knowledge is
duplicated across the language boundary with divergent semantics — see CR236-05.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| CR236-01 | **High** | `session.rollback()` expires every ORM object, so the scheduler's error handlers raise from inside themselves |
| CR236-02 | **High** | The morning brief has three entry points, two transaction contracts and no owner; the router imports a private scheduler helper |
| CR236-03 | **High** | The morning pipeline's failure isolation is tested only against mock sessions and mock profiles |
| CR236-04 | Med | Four post-activity analysis services are 68–78% identical, including four copies of a complexity-13 `generate_and_store` |
| CR236-05 | Med | `workout_type` is unconstrained free text classified by nine ad-hoc Python tests plus a divergent TypeScript implementation |
| CR236-06 | Med | `GenerationRequestInProgress` is an `HTTPException` used as cross-layer control flow, and its context manager flushes on a possibly-poisoned Session |
| CR236-07 | Med | `_morning_verdict` — the product's central decision — is a 261-line, complexity-32 function inside a 3,027-line module |
| CR236-08 | Med | Alembic's offline path omits `version_table_schema`, so `--sql` provisioning puts `alembic_version` in the wrong schema |
| CR236-09 | Med | `routers/daily_loop.py` is 45 DTOs and a 165-line serializer wearing a router's name |
| CR236-10 | Med | `scheduler.py` is 2,247 lines, 24 jobs and 47 of the codebase's 70 broad excepts |
| CR236-11 | Med | `DashboardPage.tsx` is a 2,230-line page holding 34 components and 10 mutations |
| CR236-12 | Med | Batch 184's "shared" projection assembly is still a byte-level copy of four `daily_loop` loaders |
| CR236-13 | Low | `select(Model)` is the default idiom and nothing lints it, which is why DS237-17's residuals keep reappearing |
| CR236-14 | Low | Five orphaned backfill scripts ship in the image; two live scripts are misnamed as backfills |
| CR236-15 | Low | No automated check that the zod schemas and the FastAPI models still agree |
| CR236-16 | Low | CI measures coverage and ignores it; no threshold, no trend |
| CR236-17 | Low | `run_scheduled.py`'s docstring and its `JOBS` map have drifted |
| CR236-18 | Low | The migration round trip is checked one way only |
| CR236-19 | Low | Two identical `except` bodies in `claim_generation_request`, and a `getattr(exc, "reason", …)` duck-type where a type test belongs |

---

### CR236-01 — High — `session.rollback()` expires every ORM object, so the scheduler's error handlers raise from inside themselves

**What is wrong.** `Session.rollback()` calls
`SessionTransaction._restore_snapshot(dirty_only=self.nested)`. For a top-level
transaction `nested` is `False`, so **every** state in the identity map is
expired — modified or not, and irrespective of `expire_on_commit`. Under an
`AsyncSession`, reading any attribute of an expired object (including the primary
key) attempts IO outside `greenlet_spawn` and raises
`sqlalchemy.exc.MissingGreenlet`.

Twenty of the scheduler's twenty-one rollback sites are immediately followed by
`str(profile.id)` inside a log call, or by handing an already-loaded ORM object
to the next service.

**Where.**

- `scheduler.py:592-597` — `except GenerationRequestInProgress` in
  `run_weekly_review_delivery`: `await session.rollback()` then
  `log.info(…, profile_id=str(profile.id), …)`.
- `scheduler.py:599-627` — the sibling `except Exception`: same shape, and the
  raise happens **before** `service.record_failure(...)` and
  `notify_admin_generation_failure(...)` on lines 609-620.
- `scheduler.py:695-701` (`run_state_change_coach`), `:1527-1533`
  (`_push_new_analyses`), `:1591-1597` (`run_post_workout_backstop`),
  `:1642-1648` (`run_workout_autopush`), `:892-899` (`_sync_garmin_daily`),
  `:971-976` (`_sync_morning_inputs`), `:1037-1043`, `:1133-1139`, `:1142-1148`,
  `:1163-1169`, `:1182-1188`, `:1197-1203`, `:1216-1222`.
- `scheduler.py:1163-1180` is the worst *intra*-iteration case: after the
  `push_brief_ready` handler rolls back, the same loop iteration passes the
  expired `profile` and `analysis_result.analysis` to `regenerate_for_verdict`
  (which reads `analysis` at `executable_coaching.py:224` before its first
  `await`), then to `propose_chronic_deload`, then to `record_drivers`. One push
  failure produces three further failures logged under three misleading messages.
- `routers/daily_loop.py:1702-1712` — the post-activity read handler rolls back
  and then hands `player`, `activity` and `prepared` to
  `mark_prepared_post_activity_failed`.
- **The one that gets it right:** `scheduler.py:294-297` hoists
  `profile_id = profile.id` before the `try`, with a comment naming this exact
  hazard. It was never generalised.

**Failure scenario.** Decision #266 deliberately runs the Railway `weekly-review`
cron alongside the in-process job. When they genuinely overlap, one loses
`pg_try_advisory_xact_lock` and `ReviewService.run` raises
`GenerationRequestInProgress` (`reviews.py:736-737`). Batch 232.1 added the
handler at `scheduler.py:584` precisely so that this is recorded as
`skipped_in_flight`, not as a failure. Instead: `str(profile.id)` raises
`MissingGreenlet`, which is not caught by the sibling `except Exception` (an
exception raised inside an `except` clause propagates past its siblings), escapes
the `for` loop, and is caught by the job's outer handler at `scheduler.py:653`,
which returns `JobResult.failed("weekly_review_failed")`. The job aborts for
every remaining profile, `job_runs` records a failure, and `run_scheduled.py`
exits 1. The designed outcome is reported as an outage.

The `except Exception` variant is worse: an ordinary Anthropic failure on the
weekly review now never reaches `record_failure` (no failure turn for Mark) or
`notify_admin_generation_failure` (no operator alert). This is a concrete,
mechanical reason the alerting Batch 238 credits the scheduler with
(`AI238-03`, "broad (correct)") does not actually fire on this path.

**Evidence.** `proved`. Three probes, in
`<scratchpad>/expire_probe2.py`, `async_probe.py`, `async_probe3.py`:

- Sync `Session` on the repo's own SQLAlchemy **2.0.51**, `expire_on_commit=False`:
  after `rollback()`, `inspect(obj).expired` is `True` for *untouched* objects and
  the next attribute read emits a fresh `SELECT`.
- Real `AsyncSession` (SQLAlchemy 2.0.52 + aiosqlite in an isolated scratch venv),
  reproducing the scheduler's loop shape verbatim: iteration 0 raises, the handler
  calls `await session.rollback()`, iteration 1 reads `profile.timezone` and
  fails with `MissingGreenlet`.
- Primary keys are not exempt: after rollback,
  `unloaded == ['id', 'timezone']` and **`profile.id` raises
  `MissingGreenlet`** — `greenlet_spawn has not been called; can't call
  await_only() here`.

`observed` for the enumeration of the 20 affected call sites.

**Fix shape.** Three layers, cheapest first.

1. **Hoist the identifiers.** Generalise `scheduler.py:294-297`: snapshot
   `profile_id`, `timezone` and `subject_date` into locals before every `try`,
   and log from the locals. Mechanical, no behaviour change.
2. **Stop sharing one Session across a profile loop.** Give each profile (and
   each date, in `_sync_garmin_daily`) its own `async with AsyncSessionLocal()`.
   Then a rollback expires only that iteration's objects and isolation is real
   rather than nominal. This is the structural fix and it also removes the
   cross-iteration coupling that made CR189-02 possible in the first place.
3. **Make it un-regressable.** One real-Postgres test per job family that loads a
   genuine `Profile` through the session, forces a step to fail, and asserts the
   loop still completes for a second profile. This is the same test
   `test_poisoned_garmin_step_recovers_session_for_verdict` already wants to be —
   it just needs a real profile instead of a `MagicMock` (see CR236-03).

---

### CR236-02 — High — the morning brief has three entry points, two transaction contracts and no owner

**What is wrong.** The most valuable pipeline in the product is implemented three
times in two modules, with different transaction semantics, different failure
recording and different names for the same thing. It has no single driver
function, no shared contract, and the differences are undocumented.

**Where.**

- `scheduler.py:994` `run_morning_sync` — wake: sync + nudge, no generation.
- `routers/daily_loop.py:176-278` `_generate_brief_after_checkin` — check-in:
  everything `commit=False`, one terminal `await session.commit()` at `:224`,
  `BriefGenerationStatusService.mark_failed` + admin alert in the handler.
- `scheduler.py:1069-1245` `run_morning_weather_sync` — 11:00 backstop: every
  step commits independently, `await session.rollback()` per handler, **no**
  `BriefGenerationStatus` write of any kind, admin alert only via the generic
  `JobResult` machinery.
- `run_scheduled.py:63` exposes `run_morning_weather_sync` under the name
  `morning-sync`, while the function actually called `run_morning_sync` is not
  exposed at all.
- `routers/daily_loop.py:192` — `from src.scheduler import _sync_morning_inputs`,
  a function-scope import of a private scheduler helper from a router.

**Failure scenario.** Every morning-path incident in the ledger is drift between
these three, each fixed in whichever copy it was noticed in: Batch 141 added the
failure card to the router path only; Batch 144 added the stale-`generating`
derivation at read time because no writer owned the transition; Batch 222 taught
the *router* to sync inputs by importing the scheduler's helper; Batch 232.1 had
to add the same `GenerationRequestInProgress` handler in two places
(`routers/daily_loop.py:225` and `scheduler.py:1129`) with two different bodies.
The next such fix will land in one copy again.

The concrete open asymmetry: a backstop generation failure writes no
`BriefGenerationStatus` row, so it produces no retryable failure card and no
Retry affordance — only a degraded `JobResult` behind DS237-01's missing operator
alert. It is survivable only because Mark can still check in and take the router
path.

**Evidence.** `observed` — read all three functions and the `run_scheduled.py`
job map end to end.

**Fix shape.** One `MorningBriefPipeline` service owning: input sync → presence
gate → generate → push → status write → downstream proposals, with an explicit
`commit` policy parameter and one `GenerationRequestInProgress` handler. The
three entry points become three thin callers that differ only in trigger and
policy. `_sync_morning_inputs` moves out of `scheduler.py` into that service, and
the router's cross-layer import disappears with it. Rename `run_morning_sync` →
`run_wake_nudge` so the two job names stop colliding.

---

### CR236-03 — High — the morning pipeline's failure isolation is tested only against mock sessions and mock profiles

**What is wrong.** Every test of the morning pipeline's error handling
substitutes `session = AsyncMock()` and `profile = MagicMock()`. A mocked
session's `rollback()` expires nothing; a `MagicMock` is never in an identity map.
The tests therefore assert that the *calls* were made in the right order, and are
structurally incapable of observing what the ORM does in response — which is
where CR236-01 lives.

**Where.**

- `test_scheduler.py:65-71` — `_profile()` returns a `MagicMock`.
- `test_scheduler.py:952-994` `test_poisoned_input_step_does_not_cost_verdict` —
  `session = AsyncMock()`, every service patched.
- `test_scheduler.py:883-950` `test_morning_weather_sync_runs_daily_sync_before_analysis`
  — asserts call ordering against a hand-built fake session.
- `test_scheduler.py:807-834` `test_sync_garmin_daily_isolates_profile_failure` —
  asserts `session.rollback.await_count == 4`, which is true whether or not the
  rollback is survivable.
- `test_scheduler.py:837-869` `test_poisoned_garmin_step_recovers_session_for_verdict`
  — the one real-Postgres test, written *specifically* to prove the CR189-02 fix.
  It asserts `await session.scalar(text("SELECT 1")) == 1`, i.e. that the
  connection is usable. It cannot see the expiry, because line 842 is
  `profile = _profile()` — a `MagicMock`.

**Failure scenario.** CR236-01 has been latent since the CR189-02 remediation
landed and would survive any amount of further testing in this style. The
mutation battery makes the same point from the other side: deleting the
`rollback()` from `_commit_morning_step` (M5) leaves 1,095 local tests green.

**Evidence.** `proved` — read the tests, and ran the mutation battery against a
scratchpad copy (results table in §236.6).

**Fix shape.** For the handful of tests that exist to prove *session* behaviour,
use a real `AsyncSession` over the `db_conn` fixture and a real `Profile` row.
Keep the mocks for the many tests that are genuinely about call ordering. The
distinguishing question to apply: *would this test still pass if the Session were
replaced by one that behaved incorrectly?* If yes, it is an ordering test and
should not be filed as an isolation test.

---

### CR236-04 — Medium — four post-activity analysis services are 68–78% identical

**What is wrong.** `post_workout_analysis.py` (1,443), `post_walk_analysis.py`
(772), `post_flexibility_analysis.py` (748) and `post_strength_analysis.py` (649)
are four copies of one lifecycle: pending-selector → packet → thin Anthropic
boundary → `claim_generation_request` → `Analysis` row → status write. Each
carries its own `generate_and_store` at cyclomatic complexity 13.

**Where.** Pairwise `difflib.SequenceMatcher` over the module line sequences:

```
post_flexibility vs post_strength   543 identical lines   ratio 0.78
post_walk        vs post_strength   512 identical lines   ratio 0.72
post_walk        vs post_flexibility 517 identical lines  ratio 0.68
```

The `generate_and_store` bodies are starker: `post_strength_analysis.py:335-500`
against `post_walk_analysis.py:345-510` differ in **34 of 166 lines**, and every
one of those 34 is a type name, a service name or the literal `"strength"` /
`"walk"`.

**Failure scenario.** A fix applied to one copy silently skips three. This has
already happened at least once inside the wave: Batch 232.1's
`GenerationRequestInProgress` handling is present in `post_workout_analysis` and
in the router's ride path; the other three readers inherit it only indirectly.

**Evidence.** `proved` — the diff and the similarity ratios were computed this
pass.

**Fix shape.** The abstraction already exists and is already trusted:
`post_activity_analysis.py` unified kind-selection and
`post_activity_state.py` unified the status lifecycle. Extend the same seam one
step further with a `PostActivityReadRunner` parameterised by
`(kind, packet_builder, prompt_builder, client, result_type)`. The four services
keep their packet builders and prompts — which is where the real per-discipline
content is — and lose ~450 lines of copied lifecycle each.

---

### CR236-05 — Medium — `workout_type` is unconstrained free text with ten classifiers, two of which disagree

**What is wrong.** `PlannedWorkout.workout_type` is `String(80)` with no enum and
no CHECK constraint (`models/coaching.py:416`). Ten separate pieces of code
classify it, nine in Python and one in TypeScript, and the two languages
implement different rules.

**Where.**

- Canonical leaf: `services/workout_categories.py:31-40` — explicit sets plus
  `bike_` / `strength_` / `walk_` prefixes, defaulting to `weights`.
- Bypassing it: `workout_delivery.py:130-136`, `week_ahead.py:69`,
  `weekly_mix.py:92` and `:436`, `weekly_restructure.py:146`,
  `executable_coaching.py:834`, `daily_loop.py:855` (`"strength" in …`),
  `morning_analysis.py:2825`.
- SQL: `022_post_activity_generation_status.py:139-159` re-implements the same
  mapping as a `CASE` expression inside the backfill.
- TypeScript: `apps/web/src/lib/workoutCategories.ts:12-26` uses **regexes**, not
  sets: `/bike|cycl|ride|vo2|sweet|endurance|tempo|threshold/`,
  `/deliberate.?walk/`, `/mobility|flex/`.

The two disagree for values the TS side explicitly expects. Its own
`WORKOUT_TYPE_LABELS` map (`:37-50`) lists `flexibility` and `deliberate_walk`;
`categoryForWorkoutType` sends those to `flexibility` and `walk`, while
`category_for_workout_type` sends both to **`weights`** (the fallback). A bare
`vo2` or `endurance` likewise reads as `cycle` in the app and `weights` in the API.

**Failure scenario.** Latent today: the shipped plan uses only four values
(`bike_endurance`, `bike_vo2`, `bike_sweet_spot`, `strength_maintenance`), all of
which classify identically. It becomes live the moment the block generator, the
quick-add sheet or a hand-authored plan introduces a value outside the four —
and the symptom is the app and the coach disagreeing about what kind of day it is,
with no error anywhere.

**Evidence.** `proved` for the two implementations and their divergence (read
both, traced the four live values through each); `observed` for the claim that no
other value currently reaches production.

**Fix shape.** Make the vocabulary explicit and shared: a literal union in
`packages/shared`, mirrored by a Python `StrEnum` and a CHECK constraint, with
`category_for_workout_type` the only classifier in Python and
`categoryForWorkoutType` a table lookup over the same union rather than a regex.
Then delete the eight ad-hoc string tests. Migration `022`'s `CASE` is historical
and can stay.

---

### CR236-06 — Medium — a transport exception carries domain control flow across four layers

**What is wrong.** `GenerationRequestInProgress` subclasses `HTTPException`
(`generation_requests.py:257-272`). It is raised in the service layer
(`generation_requests.py:348`, `:394`; `reviews.py:737`) and caught in four
places that each mean something different by it: a router (409 to the client,
`routers/daily_loop.py:1696`), a background task (silently return,
`routers/daily_loop.py:225`), and two scheduler jobs (count as skipped,
`scheduler.py:585`, `:1129`).

Two secondary problems follow from the shape:

1. Anything that catches broadly between the raise and the intended handler
   swallows it. This is exactly the Batch 232 defect, and the guard against a
   recurrence is currently four hand-written `except GenerationRequestInProgress`
   clauses that must each be remembered.
2. `claim_generation_request`'s own handler runs `await session.flush()` inside
   `except Exception` (`:366-372`, `:402-409`). If the body failed for a database
   reason, the Session already needs a rollback and that flush raises
   `PendingRollbackError`, replacing the original exception and losing the
   `failure_reason` it was recording.

The reason is extracted by `str(getattr(exc, "reason", "generation_error"))` —
a duck-type where `isinstance(exc, AnthropicApiError)` is meant, and it will
stringify any unrelated `.reason` attribute a future exception happens to carry.

**Failure scenario.** An `IntegrityError` during an analysis write becomes a
`PendingRollbackError` at the caller. `routers/daily_loop.py:239`'s reason
mapping falls through to `"other"`, so Mark gets the generic failure copy and the
`generation_requests` row keeps `status='running'` with a live lease until it
expires — the "stuck generating" class, from a different direction than Batch 144
covered.

**Evidence.** `observed` — read the exception class, all five raise sites and all
four handlers. Not reproduced; a Postgres session is needed to exercise it.

**Fix shape.** Declare a plain domain exception (`GenerationInProgress(Exception)`)
and translate it to 409 in one place — a FastAPI exception handler, or the router
boundary. Guard the recording path with `if session.in_transaction() and not
session.get_transaction().is_active: await session.rollback()` before the flush,
or record the failure on a fresh session. Replace the `getattr` with an
`isinstance` test against `AnthropicApiError`.

---

### CR236-07 — Medium — the product's central decision is a 261-line, complexity-32 function

**What is wrong.** `_morning_verdict` (`morning_analysis.py:2543-2804`) computes
Green / Amber / Red. It has cyclomatic complexity **32** — more than twice the
next-highest function in the codebase — takes 12 keyword arguments, and lives
1,000 lines below the service that calls it inside a 3,027-line module. Its
supporting predicates (`_positive_hrv_evidence`, `_readiness_score_ok`,
`_resting_hr_elevated`, `_sleep_credit_ceiling`, `_soft_sleep_recovery_override`,
`_training_load_cap`, `_load_driven_eligibility`, `_hrv_below_baseline`) are pure
and scattered across `:2412-2542` and `:2915-2948`.

**Failure scenario.** This is where three of Batch 240's safety findings land
(`HS240-01` an RHR 40 bpm over Mark's ceiling still produces Green; `HS240-02` an
acute HRV collapse is invisible; `HS240-17` the age credit crossing the Red line).
Each of those is a change to this function. At complexity 32, in a file this
size, with a 12-argument signature, every such change is a high-risk change and
its blast radius is hard to see. The mutation battery shows the *tests* are good
here (M1 caught by 6, M2 by 9) — the problem is reviewability, not coverage.

**Evidence.** `proved` — complexity measured this pass with
`ruff --isolated --select C901 --config 'lint.mccabe.max-complexity = 12'`.

**Fix shape.** Extract `services/morning_verdict.py` holding `_morning_verdict`
and its eight predicates, unchanged. The ladder itself then wants splitting into
a `_hard_gates` (Red), `_caution_gates` (Amber) and `_green_reasoning` sequence
returning `(status, reasons)` — which also gives Batch 240's fixes a named place
to land. Do this before 240's safety work, not after.

---

### CR236-08 — Medium — Alembic's offline path omits `version_table_schema`

**What is wrong.** `migrations/env.py` configures the online and offline paths
differently. Online (`:42-47`) passes `version_table_schema="coach"` and
`include_schemas=True`, and issues `CREATE SCHEMA IF NOT EXISTS coach` plus
`SET search_path` and `SET lock_timeout`. Offline (`:32-39`) passes none of them.

**Where.** `migrations/env.py:31-39` versus `:42-55`.

**Failure scenario.** `alembic upgrade base:head --sql` — the offline-validation
route recorded as this project's standard practice when no Postgres is available
— renders `CREATE TABLE alembic_version (…)` with **no schema qualifier**, so it
lands in whatever `search_path` resolves to (`public`) while the online path
writes it to `coach`. A database provisioned by piping that SQL is then invisible
to `alembic current`: the next online `upgrade head` sees an empty
`coach.alembic_version`, re-runs `001`, and fails on the first `CREATE TABLE`
that already exists. Offline SQL also silently omits the 5s `lock_timeout` guard.

**Evidence.** `proved` — rendered the full 1,309-line script offline this pass
and confirmed the unqualified `alembic_version` DDL at line 3 and the absence of
the lock timeout.

**Fix shape.** Add `version_table_schema="coach"` and `include_schemas=True` to
`run_migrations_offline`, and emit the `CREATE SCHEMA` / `SET search_path` /
`SET lock_timeout` statements via `op.execute` from a first-revision hook or a
literal preamble so both paths produce the same database.

---

### CR236-09 — Medium — `routers/daily_loop.py` is a serialization layer wearing a router's name

**What is wrong.** 1,719 lines containing **45 Pydantic response models**, a
165-line `_envelope` function, a Hive fan client wrapper (`:100-166`), a
background generation task (`:176-278`) and exactly **four** routes (`:1543`,
`:1565`, `:1612`, `:1638`). The HTTP surface is a small minority of the file.

**Failure scenario.** Two concrete ones already exist in the file. `_envelope`
performs a write and a commit (`:1401-1407`) because it is the only place that
sees the assembled suggestion — a responsibility a serializer should not have.
And the background task's need for input sync forced the cross-layer import at
`:192`. Both are consequences of one file owning transport, serialization,
orchestration and a device client.

**Evidence.** `observed` — counted with `grep -c "^class .*BaseModel"` and
`grep -n "^@router\."`.

**Fix shape.** `routers/daily_loop_schemas.py` for the 45 DTOs; a
`DailyLoopEnvelopeBuilder` service for `_envelope` (which also gives the REM
assignment write a testable home — CR236-03/M4); the fan wrapper into
`services/dreo_fan.py` or `services/hive_fan.py` alongside its siblings; the
background task into the CR236-02 pipeline service.

---

### CR236-10 — Medium — `scheduler.py` is an application inside a module

**What is wrong.** 2,247 lines holding 24 job coroutines, the Garmin daily-sync
driver (`_sync_garmin_daily`), the morning-inputs driver
(`_sync_morning_inputs`), the fan controller (`_apply_fan_control`,
`_record_fan_state`, `_execute_fan_decision`), the profile-clock helpers, two
retry wrappers and the APScheduler registry. **47 of the codebase's 70
`except Exception` handlers are in this one file** (67%).

**Failure scenario.** Concentration is why CR236-01 has 20 instances rather than
two: the same error-handling idiom was copied down the file 20 times, and the one
place it was corrected (`:294-297`) was invisible to the other 19 because nobody
reads 2,247 lines to write a new job. It is also why a router had to import a
private helper from here (CR236-02): the drivers live in the scheduler because
the scheduler is where they were first needed.

**Evidence.** `proved` — line count and `grep -c` this pass.

**Fix shape.** Turn `scheduler.py` into a package: `scheduler/morning.py`,
`scheduler/activities.py`, `scheduler/environment.py`, `scheduler/coach.py`,
`scheduler/ops.py`, with `scheduler/__init__.py` keeping `create_scheduler()` and
the public `run_*` names so `run_scheduled.py` and every test import is unchanged.
Move `_sync_morning_inputs` / `_sync_garmin_daily` out to services on the way.
Then the CR236-01 fix is 5 small reviewable diffs instead of one 20-site sweep.

---

### CR236-11 — Medium — `DashboardPage.tsx` is a 2,230-line page holding 34 components

**What is wrong.** The home screen file declares 34 components, 10
`useMutation`s and 12 `useState`s, and imports 30+ modules. Its test file is a
further 2,014 lines. Several of the declared components — `WorkoutRow`,
`WorkoutRowActions`, `RideIntervalTable`, `PostRideCheckInForm`,
`CompletedRideLogForm`, `ActivityCheckIn`, `ActualWorkoutForm` — are ordinary
reusable components with no dependency on the page, and at least one
(`WorkoutRow`) duplicates presentation that `WeekAheadPage.tsx` re-implements.

**Failure scenario.** No live defect found; this is a change-cost and
review-surface finding. Batch 241 owns the UX consequences. The concrete cost is
that the ten mutations share one `queryClient` invalidation surface, so any new
action has to be reasoned about against nine others in a 2,230-line context.

**Evidence.** `observed` — counted this pass.

**Fix shape.** Lift the seven independent components into `components/` (which
already holds 70 files and is the established home), leaving `DashboardPage` as
composition plus the mutations that genuinely belong to the page. Extract the
mutation cluster into a `useDailyLoopActions()` hook next to `useDailyLoop`.

---

### CR236-12 — Medium — Batch 184's "shared" projection assembly is still a copy

**What is wrong.** `CR189-14`, unfixed and unchanged.
`SleepProjectionContextService._activities`, `_latest_temperature`,
`_knowledge_base_content` and `_weather` (`sleep_projection_context.py:137-204`)
are a line-level copy of `DailyLoopService._activities`, `_latest_temperature`,
`_knowledge_base_content` and `_weather` (`daily_loop.py:749-815`).

**Where.** `diff` of the two 68-line regions produces three hunks: two
whitespace/temporary-variable differences inside `_activities` and the trailing
function boundary. The SQL, the filters and the timezone handling are identical.

**Failure scenario.** Decision-level: the app card and the evening push are meant
to be driven by one assembly, and Batch 189 recorded them as "behaviourally
holds; structurally a copy". Batch 235's egress work then had to be applied to
each history read individually; the next such sweep must remember there are two
copies of these four loaders. A divergence here is invisible — the two paths are
never compared by any test.

**Evidence.** `proved` — the diff was run this pass.

**Fix shape.** A `services/day_context_loaders.py` leaf with the four functions
taking `(session, user_id, subject_date, timezone)`, imported by both. The module
is small enough that this is a 30-minute change with no behaviour risk.

---

### CR236-13 — Low — `select(Model)` is the default idiom and nothing lints it

**What is wrong.** Batch 235 fixed the history windows and built the right leaf
(`bulk_history_reads.py`) to fix them with. But the default way to read a row in
this codebase is still `select(Model)`, so new full-row reads keep appearing —
including in code written *after* Batch 235.

**Where.** Batch 237's `DS237-17` names three (`post_workout_analysis.py:855`,
`post_walk_analysis.py:574`, `brief_chat.py:326`). This pass adds two more of the
same shape in `state_change_coach.py`: `_previous_experiment_evaluation`
(`:446-456`) and `_budget_decision` (`:467-478`) both `select(Analysis)` — a
model whose `context_packet` and `raw_response` JSONB columns average ~6.2 KB per
row — to read a handful of scalars. I am not re-reporting DS237-17; I am naming
the code-quality cause.

**Failure scenario.** The two incidents this app has had (Batch 232's pooler
refusals, Batch 235's 34.8 GB egress) both came from this idiom, and nothing
prevents the third.

**Evidence.** `observed`.

**Fix shape.** Not a lint rule — the false-positive rate would be unmanageable.
Instead: make `bulk_history_reads.py` the documented entry point for *any*
multi-row read of a JSONB-carrying model, name the four such models explicitly in
its docstring (`sleep`, `daily_metrics`, `temperature_readings`, `analyses`), and
add the check to `docs/agent-commands/batch-verify.md` so it is asked once per
batch rather than remembered.

---

### CR236-14 — Low — five orphaned backfill scripts ship in the image; two live ones are misnamed

**What is wrong.** Of seven top-level `*_backfill.py` modules, five are
unreachable from any code, test or script (`ride_analysis_backfill.py`,
`walk_analysis_backfill.py`, `strength_analysis_backfill.py`,
`flexibility_analysis_backfill.py`, `sleep_history_backfill.py`) — four measure
0% coverage locally. Conversely, `metric_baselines_backfill.py` is imported by
`scheduler.py` and is the implementation of the recurring `baseline-refresh` job,
and `garmin_history_backfill.py` is imported by `services/backup.py`. Neither is
a backfill; both are named as one.

**Failure scenario.** Low. The orphans are inside the mypy/ruff surface and the
deployed image, and each imports `AsyncSessionLocal` — so a future refactor pays
to keep them compiling, and an operator reading the directory cannot tell which
scripts are safe to run against production. `sleep_history_backfill.py`
additionally requires a workbook that is not in the repo.

**Evidence.** `proved` — reachability by `grep` over `src`/`tests`/`scripts`;
coverage from the run in §236.6.

**Fix shape.** Move the five one-offs to `scripts/one-off/` (outside the `src`
package, so they leave the type/lint surface and the image), each with a header
naming the batch that used it and the date it last ran. Rename
`metric_baselines_backfill.py` → `services/metric_baselines_refresh.py` and
`garmin_history_backfill.py` → `services/garmin_history_sync.py`.

---

### CR236-15 — Low — nothing checks that the zod schemas and the FastAPI models still agree

**What is wrong.** `packages/shared/src/schemas.ts` is 1,928 lines of zod
hand-mirroring 222 FastAPI component schemas. The mirror is used correctly — 30
web files `.parse()` at the query boundary — but the agreement is maintained by
hand and nothing verifies it. The FastAPI app already produces a complete
OpenAPI document at `/api/openapi.json`.

**Failure scenario.** zod objects strip unknown keys, so a *new* backend field
degrades silently (acceptable). A **renamed or newly-required** field throws at
parse time, which surfaces as a whole-page error rather than a missing value —
correct behaviour, but discovered by Mark rather than by CI.

**Evidence.** `proved` for the current state: I generated the OpenAPI document
and diffed `DailyLoopData`'s 24 properties against `dailyLoopSchema`'s 24
top-level keys. They match exactly, with no extras on either side. `observed` for
the absence of any automated check (`grep -rn openapi` over `apps/` and
`packages/` finds only `test_config.py`).

**Fix shape.** One test in `packages/shared` (or a small Python test) that loads a
committed `openapi.json` snapshot and asserts, for each envelope the web app
parses, that every `required` property has a corresponding non-optional zod key.
Regenerating the snapshot becomes part of any contract change, which is the point.

---

### CR236-16 — Low — CI measures coverage and ignores it

**What is wrong.** `ci.yml:81` runs `pytest --cov=src --cov-report=term-missing`
with no `--cov-fail-under` and no artifact upload, so the number is printed into
a log and discarded. There is no trend and no floor.

**Failure scenario.** `executable_coaching.py` at 17.7% and
`state_change_coach.py` at 34.3% (local suite) are exactly the modules Batch 189
flagged for thin coverage, and nothing in CI would notice them getting thinner.

**Evidence.** `proved` — read the workflow, ran coverage locally.

**Fix shape.** Add `--cov-fail-under` at the *current* CI number minus a small
margin (ratchet, not aspiration), and upload the XML so the trend is visible.
Resist a per-file threshold; the useful signal is "this PR made it worse".

---

### CR236-17 — Low — `run_scheduled.py`'s docstring and its `JOBS` map have drifted

**What is wrong.** The module docstring lists 14 jobs; `JOBS`
(`run_scheduled.py:57-73`) contains 15. `fan-control` is runnable and
undocumented. `run_morning_sync` — the wake nudge job — is in neither, so it
cannot be run from the external cron at all, while the docstring's `morning-sync`
entry describes `run_morning_weather_sync`.

**Failure scenario.** Same shape as `CR189-16` (which is closed): an operator
following the docstring during an incident cannot invoke a job that exists, or
invokes a differently-named one believing it is the wake job.

**Evidence.** `observed`.

**Fix shape.** Generate the docstring's job table from `JOBS` at import time, or
add a test asserting the two agree. Cross-check against
`docs/runbooks/scheduled-jobs-cron.md` in the same test.

---

### CR236-18 — Low — the migration round trip is checked one way only

**What is wrong.** `ci.yml:83-113` runs `alembic upgrade head` then
`alembic downgrade base`. It never runs `upgrade head` again.

**Failure scenario.** A downgrade that leaves residue — a surviving index, an
un-dropped enum type, an orphaned trigger — passes today and fails on the first
re-apply, which is precisely the situation a rollback drill would be run in.

**Evidence.** `observed` — read the workflow.

**Fix shape.** One extra line: `alembic upgrade head` after the downgrade. Costs
seconds and converts the job from "downgrade does not error" to "downgrade is
actually reversible".

---

### CR236-19 — Low — duplicated `except` bodies and a duck-typed reason in `claim_generation_request`

**What is wrong.** `generation_requests.py:365-372` and `:401-409` are the same
five lines twice, on the two branches of the insert-or-reuse decision. Both use
`str(getattr(exc, "reason", "generation_error"))`, which will stringify a
`.reason` attribute from any unrelated exception that happens to have one.

**Failure scenario.** Minor on its own; it is the mechanism by which CR236-06's
flush problem exists in two places rather than one, and by which a future
exception type could write a misleading `failure_reason` into the row that the
router then maps to user-facing copy.

**Evidence.** `observed`.

**Fix shape.** One inner helper `_fail_claim(session, claim, exc)` used by both
branches, with `isinstance(exc, AnthropicApiError)` in place of the `getattr`.

---

## What is done well — protect this

**The gates are real, and they are clean.** Proved this pass, locally:

```
pytest      1095 passed, 387 skipped        77.63s
ruff check  All checks passed!              (src + tests)
mypy src    Success: no issues found in 147 source files   (strict)
```

The 387 skips are the PostgreSQL-only tests and are expected. Nothing was
warning-suppressed to get there. `mypy` strict across 147 files on a codebase
this size, with async SQLAlchemy in it, is not free and someone has been paying
for it consistently.

**CI is unusually complete for a two-user private app.** Seven jobs: ruff (check
*and* format), mypy, pytest against a real Postgres 16 with `alembic upgrade head`
first, a **separate migration up/down job**, a web lint+typecheck+build, a
recursive `pnpm -r test` with a comment explaining exactly why `--dir apps/web`
is not enough (Batch 206's lesson, written down where it will be read), and a
security-audit job running pip-audit against a hash-pinned lockfile, a JS advisory
reviewer, an RLS posture check and gitleaks over full history. Do not let any of
these be quietly dropped for speed.

**`services/bulk_history_reads.py` is the reference for how a leaf module should
be written in this repo.** Forty lines of code, forty lines of measured
justification with real byte counts, an explicit statement of the one case it
deliberately does *not* cover (`daily_metrics.raw_payload`) and why, and
`raiseload=True` so an unforeseen reader fails loudly instead of silently
lazy-loading. If every extraction proposed above produced a module like this one,
the codebase would be in a different class.

**Read-time defences instead of writer complexity.** `_serialize_brief_generation`
(`routers/daily_loop.py:1257-1277`) derives a stale `generating` into a retryable
`failed` and lets a real analysis override any status row, with no writer, no
migration and no scheduler. That is the right instinct — it makes the state
machine forgiving of exactly the process-restart and orphan cases that a
background-task architecture produces.

**Comments that record measurements, not intentions.** `database.py:9-30`,
`generation_requests.py:315-340`, `config.py:27-53` and `verdict_scaling.py:61-67`
all explain a constant with the number that produced it and the incident that
motivated it. `generation_requests.py`'s docstring records "fifteen attempts
queued on the single key, eight acquired it after 40.4s to 117.6s, seven killed
at the 120s statement_timeout" — a future reader can re-derive the decision. This
is the single strongest thing about the codebase and it should be a hard rule for
every constant, not a habit.

**The verdict boundary holds.** `_morning_verdict` computes the status from a
packet; `verdict_scaling` receives the computed status as an argument and returns
`classificationImpact="none"`; the model never decides the verdict. Batch 189
verified this and it is still true after 47 batches. Whatever else changes,
protect the direction of that arrow.

**Test *specificity* where it exists is high.** `test_generation_timeout_budgets.py`
asserts the 600s wall rather than describing it in a comment;
`test_batch230_reconcilable_figures.py` pins a factual claim in the output;
`test_state_change_coach.py:232` genuinely opens two sessions against the advisory
lock. The mutation battery confirms it: the verdict thresholds are guarded by 6
and 9 tests respectively. The gap identified in CR236-03 is a gap in *technique*
on one axis, not a general weakness.

---

## The three highest-value fixes

**1. Snapshot before the try, then give each profile its own session
(CR236-01).** This is the only finding in this pass with a proved, silent,
production-reachable failure, and it disables the failure-recording and alerting
that three prior batches shipped. The first half — hoisting `profile_id` and
`timezone` into locals before every `try` in `scheduler.py`, exactly as
`:294-297` already does — is mechanical, un-risky and can land today. The second
half — one session per profile iteration — is the structural fix and should
follow. Pair it with the CR236-03 test change so it cannot come back.

**2. Extract `services/morning_verdict.py` before Batch 240's safety work lands
(CR236-07).** `HS240-01`, `HS240-02` and `HS240-17` are all edits to a 261-line,
complexity-32 function buried a thousand lines below its caller. Doing the
extraction first is the difference between three reviewable diffs and three
high-risk ones, and it gives the physiology fixes a named home with its own test
module. This is the highest-leverage ordering decision available in the wave.

**3. One `MorningBriefPipeline` that all three triggers call (CR236-02).** Every
morning-path defect in the ledger is drift between the check-in path, the
backstop and the wake job, and each was fixed in one copy. Consolidating the
pipeline retires the router's private import of a scheduler helper, gives
`BriefGenerationStatus` a single owner across all triggers, and makes the
transaction contract a parameter rather than an accident. It is the largest of
the three, and it is the one that stops this class of finding recurring in wave
five.

---

## Verification

Everything below was run this pass, from the repo root, using absolute paths and
without `cd` into the repo. Mutation and probe work ran against a **copy** of
`apps/api` in the session scratchpad; `git status` on the repository is unchanged
apart from this document.

| # | Check | Result |
|---|---|---|
| V1 | `pytest -c apps/api/pyproject.toml` | `1095 passed, 387 skipped` in 77.63s |
| V2 | `ruff check apps/api/src apps/api/tests` | `All checks passed!` |
| V3 | `mypy src` (strict, from `apps/api`) | `Success: no issues found in 147 source files` |
| V4 | `ruff --isolated --select C901 --config 'lint.mccabe.max-complexity = 12'` | 13 functions; `_morning_verdict` at 32 |
| V5 | Sync `Session.rollback()` expiry probe, SQLAlchemy 2.0.51 | untouched objects expire; next read emits SQL |
| V6 | `AsyncSession` scheduler-shape probe | iteration 1 raises `MissingGreenlet` |
| V7 | `AsyncSession` PK probe | `unloaded == ['id','timezone']`; `profile.id` raises `MissingGreenlet` |
| V8 | Mutation battery M1–M7 against a scratchpad copy | 4 caught, 1 uncaught, 2 CI-only (table in §236.6) |
| V9 | `pytest --cov=src` over the local suite | 66% overall; per-module figures in §236.6 |
| V10 | `alembic upgrade base:head --sql` | renders 1,309 lines; unqualified `alembic_version` at line 3 |
| V11 | OpenAPI generation + `DailyLoopData` ↔ `dailyLoopSchema` key diff | 24 vs 24, exact match |
| V12 | `difflib` similarity across the four post-activity services | ratios 0.68–0.78; 34/166 lines differ in `generate_and_store` |
| V13 | `diff` of the `sleep_projection_context` / `daily_loop` loaders | 3 hunks in 68 lines, 2 cosmetic |
| V14 | Backfill-script reachability `grep` | 5 of 7 unreferenced |

Scratchpad artefacts (not in the repo):
`expire_probe2.py`, `async_probe.py`, `async_probe3.py`, `sabotage.sh`,
`sabotage_line.sh`, `cov.json`, `openapi.json`, `full_migration.sql`.

## Explicit non-actions

- No production database was read; no Anthropic call was made. Those belong to
  Batches 237 and 238 and both had already run when this pass started.
- `DS237-17` (residual full-row reads), `AI238-02`/`AI238-03`/`AI238-09` (output
  inspection, alerting, chat observability) and `HS240-01`/`-02`/`-17` (verdict
  physiology) are **cross-referenced, not re-reported**. Where this pass adds
  something it is the code-quality cause (CR236-13 for DS237-17) or the ordering
  consequence (CR236-07 for HS240).
- No `DECISIONS.md` entry is contradicted. Decision #266 (deliberate cron
  overlap) and Decision #223 (read-time stale derivation) are both treated as
  settled; CR236-01 reports that #266's *implementation* raises, not that the
  decision is wrong.
