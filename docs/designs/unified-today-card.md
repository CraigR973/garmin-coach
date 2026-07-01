# Batch 36 — Unified "Today" card

Status: Specced (not started). Decision #107 (assigned at `/batch-start`).
Tier: 🟢 Mid (frontend-only recomposition; no new logic, no payload change).

## Goal

Collapse Home's "today's workout" from a **summary card plus N separate session
cards** into **one Today card**: a day header, the day's session(s) as rows
inside it, and the day-level actions as a footer. Removes the duplicated verdict
badge and the "parent card followed by orphan children" feel, while keeping each
session's own Edit / Swap / Skip / Approve controls fully scoped.

From Craig's 2026-07-01 Home idea: "the day's workout is better as one section
rather than three separate sections."

## Why (the problem)

In `DashboardPage.tsx`, the pre-ride / rest-day phases render `DayPlanCard`,
which is actually **two-plus** cards stacked:

1. a summary `Card` — `"{label} day"` + a verdict `Badge`, the Add
   Cycle/Weights/Flexibility buttons, View week, Skip whole day, and "I did
   something else";
2. then a **separate** `TodayCard` (its own `Card`) **per** workout, each with
   the session icon/title/status and its Edit / Swap day / Skip (and, on a coach
   adjustment, Approve & upload / Ignore / Manual edit) plus their expand panels.

So a normal 1-workout day is already **two** cards, and the verdict `Badge` is
rendered **twice** — on the summary (`DayPlanCard`) *and* on the session card
(`TodayCard`). A 2-session day (bike + weights) is three cards. The information is
one thing — "here's today" — but it's presented as a parent card orbited by
sibling cards.

## Product shape

One `Card` titled **Today**:

- **Header:** `"{label} day"` (Cycle / Weights / Rest / Mixed …) + a **single**
  verdict badge. The per-session badge is removed — the day owns the verdict once.
- **Body — session rows:** each planned workout is a row *inside* the card
  (icon, title, type · duration · intensity, adherence chip, status line), each
  keeping **its own** action set and expand panels:
  - no coach change → Edit (bike) / Swap day / Skip;
  - coach adjustment present → Approve & upload / Ignore / Manual edit / Swap /
    Skip, with the `planAdjustments` list inline;
  - non-bike → "nothing to upload to Zwift" status, no upload action.
  A visual divider (not a nested card) separates multiple sessions so each row's
  controls stay unambiguous.
- **Footer — day-level actions:** Add Cycle / Weights / Flexibility, View week
  (`/delivery`), Skip whole day, and the "I did something else" actual-workout
  form.
- **Rest day (no workouts):** the same single card shows the "Rest is the plan
  today — add something light, swap one in, or record what happened" empty state
  with the footer actions. No separate empty "Today's session" card.

## Frontend

- Rework `DayPlanCard` into the single `Card` above. The current per-workout
  `TodayCard` becomes an internal **`WorkoutRow`** sub-component rendered in the
  body rather than as its own `Card`.
- **Preserve each row's local state.** `TodayCard` currently owns `panel`
  (`none|edit|swap|skip`), `ignored`, and the duration/intensity inputs; keep that
  state per row so two sessions expand independently inside the one card. This is
  the one real care-point of the batch — the controls must stay scoped to their
  row.
- Move `AddWorkoutButtons` and `ActualWorkoutForm` into the footer of the single
  card (they already exist; only their placement changes).
- The verdict `Badge` renders once in the header; drop it from the row.
- No change to any mutation, endpoint, or the `/api/v1/daily-loop` payload — this
  is pure recomposition of existing pieces. The Batch 29 delivery actions (edit /
  approve / swap / skip) and their toasts are wired exactly as today.

## Backend

None. No route change, no migration.

## Verification (planned)

- Web unit tests: one card renders for a rest day, a 1-workout day, and a
  2-workout (mixed) day; the verdict badge appears exactly once; each session
  row's Edit/Swap/Skip panel opens independently and fires the right mutation with
  the right `workoutId`; the coach-adjustment state shows Approve/Ignore on the
  right row only; day-level Add / Skip-day / "I did something else" still work
  from the footer.
- Update `DashboardPage.test.tsx` (and any `TodayCard`-specific assertions) for
  the merged structure.
- Web lint + build clean; backend suite untouched.

## Deferred / non-goals

- No change to what actions exist or how delivery works — Batch 29's action
  contract is unchanged; only the layout consolidates.
- No backend/payload change, no migration.
- Independent of Batch 35 (sleep card) and Batch 37 (collapse model); can ship in
  any order relative to 35, but is sequenced after it so the Home section count is
  already shrinking before Batch 37 introduces the collapse shell.
