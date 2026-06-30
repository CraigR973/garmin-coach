# Design: Overnight bedroom temperature × fan × sleep chart (Batch 31)

**Status:** Planned. Designed with Craig on 2026-06-30 from the "morning check-in
should graph overnight room temp vs when the fan was on/off/what setting" idea.
Decision number assigned at `/batch-start` (next free **#101**).
Builds on Batch 3 (`temperature_readings` Hive poll), Batch 27 (fan control loop,
`services/fan_control.py` + `scheduler.run_fan_control`), and the Batch 24
detail-route Home (`/bedroom` = `BedroomPage.tsx`, fed by `useDailyLoop`).
**Related:** `DECISIONS.md` #59 (Hive read), #95–97 (fan control + drive-then-disable
honesty), #71 (reuse `analyses`/avoid new tables unless justified — see the table
justification below), and the standing `early_waking_0400` hypothesis (Batch 22),
which this series later feeds but does **not** wire in this batch.

## Goal

Make the bedroom climate loop **legible**. Today the fan autopilot runs silently
every 15 min overnight and the only evidence it acted is in Railway logs. This
batch charts, for a night, the **room temperature curve**, **what the fan actually
did** (off / on + speed, against the 19.5 °C on / 20.0 °C critical thresholds), and
**the night's sleep** layered behind it — on the existing `/bedroom` detail route,
with a one-line glance on Home that links through.

It answers the question Mark actually has — *did the room cost me sleep, and is the
fan helping?* — and it makes the autopilot debuggable and trustworthy.

## The data situation (what's free, what's the gap)

A 2026-06-30 prod read (last 9 nights) established the shape:

- **Room temperature — already captured.** `temperature_readings`
  (`models/coaching.py:166`, `TemperatureReading`) is filled every 15 min by
  `scheduler.run_hive_temperature_poll`, with full overnight coverage (~44
  readings/night) and an `(user_id, captured_at_utc)` index. Plotting the temp
  curve is a windowed query — no new capture.
- **The room runs warm right now.** Every night Jun 24–29 crossed the 19.5 °C
  fan-on threshold for most/all of the window (Jun 25 sat 26–28 °C all night). So
  there is rich variation to plot today — this is *not* a winter-only feature.
  It will also honestly show the fan **can't win** on genuinely hot nights (an
  air-circulator moves air, it doesn't cool) — useful for setting expectations.
- **Fan state — NOT persisted (the gap this batch closes).** `run_fan_control`
  (`scheduler.py:700`) reads the live temp + the fan's actual state
  (`client.read_state()`, `scheduler.py:744`), computes a `FanDecision`, applies
  it, and **only logs** (`scheduler.py:749`). There is no fan column or table
  anywhere. The fan's on/off/speed history is therefore unqueryable. Deriving it
  from temp via the pure `describe_fan_intent` would give only *intended* state and
  silently diverge on manual overrides, cloud failures, the auto-toggle, and
  hysteresis — dishonest for a chart whose whole point is "what the fan **did**."
- **Sleep — per-night row exists; hypnogram shape TBD.** The `sleep` row
  (`models/coaching.py:60`) has `sleep_start_utc` / `sleep_end_utc`, the stage
  durations, `avg_sleep_stress`, `restless_moments_count`, and `raw_payload`. A
  per-interval sleep-levels series (hypnogram) *may* live in `raw_payload`; 31.0
  confirms it.

## Persistence model — a dedicated `fan_state_readings` table

A new table (migration `011`), mirroring `temperature_readings`:

| column | notes |
|---|---|
| `user_id` | FK → `profiles.id`, cascade |
| `captured_at_utc` | when the loop fired |
| `phase` | `control` / `winddown` |
| `auto_enabled` | `Profile.fan_auto_enabled` at fire time |
| `observed_temp_c` | the temp the **decision** used (nullable — no fresh temp) |
| `fan_on` | effective on/off this tick (nullable when not read) |
| `fan_speed` | effective speed (nullable) |
| `action` | `apply` / `hold` / `no_data` / `auto_off` / `unreachable` / `winddown` |
| `reason` | `FanDecision.reason` or branch reason |

Unique `(user_id, captured_at_utc)` (idempotent under APScheduler coalesce) +
`(user_id, captured_at_utc)` index for windowed reads — same pattern as
`temperature_readings`.

**Why a new table, not `analyses`** (the #71 default is to reuse `analyses`): this
is a genuine 15-min **time series**, like `temperature_readings` /
`activity_timeseries`, not a narrative/audit artifact. `analyses` is keyed one row
per `(type, subject_date)` (the `wake_check` pattern) and would force either ~44
rows/day of audit or a JSON array — both worse to query and join than a typed
series table. **Rejected alternative:** adding `fan_*` columns to
`temperature_readings` — the Hive poll and the fan loop are *separate* 15-min jobs
that fire at different offsets, so co-locating would falsely imply simultaneity;
keep them separate and join by nearest-time at read.

**Where the write happens.** `_apply_fan_control` (`scheduler.py:736`) does cloud
I/O *outside* the DB session (closed at `scheduler.py:730`). Refactor it to
**return** the result (observed/effective `FanState`, `FanDecision`, temp), and have
`run_fan_control` open a fresh session to persist one tick. **Record a tick on
every within-window fire**, including the early-return branches —
`auto_disabled` → `action=auto_off` (no cloud read, `fan_on=null`), no fresh temp →
`no_data`, cloud unreachable → `unreachable` — so the chart **explains gaps**
("autopilot off" vs "cloud unreachable" vs "off because cold") rather than going
blank. `idle` (daytime) is still a no-op and writes nothing — exactly the window we
don't chart.

## Read API — `GET /api/v1/bedroom/overnight`

New `routers/bedroom.py` (there is no bedroom router today — `/bedroom` is fed by
`useDailyLoop`). A **pure DB read, never writes**, standard envelope:

- Query `?date=YYYY-MM-DD` = the night whose window *starts* that evening; default
  = **last completed night**.
- Window = `fan_control.WINDOW_START` (21:30) → `WINDDOWN_END` (09:00) profile-local,
  converted to UTC for the query (reuse the loop's window constants so the chart and
  the autopilot never disagree).
- Returns, server-side joined/bucketed: `temperature[]` (`{t, c}`), `fan[]`
  (`{t, on, speed, action, reason}`), `sleep` (`{start, end, awakeSec,
  restlessMoments, score, ageAdjustedScore, stages?}`), and `thresholds`
  (`{onC: 19.5, criticalC: 20.0}`). A `nights[]` list (recent dates with data)
  drives the pager. Shared Zod schema in `@coach/shared`.

Kept off `/api/v1/daily-loop` deliberately — it's a heavy detail read, and the
Batch 24/28 ethos is a lean daily-loop with dense reads on detail routes.

## Frontend — chart on `/bedroom`, glance on Home

- **`BedroomOvernightChart`** (recharts `ComposedChart`, already at `^3.8.1`):
  left Y = temperature °C (`Line`); right Y = fan speed 0–7 (`Area`/step);
  `ReferenceLine`s at 19.5 and 20.0; the sleep window as a shaded `ReferenceArea`
  (plus the hypnogram as a faint background band if 31.0 finds it), awake/restless
  annotated. Muted/hatched fan segments where `action ∈ {auto_off, unreachable}`.
  Renders below the existing fan card on `BedroomPage.tsx`. Night **pager**
  (default last night, page back through `nights[]`). Clear empty state for
  nights with no data yet.
- **Home glance line:** one line on the evening/post-ride Home —
  *"Last night: 19→21 °C, fan ran 3.5 h (peak speed 5)"* — computed from the same
  series, linking to `/bedroom`. One line only; Home stays lean.

## De-risk first (31.0, quick prod read — throwaway, like `~/garmin-spike`)

1. Inspect a real `sleep.raw_payload` for Mark: is there a per-interval
   sleep-levels array (hypnogram)? **If yes** → render it as the faint background
   band. **If no** → overlay only the sleep-window `ReferenceArea` + awake/restless
   annotation, and treat the hypnogram as a later extension. This decides 31.3's
   sleep layer and must be settled before building it.
2. Sanity-check temp vs fan-loop fire offsets within the 15-min cadence to confirm
   nearest-time join (not exact-timestamp) is the right read alignment.

## Phases

- **31.0 De-risk:** confirm the hypnogram shape + the temp/fan join alignment (above).
- **31.1 Persist fan state:** `fan_state_readings` table (migration `011`); refactor
  `_apply_fan_control` to return its result; `run_fan_control` writes one idempotent
  tick per within-window fire, covering the `auto_off` / `no_data` / `unreachable`
  branches so gaps are explained. No change to the **decision** logic or thresholds.
- **31.2 Read API:** `routers/bedroom.py` `GET /api/v1/bedroom/overnight` — pure,
  night-windowed join of temp + fan + the night's sleep row; default last completed
  night; envelope + shared schema; registered in `main.py`.
- **31.3 Chart:** `BedroomOvernightChart` on `/bedroom` — dual-axis temp+fan,
  threshold lines, sleep overlay (per 31.0), night pager, empty state.
- **31.4 Home glance:** the one-line last-night summary on the evening/post-ride
  Home, linking to `/bedroom`.
- **31.5 Tests** (below).

## Safety / invariants preserved

- **Fan logic unchanged.** This batch only *adds a write + a read*; thresholds,
  hysteresis, window, and `decide_fan_action` are untouched. The autopilot behaves
  exactly as in Batch 27.
- **Graceful degradation intact.** The loop still never raises and still skips the
  cloud when `auto` is off / no creds; persistence rides inside the existing
  try/except and must not introduce a path that can fail the job.
- **Secret-safe.** No fan/Hive credentials in the new table, API, or chart.
- **No new Hive/Dreo cloud calls.** The read API is DB-only; the chart adds no
  device polling.

## Reuses

- `temperature_readings` (Batch 3) and the `sleep` row (Batch 1) — read as-is.
- `services/fan_control.py` window/threshold constants — single source of truth for
  the chart window and reference lines.
- `BedroomPage.tsx` / `useDailyLoop` / `apiFetch` scaffolding (Batch 24/27) and the
  recharts patterns from `TrendsPage.tsx` (Batch 21).

## Testing

- **Pure:** night-windowing + the nearest-time temp/fan join; the Home glance
  summary (range, run-hours, peak speed); sleep-overlay extraction from a
  `raw_payload` fixture (with and without a hypnogram).
- **DB-backed:** `run_fan_control` writes exactly one tick per within-window fire
  across all branches (`apply`/`hold`/`no_data`/`auto_off`/`unreachable`/`winddown`),
  idempotent under a coalesced double-fire; the overnight endpoint returns a
  correct joined series for a seeded night and the right default ("last completed
  night").
- **Web:** chart renders temp+fan with threshold lines; sleep overlay present and
  absent; night pager; empty state; the Home glance line.
- Backend pytest/ruff/mypy and frontend test/build/lint green; Alembic `011`
  up/down checked in CI.

## Non-goals

- **No change to fan behaviour or thresholds** — only persistence + presentation.
- **Not wiring the `early_waking_0400` experiment** — this batch *produces* the
  fan/temp series that evaluation could later consume (Batch 22 path); the wiring
  is a separate, smaller follow-up.
- **Not live/real-time** — the chart is the completed overnight window, refreshed
  each morning (a "last night" read, matching the morning-check-in framing).
- **Not cooling** — if the chart shows the fan pegged at max while the room stays
  hot, that's a true insight (airflow ≠ cooling), not a bug to fix here.
- **Not back-filling history** — the fan series starts accumulating from the 31.1
  deploy; temp history pre-dates it, so early nights show temp + sleep with an
  empty fan track (expected, and the empty state should say so).
