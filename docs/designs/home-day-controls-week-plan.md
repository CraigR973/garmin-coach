# Batch 30 — Home day controls + rearrangeable week plan

Status: shipped in PR #45 (`263460f`) on 2026-06-30.

## Goal

Make Home answer "what kind of day is this, and what can I do about it?" while making the Plan page the place to rearrange the real active week. This builds on Batch 29's Today-card action model instead of introducing a separate planning abstraction.

## Product Shape

Day state is derived from active `planned_workouts`, not stored as a new enum:

- `rest` means no active workout rows on the date.
- `cycle` is any bike workout type.
- `weights` covers strength workout types.
- `flexibility` maps to the existing `mobility` plan concept.
- `mixed` means more than one category on the same date.

The live plan inspected before the batch had one active workout per workout day, but the data model and API already support multiple rows per date. The UI therefore treats a day as a list of actionable workouts, with a simple category label on top.

## Home

Home keeps the Today card as the action surface. It now adds day-level controls above the workout cards:

- Add Cycle / Weights / Flexibility.
- Skip whole day.
- Record "I did something else".
- View week.

Each same-day workout still renders through the Batch 29 `TodayCard`, so existing per-workout actions remain available: edit, approve adjustment, swap/move, and skip. A rest day shows the add controls and a View week link instead of pretending rest is a stored workout.

## Plan Page

The Plan page reads `GET /api/v1/plan-actions/schedule` and renders the grouped active plan, including explicit rest days in the visible date window. It supports:

- Add Cycle / Weights / Flexibility to any day.
- Skip a whole day.
- Move a workout to another day via the existing workout-delivery swap route.
- On rest days, swap an already planned workout into the rest date.

The old hard-coded weekly shape and proposal-approval flow are removed from this page; proposal approval now belongs to Home's Today card.

## Backend

New router: `apps/api/src/routers/plan_actions.py`.

New service boundary: `apps/api/src/services/plan_actions.py`.

Supporting taxonomy: `apps/api/src/services/workout_categories.py`.

Routes:

- `GET /api/v1/plan-actions/schedule`
- `POST /api/v1/plan-actions/days/{workout_date}/workouts`
- `POST /api/v1/plan-actions/days/{target_date}/swap-in`
- `POST /api/v1/plan-actions/days/{workout_date}/skip`
- `POST /api/v1/plan-actions/days/{workout_date}/actual`

Bike additions create a simple endurance structured-workout row and reconcile through the Batch 29 delivery rail. Weights/flexibility additions are local plan rows with no Zwift upload. Whole-day skip loops over active workouts and applies the existing skip behavior to each. "Did something else" writes an unplanned `ManualEntry` so reality is captured without fabricating a planned workout.

## Delivery Safety

Mixed days require delivery state to attach to the workout, not just the date. Batch 30 therefore prefers `planned_workout_id` when looking up delivery proposals and falls back to date-only rows for older data. Reslotting no longer deactivates every active workout already on the target date, so moving one workout into a mixed day preserves the others.

## Verification

- Backend focused plan-action/executable-coaching tests: `8 passed, 25 skipped`.
- Backend full suite: `348 passed, 118 skipped`.
- Backend ruff: clean.
- Backend mypy: clean.
- Shared tests: `7 passed`.
- Web targeted Dashboard/WeekAhead tests: `12 passed`.
- Web lint: 0 errors, existing Fast Refresh warnings only.
- Web build: clean.
- Full web vitest: passed with `--testTimeout=10000`; the default 5s timeout was too tight under local whole-suite load.

## Deferred

- No new migration.
- No automatic closeout or production deploy in this batch-start session.
- No bulk plan generator changes beyond preserving mixed-day delivery semantics.
- No new Zwift workout editor for added bike sessions beyond the simple default endurance template.
