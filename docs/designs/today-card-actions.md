# Design: Today-card actions + push-on-plan-set delivery (Batch 29)

**Status:** Shipped in PR #44 (squash `8b5a71e`, 2026-06-29). Every open fork
below was **settled** in the 2026-06-29 design session with Craig. Builds on
Batch 24 (time-aware Home),
Batch 25 (same-day delivery + manual override, `services/executable_coaching.py`),
and the Batch 12 intervals.icu delivery rail.
**Related:** `DECISIONS.md` #29/#30 (propose→approve→push; verdict-adjusted IR),
#31 (lead-days=2 auto-push — **superseded**), #91 (same-day-on-approval —
**superseded**), #97 (drive-then-disable: keep local state honest on a failed
cloud write).

## Goal

Make the Home "Today" card the one place Mark acts on his day. It shows
**whatever workout is next, regardless of type**, and offers the right actions
for the situation:

- **No coach changes** (e.g. a cycling day, slept fine — the session is already
  in Zwift): **Edit · Swap day · Skip**.
- **Coach changed it off last night's sleep/recovery** (Amber/Red verdict):
  **Approve & upload to Zwift · Ignore suggestions · Manual edit · Swap day · Skip**.

A non-bike (strength/etc.) session shows the same card with **Edit/Swap/Skip**
but **no Zwift upload**.

## The two states (driven by data, not a manual toggle)

The "did the coach change it?" split is already a real signal. `adjust_ir_for_verdict`
(DECISIONS #30, `services/executable_coaching.py`) annotates the IR with
`adjustment.changed` — `false` on Green (`origin: as_planned`), `true` on Amber
(`amber_regeneration`) / Red (`red_substitution`). The card reads that flag:

- `changed == false` → **no-changes** state (Edit / Swap / Skip).
- `changed == true` → **changes** state (Approve & upload / Ignore / Manual edit
  / Swap / Skip), with the adjustment summary (`planAdjustments`) shown inline as
  *the thing being approved*, not the current passive banner.

## Delivery model — push when the plan is set (the key change)

**Decision:** each workout is delivered to Zwift **as soon as it is in the plan**
(days ahead), not on morning approval. So by the morning the as-planned session
is already in Zwift and the morning is **review-only**. This supersedes both #31
(lead-days=2 auto-push) and #91 (same-day-on-approval).

Consequence: **every Home action becomes a re-sync of the already-delivered
event**, not a first-time send.

| Action | State | Zwift effect |
|---|---|---|
| (plan set / restructured) | — | **create** the event |
| Edit (manual duration/intensity) | both | **replace** the event |
| Approve & upload | changes | **replace** with the adjusted IR |
| Ignore suggestions | changes | **no-op** (dismiss; original stays) |
| Swap day | both | **move** both affected events to their new dates |
| Skip | both | **delete** the event |

The intervals.icu rail today is **create + delete** (Batch 12 `create_workout_event`;
delete proven in the #91 smoke). Batch 29 adds **replace** (update-in-place, or
delete-then-recreate) and **move** (update the event date), keyed idempotently to
`planned_workout_id` + `version` so re-syncs never duplicate.

## Settled forks (2026-06-29 design session)

1. **Swap day = unified move-or-swap.** Mark picks a target day; if it's empty
   the session **moves** there, if it already has one the two **swap**. (He was
   happy with either reading; one control covers both.)
2. **Ignore suggestions = pure dismiss.** No backend call — the original is
   already in Zwift, so "ignore" just clears the adjustment and leaves the
   delivered session to ride.
3. **Skip = mark-only.** A `planned → skipped` status transition (the
   `planned_workouts.status` column is already a free `String(50)`, so **no
   migration**) plus the Zwift delete. **No reshuffle "for now"** — reshuffling
   stays the separate `/restructure` tool.
4. **Universal card across types.** `useDailyPhase` currently forces a
   strength-only day to `rest_day`; change it so **any** planned workout today
   leads the card. `rest_day` only when nothing is planned. Non-bike sessions get
   Edit/Swap/Skip with no Zwift upload.

## Safety / invariants preserved

- **Red-never-VO2** (`blocks_red_vo2`, DECISIONS #30) still gates **Approve &
  upload** — "Ignore suggestions" can keep the planned session, but Approve can
  never push a VO2 set on a Red day.
- **Audit** every create/replace/move/delete/skip as an `analyses` row (mirrors
  the Batch 13 `workout_proposed` / `workout_pushed` audit), so the Zwift state
  is reconstructable.
- A failed Zwift re-sync must **leave local state honest** (#97 drive-then-disable
  lesson): don't record a workout as skipped/swapped/edited locally if the Zwift
  mutation failed without surfacing the divergence.

## Policy change to record (DECISIONS #99)

Push-on-plan-set means the **as-planned** workout reaches Zwift **without a
per-workout human approval** — a deliberate reversal of #29/#30's "nothing
delivered silently" for the *baseline*. Approval now gates **only the morning
adjustment** (Approve & upload). Recorded as #99 so it is not read as a regression.

## De-risk first (throwaway spike, like `~/garmin-spike`)

Before wiring, prove the intervals.icu event lifecycle Batch 29 depends on:
**create → update-in-place (or delete+recreate) → move date → delete**, confirm
how each propagates to Zwift and its timing (the #91 same-day appearance-latency
note), and record the chosen replace/move mechanism (true update vs
delete+recreate) as the spike outcome.

## Reuses (thin delta over existing rails)

- `adjust_ir_for_verdict` / `blocks_red_vo2` / `ExecutableCoachingService`
  (Batch 25/13) — the adjusted IR and the gate, unchanged.
- The Batch 12 intervals.icu client + `WorkoutDeliveryProposal` table + ZWO /
  payload builders.
- `WeeklyRestructureService` stays the separate reshuffle tool (**not** invoked
  by skip/swap).
- The Batch 24 Home/phase scaffolding (`hooks/useDailyPhase.ts`,
  `lib/dailyFlow.ts`, `pages/DashboardPage.tsx`).

## Testing

- **Pure:** two-state selection off `adjustment.changed`; swap resolution
  (empty→move, occupied→swap); skip status transition; Red-never-VO2 still blocks
  Approve.
- **Rail:** create/replace/move/delete idempotent and keyed to workout id+version;
  audit rows written.
- **DB-backed:** push-on-plan-set fires on plan create/restructure; each action
  re-syncs and audits; a failed re-sync leaves local state honest.
- **Web:** card renders both states and all types; non-bike has no upload; phase
  logic shows an any-type day (not `rest_day`).

## Non-goals

- Reshuffling the week on skip (stays `/restructure`).
- Showing the *next future* session on an empty day — the card is scoped to
  **today's** planned workout (consistent with the today-centric daily-loop). If
  Mark later wants "next up" surfaced on a rest day, that is a small extension.
- Changing the verdict logic — only delivery **timing** and the card **actions**
  change.
