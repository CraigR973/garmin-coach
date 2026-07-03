# Design: Evening sleep projection (Batch 46)

**Status:** Shipped in PR #66 (`5bf9940`). Backend + frontend, no migration;
optional `analyses` audit row/push and post-workout "impact tonight" line
deferred. Decision #116.
Closes the daily loop **back to sleep** — the stage Mark named: "seeing how that
[workout] analysis will impact his sleep, and then prepare his bedroom for the
night." Builds cleanly on Batch 45 for the evening push, but the read surface
ships without it.

## Problem

The loop's forward-looking read is **training-only**: the post-workout analysis
gives "impact on tomorrow['s training]", and the "Tonight" Home section
(`SleepPrepBody` + the `run_evening_nudge` copy) is the **static** KB sleep
protocol (pre-cool 17 °C, 20:00 breathing, snack ≤ 21:30, seal ~22:00, bed
23:15). Nothing projects **how today's training will affect tonight's sleep**, so
Mark can't prepare the room / routine specifically for the night the day's work
set up.

## Builds on / reuses

- **Today's training load** — already assembled: activities + Batch 44
  `ride_intervals` execution / Training Effect / duration / session timing; the
  Batch 20 `reviews` rollups already aggregate load and the morning packet
  already carries the day's plan.
- **Mark's own measured sleep drivers** — Batch 17 `insights.compute_drivers`
  (the strongest Pearson movers of sleep/recovery over his history) and the
  Batch 34 bedroom×sleep driver keys. This is *his* data on what actually moves
  his sleep, not a generic model.
- **Overnight weather** — `weather_daily` overnight low / wind (already synced).
- **The static protocol** — the KB `sleep_protocol` section, as the baseline the
  projection *modulates* rather than replaces.
- **The surface** — the `tonight` Home section (`homeSections.ts`) +
  `SleepPrepBody`; optionally the Batch 45 evening push rail.

## What the change adds

**Backend**

- **`services/sleep_projection.py`** — a pure, DB-free core. Given today's
  training-load signals (a late and/or high-intensity session, high TSS, evening
  workout timing), Mark's measured drivers (Batch 17/34), and the overnight
  weather, produce a small, **explainable** projection:
  - a **qualitative directional read** — e.g. "hard late session + warm overnight
    → HRV may dip; protect the wind-down" — with its evidence (which driver, which
    load signal). **No numeric sleep-score prediction** — false precision that
    won't reproduce run-to-run (consistent with the Batch 44 no-numeric-rating
    decision, #114).
  - **1–2 personalised prep actions** layered on top of the static protocol —
    e.g. "you trained hard at 18:00, so bring the seal forward; the fan will
    pre-cool from 21:00." When the autopilot is on, the actions defer to it
    (Batch 45 reconciliation) and only ask Mark for a genuine manual step.
- **Fallback** — a rest day, or before enough driver history exists, degrades to
  the plain static protocol (no regression).
- **Optional `analyses` audit row** (`analysis_type='sleep_projection'`,
  idempotent per subject-date) so the evening push and the Home read share one
  generated projection.

**Shared / Frontend**

- Surface the projection in the **Tonight** Home section (augments / replaces the
  static protocol text) with its evidence one tap away; optionally append an
  "impact on tonight's sleep" line to the post-workout read.
- Optional Zod field if the projection rides the daily-loop payload.

## Boundaries (kept)

- **Deterministic + advisory** — never changes the Green/Amber/Red verdict or the
  `fan_control.py` thresholds (consistent with #71/#72 and the Batch 34 advisory
  boundary). It informs Mark and the wind-down; it does not tune the autopilot.
- **Graceful degradation** — rest day / insufficient driver history → static
  protocol.
- **No migration** — reads existing series; the optional audit row lands in
  `analyses` (`analysis_type` is already `String(50)`).

## Tests

- Pure projection over fixtures: hard-late vs easy-early vs rest day; warm vs
  cool overnight; with vs without measured drivers — asserting the directional
  read + prep actions and that no numeric score is emitted.
- Fallback to the static protocol when there is nothing to say.
- Home Tonight render shows the projection + evidence; the static protocol still
  renders on a rest day.
- If pushed: idempotent per subject-date via the Batch 45 rail.
