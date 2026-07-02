# Design: Walking integration (Batch 41)

**Status:** Specced, not started. Designed with Craig on 2026-07-02 from the same
full-history census that surfaced the mobility habit (Batch 40). Decision number
assigned at `/batch-start` (next free **#112**, after Batch 40's #111). Second of
the 40–42 non-cycling trio. Craig's decision (2026-07-02): **per-session analysis
too** — a walking brief *and* an analysis for deliberate walks, not just a rollup.

Builds on / reuses:
- **Batch 19 strength watching-brief** (`services/strength_brief.py`) as the
  deterministic-rollup template — a pure `compute_*_rollup` over already-synced
  `activities`, a thin read-only `*BriefService`, a `GET /api/v1/*-brief` route,
  and a daily-loop envelope field. No LLM, advisory-only.
- **Batch 8 post-workout analysis** as the per-session template (`analyses`,
  `analysis_type`, `activity_id`, hourly-poll trigger, daily-loop surfacing) — but
  with an **HR/pace** packet, not the power/FTP one.
- **`services/morning_analysis.py`** — already ingests `totalSteps` (step count);
  this adds **deliberate-walk activity volume** as an additive active-recovery
  context, without changing verdict logic.
- **DECISIONS #93** — walking **already carries per-second detail** (387 walks
  backfilled: HR/cadence/speed), so the per-session analysis has real time-series
  to read with **no new ingestion** and no storage-cap risk.

## The grounding evidence (2026-07-02 census)

**450 walking activities** (`typeKey == "walking"`, parent 17), Dec 2014 → Jul 2026
— his second-most-frequent activity after cycling. They carry distance, pace, HR
and (recently) per-second HR. Today walking is invisible as an *activity*: it is
not `_is_ride`, not `is_strength_activity`, so only aggregate `totalSteps` reaches
the coach — the walks themselves are dropped. Most are short auto-tracked ambient
walks; the coaching value splits cleanly into **aggregate volume** (Z1–Z2 aerobic
base / active recovery) and the **occasional deliberate walk** worth a read.

## Three pieces

### 1. Walking brief (deterministic, Batch 19 clone)

A pure `compute_walking_rollup(sessions, as_of)` → 4-week / 12-week `WindowStats`
(session count, total distance, total duration, sessions/week) + a first-vs-second-
half **trend**, exactly like `compute_strength_rollup`. `WalkingBriefService.brief`
reads `activities` where `typeKey == "walking"` (read-only, never writes),
`GET /api/v1/walking-brief`, and a `walkingBrief` field on `/api/v1/daily-loop`.

### 2. Morning-verdict active-recovery context (additive)

Fold **recent deliberate-walk volume** (last N days' distance/duration) into the
morning context packet as a low-intensity aerobic / active-recovery signal, so the
coach can read a walk as active recovery on a rest day and see walking base
alongside `totalSteps`. **Advisory only** — it enriches the packet the model reads;
it does **not** change the Green/Amber/Red classification math.

### 3. Per-session deliberate-walk analysis (threshold-gated, LLM)

Only walks that clear a **deliberate threshold** get a Claude analysis, so ambient
10-minute ambles never trigger a call:

```python
WALK_ANALYSIS_MIN_DURATION_SEC = 30 * 60   # tunable, named
WALK_ANALYSIS_MIN_DISTANCE_M   = 3_000     # tunable, named
def is_deliberate_walk(a):  # typeKey walking AND clears either bar
    return a.activity_type == "walking" and (
        (a.duration_sec or 0) >= WALK_ANALYSIS_MIN_DURATION_SEC
        or (a.distance_m or 0) >= WALK_ANALYSIS_MIN_DISTANCE_M
    )
```

Its packet is **HR/pace-based, not power-based**: distance, duration, pace
(min/km), avg/max HR, **HR-zone distribution** (from the per-second HR channel
against the KB profile's HR zones — walking has no power/FTP), elevation gain,
calories, plus plan context + any check-in. New `SYSTEM_PROMPT`: an **aerobic /
Zone-2 walking coach** (was this genuine easy aerobic work / active recovery, HR
drift, next-step) — never power/cadence-in-rpm talk. Stored as
`analysis_type='post_walk'`, triggered off the hourly poll after the ride +
flexibility passes, idempotent, with a one-off backfill of qualifying historical
walks.

## The parallel

| Concern | Cycling (Batch 8) | Deliberate walk (this batch) |
|---|---|---|
| Zones | %FTP **power** zones | **HR** zones (profile HR bands) |
| Effort read | NP / IF / power | pace + HR drift |
| Time-series | power/HR/cadence (backfilled) | **HR/speed** (already backfilled, #93) |
| Sub-threshold | n/a | ambient walks → **brief only**, no LLM |
| Verdict/recovery | full ride recovery | **advisory** — active-recovery context only |

## Phases

- **41.1** Pure `compute_walking_rollup` + `WalkingBriefService` +
  `GET /api/v1/walking-brief` + `walkingBrief` daily-loop field + shared schema
  (Batch 19 clone).
- **41.2** Additive walk-volume active-recovery context in the morning packet
  (deliberate-walk distance/duration over a recent window); verdict math untouched.
- **41.3** `is_deliberate_walk` (threshold constants) + the HR/pace
  `assemble_walk_packet` + `post_walk` `SYSTEM_PROMPT`.
- **41.4** `pending_walk_activities` + `generate_for_pending_walks` (idempotent) +
  store in `analyses`; scheduler wiring; daily-loop surfacing; shared schema.
- **41.5** Frontend: walking brief panel + a deliberate-walk read on Home
  (reuse the post-workout card + Markdown renderer).
- **41.6** Backfill qualifying historical deliberate walks; tests + green gates.

## Testing

- **Pure:** `compute_walking_rollup` window/trend maths; `is_deliberate_walk` at
  the duration/distance boundaries (a 10-min amble is rejected, a 45-min walk
  accepted); HR-zone distribution from a fixture time-series.
- **Packet/boundary:** the walk packet is HR/pace-based with **no** power/FTP keys;
  fakeable without `ANTHROPIC_API_KEY`.
- **Isolation:** the active-recovery context does not alter the Green/Amber/Red
  verdict in a fixture where only walk volume changes.
- **DB-backed:** brief endpoint reflects synced walks; one `post_walk` row per
  qualifying walk; idempotent re-poll.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No LLM analysis of sub-threshold ambient walks** — they count in the brief and
  the volume context only.
- **No change to the Green/Amber/Red verdict logic** — walking is advisory context
  (consistent with recovery isolation, #49/#80).
- **No new Garmin ingestion** — walking summaries + per-second detail already sync
  (#93); this reads what exists.
- **No mobility / breathwork** — Batches 40 / 42.

## Open decisions to settle at `/batch-start`

1. **Threshold values** — the 30-min / 3-km bars (and whether it's OR vs AND).
2. **Active-recovery labelling** — may walk volume *relabel* a rest day as "active
   recovery" on Home, or stay purely informational in the packet?
3. **Shared engine vs. parallel** — reuse a generalised post-session engine (with
   Batch 40) or a parallel `post_walk` path.
4. **HR zones source** — the KB profile HR bands vs. a max-HR % model.
5. **Backfill window** — all qualifying historical walks vs. a recent window.

## Dependency & sequencing

- **Independent**; builds on the Batch 19 + Batch 8 patterns. Natural to build
  after Batch 40 (which may establish a shared post-session engine), but order is
  flexible.

## Safety / invariants preserved

- **Advisory only** — the Green/Amber/Red verdict is never changed by walking.
- **No storage-cap risk** — walking per-second detail already exists (#93); no new
  ingestion.
- **Idempotent** per-session analysis; deterministic, unit-testable brief + rollup.
