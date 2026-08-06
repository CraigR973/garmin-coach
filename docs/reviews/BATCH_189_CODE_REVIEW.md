# Batch 189 — Code review: the 157–187 delta + the new rails

**Date:** 2026-08-06
**Branch:** `chore/batch-189-code-review`
**Mode:** diagnose-only — this batch changes documentation, not product code,
migrations, configuration or production data
**Scope:** the diff `7e77169..cc344f0` — **82 commits, 228 files, +25,086 −3,362** —
plus the engine hotspots the delta touches: `services/state_change_coach.py`,
`services/weekly_review_delivery.py`, `services/sleep_projection_context.py`,
`services/generation_requests.py`, `services/verdict_scaling.py`,
`services/body_metrics.py`, `services/daily_metric_coverage.py`,
`services/morning_analysis.py`, `scheduler.py`, `run_scheduled.py`,
migrations `022`–`026`, and the backend/web test suites.
**Base:** `main` @ `cc344f0` (Batch 188 closed out)
**Not in scope:** deployed RLS state, backup recoverability, egress and cron
reliability (Batch 190); coaching quality on real data (Batch 191); the live UX
(Batch 192). Where this review touches those, it stops at the repo and hands off.

---

## Executive summary

**Most of the boundary claims hold, and several hold better than they had to.**
Batch 173's `verdict_scaling.py` is genuinely downstream of the verdict — the
packet builder takes the already-computed `status` as an *argument*
(`morning_analysis.py:1522-1545`), so it cannot feed back. Batch 176/177's
`body_metrics.py` is read-only and reaches only two packet builders. Batch 180's
coverage guard really does gate the driver correlation that chronic patterns
depend on (`insights.py:803`), and the load cap it might have disturbed reads only
`acuteChronicLoadRatio` and `recoveryTimeMin` (`morning_analysis.py:1125-1133`) —
never the stress or Body Battery columns the guard covers. Batch 178's
`TrainingWeekService.build_window` refactor is behaviour-preserving for the
existing caller (old `is_subject_date = day == end_date` and new
`is_before_subject_date = day < anchor` agree for every day in a week-to-date
window). Batch 179's nullable `analysis_id` is handled correctly by every consumer
I could find — router serialization, the per-read history filter, and both
`conversation_learning` joins. And RLS-enabled-without-policies in `022`/`024` is
not the anomaly it looks like: **no** `coach.*` RLS migration creates policies
(`015`, `019`, `020`, `021` included), so the pattern is consistent, and the
deployed check belongs to Batch 190.

**The two serious problems are both in the newest, least-exercised code.**

First, **Batch 187 shipped a feature with no way to notice it.** Decision #268
states that "Batch 185's unseen coach launcher is the visibility rail" and that no
new push type was needed. The launcher's unread dot is hard-coded to
`originKind === 'weekly_review'` (`CoachLauncher.tsx:80-82`), so a `state_change`
turn lights nothing, sends nothing, and is discoverable only if Mark happens to
open the coach sheet. The backend added `state_change` to its origin vocabulary
(`chat_context.py:129`); the shared schema and the frontend never did
(`schemas.ts:811-826`, `coachOrigin.ts:30-45`). The entire "the coach speaks when
something changes" rail is, in effect, mute.

Second, **the scheduler's per-step error isolation is not isolation.** Only the
two jobs added by Batches 185 and 187 call `session.rollback()` in their handlers
(`scheduler.py:261`, `283`, `325`). Every other job — including the morning
pipeline — catches, logs and carries on with the same Session. SQLAlchemy marks a
Session as needing rollback after a failed flush, so the next statement and the
trailing `commit()` both raise `PendingRollbackError` (**verified by execution**,
see Verification). In `_sync_garmin_daily` that means a single bad row on one of
the four re-synced dates poisons the Session, `_sync_morning_inputs`'s `commit()`
raises, and the whole of `run_morning_weather_sync` aborts before the verdict is
generated — logged as one line reading `morning weather sync failed`.

Then, in descending order: the state-change coach is the only new writer with **no
serialization at all** while the weekly review and the generation lease shipped in
the same window with an advisory lock each; detecting an experiment transition
*writes* an audit row, and one of its return paths never commits it, so those rows
are either discarded or committed under the **next profile's** transaction; the
morning read and the delivery rail use **two different definitions of "VO2
today"** — a workout-type name versus step intensity ≥106% FTP; migration `022`'s
backfill pairs the Nth activity to the Nth planned workout using two *unrelated*
arbitrary orderings and then overwrites `status` with `completed` without
excluding `skipped`.

**On test coverage, the pattern is clear and consistent: the pure functions are
well covered and the mechanisms are not.** The one database test for the
state-change coach subclasses the service and replaces `_candidates` with a fake
(`test_state_change_coach.py:78-90`), so the whole detection layer — including the
"derive previous state from stored packets" mechanism Decision #268 rests on — has
zero coverage. `run_state_change_coach` has no scheduler test. And **no test
anywhere opens two concurrent sessions against an advisory lock or the generation
lease**, so the suite cannot distinguish "serialized" from "unsynchronized" — even
though `test_auth.py:131` proves the project already knows how to write that test.

**20 findings: 2 High, 9 Medium, 9 Low** (`CR189-01…20`), ranked severe-first.

---

## 189.1 — The delta, and each batch's boundary claim

Verified independently against code, not against the batch note.

| Batch | Claim | Verdict | Evidence |
|---|---|---|---|
| **173** | `verdict_scaling.py` is explanatory; "never influences the verdict" | **Holds** | `_verdict_adjustment_packet(status, …)` takes the computed status as a parameter (`morning_analysis.py:1522`); `summarize_verdict_adjustment` returns `classificationImpact="none"` and is called after the ladder. No import of `verdict_scaling` appears above the verdict in `_morning_verdict`. |
| **176** | weight → W/kg, ride read only, no verdict change | **Holds** | `resolve_effective_weight_kg` is a single read-only `SELECT … LIMIT 1` (`body_metrics.py:28-62`) and is imported only by `post_workout_analysis.py:33`. |
| **177** | live VO2max overlays the packet profile only | **Holds** | `resolve_effective_vo2max` is imported by `morning_analysis.py:34` and `post_workout_analysis.py:33`; in the morning path it is consumed at `morning_analysis.py:396-398` during packet assembly, and `_morning_verdict`'s signature has no VO2max parameter. |
| **180** | coverage guards the morning narrative and chronic stress inputs; no verdict change | **Holds, with a named residual** | Three guard sites: `garmin_history_backfill.py:181`, `morning_analysis.py:1679`, `insights.py:803` (the driver correlation that feeds `chronic_patterns` via `sleep_drivers`). The verdict's only load inputs are `acuteChronicLoadRatio`/`recoveryTimeMin` (`morning_analysis.py:1125-1133`), neither of which the guard covers — so the verdict genuinely cannot move. **Residual:** five other consumers of the same partially-covered columns are unguarded — see **CR189-08**. |
| **182** | Red-cluster qualification does not change the daily verdict | **Holds** | `_morning_verdict` has no chronic parameter; `ChronicActionSignal` reaches the packet as `verdict.chronicAction` and the plan only via `propose_chronic_deload` on the propose/confirm rail (`scheduler.py:600-612`). `adjust_ir_for_chronic_deload` explicitly sets `"verdict": None` (`verdict_scaling.py:216-218`). |
| **178** | `build()` delegates to the new `build_window` unchanged | **Holds** | Verified by equivalence: for a week-to-date window every day satisfies `day <= end_date`, so `day == end_date` (old) and `not (day < anchor)` (new) select the same single day. |
| **179** | nullable `analysis_id`; every consumer handled | **Holds** | `serialize_message` (`brief_chat.py:93-105`) coerces to `None`; `history()` still filters on the anchor and is ownership-gated by `_owned_analysis`; both `conversation_learning` joins became outer joins. One asymmetry — **CR189-13**. |
| **184** | one shared sleep-projection assembly drives app and push | **Behaviourally holds; structurally it is a copy** | `sleep_projection_context._activities` (`:136-158`) is byte-for-byte `daily_loop._activities` (`:734-758`), and `_latest_temperature`, `_knowledge_base_content`, `_weather` and `_activity_local_date` are likewise duplicated — see **CR189-14**. |
| **185** | review/message/push idempotency makes cron+APScheduler overlap safe | **Holds** | `ReviewService.run` takes `pg_advisory_xact_lock` *before* the existence check (`reviews.py:697-706`) and the lock is transaction-scoped, so `WeeklyReviewDeliveryService.run`'s message dedupe and push all sit inside it. Under READ COMMITTED the blocked worker's post-lock `SELECT` sees the committed review. One narrow exception — **CR189-18**. |
| **187** | the launcher is the visibility rail; no new push type needed | **Does not hold** | **CR189-01.** |

---

## 189.2 — The asynchronous rails

Three writers were added in this window, and they use three different levels of
concurrency control:

| Writer | Mechanism | Assessment |
|---|---|---|
| `ReviewService.run` (185) | `pg_advisory_xact_lock(hash(user, period, period_start))` taken before the existence check, held to commit | **Sound.** Serialize-then-check is the right order; a second worker sees the first's committed row. |
| `claim_generation_request` (161) | `pg_advisory_xact_lock(lease_scope)` + `uq_generation_requests_identity` + a 3-minute lease | **Sound in design.** Belt and braces: the unique index bridges the `commit=False` window even if two callers pick different lease scopes. |
| `StateChangeCoachService.run` (187) | read `_budget_spent` → compute → read `_existing_analysis` → insert | **Unprotected.** No lock; `analyses` carries no unique constraint (`models/coaching.py:455-458`) — **CR189-03**. |

Transaction boundaries in the two new scheduler jobs are correct in the sense that
they roll back on failure — they are the *only* jobs that do (**CR189-02**). But
`StateChangeCoachService.run` has three exits and only two of them commit
(**CR189-04**), and detection has a write side effect that couples the experiment
audit trail to the unprompted-speech budget.

Idempotency under a double fire, by rail:

- **Weekly review** — genuinely idempotent. A second fire finds the review
  (same `PROMPT_VERSION`), finds the message (keyed on `review.id`), and
  `_send_once` finds the push audit. Zero writes, zero paid calls.
- **Generation lease** — idempotent per `request_identity`; a reclaimed expired
  lease correctly restarts.
- **State change** — idempotent *sequentially* (the budget check catches the
  second run, which is what `test_state_change_coach.py:118-119` asserts) but not
  *concurrently*.

The Railway cron picture is worth stating plainly: `run_scheduled.py:56` exposes
`state-change` as an external job, and `docs/runbooks/scheduled-jobs-cron.md`
explicitly instructs operators to run cron *alongside* the in-process scheduler
until cutover — the exact overlap the weekly review was given a lock for. The
`state-change` row is also absent from the runbook's cron table (**CR189-16**).

---

## 189.3 — Migrations 022–026 as a set

| Migration | Assessment |
|---|---|
| `022` post-activity generation status | Table/constraint shape is correct: `uq_…_user_activity`, FK cascade on `user_id`/`activity_id`, `SET NULL` on `planned_workout_id`. **The backfill is not** — **CR189-06**. |
| `023` device-token-only auth | **Good.** The pre-flight `DO $$` block refuses to strand an active profile before dropping anything, and the downgrade restores the columns with a disabled-PIN default. Reversible and guarded. |
| `024` generation requests | Correct. `uq_generation_requests_identity` is the constraint `claim_generation_request`'s `ON CONFLICT DO NOTHING` targets, and the composite `(user_id, status)` index matches the read. |
| `025` RLS hardening | Correct and idempotent (`DROP POLICY IF EXISTS` before each `CREATE`), `SET search_path` pinned on the trigger function, `(select auth.uid())` used so the initplan is hoisted. The downgrade faithfully restores the unhardened form. Deployed verification is Batch 190's. |
| `026` nullable coach anchor | Correct, and unusually careful — the downgrade deletes unanchored rows before restoring `NOT NULL`, which is the only honest reversal, and it adds the `(user_id, created_utc)` index the new read path needs while keeping `018`'s analysis index for the per-read view. |

**Nullable-anchor consumers** were enumerated and all handle `None`:
`routers/brief_chat.py:95-105` (serialization), `services/brief_chat.py:302-320`
(per-read history, ownership-gated), `services/conversation_learning.py:451-452`
and `:738-742` (both outer joins), `services/weekly_review_delivery.py:80`
(explicitly `is_(None)` for the failure turn),
`services/state_change_coach.py:508`, and `packages/shared/src/schemas.ts:830`
(`analysisId: z.string().uuid().nullable()`). The single defect is the join-clause
asymmetry in **CR189-13**.

**RLS coverage.** `022` and `024` enable RLS and create no policies — but so do
`015`, `019`, `020` and `021`. The pattern is deliberate and consistent
(deny-all to `authenticated`; the app connects as the table owner, which is
exempt unless `FORCE ROW LEVEL SECURITY` is set). Not a finding. The test that
guards it, however, is nominal — **CR189-11**.

---

## 189.4 — Test-gap analysis

18 new test files landed in this window and 71 test files were touched, so the
gaps are not for want of tests — they are consistently in the *same place*: the
pure reducers are covered, the mechanisms that make them safe are not.

**Gap 1 — the detection layer of the state-change coach (CR189-09).**
`test_state_change_coach.py` is 148 lines and four tests. Three are pure-function
tests over hand-built `StateSnapshot` values. The fourth is the only DB test, and
it subclasses the service to replace `_candidates` wholesale
(`test_state_change_coach.py:78-90`). Consequences: `_current_chronic`,
`_current_weekly_mix`, `_experiment_candidates`, `_previous_morning`,
`_previous_experiment_evaluation`, `_chronic_snapshot_from_packet` and
`_weekly_mix_snapshots_from_packet` are executed by no test. The Sunday skip
(`state_change_coach.py:356`) is untested. `run_state_change_coach` appears in no
scheduler test — `test_scheduler.py` imports and exercises
`run_weekly_review_delivery` only.

**Gap 2 — every concurrency mechanism (CR189-10).** `grep -rn "concurrent"` over
`apps/api/tests` returns exactly one hit, `test_auth.py:131`. The three
idempotency mechanisms shipped in this window are all tested by calling the
service twice in one session, which passes identically whether the lock exists or
not. `test_generation_requests.py`'s three tests
(`:63`, `:178`, `:281`) are all single-session, including the lease-reclaim test.

**Gap 3 — migration behaviour (CR189-11).** No test executes any migration.
`test_coach_rls_migration.py` loads each migration module and asserts its
`RLS_TABLES` *constant* covers `Base.metadata.tables` — a migration could declare
the constant and omit the `ALTER TABLE … ENABLE ROW LEVEL SECURITY` and the suite
would stay green. `test_auth_cutover_migration.py` likewise loads `023` by path
rather than running it. `022`'s ~90-line backfill CTE — the only data-modifying
statement in the set — has no test at all, which is how **CR189-06** survived.

**Gap 4 — prompt-string assertions standing in for behaviour.** 28 test files
assert on `PROMPT_VERSION`/system-prompt substrings. That is the right tool for
the floors audit, but it means several Batch 165–181 policy changes rest on "the
sentence is present in the prompt" rather than on an observed model behaviour or
a deterministic gate. Batch 188 already characterised this for the floors
registry (`CC188-04`, closed-world topic adjacency); this review confirms the
same shape in the read prompts and does not re-report it.

**Where coverage is genuinely good**, and worth saying: `test_chat_context.py`
(602 lines) exercises the trim order and budget against the real builder;
`verdict_scaling`'s properties are covered through `test_executable_coaching.py`
and `test_morning_analysis.py`; `test_daily_metric_coverage.py` covers the
boundary cases including the 23:55 final-sample tolerance; and
`test_weekly_review_delivery.py` asserts idempotency across all three writes
(review, message, push) in one test rather than three.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| CR189-01 | **High** | Batch 187's unprompted coach turn lights no unread indicator and sends no push — the launcher dot is hard-coded to `weekly_review` |
| CR189-02 | **High** | Scheduler jobs continue on a poisoned Session; one DB error aborts the whole morning pipeline before the verdict |
| CR189-03 | Med | `StateChangeCoachService.run` is an unsynchronized read-then-write, alone among the window's new writers |
| CR189-04 | Med | Detecting an experiment transition writes an audit row, and the `already_delivered` path never commits it |
| CR189-05 | Med | Two divergent definitions of "VO2 today": workout-type name vs step intensity |
| CR189-06 | Med | Migration `022`'s backfill pairs sessions by two unrelated arbitrary orderings and overwrites `skipped` with `completed` |
| CR189-07 | Med | `_previous_experiment_evaluation` loads every historical evaluation packet with no `LIMIT` |
| CR189-08 | Med | Batch 180's coverage guard reaches three call sites; five other consumers of the same columns are unguarded |
| CR189-09 | Med | The state-change coach's entire detection layer is untested; the only DB test fakes it out |
| CR189-10 | Med | No test exercises any advisory lock or lease concurrently |
| CR189-11 | Med | The RLS guard test asserts a constant, not the migration's SQL |
| CR189-12 | Low | A Postgres advisory lock and an open transaction are held across a 60-second Anthropic call |
| CR189-13 | Low | `conversation_learning._sources` omits the `Analysis.user_id` predicate its sibling join carries |
| CR189-14 | Low | Batch 184's "shared" projection assembly duplicates five loaders from `daily_loop.py` |
| CR189-15 | Low | `_send_once` push dedupe is a read-then-write with no constraint |
| CR189-16 | Low | The `state-change` job is exposed in `run_scheduled.py` but absent from the cron runbook |
| CR189-17 | Low | `safetyRulesApplied` reports the load cap when it was triggered but not applied |
| CR189-18 | Low | A `PROMPT_VERSION` bump between two same-Sunday fires yields two weekly-review turns |
| CR189-19 | Low | The weekly-review failure turn dedupes on exact message-string equality |
| CR189-20 | Low | `run_scheduled.py` exits 0 on internal failure, so a cron platform cannot alert on it |

---

### CR189-01 — High — Batch 187's coach turn has no visibility rail

**Where:** `apps/web/src/components/CoachLauncher.tsx:80-82`,
`packages/shared/src/schemas.ts:811-826`, `apps/web/src/lib/coachOrigin.ts:30-45`,
`apps/api/src/services/state_change_coach.py:28`,
`apps/api/src/services/chat_context.py:129`

```tsx
const hasUnreadAssistant = Boolean(
  newestAssistant?.originKind === 'weekly_review' && newestAssistant.id !== lastSeenAssistantId,
);
```

Decision #268 records the delivery decision as: write an assistant `BriefMessage`
with controlled origin `state_change` and **do not add a new push type**, because
"Batch 185's unseen coach launcher is the visibility rail". That rail was built by
Batch 185 for weekly reviews and was never widened. A `state_change` turn
therefore produces no push (by design), no unread dot (not by design), and no
entry anywhere else in the UI — `grep -rn "state_change" apps/web packages`
returns nothing.

The vocabulary drifted at the same time. Batch 187 added `"state_change"` to the
backend's `ORIGIN_KINDS` (`chat_context.py:129`) so the prompt can name the
surface, but `coachOriginKindSchema` and `ORIGIN_PROMPTS` still list the fourteen
Batch 179 origins. The frontend cannot express the origin it is receiving.

**Failure scenario.** The 11:45 job detects a chronic deload transition and writes
the turn. Mark's phone shows nothing. The launcher button shows nothing. He opens
the coach sheet three days later for an unrelated question and finds a
"Something changed" message about a recovery pattern that has since moved on —
and because the seven-day budget was spent silently on that turn, no *later*
transition could speak either.

**Remediation stub.** Widen the unread predicate from an origin equality to
"newest assistant turn was coach-initiated" — the set is exactly
`{weekly_review, state_change}` today, so it wants a shared constant in
`packages/shared` rather than a literal in the component. Add `state_change` to
`coachOriginKindSchema` and `ORIGIN_PROMPTS` in the same change. Decide explicitly
whether an unprompted turn deserves a push; if the answer stays no, the launcher
dot has to actually work, because it is then the only signal.

---

### CR189-02 — High — Scheduler jobs continue on a poisoned Session

**Where:** `apps/api/src/scheduler.py:404-424` (`_sync_garmin_daily`),
`:455-462` (`_sync_morning_inputs`), `:549-646` (`run_morning_weather_sync`);
contrast `:261`, `:283`, `:325`

Every per-step handler in the morning pipeline catches `Exception`, logs, and
continues on the same `AsyncSession`. Only the two jobs added by Batches 185 and
187 call `await session.rollback()` first. SQLAlchemy invalidates a Session after
a failed flush, so everything downstream on that Session raises
`PendingRollbackError` — confirmed by execution (see Verification):

```
step 1 failed as expected: IntegrityError
step 2 POISONED: PendingRollbackError: This Session's transaction has been rolled back …
commit POISONED: PendingRollbackError: This Session's transaction has been rolled back …
after an explicit rollback the session works again: True
```

`sync_daily` issues `SELECT`s and `session.add()`s (`garmin_sync.py:332-353`), so
a bad row surfaces at the next statement's autoflush — inside the `try`, where it
is logged and swallowed.

**Failure scenario.** Batch 180 widened the daily sync from one date to four
(`scheduler.py:404-407`). A constraint violation on D-2 is caught and logged;
D-3's `SELECT` autoflushes and raises `PendingRollbackError`, also caught and
logged; `_sync_morning_inputs`'s `await session.commit()` (`:462`) then raises
*outside* any per-step handler, unwinds past every remaining stage — morning
analysis, brief-ready push, Amber regeneration, chronic deload, driver cache — and
lands in the outer handler at `:646`, which emits a single line reading
`morning weather sync failed`. Mark gets no verdict that day and the log names
neither the profile nor the step.

**Remediation stub.** `await session.rollback()` in every per-step handler that
can follow a DB write, matching `:261`/`:283`/`:325`. Separately, give
`_sync_morning_inputs`'s two `commit()` calls their own guard so a commit failure
degrades the *inputs* rather than the verdict — the morning analysis should still
run on whatever synced successfully.

---

### CR189-03 — Medium — The state-change coach is the only unsynchronized new writer

**Where:** `apps/api/src/services/state_change_coach.py:228`, `:249-254`,
`:291-303`, `:452-464`; `apps/api/src/models/coaching.py:455-458`;
`run_scheduled.py:56`; `docs/runbooks/scheduled-jobs-cron.md`

`run()` reads the seven-day budget, computes candidates, re-reads for an existing
analysis, then inserts — with no lock. `analyses` has three plain indexes and no
unique constraint, so nothing at the database level prevents two overlapping runs
from both passing `_budget_spent` and both inserting an `Analysis` + `BriefMessage`.

This is a consistency finding as much as a correctness one: `ReviewService.run`
takes an advisory lock *specifically* because "the external cron and in-process
scheduler may overlap during cutover" (`reviews.py:697-699`), and
`claim_generation_request` uses a lock plus a unique index. The state-change
coach, shipped two batches later onto the same rail and exposed as the same kind
of external job, got neither. `max_instances=1` on the APScheduler job guards only
within one process.

**Failure scenario.** An operator follows the runbook's cutover instructions and
schedules `python -m src.run_scheduled state-change` while `SCHEDULER_ENABLED` is
still true. Both fire near 11:45; both see an empty budget; Mark gets two
unprompted turns in one morning, and the seven-day budget is now double-spent.

**Remediation stub.** Take `pg_advisory_xact_lock` on
`hash("state_change", user_id, as_of)` as the first statement in `run()`, before
`_budget_spent`, mirroring `reviews.py:700-706`. A partial unique index on
`analyses (user_id, subject_date) WHERE analysis_type = 'state_change_coach'`
would make the property structural rather than procedural.

---

### CR189-04 — Medium — Detection writes, and one exit path never commits

**Where:** `apps/api/src/services/state_change_coach.py:366-406`, `:249-263`,
`:239-247`, `:304-307`; `apps/api/src/services/experiment_evaluation.py:660-685`;
`apps/api/src/scheduler.py:311-330`

`_experiment_candidates` calls `ExperimentEvaluationService.run(..., commit=False)`
purely to read a recommendation. That call **inserts** an `experiment_evaluation`
`Analysis` when none exists for the subject date (`experiment_evaluation.py:668-681`).
Two consequences:

1. **The experiment audit trail is coupled to the unprompted-speech budget.**
   `_candidates` runs only after `_budget_spent` returns `False` (`:228-236`), so
   on any day the budget is already spent, no evaluation audit is written by this
   path at all.
2. **The `already_delivered` exit returns without committing** (`:255-263`), while
   `no_transition` (`:239-240`) and `delivered` (`:304-307`) both commit. The rows
   written during detection are left pending in the shared Session. In
   `run_state_change_coach` the Session spans every profile, so those rows are
   either discarded when the `async with` block closes, or committed under a
   *later* profile's `commit()`.

**Failure scenario.** Profile A hits `already_delivered`; its two experiment
evaluations stay pending. Profile B delivers a turn and commits. A's evaluation
rows land inside B's transaction — and if B instead raises, `scheduler.py:325`
rolls back A's rows too.

**Remediation stub.** Separate detection from evaluation: add a read-only
`ExperimentEvaluationService.evaluate`-based path for candidate detection (the
method already exists and is pure — `experiment_evaluation.py:464`), and leave
audit-row creation to the experiment job that owns it. Failing that, make every
exit of `run()` honour `commit` symmetrically.

---

### CR189-05 — Medium — Two definitions of "VO2 today"

**Where:** `apps/api/src/services/morning_analysis.py:1985-1989`, `:2142-2143`,
`:2190`; `apps/api/src/services/verdict_scaling.py:57-74`;
`apps/api/src/services/executable_coaching.py:95`, `:153-157`, `:839`

The morning read decides whether today holds VO2 work by matching the workout's
*type name*:

```python
has_vo2 = not is_rest_day and any(
    "vo2" in workout.workout_type.lower() …
```

The safety layer decides by *intensity* — any IR step at or above
`HIT_FLOOR_PCT = 106` (`verdict_scaling.py:57-63`). `bike_vo2` is the only
VO2-named type in the vocabulary, so the two tests are independent.

The project already recognises the coupling in one place: the interval editor
re-derives the type from the block's intensity on save
(`executable_coaching.py:839` → `block_workout_type`, `interval_workout_editor.py:197-202`,
which uses the same 106 threshold). It is not universal.
`apply_manual_override_to_ir` allows a working step up to
`MAX_MANUAL_POWER_PCT = 150` (`executable_coaching.py:95`, `:153-157`) and updates
no `workout_type`.

**Failure scenario.** A `bike_threshold` session carries a manual intensity
override to 115% FTP. The morning is Red. The read computes
`hasVo2WorkoutToday: false`, so `_plan_adjustments` never appends "Replace VO2
with rest, mobility, or a very easy spin" and the narrative describes an ordinary
eased day. `blocks_red_vo2` then refuses the push at delivery
(`executable_coaching.py:412`/`:522`). Mark reads a brief that does not mention
VO2 and finds the session did not arrive, with nothing connecting the two.

**Remediation stub.** Compute `has_vo2` from the IR via `ir_has_vo2` where an IR
is buildable, falling back to the type-name test only for non-structured
workouts — the exact pattern `_verdict_adjustment_packet` already uses
(`morning_analysis.py:1538-1541` builds the IR and returns `None` when it cannot).

---

### CR189-06 — Medium — Migration 022's backfill pairs sessions arbitrarily

**Where:** `migrations/versions/022_post_activity_generation_status.py:133`,
`:160`, `:163`, `:193`

The backfill ranks activities and planned workouts independently and joins them on
rank:

```sql
row_number() OVER (PARTITION BY p.user_id, p.subject_date, p.activity_kind
                   ORDER BY p.activity_id)   AS session_number   -- line 133
…
row_number() OVER (PARTITION BY w.user_id, w.workout_date, …
                   ORDER BY w.version DESC, w.id) AS session_number  -- line 160
```

`p.activity_id` is a v4 UUID, and `w.id` is a v4 UUID. **Neither ordering carries
any temporal or structural meaning, and they are unrelated to each other.** On any
day with two same-kind sessions the pairing is a coin flip. Time-of-day
(`activities.start_utc`) and the plan's own ordering were both available.

The statement then does something stronger than link:

```sql
UPDATE coach.planned_workouts AS w
SET status = 'completed'                 -- line 193
WHERE w.id IN (SELECT workout_id FROM linked_analyses)
```

with no exclusion for workouts already marked `skipped`, and `ranked_workouts`
filters only on `is_active IS TRUE` (line 163), not on status. A workout Mark
explicitly skipped can be flipped to `completed` by an activity matched to it
positionally.

This migration ran in production on 2026-07-26, so the finding is retrospective:
the question is whether Mark's history now contains a mislinked read or a
resurrected skip, not whether to change the migration.

**Remediation stub.** Do not amend `022`. Write a read-only audit query against
production that lists days with ≥2 same-kind post-activity analyses and compares
each `analyses.planned_workout_id` against the time-ordered pairing, plus any
`planned_workouts` whose `status` moved to `completed` on the migration date while
an `action_audit` row records a skip. Hand the result to Batch 190/191's data pass.

---

### CR189-07 — Medium — Unbounded scan of historical evaluation packets

**Where:** `apps/api/src/services/state_change_coach.py:423-450`

```python
select(Analysis)
    .where(Analysis.user_id == …, Analysis.analysis_type == AUDIT_TYPE_EVALUATION,
           Analysis.subject_date < before)
    .order_by(desc(Analysis.subject_date), desc(Analysis.generated_at_utc))
```

No `LIMIT`. Every historical evaluation row for the user is materialised — each
carrying a full JSONB `context_packet` — and then filtered in Python by
`packet.get("experimentId")`. This runs once per active experiment, every time the
job fires. With one evaluation per active experiment per day, the scan grows
linearly forever, and the work is quadratic in the number of active experiments.

**Remediation stub.** Push the `experimentId` predicate into SQL against the JSONB
column and add `.limit(1)`; the `(user_id, analysis_type, subject_date)` index
already exists (`models/coaching.py:456`). Storing `experiment_id` on the audit
row would be cleaner still, but that needs a migration and belongs in a
remediation batch, not here.

---

### CR189-08 — Medium — The coverage guard reaches three call sites, not all consumers

**Where:** guarded — `morning_analysis.py:1679-1703`, `insights.py:803`,
`garmin_history_backfill.py:181`; unguarded —
`metric_baselines.py:93`, `reviews.py:427` and `:813-814`, `sleep_history.py:71`,
`routers/daily_loop.py:960-961`, `morning_analysis.py:1115-1116`

Batch 180's stated scope — the morning whole-day narrative and chronic stress
inputs — is correctly implemented. But `daily_metrics.body_battery_charged` /
`body_battery_drained` and the stress columns are read by five further consumers
with no coverage check. `metric_baselines.sample_values` feeds
`body_battery_charge` into the rolling personal baselines; `reviews._build_rollup`
averages it across the week; `sleep_history` and the daily-loop envelope surface
it directly.

This is not a verdict risk — the verdict's only load inputs are ACWR and recovery
time, neither of which the guard covers (`morning_analysis.py:1125-1133`) — but a
morning-written partial row can still skew a baseline band and a weekly average.
Batch 180's note does not mention the residual, which is what makes it worth
recording.

**Remediation stub.** Decide the policy once: either the partial row should never
be written with aggregate columns populated (fail closed at
`garmin_sync.sync_daily`), or every consumer reads through a shared
`coverage_gated_metric()` helper. The current split — one guard at three sites,
raw columns everywhere else — is the state that will drift.

---

### CR189-09 — Medium — The state-change coach's detection layer is untested

**Where:** `apps/api/tests/test_state_change_coach.py:78-90`, `:93-148`;
`apps/api/tests/test_scheduler.py`

```python
class FakeStateChangeCoachService(StateChangeCoachService):
    async def _candidates(self, player, *, as_of):
        return self._fake_candidates
```

The only database-backed test replaces the method under review. Untested as a
result: `_current_chronic`, `_current_weekly_mix`, `_experiment_candidates`,
`_previous_morning`, `_previous_experiment_evaluation`,
`_chronic_snapshot_from_packet`, `_weekly_mix_snapshots_from_packet`, and the
Sunday skip at `:356`. That set *is* Decision #268's central design claim —
"previous state is derived from existing evaluation/audit rows" — and nothing
executes it. `run_state_change_coach` has no scheduler test; `test_scheduler.py`
covers `run_weekly_review_delivery` only (`:259`, `:297-300`).

**Remediation stub.** One DB test that seeds yesterday's morning `Analysis` with a
`verdict.chronicAction` packet and today's live chronic signal, then asserts a
transition is detected — and its negative, where the two packets agree. One
scheduler test for `run_state_change_coach` mirroring the existing
`run_weekly_review_delivery` rollback test.

---

### CR189-10 — Medium — No concurrency test for any lock or lease

**Where:** `apps/api/tests/test_generation_requests.py:63`, `:178`, `:281`;
`apps/api/tests/test_weekly_review_delivery.py:56`; contrast
`apps/api/tests/test_auth.py:131`

Every idempotency test in this window calls the service twice on one session. That
assertion passes identically whether the advisory lock is present or removed —
it proves the *existence check* works, not the *serialization*. The lease-reclaim
test (`:281`) likewise never has two claimants in flight simultaneously.

`test_auth.py:131` (`test_concurrent_activation_consumes_code_once_and_mints_one_device`)
shows the project already has this capability against the PostgreSQL fixture.

**Remediation stub.** One test per mechanism, modelled on `test_auth.py:131`: two
`AsyncSession`s on separate connections entering `claim_generation_request` /
`ReviewService.run` for the same scope, asserting one proceeds and one either
blocks-then-reuses or raises `GenerationRequestInProgress`. These are the tests
that would fail today against `StateChangeCoachService.run` (CR189-03).

---

### CR189-11 — Medium — The RLS guard test asserts a constant, not the SQL

**Where:** `apps/api/tests/test_coach_rls_migration.py:59-85`

```python
def _all_rls_tables() -> set[str]:
    for filename in RLS_MIGRATION_FILES:
        tables |= set(_load_migration(filename).RLS_TABLES)
```

The test imports each migration module and reads its `RLS_TABLES` tuple. It never
inspects the `upgrade()` body and never runs it. A future migration that declares
`RLS_TABLES = ("new_table",)` and omits the
`ALTER TABLE … ENABLE ROW LEVEL SECURITY` passes the suite while shipping an
unprotected table — the exact gap the docstring says it exists to prevent.

The check is still worth keeping: it catches the *forgotten table*, which is the
more common mistake. It just should not be read as evidence that RLS is on.

**Remediation stub.** Either assert the migration source contains an
`ENABLE ROW LEVEL SECURITY` statement naming each table in its own `RLS_TABLES`,
or (better) add one PostgreSQL-fixture test querying `pg_class.relrowsecurity`
after `alembic upgrade head`. Deployed-state verification stays Batch 190's.

---

### CR189-12 — Low — An advisory lock is held across a 60-second model call

**Where:** `apps/api/src/services/reviews.py:700-721`,
`apps/api/src/services/generation_requests.py:191-192` (through the `yield`)

Both mechanisms take `pg_advisory_xact_lock` and then perform the Anthropic HTTP
call inside the same transaction. The connection, its transaction, and the lock
are all held for the duration of an external network call with a 60-second
timeout. On the Supabase pooler in session mode that is a pooled connection held
idle-in-transaction. It is the correct trade for correctness and the concurrency
here is one user, but it is worth recording as a known cost rather than
rediscovering it under load.

---

### CR189-13 — Low — Asymmetric ownership predicate in the learning joins

**Where:** `apps/api/src/services/conversation_learning.py:451-452` vs `:738-742`

```python
.outerjoin(Analysis, BriefMessage.analysis_id == Analysis.id)                       # _sources
.outerjoin(Analysis, (BriefMessage.analysis_id == Analysis.id)
                     & (Analysis.user_id == user_id))                              # _resolve_source
```

`_sources` omits the `Analysis.user_id` predicate its sibling carries. Not
currently exploitable — `BriefChatService._owned_analysis` (`brief_chat.py:291-300`)
403s before a cross-user anchor can be written — so this is defence in depth that
one of the two joins has and the other does not.

---

### CR189-14 — Low — Batch 184's "shared" assembly is a copy

**Where:** `apps/api/src/services/sleep_projection_context.py:136-207` vs
`apps/api/src/services/daily_loop.py:65-70`, `:734-799`

`_activities`, `_latest_temperature`, `_knowledge_base_content`, `_weather` and
`_activity_local_date` are duplicated verbatim between the two services. The
behaviour is identical today, which is why the batch's claim of one shared
projection holds — but `_activity_local_date` now exists in **four** files
(`training_week.py:465`, `daily_loop.py:65`, `sleep_projection_context.py:202`,
`post_workout_analysis.py:941`), so a timezone fix has four places to land.

---

### CR189-15 — Low — Push dedupe is a read-then-write with no constraint

**Where:** `apps/api/src/services/nudge_alerts.py:817-856`

`_send_once` checks `_already_recorded(user, analysis_type, tag, subject_date)`
then sends and inserts the audit `Analysis`. No lock, no unique constraint. The
weekly-review path inherits the review's advisory lock and is therefore safe; the
brief-ready, good-morning and evening-nudge paths are not. Same shape as
CR189-03, lower stakes (a duplicate push, not a duplicate coach turn).

---

### CR189-16 — Low — `state-change` is missing from the cron runbook

**Where:** `apps/api/src/run_scheduled.py:23`, `:56`;
`docs/runbooks/scheduled-jobs-cron.md` (external-cron table)

The job is exposed and documented in the module docstring but absent from the
runbook's cadence table, which is the document an operator provisions from. Given
CR189-03, scheduling it externally today is the exact thing that is unsafe — so
the omission is currently protective and should be replaced with an explicit note
rather than a row.

---

### CR189-17 — Low — `safetyRulesApplied` reports a rule that was not applied

**Where:** `apps/api/src/services/morning_analysis.py:2123-2128`, `:2156-2158`

```python
if training_load_cap["triggered"]:
    safety_rules.append("training_load_amber_cap")
```

The cap only *does* anything when the status was Green (`:2124-2126`). On a Red or
already-Amber morning with a high ACWR, `trainingLoadCap.applied` is `False` while
`safetyRulesApplied` lists the rule. The two adjacent flags in the same packet
(`sleep_credit_ceiling["applied"]`, `cumulative_escalation["applied"]`) both gate
on `applied`. Packet honesty, not behaviour.

---

### CR189-18 — Low — A prompt-version bump mid-Sunday yields two review turns

**Where:** `apps/api/src/services/reviews.py:707-712`;
`apps/api/src/services/weekly_review_delivery.py:126-152`

`ReviewService.run` reuses the stored review only when
`latest_review.prompt_version == PROMPT_VERSION`. The delivery service dedupes the
thread message on `analysis_id == review.id`. If a deploy changes the review
prompt version between the 17:00 and 18:00 UTC cron candidates (or between the
cron and the in-process job), the second fire generates a *new* review row and
therefore inserts a *second* assistant turn for the same week. The push still
dedupes on `(analysis_type, tag, subject_date)`, so there is no second
notification. Narrow, but the message dedupe should key on the week, not the row.

---

### CR189-19 — Low — The failure turn dedupes on exact string equality

**Where:** `apps/api/src/services/weekly_review_delivery.py:74-89`

`record_failure` finds an existing failure turn by
`BriefMessage.content == WEEKLY_REVIEW_FAILURE_MESSAGE`. Editing that constant —
a copy change, the most likely kind — silently breaks the dedupe, and a repeatedly
failing Sunday would then stack turns. `origin_kind` + `origin_date` + `role`
already identify the row uniquely without the content comparison.

---

### CR189-20 — Low — The cron runner exits 0 on internal failure

**Where:** `apps/api/src/run_scheduled.py:9-12`, `:70-76`

The runner deliberately mirrors the in-process scheduler by letting job functions
swallow their own errors, so `python -m src.run_scheduled weekly-review` exits 0
whether the review was delivered or the job logged an exception. The runbook says
so explicitly ("Watch the logs, not the exit code"). That is a defensible choice
for a job that must not fail a deploy, but it means the Railway cron service's own
success/failure signal carries no information — and it compounds the Decision #258
stale-SHA gap, where a silent platform failure had no automated detector. Batch
190.5 owns the detection question; this records the code-level reason the exit
code cannot be part of the answer.

---

## Verification

Diagnose-only. No product code, prompt, migration, configuration or production
data was touched; the branch adds this document.

- **Focused backend pytest** over the suites this review makes claims about —
  `test_state_change_coach.py`, `test_weekly_review_delivery.py`,
  `test_generation_requests.py`, `test_chat_context.py`,
  `test_coach_rls_migration.py`, `test_auth_cutover_migration.py`,
  `test_scheduler.py`: **42 passed, 27 skipped** (the skips are the expected
  PostgreSQL-fixture tests, which run in CI).
- **CR189-02 was confirmed by execution**, not inference. A throwaway script in
  the session scratchpad (not added to the repo) drove SQLAlchemy's Session state
  machine through the exact sequence `scheduler.py` performs — failed flush,
  caught and logged, continue on the same Session — and reproduced
  `PendingRollbackError` on both the next statement and the trailing `commit()`,
  with recovery after an explicit `rollback()`. The sync `Session` was used
  because it is the same `_SessionTransaction` state machine `AsyncSession`
  delegates to and needs no async driver.
- **CR189-01, CR189-05, CR189-06, CR189-13** were each confirmed by reading both
  sides of the divergence rather than one, and the negative greps are recorded
  inline (`grep -rn "state_change" apps/web packages` → no hits;
  `grep -rn "concurrent" apps/api/tests` → one hit).
- **The `022`/`024` RLS-without-policies shape was checked against `015`, `019`,
  `020` and `021` before being written up**, and is not a finding — all six behave
  the same way.
- No production database was queried. The `022` backfill finding is a code
  reading; whether it actually mislinked anything in Mark's history is a
  production-data question and is handed to Batch 190/191.

## Remediation stubs

Every stub above is a review-local placeholder. **No ledger batch numbers are
allocated here** — the whole wave (188–192) is triaged into one roadmap for
Craig's approval before any remediation code starts, exactly as
`BATCH_153-156_REMEDIATION_ROADMAP.md` sequenced R1–R9.

Two findings are worth flagging for the roadmap as *cheap and high-value*:
**CR189-01** is a handful of lines across one component and one shared enum, and
it restores a feature that is currently dark; **CR189-02** is a `rollback()` call
per handler and removes a single-point failure on the morning verdict.
