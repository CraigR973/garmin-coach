# Design: Workout scheduling — separate sessions & swap-first recovery (Batches 65–66)

Mark's 2026-07-07 feedback, now that he is running the whole week from the app.
Three observations — two are defects in the same place, one is a coaching-philosophy
gap:

1. He agreed with the app that today was **not a VO2 day** (two poorer nights) and
   **juggled the week around** to cope. His stated preference in these situations is
   to **swap sessions across the week, not soften any of them** — he did exactly that
   this week and it "worked perfectly."
2. The app puts **Bodyweight on Monday and Dumbbells on Saturday** — it should be the
   **other way round** (Dumbbells Monday, Bodyweight Saturday).
3. Saturday's ride and its dumbbells are **one combined workout**, so moving the
   Saturday Z2 to Thursday dragged the dumbbells with it. Cycling and strength "need
   to be separate so I can move them independently."

## The ask, and the reframe

Reviewed against the code with Craig before scoping:

- **Points 2 and 3 are one root cause and ship together (Batch 65).** Both come from
  a single plan row. Every build-week Saturday in `apps/api/data/plans/plan_no2.json`
  is one `bike_endurance` workout titled `"Z2 + Neuromuscular + Dumbbells"` whose
  `structured_workout.summary` even ends `"Then: 20min dumbbells"` — the strength is
  prose welded onto a bike row. Because movability is per-row and the day-category is
  derived from `workout_type` alone (`workout_categories.py:40`), the day reads as
  "Cycle" and moves as one unit. Correcting the Mon/Sat mapping (2) and splitting the
  row (3) are the same edit: pull the strength out into its own session and put the
  right one on each day.
- **Point 1 is a philosophy the app currently inverts (Batch 66).** The morning
  verdict only ever recommends *softening* — `_plan_adjustments`
  (`morning_analysis.py:1211`) returns "Cut duration 20–30%, drop a zone, remove HIT"
  (Amber) / "Substitute recovery, mobility, or rest" (Red). Mark's instinct is the
  opposite and, for a fixed weekly volume, the better one: **move the hard session to
  a better day and pull an easier one forward.** The engine to do this already exists
  and is simply unreachable — so Batch 66 is mostly *surfacing and recommending* what
  is built, not building new logic.

## What the code already gives us

1. **Multi-workout days already work end-to-end — except at import and swap-target
   detection.** The schedule service returns a **list** per day
   (`PlanDay.workouts`, `plan_actions.py:33`), `day_state_for_workout_types` composes
   "Cycle + Weights", and the Plan page renders one `WorkoutRow` **per workout, each
   with its own Move button** (`WeekAheadPage.tsx:208`). `add_workout` and the swap
   `_reslot` already stack multiple *active* rows on one date by incrementing
   `version` — the slot half of the `(user_id, workout_date, version)` unique
   constraint (`coaching.py:352`). So a split Saturday renders as two independent
   cards **with no frontend or schema change**.
2. **Two spots still assume one workout per day.** (a) The importer writes every row
   at `version=1` (`plan_import.py:201`), so two Saturday entries would collide on the
   unique constraint. (b) Swap-target detection `_active_workout_on`
   (`executable_coaching.py:898`) does `.limit(1)` ordered by version — with two rows
   on a day it silently picks one. Both are the real work in Batch 65.
3. **A swap-not-soften engine already exists but no screen reaches it.**
   `weekly_restructure.py` (Batch 14) defers hard sessions when fatigued
   (`assess_recovery_signal` reads readiness + HRV + verdict trend), enforces the ≥2-day
   VO2/Sweet-Spot no-stack rule, and is exposed as `GET /api/v1/restructure/week-ahead`
   (preview) + `POST /api/v1/restructure/apply` — but **no web page consumes it**.
   Manual per-workout **Move** already works (the Plan page) — it is exactly what Mark
   used by hand this week.
4. **The softening path is orthogonal and stays.** `adjust_ir_for_verdict`
   (`executable_coaching.py:153`) and the Red-never-VO2 gate (`blocks_red_vo2`,
   `:110`) ease *today's delivered ride*; that is the fallback when the week can't be
   rearranged, and is untouched.
5. **The verdict already reads the whole day's plan.** `_plan_adjustments` and the
   verdict packet take a *sequence* of today's planned workouts, so splitting a day
   into two rows is verdict-safe (cycling + strength are already handled together).

## What we build

### Batch 65 — Separate cycling & strength, correct the Mon/Sat mapping (🔴 High, backend + data)

- **65.1 Data — rewrite the plan JSON.** For every week: Monday's strength becomes the
  **Dumbbell** session (~22 min full-body circuit — biceps, shoulder press, triceps,
  rows, flys, shoulder matrix, pullover, core — from `Dumbbell & Bodyweight
  19.06.26.docx`). Each build-week Saturday splits into **two day entries for the same
  `dow`**: a cycle (`bike_endurance`, title "Z2 + Neuromuscular", the existing bike
  steps with the "Then: 20min dumbbells" tail dropped) and a **Bodyweight** strength
  session (squat / dead-bug / mountain-climber / glute-bridge / push-up, from the same
  doc). Net effect: Dumbbells and Bodyweight swap days, and Saturday's ride and
  strength become distinct rows.
- **65.2 Importer — per-date versioning.** `build_plan_rows` already emits one
  `WorkoutRow` per day entry, so two Saturday entries produce two rows unchanged.
  `import_plan` assigns **incrementing versions per date** (cycle = v1, strength = v2,
  deterministic order) instead of a flat `version=1`, so same-day rows satisfy the
  unique constraint. Re-runnable to the same versions.
- **65.3 Swap engine — category-scoped so it never drags a second session.** Swap-
  target detection is scoped to the **same category as the source** (a moved ride
  swaps with the target day's ride only), so moving Saturday's Z2 to Thursday leaves
  Saturday's Bodyweight in place, and swapping two ride days never disturbs either
  day's strength. Keep the Batch 60 completed-session 409 guards.
- **65.4 Re-import to prod without wiping the live week.** `import_plan` deletes the
  forward schedule from the plan's Monday start, and **Mark has already hand-juggled
  the current week** (moved Sat Z2 → Thu). Re-import **forward from next Monday**
  (`start_date` override) so the in-progress week is preserved, then
  `reconcile_deliveries` re-syncs Zwift for the new bike rows. Documented as an
  explicit closeout step, not a blind re-run.
- **65.5 Tests + gates.** Importer per-date versioning + split-day; swap-engine
  category-scoped multi-workout (ride moves off a two-session day, strength stays;
  swap two ride days that each carry strength); plan-JSON shape; a web guard that a
  split day renders two Move-able rows. Backend pytest/ruff/mypy, shared typecheck,
  web vitest/tsc/lint/build (Node 20); closeout prod smoke on the merge SHA.

### Batch 66 — Swap-first recovery guidance (🔴 High, verdict + UI)

- **66.1 Record the preference in the knowledge base.** Add to Mark's coaching
  protocol: *when readiness is low and a hard session (VO2/Sweet-Spot) is scheduled,
  prefer rearranging the week — move the hard session to a better day and pull an
  easier session (Z2/recovery) forward — over softening the prescription; soften only
  when the week can't be rearranged.* This is what makes the prompt narrate swap-first.
- **66.2 Verdict leads with the swap.** On Amber/Red with a hard session scheduled,
  `_plan_adjustments` (and the morning prompt) **lead** with a concrete rearrangement
  computed from `weekly_restructure` ("Today isn't a VO2 day — move it to <next good
  day> and bring <easier session> forward"), with softening as the explicit secondary
  fallback. Bump `PROMPT_VERSION`.
- **66.3 Make it actionable.** Surface the existing restructure **preview → apply**
  (`/api/v1/restructure/week-ahead` + `/apply`) from the verdict surface so one tap
  rearranges the week; reuse the endpoints and the Batch 12/13 approval rail — no new
  engine. (Minimal fallback if the preview UI is too big for one batch: deep-link the
  existing per-workout Move sheet, pre-targeted at the suggested day.)
- **66.4 Keep softening safe.** The Amber/Red ease-the-ride transform and Red-never-VO2
  are unchanged and remain the fallback; a swapped VO2 still passes the ≥2-day no-stack
  rule and Red-never-VO2 at delivery.
- **66.5 Tests + gates.** Verdict leads with a swap when a hard session meets low
  readiness; restructure preview/apply reachable from the verdict; softening fallback
  intact; spacing + Red-never-VO2 preserved. Full gates; closeout prod smoke.

## System interactions & safety

- **No schema migration in either batch.** Batch 65 reuses the existing version-as-slot
  mechanism; Batch 66 reuses tables/endpoints that already exist.
- **Verdict invariants untouched.** Neither batch changes the Green/Amber/Red rules,
  the #133 soft-sleep override, the #135 Poor-readiness gate, or Red-never-VO2. Batch 66
  changes the *recommendation and its reachability*, not the gate.
- **Home Today card.** A split Saturday means the day can carry both a ride and a
  strength row; confirm the Home "today" surface renders the strength alongside the
  ride (the Plan page already does). Flagged for `/batch-start`.
- **Completion + delivery stay ride-scoped.** Batch 60 completion and the Zwift rail
  already operate per planned-workout row, so splitting is consistent with them.

## Boundaries (non-goals)

- Batch 65 does **not** add a `slot` column or a plan-editor UI — the version-as-slot
  path is sufficient; formalising slots is a later call if it proves fragile.
- Batch 65 does **not** rewrite the whole plan's content — only the Mon/Sat strength
  mapping and the Saturday split; all bike prescriptions are unchanged.
- Batch 66 does **not** auto-rearrange the week — it *recommends* and offers a one-tap
  apply through the existing approval gate; Mark stays in control.
- No change to the softening transform or the delivery safety gates.

## Verification plan

- **65:** importer versioning + split-day unit tests; swap-engine category-scoped
  multi-workout tests; plan-JSON shape; web render guard; then the **prod re-import
  from next Monday** with Mark's current week preserved, and a Plan-view check that
  Monday shows the Dumbbell session and Saturday shows a separate ride + Bodyweight,
  each Move-able independently.
- **66:** verdict-recommendation tests (swap-first on Amber/Red + hard session),
  restructure preview/apply reachable from the verdict, softening fallback intact,
  spacing/Red-never-VO2 preserved; full gates; closeout prod smoke on merge SHA.

## Resolved defaults (decided at spec time; `/batch-start` may adjust)

- **Two batches, 65 then 66** — the split/mapping is the visible defect Mark hit;
  swap-first guidance follows.
- Both from Mark's **2026-07-07** feedback; **no migration** in either.
- Batch 65 uses the existing **version-as-slot** (no new `slot` column); swap-target
  detection becomes **category-scoped**; prod re-import runs **forward from next
  Monday** to preserve the hand-juggled current week.
- Batch 66 **surfaces the existing `weekly_restructure` engine** rather than adding
  new rescheduling logic; recommendation leads with the swap, softening stays the
  fallback.
- Proposed Decision **#138** (Batch 65) and **#139** (Batch 66).
