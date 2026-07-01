# Design: Bedroom overnight temperature verdict (Batch 33)

**Status:** Planned. Designed with Craig on 2026-07-01, following up directly on
Batch 31 (`docs/designs/bedroom-overnight-chart.md`). Decision number assigned at
`/batch-start` (next free **#103**). Builds on Batch 31's `fan_state_readings`
(migration `011`) and `services/bedroom_overnight.py`'s `summarize_overnight` +
threshold constants (`THRESHOLD_ON_C=19.5`, `THRESHOLD_CRITICAL_C=20.0`), and
reuses the app's existing Green/Amber/Red vocabulary (`verdictBadgeVariant` /
`verdictLabel` in `DashboardPage.tsx`/`lib/copy.ts`) rather than inventing a new
one.

## Goal

Batch 31 shipped a chart, but reading a chart still takes a moment. Give Mark a
one-glance **verdict** for how the room did last night — Green / Amber / Red —
right next to the existing "Last night: 19→21 °C, fan ran 3.5 h" glance on Home,
and at the top of the `/bedroom` chart. The verdict answers "did the room cost me
sleep last night, yes or no" without reading the curve.

## What's already there vs. the gap

- `summarize_overnight` (`services/bedroom_overnight.py`) already rolls a night's
  temperature + fan series into `OvernightSummary` (`min_temp_c`, `max_temp_c`,
  `fan_ran_minutes`, `peak_speed`) from the same per-reading series the chart
  renders — no new data, no new query.
- **The gap:** nothing today measures *how long* the room actually sat in the
  disruption zone, only its min/max. A room that touched 19.6 °C for five minutes
  and one that sat at 22 °C all night both show the same qualitative shape today
  (temp above the line) with no sense of severity.

## Classification — reusing the Batch 31 thresholds, not new ones

Extend `OvernightSummary` with two derived fields, computed the same way
`fan_ran_minutes` already is (reading count × the poll interval — Hive polls
`temperature_readings` on the same ~15-minute cadence as `fan_control.INTERVAL_MIN`,
so no new interval constant is introduced):

- `warning_minutes` — minutes with a reading `>= THRESHOLD_ON_C` (19.5 °C).
- `critical_minutes` — minutes with a reading `>= THRESHOLD_CRITICAL_C` (20.0 °C).

Then a pure classifier, `room_verdict(warning_minutes, critical_minutes) -> Verdict`:

| Verdict | Rule |
|---|---|
| `green` | `warning_minutes == 0` — the room never crossed the fan-on line. |
| `amber` | `warning_minutes > 0` and `critical_minutes < RED_CRITICAL_MINUTES`. |
| `red` | `critical_minutes >= RED_CRITICAL_MINUTES`. |

`RED_CRITICAL_MINUTES` is a **judgment call, not a derived number** — proposed
default **60** (an hour or more at/above 20 °C reads as a genuinely disruptive
night, consistent with the existing thermal-alert framing in `nudge_alerts.py`).
Craig/Mark can tune it after seeing a few real verdicts; it's a single named
constant next to the other threshold constants, not buried in logic.

## API — extend the existing overnight response, no new route

`OvernightSummaryOut` (`routers/bedroom.py`) gains `warningMinutes`,
`criticalMinutes`, `roomVerdict` (`"green" | "amber" | "red"`). Same envelope,
same endpoint (`GET /api/v1/bedroom/overnight`), same shared Zod schema extended
— no new migration, no new query (the classifier runs over the same rows
`summarize_overnight` already reads).

## Frontend — a badge, not a new card

- **Home glance:** the existing `OvernightGlance` line (now living in the morning
  brief per the earlier fix) gets a small `Badge` (reusing `verdictBadgeVariant`'s
  success/warning/error mapping) before or after the text —
  e.g. 🟡 *"Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)"*.
- **`/bedroom` chart:** the same badge sits in the chart card header, next to the
  night pager, so paging back through nights shows the verdict for whichever
  night is in view.
- No new screen, no new route.

## Phases

- **33.1** Extend `summarize_overnight` with `warning_minutes` / `critical_minutes`
  + the pure `room_verdict` classifier and its threshold constant.
- **33.2** Extend `OvernightSummaryOut` + the shared Zod schema with the three new
  fields; no migration.
- **33.3** Frontend: verdict badge on the Home glance and the `/bedroom` chart
  header, reusing `verdictBadgeVariant`.
- **33.4** Tests: pure classifier boundary cases (0 min, just under/at/over
  `RED_CRITICAL_MINUTES`, warning-only vs. critical nights); DB-backed endpoint
  returns the new fields for a seeded night; web renders the correct badge colour
  for each verdict and updates the existing glance/chart tests.

## Safety / invariants preserved

- **No change to the fan control loop, thresholds, or the chart itself** — this
  batch only classifies data the chart already renders.
- **No new table, no new endpoint, no new cloud call.**

## Non-goals

- **Not a new Green/Amber/Red framework** — reuses the app's existing verdict
  vocabulary and badge component so it reads as "the same kind of verdict you
  already trust," not a fourth traffic-light system.
- **Not tunable per-user yet** — `RED_CRITICAL_MINUTES` is a single constant; a
  settings surface to adjust it is a later idea if the default proves wrong in
  practice, not part of this batch.
- **Not predictive** — this classifies the night that already happened, same as
  the chart; Batch 34 is where a longer-horizon "what should the fan do
  differently" read would live.
