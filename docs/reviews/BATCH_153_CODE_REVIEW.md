# Batch 153 code review — recent batches 147–152 + engine hotspots

**Date:** 2026-07-25
**Branch:** `chore/batch-153-code-review`
**Mode:** diagnose-only — this batch changes documentation, not product code
**Reviewed commits:** `cb666de` (147), `8e249c5` (148), `546070f`
(149), `fc4203e` (150), `071992e` (151), `35a90d7` (152)

## Executive summary

The central coaching-safety claim held across all six batches: none created a
new path that can change the deterministic Green/Amber/Red classification,
#133/#135 missing-data rules, verdict thresholds, or Red-never-VO2. Batch 151's
confirmed `learned_context` is narrative context only; Batch 150's post-session
chat cannot mutate the plan; and Batch 147 runs the hard Red/VO2 gate against
the fully expanded interval workout before delivery.

The review nevertheless found **two High, five Medium, and one Low** material
issues:

1. a failed intervals.icu replacement can commit the new local workout pointer
   while leaving the old cloud workout in place, after which reconciliation
   incorrectly decides there is nothing to retry;
2. Batch 152's Week lookup cannot return completed strength, flexibility, or
   walk reads and does not distinguish absent, generating, and failed states;
3. follow-up chat turns have nondeterministic same-timestamp ordering and the
   post-session prompt can promise an adjustment affordance that the code
   deliberately withholds;
4. identical concurrent generation requests can create duplicate paid calls
   and current-version analysis rows;
5. prompt-version invalidation is inconsistent across analysis services;
6. conversation-learning and pending post-session scans contain avoidable
   N+1 query loops;
7. Plan Week groups activities by UTC date rather than profile-local date; and
8. malformed deliverable workouts are silently skipped without a durable
   operator- or user-visible failure.

Each finding below has a proposed remediation-batch stub. The identifiers are
review-local placeholders, not allocated ledger batch numbers.

## Ranked findings

### CR153-01 — High — failed cloud replacement can commit a false local delivery state and suppress retry

**Evidence**

- `ExecutableCoachingService._deliver_one` mutates
  `live.planned_workout_id` and `live.planned_workout_version` before calling
  `replace_event(..., commit=False)` (`apps/api/src/services/executable_coaching.py:602-617`).
- `approve_interval_edit` deactivates the current workout, inserts its
  replacement, and calls `WorkoutDeliveryService.approve`; `approve` performs a
  full session commit (`apps/api/src/services/executable_coaching.py:764-805`,
  `apps/api/src/services/workout_delivery.py:529-548`). It then repoints the live
  proposal before the cloud replacement (`executable_coaching.py:807-817`).
- On an intervals.icu `HTTPException`, `replace_event` writes `last_error` and
  calls `session.commit()` even when its caller supplied `commit=False`
  (`apps/api/src/services/workout_delivery.py:651-675`). That commit also
  persists any caller-owned dirty ORM state, including the new pointer/version.
- The next `_deliver_one` pass treats pointer/version equality as proof that the
  exact workout is already on Zwift and returns early
  (`executable_coaching.py:605-610`), although the cloud event still carries the
  previous IR.
- The same pre-repoint pattern exists in `_resync_event`
  (`executable_coaching.py:1101-1116`), so this is a delivery-rail transaction
  problem rather than an interval-editor-only problem.

**Impact**

A transient external update failure can leave the app claiming that the newest
workout version is live while Zwift still has the previous content. The stored
pointer then blocks the normal reconciliation retry. In Batch 147's exact
interval editor, Mark could approve one interval structure and receive another.

**Test gap**

The replacement service has an isolation test proving that the old IR remains
after a failed cloud write, but the test does not include a real caller with
dirty workout/pointer changes in the same session. Batch 147 covers successful
replacement and the Red/VO2 gate, not external-update failure followed by
reconciliation.

**Proposed remediation batch R153-A — atomic delivery replacement and retry**

- Make failed cloud operations roll back or isolate caller-owned mutations;
  `commit=False` must never commit the surrounding unit of work.
- Persist the new workout pointer/version only after the cloud update succeeds,
  or explicitly restore the old values on failure.
- Do not use pointer/version alone as evidence that cloud content is current;
  retain a content/version fingerprint or retryable sync state.
- Add a DB-backed full-service test for failure, persisted state, and a
  successful subsequent reconciliation retry, covering interval edit and the
  generic resync path.

### CR153-02 — High — the completed-Week read contract is not implemented for non-ride sessions or generation states

**Evidence**

- Batch 152 specified that completed strength/flexibility/walk sessions use the
  same lookup and that absent, still-generating, and failed reads render
  distinct honest states (`docs/phase-batches.md`, Batch 152.3).
- The lookup selects any `Analysis` whose ORM `planned_workout_id` matches
  (`apps/api/src/routers/plan_actions.py:412-458`), but only
  `PostWorkoutAnalysisService.generate_and_store` calls
  `complete_matched_planned_workout` and writes that column
  (`apps/api/src/services/post_workout_analysis.py:426-466`).
- Strength, flexibility, and walk generators write `activity_id` and their
  post-* analysis type, but not `planned_workout_id`
  (`post_strength_analysis.py:273-309`,
  `post_flexibility_analysis.py:375-410`,
  `post_walk_analysis.py:283-318`). Their completed reads therefore cannot be
  returned by the Batch 152 endpoint.
- The endpoint has no generation-state source. A missing read, an in-flight
  generation, and a failed generation all return `read: null`; the frontend can
  only show the same "No read yet" state for all three.
- The endpoint does not constrain `analysis_type`. That is harmless while
  `post_workout` is the only writer of the ORM link, but becomes unsafe when the
  missing non-ride linkage is fixed unless the accepted post-session types are
  defined explicitly.

**Impact**

The shipped surface says that an existing strength, mobility, or walk read does
not exist. It also loses the specific recovery guidance Batch 152 required for
generation failures and can leave a user waiting without knowing whether a read
is still being written or needs a retry.

**Test gap**

The endpoint tests seed a linked `post_workout` row and an empty state. They do
not cover a completed linked strength/flexibility/walk activity, allowed
analysis-type selection, generating state, or failed state.

**Proposed remediation batch R153-B — generic completed-session read linkage and state**

- Move planned-workout completion/linking to a shared post-activity seam for
  cycle, strength, flexibility, and walk categories.
- Limit the read selector to the explicitly supported post-session analysis
  types and verify the requested workout belongs to the caller.
- Add a small persisted generation-status contract for post-session reads, or
  derive a reliable state from an existing job/status source.
- Add negative and positive DB tests for every post-* type, no-read,
  generating, failed, foreign-user, and unrelated-analysis cases, plus frontend
  state tests.

### CR153-03 — Medium — follow-up chat turn order is nondeterministic and its post-session action contract is contradictory

**Evidence**

- A user message and its assistant reply are stored with exactly the same
  `created_utc` (`apps/api/src/services/brief_chat.py:275-290`).
- Both history and model-context queries order only by `created_utc`
  (`brief_chat.py:192-205`, `brief_chat.py:243-257`). SQL does not guarantee row
  order for equal sort keys; UUID primary keys are not a valid implicit turn
  sequence.
- The universal prompt says that, when Mark wants an adjustment, the app can
  propose one for confirmation (`brief_chat.py:55-73`).
- The deterministic affordance is correctly restricted to morning analyses
  (`brief_chat.py:271-273` and `_analysis_allows_adjustment_proposal`), so a
  post-session response can promise a next action that the UI will never offer.
  The mutation boundary from Batch 150 is intact; the language contract is not.
- `PROMPT_VERSION = "brief-chat-v2-2026-07-24"` is defined but neither persisted
  with a conversation/message nor used in invalidation or observability.

**Impact**

Equal-timestamp rows can be rendered or replayed assistant-before-user, and
Anthropic can receive a malformed conversational sequence. Separately, a
post-session answer may tell Mark to confirm a proposal that is intentionally
unavailable.

**Test gap**

The tests cover ownership, turn limits, context grounding, and proposal gating,
but not deterministic ordering of an actual same-timestamp pair or
analysis-type-specific action wording.

**Proposed remediation batch R153-C — explicit chat turns and per-read action capability**

- Add an explicit monotonic turn/sequence value, or another deterministic
  composite order that preserves user-then-assistant pairs under concurrency.
- Build the system prompt from an explicit capability flag: morning may explain
  the confirmable proposal path; post-session reads must say that the chat is
  explanatory/advisory only.
- Persist prompt provenance per assistant turn (or remove the misleading
  version constant if chat provenance is intentionally out of scope).
- Test same-timestamp history ordering, concurrent questions, and the exact
  morning versus post-session capability contract.

### CR153-04 — Medium — concurrent generation has no lease or idempotency boundary

**Evidence**

- Every current-day manual-entry PUT marks the brief as generating and enqueues
  a new background task (`apps/api/src/routers/daily_loop.py:1482-1513`).
- Each task force-generates a morning analysis
  (`apps/api/src/services/executable_coaching.py:342-370`); two rapid requests
  can therefore make two paid model calls and insert two same-version rows.
- Post-session force generation likewise does check/generate/insert without a
  per-user/activity lease (`routers/daily_loop.py:1564-1580`).
- `analyses` intentionally has no uniqueness constraint
  (`apps/api/src/models/coaching.py:453-482`). Decision #219 preserves historical
  regenerations and feedback references, so a blunt unique constraint would be
  the wrong fix; the missing boundary is between intentional history and
  concurrent execution of the same request.

**Impact**

Rapid retries, two tabs, or an overlapping worker/request can spend duplicate
Anthropic calls, produce duplicate "current" reads, send duplicate ready
notifications, and race generation status. Latest-wins readers mask the rows
but do not prevent cost or side effects.

**Test gap**

No test launches two identical generation requests concurrently or proves a
single model call/notification while retaining intentional regeneration after a
changed check-in.

**Proposed remediation batch R153-D — generation lease and request identity**

- Define an idempotency identity for user/date/source-version (morning) and
  user/activity/check-in-version/prompt-version (post-session).
- Acquire a short DB-backed lease or advisory lock before the paid boundary.
- Preserve historical rows for genuinely changed input or prompt versions.
- Add concurrency tests proving one paid call for identical work and two
  historical rows for deliberately distinct generations.

### CR153-05 — Medium — prompt-version invalidation is inconsistent across the 19-file prompt surface

**Evidence**

All 19 `PROMPT_VERSION`-carrying source files were inventoried:

`ride_analysis_backfill.py`, `scheduler.py`, `brief_chat.py`, `daily_loop.py`,
`executable_coaching.py`, `experiment_evaluation.py`,
`experiment_tracker.py`, `handover.py`, `insights.py`, `morning_analysis.py`,
`nudge_alerts.py`, `post_flexibility_analysis.py`,
`post_strength_analysis.py`, `post_walk_analysis.py`,
`post_workout_analysis.py`, `reviews.py`, `trends.py`, `wake_detection.py`, and
`weekly_restructure.py`.

The core currentness implementations are sound in morning, post-workout,
reviews, and trends. Deterministic audit/event producers legitimately use a
version as provenance rather than invalidation, while scheduler/backfill/daily
loop are callers or reference carriers.

The gaps are:

- flexibility, strength, and walk define and store a prompt version, but their
  `_analysis_covers_activity_checkin` helpers compare only the check-in timestamp
  (`post_flexibility_analysis.py:556-566`, with equivalent helpers in
  `post_strength_analysis.py:457-467` and `post_walk_analysis.py:580-590`);
  pending scans and `generate_and_store` therefore reuse an old-prompt analysis
  when the check-in has not changed;
- handover returns any latest export for the date before considering its prompt
  version (`apps/api/src/services/handover.py:614-626`); and
- brief chat's version is dead provenance, covered in CR153-03.

**Impact**

A prompt bump can be deployed without the affected reader ever using it for an
unchanged activity/date. Operators and tests can see a new constant in code
while users continue to receive the old generated artifact.

**Test gap**

There is no shared test asserting that a prompt-version bump invalidates every
AI-generated artifact for which currentness is promised.

**Proposed remediation batch R153-E — central prompt-currentness policy**

- Classify each versioned producer explicitly as immutable audit, latest-only,
  or regenerable artifact.
- Give regenerable artifacts a shared currentness helper using prompt version
  plus their input/check-in version.
- Cover strength/flexibility/walk/handover with old-version and changed-input
  tests; document the intentional provenance-only producers.

### CR153-06 — Medium — learning and pending-read scans perform N+1 queries

**Evidence**

- Conversation learning loads up to 60 manual-entry sources, then performs a
  separate latest-analysis query for each entry
  (`apps/api/src/services/conversation_learning.py:366-405`).
- Each pending flexibility activity performs one latest-analysis query and one
  check-in query inside the activity loop
  (`post_flexibility_analysis.py:230-257`). Strength and walk repeat the same
  pattern; the ride pending scan has the same query shape.
- These post-session scans run over a seven-day window and are used by recurring
  orchestration, so the round trips recur even though this is a small private
  deployment.

**Impact**

The current volume keeps wall time tolerable, but query count scales directly
with activities/check-ins and adds avoidable scheduler latency. The learning
scan can issue roughly 60 extra queries from one explicit user action.

**Test gap**

Tests assert returned activities/sources, not bounded query count or bulk
latest-row semantics.

**Proposed remediation batch R153-F — bulk source and post-activity lookups**

- Bulk-fetch the latest analysis and check-in rows keyed by activity/date, then
  reduce latest-wins in one place.
- Preserve current source ordering and the Decision #219 historical audit trail.
- Add query-count regression tests for a multi-activity week and a 60-entry
  learning window.

### CR153-07 — Medium — Plan Week assigns activities to UTC dates instead of the profile-local calendar

**Evidence**

- `PlanActionService._activities_by_date` receives no timezone, queries naive
  UTC-midnight bounds, and groups with `activity.start_utc.date()`
  (`apps/api/src/services/plan_actions.py:641-691`).
- Batch 149 anchors the Week view and "today" boundary in the profile timezone.
  The training-week grounding service also uses profile-local dates, so the
  schedule endpoint is the inconsistent path.

**Impact**

During BST, an activity between local midnight and 01:00 is assigned to the
previous Week day. Completed-kind suppression can then hide or duplicate the
wrong row relative to the planned workout, and the calendar-week narrative and
organiser can disagree.

**Test gap**

Batch 149 tests the frontend's Monday/today boundary, but there is no backend
schedule test with an activity on a UTC/profile-local date boundary.

**Proposed remediation batch R153-G — timezone-correct Plan Week activity grouping**

- Pass the player's IANA timezone into the activity fetch.
- Convert local day bounds to UTC for the query and convert every `start_utc` to
  a local date for grouping.
- Add GMT and BST midnight-boundary tests, including completed-kind
  deduplication.

### CR153-08 — Low — malformed deliverable workouts disappear without a durable failure signal

**Evidence**

- `_deliver_one` catches any `HTTPException` raised while loading FTP/building
  the structured IR and returns `None`
  (`apps/api/src/services/executable_coaching.py:591-598`).
- The reconciliation loop treats that identically to an intentional
  non-delivery/idempotent no-op. No proposal failure, audit row, alert, or
  structured log identifies the workout that was skipped.

**Impact**

Bad stored workout content or missing FTP can leave a session absent from Zwift
without a visible explanation. This is lower severity because malformed
workouts are uncommon and current builders validate normal creation paths, but
when it occurs the failure is operationally silent.

**Test gap**

Tests accept the no-op behavior; none requires a durable diagnostic tied to the
workout.

**Proposed remediation batch R153-H — observable non-deliverable state**

- Distinguish expected non-bike/non-deliverable cases from malformed bike data.
- Persist or emit a structured retryable/non-retryable delivery failure with
  user/workout/version context and surface an honest status where appropriate.
- Test malformed IR, missing FTP, and intentional no-op paths separately.

## Recent-batch boundary verification

| Batch | Boundary claim reviewed | Result |
|---|---|---|
| 147 — interval editor | Exact interval edits preserve fixed steps and cannot deliver VO2 on Red; no verdict rewrite. | **Verified.** The deterministic verdict is read, the fully expanded edited steps are passed to `blocks_red_vo2`, and rejection occurs before proposal/version delivery. The editor does not modify `_morning_verdict`. CR153-01 is a delivery-transaction defect, not a Red-gate bypass. |
| 148 — training-week grounding | Planned → changed → executed week data grounds narratives without changing classification. | **Verified.** The reducer is read-only packet assembly used by morning/review prompts. It does not feed the deterministic verdict calculation or threshold inputs. |
| 149 — Monday Week | Profile-local Monday/two-week organisation and past-day UI guards do not alter engine state. | **Verified.** The change is frontend schedule anchoring/read-only affordances; engine/verdict code is untouched. CR153-07 is an older backend timezone inconsistency exposed by the new calendar framing, not a classification path. |
| 150 — post-workout chat | Completed-session chat is advisory-only and cannot propose/apply plan changes. | **Verified for mutation safety.** The proposal ID is code-gated to `analysis_type == "morning"` and the frontend has no completed-session apply path. CR153-03 records ordering and truthful-capability gaps, not a mutation bypass. |
| 151 — conversational learning | Only reviewed durable context reaches packets; it cannot modify verdict thresholds, data-quality rules, or Red-never-VO2. | **Verified.** Accepted rows have one destination, `learned_context`; pending/rejected rows do not propagate. Morning computes the deterministic verdict before adding learned context to narrative packet data. The post-* services likewise consume it as context, not classifier input. Prompt-injection/sycophancy behavior remains explicitly assigned to full-app Batches 154/155. |
| 152 — Week read + ERG | Read-only lookup/profile context/prompt changes leave deterministic safety logic unchanged. | **Verified for engine safety; product acceptance violation raised.** The endpoint does not regenerate or write, and the ERG changes are KB/prompt context only. CR153-02 records the missing non-ride linkage and generation states. ERG coaching integrity itself remains Batch 155 scope. |

## Hotspot coverage

The sweep covered:

- morning and all post-session packet/generation services;
- the 19 `PROMPT_VERSION` carriers listed in CR153-05;
- executable coaching, plan actions, delivery proposal/create/replace/move/delete
  paths, and the interval editor;
- recent analysis/read/chat/learning routers and their user filters;
- `Analysis`, `BriefMessage`, delivery, learning, and generation-status storage;
  and
- silent exception, duplicate-row, N+1, dead-version, and timezone patterns.

Recent routes consistently apply the current authenticated profile and user
filters in the paths reviewed. This was a correctness-oriented ownership check,
not the promised full RLS/endpoint/secret threat-model sweep; Batch 154 retains
that full-app security scope so findings are neither duplicated nor prematurely
closed.

## Test-gap analysis

| Batch / area | What is well covered | Material gap |
|---|---|---|
| 147 interval editor | Pure grammar/mapping tests, successful exact replacement, Red/VO2 rejection. | Caller-level cloud replacement failure + persisted retry state (CR153-01). Most service cases require Postgres and skip without `DATABASE_URL`. |
| 148 training week | Pure reducer/prompt cases and DB-backed service integration. | DB-backed packet integration is not exercised in a default local run; no new safety gap found. |
| 149 Monday Week | Frontend Monday/BST, elapsed-day guards, move targets, organiser flows. | Backend activity grouping across local midnight (CR153-07). |
| 150 follow-up chat | Ownership, turn caps, grounding, morning proposal gate, post-workout mounting. | Equal-timestamp ordering and analysis-specific action language (CR153-03); stateful cases are DB-backed. |
| 151 learning | Pure taxonomy/parser/evidence validation and DB-backed proposal/accept/packet flows. | Query-count regression (CR153-06); adversarial durable-write behavior belongs to Batch 154 and sycophancy behavior to 155. |
| 152 Week read / ERG | Linked ride read, empty state, UI read/feedback/chat, ERG packet/prompt shape. | Non-ride linkage, allowed type selection, and explicit generating/failed states (CR153-02). Model-behavior integrity belongs to 155. |
| Engine-wide | Latest-wins readers retain intentional history; common happy paths are strong. | Concurrent identical generation (CR153-04), shared prompt-currentness policy (CR153-05), malformed-delivery observability (CR153-08). |

The focused backend run completed **99 passed / 91 skipped**. The skips are the
expected Postgres-backed tests guarded by `DATABASE_URL`; CI supplies Postgres.
The three directly relevant frontend files completed **85 passed**. Ruff, mypy,
and web TypeScript checks were clean.

## Dependency-audit and report-location decisions

- **Dependency vulnerability audits stay in Batch 154.** `pnpm audit` and a
  Python dependency advisory scan are security/posture work and belong beside
  the full-app secret/auth/RLS audit. They were deliberately not run or
  partially interpreted here.
- **This report lives in `docs/reviews/`.** It is a durable review artifact,
  while the root documents retain the architecture, decision, and current
  handoff summaries.

## Scope exclusions

This review intentionally does not:

- change product code, migrations, verdicts, thresholds, prompts, or tests;
- perform the Batch 154 full RLS, secret, auth, and conversational-learning
  threat model;
- re-grade ERG trust, sycophancy, or coaching behavior assigned to Batch 155;
  or
- perform the live cross-route UX walkthrough assigned to Batch 156.
