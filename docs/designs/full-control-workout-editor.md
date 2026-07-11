# Full-control cycling workout editor

Status: Specced 2026-07-11 with Craig — **not started**. Batch 88, 🔴 High.
Decision #161 (assigned at `/batch-start`).

Builds on the Batch 77 structured workout builder
(`docs/designs/structured-workout-builder.md`, Decision #150).

## Motivation

Craig wants Mark to have **full control** over a cycling workout's structure on any
given day if he chooses — beyond the Batch 77 builder's single interval-pair-or-block
shape, and beyond the Today-card's whole-workout duration/intensity scaling. Mark
already has basic manual edits; this gives him the whole canvas when he wants it.

Two decisions taken with Craig (2026-07-11):

1. **Control level = free-form segment builder.** Mark can add and reorder any number
   of segments (warm-up ramp, steady blocks, several interval sets, recovery,
   cool-down), each with its own duration and %FTP.
2. **Guardrails = soft warnings.** On Mark's explicit manual authoring path the current
   hard limits become non-blocking warnings — he sees a heads-up on an unusual/aggressive
   choice, but nothing he builds is silently rejected. The coach/automated authoring
   path keeps them **hard**.

## Key finding — the engine already supports this

The delivery format is **not** the bottleneck. `expand_structured_steps`
(`services/workout_delivery.py:139`) already walks an **arbitrary-length ordered
`steps` list**, expanding each raw step via `_expand_step` into the IR, where a step is
one of:

- **ramp** — `{label, minutes, ramp: [startPct, endPct]}`
- **steady** — `{label, minutes, target: "N%"}`
- **interval set** — `{label, target: "N%", pattern: "R x Amin / Bmin @C%", repeats}`

The intervals.icu/Zwift push (`reconcile_deliveries`) and the Batch 78 Garmin export
both consume that IR unchanged. The single-pair-or-block ceiling lives **only** in the
builder spec `CustomBikeWorkoutSpec` (`services/structured_workout_builder.py`) and its
UI. So "full control" is a builder + UI change over the same rail Mark already uses — it
is **not** a delivery-path rewrite, and the risky part (the code that talks to Zwift and
Garmin) is untouched.

## Scope

### Backend — free-form spec
- Replace the fixed-field `CustomBikeWorkoutSpec` with an **ordered list of segments**,
  each tagged `kind ∈ {ramp, steady, interval}` with its own fields, reusing the exact
  per-kind step emission `build_custom_bike_workout` already does inline. Any count, any
  order.
- `build_custom_bike_workout` keeps emitting the existing `structured_workout` `steps`
  dict and computing `totalDurationMin` + workout-type classification from the expanded
  IR — the downstream contract is unchanged.

### Backend — soft warnings (path-scoped)
The three gates that sit between authoring and delivery become **warn-not-block on
Mark's explicit manual path only**:

- power outside 45–150% FTP (`_required_power`, currently raises 422),
- no warm-up/cool-down ramp (the `validate_deliverable_bike_workout` ramp gate,
  `workout_delivery.py:178`),
- VO2 on a Red-readiness day (the Red-never-VO2 delivery gate).

The **coach/automated authoring path keeps all three hard** — a bad auto-generated plan
must still fail loudly. This path-scoping is the batch's central design point.

Making Red-never-VO2 a *warning* on the manual path is a deliberate, recorded reversal
of the long-held "Red-never-VO2 unchanged" invariant — scoped **strictly** to a workout
Mark explicitly authored for himself, never to a coach adjustment. Decision #161 records
it (precedent: Batch 29/#99 reversed the "nothing delivered without approval" invariant
for the baseline only).

### Backend — warnings channel
The add/edit responses carry only hard `errors` today. Add a `warnings: [...]` list so a
**successful** save can return advisory messages the UI can surface.

### Frontend — segment-list editor
- A segment-list UI: rows Mark can add / remove / reorder, each with a kind selector and
  its fields, on the same Week-tab **build** surface (create) and **structured-edit**
  surface (edit an active bike session) Batch 77 shipped.
- Warnings surface inline (amber "heads-up… deliver anyway") rather than blocking submit.
- A live power-profile preview + running total duration from the expanded IR (the engine
  already produces `powerStartPct/powerEndPct/durationSec` per step) so Mark sees the
  workout before it ships. Nice-to-have — confirm in scope at `/batch-start`.

### Delivery — unchanged
Reuse the existing add (`customBike` payload) and structured-edit
(`POST /api/v1/plan-actions/planned-workouts/{id}/structured`, `plan_actions.py:349`)
endpoints, so versioning, indoor Zwift re-sync, and outdoor Garmin routing carry over.

## Boundaries
- Indoor → intervals.icu/Zwift and outdoor → Garmin (Batch 78) delivery paths unchanged;
  this is authoring only.
- Completed workouts still cannot be structurally edited (Batch 77 boundary retained).
- Supersedes the Batch 77 "no arbitrary graph editor" boundary **only** for Mark's
  explicit builder; the coach/automated path keeps the guided shape and hard gates.
- Verdict / #133 / #135 logic unchanged; Red-never-VO2 stays hard everywhere **except**
  the explicit manual authoring path.
- Likely **no migration** (segments still serialize into the existing `structured_workout`
  JSON `steps`) — confirm at `/batch-start`.

## Open `/batch-start` decisions
1. Mechanism for the path-scoped soft gates — a flag on the spec vs. a separate
   validation entrypoint for manual authoring.
2. The `warnings` response contract — shape, and where it surfaces (add + edit).
3. Whether the live power-profile preview is in scope now or a fast-follow.
4. Confirm no migration.
5. Any absolute sanity floor kept even under soft warnings (e.g. reject ≤0% power or
   absurd durations) vs. warn-only.
