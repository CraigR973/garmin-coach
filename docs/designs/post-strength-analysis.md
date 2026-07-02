# Design: Post-strength analysis (Batch 43)

**Status:** Specced, not started. Added 2026-07-02 in the Batch 38/39-withdrawal
replan (DECISIONS #108): Mark clarified he tracks his strength (and flexibility)
workouts on his watch and wants only the *post-workout analysis* in the app, not an
in-app player to run the session. The withdrawn **Batch 38 (in-app guided strength
player)** never actually gave strength a per-session *analysis* — it added a player
and extended the Batch 19 rollup brief — so removing it left strength with no
per-session read at all. This batch fills that gap. Decision number assigned at
`/batch-start` (next free **#113**, after Batch 42's #112). The strength sibling of
**Batch 40 (post-flexibility/mobility analysis)** in the 40–43 non-cycling analysis
set.

Builds on / reuses:
- **Batch 8 post-workout analysis** as the exact template — `services/post_workout_analysis.py`:
  `PostWorkoutAnalysisService` (`pending_ride_activities` → `assemble_context_packet`
  → thin Anthropic Messages boundary → store in `analyses` with `analysis_type` +
  `activity_id`), triggered by the **hourly Garmin activity poll** (`scheduler.py`
  `generate_for_pending_rides`) and surfaced on `/api/v1/daily-loop` as
  `postWorkoutAnalyses`. This batch is the **same architecture with a different,
  lean packet + prompt** — exactly like Batch 40, not a reuse of the power-centric
  ride packet.
- **The Batch 19 strength brief (`services/strength_brief.py`, DECISIONS #49/#80)** —
  `is_strength_activity` (delegates entirely to `activity.exclude_from_recovery`, set
  at Garmin sync time by the Batch 8 wrist-HR detection, #49) and the pure
  `compute_strength_rollup` over `StrengthSession` sequences. **This batch reuses
  both directly**, so — unlike Batch 40, which had to write a new name-based selector
  and a new consistency rollup — the selector and the consistency read already exist.
- **Day categorisation** — `services/workout_categories.py` already maps `strength_*`
  → `DAY_CATEGORY_WEIGHTS`; the analysis attaches to a weights day.
- **The recovery-isolation invariant (#49/#80)** — like mobility, a strength session
  must never feed the Green/Amber/Red verdict or ride-recovery decisions. The Batch
  19 brief is advisory-only; this per-session read is too.
- **Batch 26 activity-linked check-in** — the same `ManualEntry` (`rpe` /
  `subjective_score`) shape, if Mark leaves one on the session.

## The grounding

Mark's strength sessions already land in `activities` with `exclude_from_recovery=True`
(Batch 8 wrist-HR detection) and are read **only** by the Batch 19 *rollup* brief —
a weekly/12-week frequency-volume-load summary. There is no per-session narrative for
strength the way cycling gets one (Batch 8) and mobility will (Batch 40). His
documented cadence is ~2 sessions/week — the **Monday ~20-min Dumbbell** and
**Saturday ~16-min Bodyweight** workouts from his own document (the same two the
withdrawn Batch 38 was going to seed) — done on the watch, so each produces a Garmin
`strength_*` activity with HR but no power/cadence.

## ⚠️ No selector landmine (unlike Batch 40)

Batch 40 had to key on the activity **name** because Garmin files mobility under the
two-population `typeKey == "other"` bucket (47 mobility sessions **+** 153 old
misclassified road rides). **Strength has no such trap:** `is_strength_activity`
already exists and delegates to `exclude_from_recovery`, which the Batch 8 sync sets
correctly for `strength_*` sessions. So this batch reuses that selector unchanged —
no new classification code, no name matching. A test still asserts it selects a
`strength_*` session and rejects a ride and a `mobility` session.

## The parallel — same machinery, a different (lean) packet

| Concern | Cycling (Batch 8, exists) | Strength (this batch) |
|---|---|---|
| Selector | `_is_ride` (type/name tokens) | `is_strength_activity` (**exists**, `exclude_from_recovery`) |
| Trigger | hourly poll → `generate_for_pending_rides` | hourly poll → `generate_for_pending_strength` |
| Store | `analyses`, `analysis_type='post_workout'`, `activity_id` | `analyses`, `analysis_type='post_strength'`, `activity_id` |
| Packet | power, FTP zones, cadence, stamina, PC, TE, per-second time-series | **duration, HR vs resting, consistency, planned session, check-in** |
| Time-series | per-second channels (backfilled) | **none** — strength carries no per-second detail (#93) |
| Prompt | "endurance post-workout analyst" | **strength / resistance-training coach** |
| Consistency read | n/a | **reuses Batch 19 `compute_strength_rollup`** |
| Verdict/recovery | full ride recovery decision | **advisory only** — unchanged (#49/#80) |

Pointing the ride machinery at a 20-minute dumbbell session would yield a packet of
nulls (no power/cadence/FTP/stamina/PC/TE, no time-series) and a prompt asking an
endurance analyst to discuss power zones on a resistance set. So the packet is
purpose-built and small — the strength twin of Batch 40's lean mobility packet.

## The lean context packet (`post_strength`)

A parallel `assemble_strength_packet` (mirroring `assemble_context_packet` /
`assemble_flexibility_packet`) with only what a strength session actually carries +
what makes it coachable:

- **Session:** `activityName`, `activityType`, duration, avg/max HR, calories.
- **HR read:** avg/max HR **relative to resting HR** (from the day's `daily_metrics`)
  — a light gauge of how hard the session ran, not a training-zone judgement.
- **Consistency (the point):** frequency / volume / load-proxy over the 4-week and
  12-week windows and the trend, from Batch 19's pure `compute_strength_rollup` —
  with strength the coaching story *is* the habit + progressive overload, so this is
  the richest signal.
- **Plan context:** the day's planned `strength_*` workout (if any) — was it planned?
  Surface the documented progression rule (dumbbell → add weight; bodyweight → add
  reps) as guidance, not an auto-applied prescription.
- **Subjective:** any activity-linked `ManualEntry` (Batch 26 shape).
- **Guardrails:** the KB data-quality rules echoed, as Batch 8 does.

**No** power zones, cadence, stamina, Performance Condition, Training Effect, FTP, or
time-series summary — none exist for this type.

A new `SYSTEM_PROMPT` frames a **strength / resistance-training coach**: acknowledge
the session, read consistency + progression vs. his routine, note HR only as a light
effort gauge, and give a short encouragement/next-step (e.g. progressive-overload
nudge) — never power/zone talk and never a recovery verdict.

## Relationship to the Batch 19 rollup brief

Batch 19 is the **rollup** (a weekly/12-week watching-brief); this is the
**per-session** read. They are complementary and both advisory:
- Batch 19 answers "how has strength training been trending?" (frequency/volume/load).
- Batch 43 answers "how was *this* session, and what next?" per activity.

This batch **does not modify** the Batch 19 brief, its endpoint, or its rollup. (The
withdrawn Batch 38 was going to extend the brief to union in-app `guided_sessions`
logs for a count-once reconciliation — that whole concern is gone with 38/39, since
there is no in-app session log; every strength session is a Garmin activity.)

## Trigger, storage, surfacing

- **Trigger:** extend the existing hourly activity poll (`scheduler.py`) to also run
  `generate_for_pending_strength` after the ride + flexibility passes — one analysis
  per strength activity, idempotent (same `latest_analysis_for_activity` guard), no
  new cron.
- **Storage:** `analyses`, `analysis_type='post_strength'`, `activity_id` FK — **no
  migration** (`analysis_type` is already `String(50)`; mirrors the
  `post_flexibility`/`weekly_review`/`seasonal_trend` additive-type pattern).
- **Surfacing:** add `postStrengthAnalyses` to the `/api/v1/daily-loop` serializer
  (or the generalised post-session list, if Batch 40/41 established one — settle at
  `/batch-start`) and a strength read on Home's weights day, beside the ride card.
- **Backfill:** the strength sessions already in prod predate the selector wiring, so
  a one-off backfill generates their analyses (exactly as the #51 fix backfilled the
  historical outdoor rides and as Batch 40 backfills mobility).

## Phases

- **43.1** Reuse the existing `is_strength_activity` selector (no new selector) +
  reuse Batch 19's pure `compute_strength_rollup` for the consistency read;
  explicit tests that a ride and a `mobility` session are *not* selected as strength.
- **43.2** `assemble_strength_packet` + the `post_strength` `SYSTEM_PROMPT` and
  output rules; reuse the thin Anthropic boundary (#47, fakeable, no key in tests).
- **43.3** `pending_strength_activities` + `generate_for_pending_strength`
  (idempotent, one-per-activity) + store in `analyses`.
- **43.4** Scheduler wiring (hourly poll runs the strength pass after the ride +
  flexibility passes); daily-loop serializer surfaces `postStrengthAnalyses`; shared
  Zod schema.
- **43.5** Frontend strength read on Home's weights day (reuse the post-workout card
  + Markdown renderer).
- **43.6** One-off backfill of existing strength sessions; tests + green gates.

## Testing

- **Pure:** `is_strength_activity` selects a `strength_*` session and rejects a ride
  and a `mobility` session; `compute_strength_rollup` still computes
  frequency/volume/load and degrades on sparse data (already covered by Batch 19 —
  re-assert in context).
- **Packet/boundary:** the packet carries HR-vs-resting + consistency and **no**
  power/zone/FTP/time-series keys; generation is fakeable without `ANTHROPIC_API_KEY`.
- **Idempotency:** a second poll does not regenerate an already-analysed session; a
  newer activity-linked check-in marks it pending (Batch 26 rule).
- **DB-backed:** generate + store one `post_strength` row; the daily-loop payload
  exposes it on a weights day.
- **Isolation:** no verdict/recovery field is written or read as a recovery signal
  (the same `__dataclass_fields__` guard Batch 19 uses, #49/#80); the Batch 19 brief
  output is unchanged.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No in-app player** — that was the withdrawn Batch 38; Mark runs the session on
  his watch. This batch only *reads* the resulting Garmin activity.
- **No `guided_sessions` table / no reconciliation** — there is no in-app session
  log to reconcile against; every strength session is a Garmin activity.
- **No change to the Batch 19 rollup brief** — it stays as the complementary
  watching-brief; this batch adds a per-session read alongside it.
- **No per-second ingestion** — strength has no per-second detail and none is added
  (keeps clear of the shared free-tier 500 MB cap, #93/#34).
- **No verdict/recovery impact** — strength stays advisory (#49/#80).
- **No strength authoring / progression automation** — the documented progression
  rule is surfaced as guidance in the read, never auto-applied.

## Open decisions to settle at `/batch-start`

1. **Minimum-session guard** — analyse every strength activity, or set a floor so
   incidental short logs don't each get a read? (Proposed: analyse all; let the
   prompt weight a very short session lightly, as Batch 40 proposes for mobility.)
2. **Parallel service vs. generalise `PostWorkoutAnalysisService`** — by the time
   this builds, Batch 40 (and maybe 41) may have generalised Batch 8 into a shared
   post-session engine; if so, add strength as another consumer rather than a fresh
   sibling. (Proposed: reuse the shared engine if it exists, else sibling.)
3. **Daily-loop shape** — a dedicated `postStrengthAnalyses` list vs. the unified
   post-session list (match whatever Batch 40 chose).
4. **Backfill window** — all historical strength sessions, or only from a recent
   start date.

## Dependency & sequencing

- **Independent of the Home-refinement batches 35–37** (a backend analysis surface).
- **Closest sibling of Batch 40** — same machinery, and it *increases* the reuse case
  for generalising the post-session engine (open decision #2 in both specs). Natural
  to build **alongside or right after Batch 40**; because Mark explicitly asked for
  the strength read, it may be prioritised with 40 rather than left to the end.
- **Requires neither Batch 38 nor 39** (both withdrawn) — it never needed them; it
  keys on the Garmin strength activity alone.

## Safety / invariants preserved

- **Existing selector** (`exclude_from_recovery`) — no new classification, no
  name-matching landmine.
- **Recovery isolation (#49/#80)** — strength carries ~no load and never touches
  verdict/recovery; the Batch 19 brief stays advisory and unchanged.
- **Idempotent** — one analysis per activity, regenerated only on a newer check-in.
- Reuses the thin Anthropic boundary (#47) — fakeable, prompt/version stored.
