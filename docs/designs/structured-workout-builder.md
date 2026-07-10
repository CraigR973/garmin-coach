# Structured Workout Builder

Status: Shipped via PR #102 / squash `80ff8ba` (2026-07-10). Decision #150.

Source: Mark's `Workout Structure for The App 10.07.26.xlsx`.

## Scope

Batch 77 turns Mark's spreadsheet shape into the app's existing structured bike
workout grammar instead of creating a second workout model.

The builder supports:

- Indoor or outdoor.
- Optional warm-up ramp, defaulting to 45% -> 75% FTP.
- Optional Zone 2 lead-in at 55% FTP.
- Either one repeated interval pair:
  - interval 1 duration + %FTP
  - interval 2 duration + %FTP
  - repeats
- Or one steady block:
  - block duration
  - block %FTP
- Optional cool-down ramp, defaulting to 75% -> 45% FTP.

The output is stored in `planned_workouts.structured_workout` with
`format="bike"`, the existing Batch 67 `steps` grammar, `source="structured_builder"`,
and a `delivery` flag (`indoor` or `outdoor`). No migration is required.

## Behaviour

- A custom built workout saved from the Week tab becomes a normal
  `source="plan_action_add"` planned workout on the chosen day.
- Indoor custom workouts use the existing push-on-plan-set rail:
  `ExecutableCoachingService.reconcile_deliveries(...)` builds the IR and updates
  intervals.icu/Zwift.
- Outdoor custom workouts are stored but deliberately not delivered to Zwift.
  Batch 78 owns Garmin Connect / bike-computer delivery.
- Editing an existing bike session uses the same builder payload. The old row is
  deactivated, a new version is inserted for the same date, and indoor edits
  re-sync the existing Zwift event in place via the same reconcile path.
- Completed workouts cannot be structurally edited.

## Boundaries

- No arbitrary graph editor beyond Mark's spreadsheet fields.
- No migration.
- No Garmin Connect write path; outdoor delivery is Batch 78.
- No change to verdict logic, #133, #135, or Red-never-VO2.
- Existing quick-add subtype presets remain available and unchanged.

## Verification

- Full backend pytest: 551 passed / 183 skipped.
- Backend ruff check + format check clean on touched files.
- Backend mypy clean on touched files.
- Shared typecheck + tests clean.
- Web typecheck clean.
- Full web vitest: 193 passed.
- Web lint: 0 errors, 6 pre-existing Fast Refresh warnings.
- Web build clean under Node 20.
