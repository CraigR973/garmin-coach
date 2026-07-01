# Design: Bedroom temperature × sleep correlation (Batch 34)

**Status:** Implemented on `feat/batch-34-bedroom-sleep-correlation`; awaiting
review/closeout. Designed with Craig on
2026-07-01, discussing whether Batch 31/33's bedroom data could inform the fan's
own thresholds over time. Decision number assigned at `/batch-start` (next free
**#105**, after Batch 33's #104). Builds on Batch 31 (`fan_state_readings`,
`services/bedroom_overnight.py`), optionally Batch 33's warning/critical-minute
classification, and — most directly — the **existing** Batch 17 driver-correlation
engine (`services/insights.py`: `compute_drivers`, `DRIVER_KEYS`) and the Batch 22
`early_waking_0400` experiment evaluator (`services/experiment_evaluation.py`,
`SLUG_EARLY_WAKING`). **This closes an explicit deferred item from Batch 31**
(DECISIONS #101's non-goals: *"Not wiring the `early_waking_0400` experiment —
this batch produces the fan/temp series that evaluation could later consume"*).

## Goal

Batch 33 tells Mark *what happened* one night at a time (a verdict). This batch
asks the longer question across many nights: **does the bedroom's overnight
temperature/fan activity actually move his sleep score**, and if so, by how much —
so any future change to the fan's thresholds (when it turns on, how hard it runs)
is informed by his own measured data, not guesswork.

**Important framing, agreed up front:** this is a **read**, not a controller. It
never changes `fan_control.py`'s thresholds itself. The output is a
correlation-strength report — advisory evidence — and a human (Craig/Mark)
decides whether and how to act on it, exactly like every other insight/experiment
engine in this app (Decision #71/#72). Turning the recommendation into an
automatic threshold-tuning loop is a distinct, much larger decision (closed-loop
control of a physical device from a statistical model) and is explicitly **out of
scope** here.

## Why this is mostly reuse, not a new engine

This app already has the exact statistical machinery this needs:

- `insights.compute_drivers(records, outcome_key, driver_keys)` Pearson-ranks any
  set of named per-night driver values against an outcome (already used for
  `overnight_low_c`, `prev_day_training_load`, `sleep_stress_avg`, etc. against
  `sleep_score` / `recovery_hrv_ms`). It is fully generic over the driver keys —
  adding new ones is adding dict entries, not new maths.
- `InsightsService._driver_records` already builds one dict per calendar day
  merging `daily_metrics` / `sleep` / `weather_daily` / `activities` into driver
  keys. Note it already has `overnight_low_c`, but that's **outdoor** weather
  (`WeatherDaily.overnight_low_c`) — the indoor bedroom read from Batch 31 is a
  genuinely new signal, not a duplicate.
- `experiment_evaluation.py`'s `early_waking_0400` correlation evaluator already
  Pearson-ranks "measured candidate drivers" against a disruption proxy
  (`awake_sleep_sec`) — it just doesn't have indoor-temp/fan data as a candidate
  yet, because that data didn't exist before Batch 31.

So the net-new work is **assembling the per-night bedroom summary as driver
values** and plugging them into both existing engines — not building a model.

## New driver keys (sourced from Batch 31's series)

Per completed night (keyed by the wake-morning date, matching
`sleep_calendar_date(night) = night + 1`), derive from `temperature_readings` +
`fan_state_readings` (reusing `summarize_overnight` / Batch 33's classifier if
shipped, else computing the same rollup inline):

- `bedroom_warning_minutes` — minutes `>= THRESHOLD_ON_C` (19.5 °C).
- `bedroom_critical_minutes` — minutes `>= THRESHOLD_CRITICAL_C` (20.0 °C).
- `bedroom_fan_ran_minutes` — minutes the fan was on (already computed by
  `summarize_overnight`).
- `bedroom_peak_fan_speed` — the night's peak speed.

## 34.1 — Extend the existing driver-correlation engine

Add the four keys above to `insights.DRIVER_KEYS` and to
`InsightsService._driver_records`'s per-day dict, sourced by a per-night bedroom
lookup keyed the same way the existing weather/metrics dicts are. `GET
/api/v1/insights/drivers` (already live, preview-only) then surfaces them ranked
alongside the existing candidates — no schema change beyond the driver key
appearing in the existing `DriverCorrelation[]` list.

## 34.2 — Wire `early_waking_0400`'s measured candidates

Add the same four keys to the candidate list the `early_waking_0400` correlation
evaluator measures (`experiment_evaluation.py`), so the standing 04:00-waking
hypothesis can now test "was it the room" with real indoor data instead of only
outdoor overnight low. This is the exact item Batch 31 flagged as deferred.

## 34.3 — Plain-language surface, not just a coefficient

A Pearson `r` is not a useful headline on its own. Add a small deterministic
"read" layer (pure function, no LLM) that turns a driver's correlation +
its underlying grouped means into a sentence, e.g.:

> *"Nights with 60+ min above 20 °C average 6 points lower sleep score than
> cooler nights (12 nights measured)."*

Reuses `_mean`/grouping over the same `records` list `compute_drivers` already
built — no new statistics, just a sentence template around numbers already
computed. Surfaced wherever the driver ranking is already shown (the existing
`/trends` or a `/insights` detail read — exact placement decided at
`/batch-start` against whatever detail routes exist then) and, if `34.2` lands,
as part of the `early_waking_0400` experiment's evaluation text on `/experiments`.

## Sample-size gating (reuses the existing #71 pattern)

Every driver-correlation call already skips a driver below `MIN_CORRELATION_SAMPLES`
(currently 8) rather than reporting a misleading coefficient. Because
`fan_state_readings` only starts accumulating at the Batch 31 deploy, this
correlation will report **insufficient history** for a while after Batch 31/33/34
ship — that's correct, expected behaviour, not a bug, and matches how Batch 21's
year-on-year trends degrade gracefully until enough time has passed.

## Explicitly out of scope

- **No automatic fan-threshold tuning.** However strong the correlation, nothing
  in this batch writes to `fan_control.py`'s `ON_THRESHOLD_C` or the speed ladder.
  If the evidence later supports changing a threshold, that's a **human decision**
  — possibly a tiny follow-up batch to change a constant, reviewed like any other
  code change — not a model writing to its own config.
- **No new stats engine.** Everything here is `compute_drivers` / `pearson` /
  `_mean`, already shipped in Batch 17.
- **No new table.** Bedroom driver values are derived on read from
  `temperature_readings` / `fan_state_readings`, the same way weather/metrics
  drivers are derived on read today.
- **Not immediately actionable.** This is explicitly the "longer term" idea from
  the conversation that prompted it — real signal needs weeks of accumulated
  `fan_state_readings`, so this batch is worth sequencing well after Batch 31/33
  have been live for a while, not immediately after.

## Phases

- **34.1** Add the four bedroom driver keys to `insights.DRIVER_KEYS` +
  `_driver_records`, sourced from the Batch 31 series.
- **34.2** Add the same keys to the `early_waking_0400` correlation evaluator's
  measured candidates.
- **34.3** Pure plain-language summary sentence for a driver's correlation +
  grouped means; surfaced on the existing drivers/experiment read.
- **34.4** Tests: pure driver-record assembly from bedroom fixtures (including the
  night-keying join), the sentence template over fixed correlation fixtures, the
  sample-size gate (insufficient-history path), and the `early_waking_0400`
  evaluator picking up the new candidates; backend pytest/ruff/mypy pass, no
  migration, no new endpoint required (extends existing `GET
  /api/v1/insights/drivers` and `GET /api/v1/experiments/{id}/evaluate`).

## Testing

- Pure: driver-record assembly joins a bedroom-summary fixture onto a calendar
  date correctly (including nights with no bedroom data — must degrade to `None`
  for those keys, not crash); the plain-language sentence template over a few
  fixed `DriverCorrelation` + grouped-mean fixtures; the sample-size gate.
- DB-backed: `GET /api/v1/insights/drivers` includes the new keys once enough
  nights exist; `GET /api/v1/experiments/{id}/evaluate` for `early_waking_0400`
  picks up the new candidates without changing its gate/recommendation logic
  for experiments that don't have bedroom data.
- Backend pytest/ruff/mypy pass; frontend touched only if `34.3`'s sentence is
  surfaced in an existing page, in which case its render is covered too.
