# Batch 32 — Plan page tap-to-move day picker

Status: Specced (not started). Decision #102 (assigned at `/batch-start`).

## Goal

Replace the Plan page's fragmented workout-move controls with **one tap-to-move
day picker**, so rescheduling a workout is a single, consistent gesture that
works well for Mark on his phone. Explicitly **not** drag-and-drop: the Plan page
is edited by Mark on a phone, and touch-dragging a card across a vertically
scrolling day list is the least reliable interaction there is for the primary
user. A bottom-sheet day picker gives the same "put this on that day" outcome
with large tap targets and no drag.

## Why (the problem)

`apps/web/src/pages/WeekAheadPage.tsx` (route `/delivery`, nav label "Plan")
currently exposes moving a workout through two different, asymmetric controls:

- Each workout row shows up to three `Move <date>` buttons — but only the **next
  3 days** (`nextScheduleDates`), so a session can't be moved earlier or more
  than 3 days out.
- A separate "Swap a workout into this rest day" button-list appears **only on
  rest days**, listing other workouts by date.

These are two UIs for what is, in the backend, a single operation. Both the
per-workout move (`POST /api/v1/workout-delivery/planned-workouts/{id}/swap`) and
the rest-day swap-in (`POST /api/v1/plan-actions/days/{date}/swap-in`) call the
same `ExecutableCoachingService.swap_day(planned_workout_id, target_date)`, which
already:

- **moves** the session when the target day is empty,
- **swaps** the two when the target day is occupied,
- works in **either direction** (the only guard is `target == source` → HTTP 400),
- moves the Zwift event(s) in place and audits the action (Decisions #99, #97).

So the limitation is purely presentational. The backend already supports "move
this workout to any day, either direction."

## Product shape

One control per workout row: a **Move** button. Tapping it opens a bottom-sheet
day picker listing the days of the visible plan window (the page's rolling
14-day schedule). Each day row shows:

- weekday + date,
- what's already scheduled that day (workout title(s), or "Rest"),
- a "Today" marker,
- the workout's current day rendered as current and **disabled**.

Tapping a day calls the single swap route with that `targetDate` and closes the
sheet. The backend decides move-vs-swap; the toast reflects the outcome through
the existing success handling. This removes the "next 3 days only" limit and the
separate rest-day swap-in list — a rest day is just another selectable row in the
picker.

## Frontend

- Page: `apps/web/src/pages/WeekAheadPage.tsx`. Widen its schedule window from
  `days=7` to `days=14` (the backend already caps
  `GET /api/v1/plan-actions/schedule` at 14) so a session can be pushed into next
  week — the common fatigue move — without introducing a second date space.
- Extract the picker as a **reusable component** (`MoveWorkoutSheet`), not inline
  in the page, so Home's Today-card swap can adopt the same UX later at low cost.
- Picker primitive: shadcn `Sheet` with `side="bottom"` (already present at
  `apps/web/src/components/ui/sheet.tsx`) — thumb-reachable, focus-trapped, no
  drag. (A `vaul` Drawer could be added later for drag-to-dismiss polish; not
  required for this batch.)
- The picker's day list **is** the days the page renders (the same 14-day
  window) — never a separate calendar — so it can never offer a day the page
  doesn't show. Derived from the already-fetched `plan-schedule` query, so no new
  network call.
- Standardize every move on the per-workout swap route
  `POST /api/v1/workout-delivery/planned-workouts/{id}/swap`; drop the
  `WorkoutRow` `Move <date>` button trio (and its `nextScheduleDates` helper) and
  the rest-day swap-in block from this page.
- Reuse the existing `moveMutation`; retire `swapIntoMutation` from this page (the
  `/plan-actions/days/{date}/swap-in` endpoint stays for any other caller).

## Backend

None. No new route, no service change, no migration. `swap_day` already covers
move-or-swap in both directions.

## Accessibility / mobile

- All targets are buttons in a bottom sheet — no pointer precision, no
  long-press, no scroll/drag conflict.
- Keyboard + screen-reader usable for free (`Sheet` handles the focus trap and
  escape).
- If plan-page editing later becomes desktop-primary, drag-and-drop can be
  layered on top of this same swap model as a pointer-only enhancement without
  removing the tap path.

## Verification (planned)

- Web: unit-test the picker — opening from a workout, day-list contents (rest vs
  occupied, today marker, current day disabled), selecting a day fires the `swap`
  mutation with the correct `targetDate`, sheet closes; loading/empty states.
- Rewrite `apps/web/src/pages/WeekAheadPage.test.tsx` for the new control; remove
  assertions on the old `Move <date>` trio and the rest-day swap-in list.
- Web lint + build clean; shared package unaffected.
- Backend suite untouched (no backend delta) — run once to confirm no incidental
  breakage.

## Deferred

- No drag-and-drop (out of scope for the mobile-primary user; revisit only if
  desktop editing becomes primary).
- No backend change, no migration.
- Home's Today-card swap (Batches 29/30) is left unchanged here, but the picker
  is built as a reusable `MoveWorkoutSheet` so Home can adopt the same gesture in
  a fast follow-up without a rewrite — proving the pattern on the Plan page first
  keeps a shipped, separately-tested surface out of this batch's blast radius.
- The `/plan-actions/days/{date}/swap-in` route is left in place; only the Plan
  page stops using it.
