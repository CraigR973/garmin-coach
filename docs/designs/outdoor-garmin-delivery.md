# Outdoor Garmin delivery

Status: In progress — Batch 78. Decision #151.

Source: Mark's `Workout Structure for The App 10.07.26.xlsx` Indoor/Outdoor field
+ his Q2 ("build an outdoor ride into Garmin Connect → bike computer").

## Scope

Batch 77 gave the structured-workout builder an Indoor/Outdoor choice, stored as
a `delivery` flag (`indoor` | `outdoor`) inside `planned_workouts.structured_workout`.
Indoor rides deliver to Zwift through the existing intervals.icu rail; outdoor
rides were stored but deliberately **not** delivered. Batch 78 delivers outdoor
rides to Garmin Connect so they sync to Mark's Edge and he can follow the
structured targets on the road.

## Two decisions settled at `/batch-start`

1. **Direct Garmin upload — not intervals.icu's own Garmin sync.**
   `garminconnect` (0.3.6, already our authenticated read-only dependency) exposes
   `upload_workout`, `schedule_workout`, `get_workouts`, `delete_workout`, and
   `unschedule_workout`, plus a typed `CyclingWorkout` with a `POWER_ZONE` target.
   Direct upload gives a synchronous result we can be honest about on failure
   (#97), needs no dependency on Mark having connected Garmin↔intervals.icu, and
   keeps the intervals.icu path meaning "Zwift" only.

2. **A new `garmin_workout_deliveries` table — not a reuse of
   `workout_delivery_proposals`.** The intervals table's columns are
   intervals-shaped (`zwo_xml` NOT NULL, `intervals_event_id`/`intervals_payload`)
   and reuse would force provider-guards onto the live Zwift-path queries. A
   dedicated table isolates the Garmin write path from the rail Mark rides daily,
   stores the Garmin identifiers under honest names, and survives Batch 77's row
   re-versioning by keying on `(user_id, workout_date)`. The indoor/outdoor flag
   itself still rides in `structured_workout` JSONB (no migration for that).

## Pieces

- **`services/garmin_workout_export.py`** — pure `build_garmin_workout(ir, ftp_watts)`
  maps the Batch 67 IR to Garmin's cycling-workout JSON. Mirrors `build_zwo_xml` /
  `build_intervals_payload`. Flat expanded steps (the IR is already expanded):
  - warm-up phase → `warmup` step; cool-down → `cooldown`; interval work →
    `interval`; the recovery valleys inside an interval → `recovery`.
  - `time` end condition, value = `durationSec`.
  - `power.zone` target in **absolute watts** from FTP: `watts = round(ftp*pct/100)`.
    A ramp step (`powerStartPct != powerEndPct`) becomes a low→high target range;
    a steady step becomes a tight band (±`POWER_BAND_PCT` FTP, min `POWER_BAND_MIN_WATTS`).
  - Cadence targets are not emitted (Garmin steps carry a single target; power wins
    for a road ride).
- **`GarminConnectClient` write methods** (`garmin_sync.py`) — `upload_and_schedule_workout`
  and `delete_scheduled_workout`, on the same authenticated garth session as the
  read path. The read/sync path is unchanged (Garmin stays ingestion-direct, #27).
- **`services/garmin_workout_delivery.py`** — async `GarminWorkoutDeliveryService`.
  `reconcile_workout(...)` builds the IR → Garmin JSON, uploads + schedules via
  `asyncio.to_thread`, and upserts the delivery row. Idempotent (a row already
  carrying the current planned-workout version is a no-op). Honest on failure
  (row `status='failed'` + `last_error`; never silently dropped; retried next
  reconcile). Replace-in-place on edit: unschedule + delete the old Garmin workout,
  then upload + schedule the new one.
- **Routing** (`executable_coaching.py`) — `reconcile_deliveries` now also delivers
  **outdoor** bike workouts to Garmin, alongside the unchanged indoor→Zwift pass.
  Each workout is reconciled in isolation, and Garmin is only touched when the
  window actually contains an outdoor ride — so the indoor-only path (and every
  existing test) is unaffected.
- **Surface** — the outdoor delivery status (delivered / failed) is exposed
  read-only on the workout so a failure is visible, not silent.

## Data model — `garmin_workout_deliveries` (coach schema)

`id`, `user_id` (FK profiles, CASCADE), `planned_workout_id` (FK, SET NULL),
`planned_workout_version`, `workout_date`, `status`
(`pushed` | `failed` | `deleted`), `garmin_workout_id`, `garmin_schedule_id`,
`garmin_payload` (JSONB), `structured_workout_ir` (JSONB), `last_error`,
`pushed_at_utc`, `created_at`, `updated_at`. Unique on
`(user_id, workout_date)` — one live Garmin delivery per slot, re-synced in place.

## Boundaries

- The indoor→Zwift rail is untouched.
- No change to verdict logic, #133, #135, or Red-never-VO2.
- Garmin remains ingestion-direct (#27); this only *writes* a planned workout.
- No arbitrary graph editor; the Garmin JSON is authored from the same IR the app
  already builds.

## Verification

- Unit: IR→Garmin JSON mapping (step types, watts from FTP, ramp range vs steady
  band, durations, flat expansion).
- Service: outdoor flag routes to Garmin (fake client); indoor path unchanged;
  idempotent no-op on the same version; honest failure records `last_error` while
  the rest of the reconcile still runs; replace-on-edit unschedules + re-uploads.
- Gates: backend pytest/ruff/format/mypy, shared typecheck, web vitest/tsc/lint/build.
- Closeout: production smoke incl. a Garmin device spot-check (an outdoor ride
  appears on Mark's calendar/Edge with its targets).
