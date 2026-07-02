# Design: Post-flexibility (mobility) analysis (Batch 40)

**Status:** Specced, not started. Designed with Craig on 2026-07-02 after a live
census of Mark's full Garmin history surfaced a near-daily mobility habit the app
is currently blind to. Decision number assigned at `/batch-start` (next free
**#111**, after the #106–#110 reserved for specced Batches 35–39). First of three
sibling batches (40 mobility, **41 walking**, **42 breathwork**) that give the
non-cycling activity types a coaching read.

Builds on / reuses:
- **Batch 8 post-workout analysis** as the exact template — `services/post_workout_analysis.py`:
  `PostWorkoutAnalysisService` (`pending_ride_activities` → `assemble_context_packet`
  → thin Anthropic Messages boundary → store in `analyses` with `analysis_type` +
  `activity_id`), triggered by the **hourly Garmin activity poll** (`scheduler.py`
  `generate_for_pending_rides`) and surfaced on `/api/v1/daily-loop` as
  `postWorkoutAnalyses`. This batch is the **same architecture with a different,
  lean packet + prompt** — *not* a reuse of the power-centric ride packet.
- **Day categorisation** — `services/workout_categories.py`
  (`WORKOUT_TYPE_FLEXIBILITY = {"mobility"}`, `DAY_CATEGORY_FLEXIBILITY`) already
  routes `mobility` to a flexibility day; the analysis attaches there.
- **The recovery-isolation invariant (#49/#80)** — like strength, a mobility
  session must never feed the Green/Amber/Red verdict or ride-recovery decisions.
- **Batch 39's `guided_sessions` (`format:"flexibility"`)** *if shipped* — an
  optional enrichment (the in-app completion log), never a hard dependency: this
  batch keys on the **Garmin activity** exactly as Batch 8 does.

## The grounding evidence (2026-07-02 live census)

A throwaway probe over Mark's **entire** Garmin history (4,280 activities,
Dec 2014 → Jul 2026, 10 distinct `activityType.typeKey`s) found a **near-daily
mobility routine** that started June 2026 and is currently invisible to every
analysis path:

| Name | Count | typeKey | distance | HR | since |
|---|---|---|---|---|---|
| 16 Min Mobility Workout | 28 | `other` | 0 | 60s–90s bpm | Jun 2026 |
| 3 Minute Mobility Workout | 19 | `other` | 0 | 60s–90s bpm | Jun 2026 |

These fail every existing selector: they are not `_is_ride`, and
`is_strength_activity` is False (their typeKey is `other`, not `strength_*`), so
they land in `activities` and are then dropped.

## ⚠️ The classification landmine (must be honoured)

Garmin logs mobility under **`typeKey == "other"`** — but `other` is a *two-population
bucket*. The same bucket holds **153 old (2016–2020) misclassified road rides**
(names like "East Ayrshire Road Cycling", `distance > 0`), which already match
`_is_ride` **by name** and are correctly picked up as rides.

**Therefore the flexibility selector must key on the activity *name*, never on
`typeKey == "other"`** — otherwise a decade of misclassified rides would be roped
into flexibility analysis:

```python
def is_flexibility_activity(a: Activity) -> bool:
    return "mobility" in a.activity_name.lower()
```

Yoga (`typeKey == "yoga"`, 9 sessions) is **deliberately excluded** (Craig's
decision 2026-07-02 — mobility only, matching `WORKOUT_TYPE_FLEXIBILITY`).

## The parallel — same machinery, a different (lean) packet

| Concern | Cycling (Batch 8, exists) | Mobility (this batch) |
|---|---|---|
| Selector | `_is_ride` (type/name tokens) | `is_flexibility_activity` (**name = "mobility"**) |
| Trigger | hourly poll → `generate_for_pending_rides` | hourly poll → `generate_for_pending_flexibility` |
| Store | `analyses`, `analysis_type='post_workout'`, `activity_id` | `analyses`, `analysis_type='post_flexibility'`, `activity_id` |
| Packet | power, FTP zones, cadence, stamina, PC, TE, per-second time-series | **duration, HR vs resting, consistency, planned session, check-in** |
| Time-series | per-second channels (backfilled) | **none** — no per-second detail exists for `other` (#93) |
| Prompt | "endurance post-workout analyst" | **mobility / recovery coach** |
| Verdict/recovery | full ride recovery decision | **advisory only** — unchanged (#49/#80) |

Pointing the ride machinery at a 15-minute mobility session would yield a packet
of nulls (no power/cadence/FTP/stamina/PC/TE, no time-series) and a prompt asking
an endurance analyst to discuss power zones on a stretch. So the packet is
purpose-built and small.

## The lean context packet (`post_flexibility`)

A parallel `assemble_flexibility_packet` (mirroring `assemble_context_packet`)
with only what a mobility session actually carries + what makes it coachable:

- **Session:** `activityName`, `activityType`, duration, avg/max HR, calories.
- **HR read:** avg HR **relative to resting HR** (from the day's `daily_metrics`)
  — is this genuinely relaxed/parasympathetic, or was he pushing?
- **Consistency (the point):** current streak, sessions this week, 4-week
  frequency — with mobility the coaching story *is* the habit, so this is the
  richest signal. Computed by a pure, DB-free rollup over the flexibility
  activities (mirrors `compute_strength_rollup`).
- **Plan context:** the day's planned `mobility` workout (if any) — was it planned?
- **Subjective:** any activity-linked `ManualEntry` (reuse the Batch 26 shape).
- **Guardrails:** the KB data-quality rules echoed, as Batch 8 does.

**No** power zones, cadence, stamina, Performance Condition, Training Effect, or
time-series summary — none exist for this type.

A new `SYSTEM_PROMPT` frames a **mobility/recovery coach**: acknowledge the
session, read consistency vs. his routine, flag if HR was unusually high for a
mobility session, and give a light encouragement/next-step — never power/zone talk.

## Trigger, storage, surfacing

- **Trigger:** extend the existing hourly activity poll (`scheduler.py`) to also
  run `generate_for_pending_flexibility` after the ride pass — one analysis per
  mobility activity, idempotent (same `latest_analysis_for_activity` guard), no
  new cron.
- **Storage:** `analyses`, `analysis_type='post_flexibility'`, `activity_id` FK —
  no migration (`analysis_type` is already `String(50)`; this mirrors the
  `weekly_review`/`seasonal_trend`/etc. additive-type pattern).
- **Surfacing:** add `postFlexibilityAnalyses` to the `/api/v1/daily-loop`
  serializer (or a generalised post-session list — settle at `/batch-start`) and
  a flexibility read on Home's flexibility day, beside the ride card.
- **Backfill:** the ~47 mobility sessions already in prod predate the selector, so
  a one-off backfill generates their analyses (exactly as the #51 fix backfilled
  the 19 historical outdoor rides).

## Phases

- **40.1** Pure `is_flexibility_activity` (name-based) + a pure DB-free
  `compute_flexibility_consistency` rollup (streak / week / 4-week frequency),
  fully unit-testable; explicit tests that `other`-typed **rides** are *not*
  selected.
- **40.2** `assemble_flexibility_packet` + the `post_flexibility` `SYSTEM_PROMPT`
  and output rules; reuse the thin Anthropic boundary (fakeable, no key in tests).
- **40.3** `pending_flexibility_activities` + `generate_for_pending_flexibility`
  (idempotent, one-per-activity) + store in `analyses`.
- **40.4** Scheduler wiring (hourly poll runs the flexibility pass after rides);
  daily-loop serializer surfaces `postFlexibilityAnalyses`; shared Zod schema.
- **40.5** Frontend flexibility read on Home's flexibility day (reuse the
  post-workout card + Markdown renderer).
- **40.6** One-off backfill of the existing ~47 mobility sessions; tests + green
  gates.

## Testing

- **Pure:** `is_flexibility_activity` selects "16 Min Mobility Workout" and
  rejects "East Ayrshire Road Cycling" (the `other`-typed old ride) and a
  `strength_*` session; the consistency rollup computes streak/frequency and
  degrades on sparse data.
- **Packet/boundary:** the packet carries HR-vs-resting + consistency and **no**
  power/zone/time-series keys; generation is fakeable without `ANTHROPIC_API_KEY`.
- **Idempotency:** a second poll does not regenerate an already-analysed session;
  a newer activity-linked check-in marks it pending (Batch 26 rule).
- **DB-backed:** generate + store one `post_flexibility` row; the daily-loop
  payload exposes it on a flexibility day.
- **Isolation:** no verdict/recovery field is written or read as a recovery signal.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No yoga** — mobility only (Craig, 2026-07-02); yoga could fold in later by
  widening the selector.
- **No per-second ingestion** — `other` has no per-second detail and none is added
  (keeps clear of the shared free-tier 500 MB cap, #93/#34).
- **No verdict/recovery impact** — flexibility stays advisory (#49/#80).
- **No standalone flexibility *brief*** — the consistency read lives *inside* the
  per-session packet (cycling has no separate brief either); a standalone brief
  analogous to Batch 19 remains a possible later idea, and Batch 39 anticipated it.
- **No walking / breathwork** — Batches 41 / 42.

## Open decisions to settle at `/batch-start`

1. **Minimum-session guard** — do we analyse the 3-minute sessions, or set a floor
   (e.g. skip < N minutes) so only the 16-minute routine gets a read? (Proposed:
   analyse all, but let the prompt treat a 3-min session lightly.)
2. **Parallel service vs. generalise `PostWorkoutAnalysisService`** — a sibling
   `post_flexibility` path, or refactor Batch 8 into a shared post-session engine
   that Batch 41's walking analysis also uses. (Proposed: sibling now, generalise
   if 41 confirms the shape.)
3. **Daily-loop shape** — a dedicated `postFlexibilityAnalyses` list vs. one
   unified post-session list.
4. **Guided-session enrichment** — if Batch 39 has shipped, also read the matched
   `guided_sessions(format="flexibility")` completion into the packet, or ignore it.
5. **Backfill window** — all ~47, or only sessions from the routine's start.

## Dependency & sequencing

- **Independent of Batches 35–39** (a backend analysis surface, not a Home
  refinement); keys on the Garmin mobility activity alone.
- Flagship of the 40–42 trio; natural to build first. Composes with Batch 39 (the
  in-app flexibility video) if that ships, but requires neither 38 nor 39.

## Safety / invariants preserved

- **Name-based selector** guards the `other`-bucket landmine — old misclassified
  rides can never enter flexibility analysis.
- **Recovery isolation (#49/#80)** — mobility carries ~no load and never touches
  verdict/recovery.
- **Idempotent** — one analysis per activity, regenerated only on a newer check-in.
- Reuses the thin Anthropic boundary (#47) — fakeable, prompt/version stored.
