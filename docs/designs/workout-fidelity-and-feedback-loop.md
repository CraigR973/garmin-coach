# Design: Workout fidelity & the ride feedback loop (Batches 67–70)

Mark's 2026-07-07/08 feedback, after a week of running everything through the app
and accepting its recommendations. Eleven observations across five screenshots;
they collapse onto **one root cause plus three engine gaps and one new feature**.

The observations (kept numbered so they map back to his messages):

1. A Z2 ride written "65–72% FTP" was graded **"Under" against the top of the band
   (72%)** — 64.9% actual → red "Under" — even though he rode the band fine. He asked
   for the option to set a **fixed FTP % per work interval** before a ride.
2. He accepted the app's recommended workout; it reached Zwift but (a) at **very low
   wattage** (a flat 154 W) and (b) with **no ramped warm-up/cool-down** — which the
   app's own read elsewhere says to keep.
3. The **ride-feedback logger sits inside the morning check-in** (asks pre-ride how
   today's ride went); "Changed it" (a) makes him re-enter a change he *accepted from
   the app*, and (b) only captures minutes/RPE, so it can't record "dropped the VO2,
   did a flat bottom-of-Z2".
4. If it drops the VO2 for an easier Z2, does it **notice no VO2 was done this week and
   patch it back in** later? His want: maintain fitness **without burnout or going too
   easy** — dynamically, to the morning metrics.
5. He did the easier Z2 as recommended, but the **post-workout read still graded him as
   if he'd attempted the VO2**.
11. The plan has AI-authored errors — e.g. a **VO2 session set to 60 min when it's
   really ~47**, plus the band issue he'd asked it not to repeat.

## The root cause behind 1, 2, 5, and 11

**Every one of the 65 bike sessions in `apps/api/data/plans/plan_no2.json` is authored
as a single collapsed step** — `{label, target: <prose>, minutes: <total>}` — with the
real structure living only in a human-readable `summary` string the delivery engine
never parses. His VO2 day, verbatim:

```json
"steps": [{ "label": "VO₂ (5 × 2 min @ 120%)", "target": "VO₂ (see prescription)", "minutes": 60 }],
"summary": "10 min ramp 55→80%, 2×30s @100%… Main: 5×2 min @120%… CoolDown: 10 min ramp 70→45%"
```

`import_plan` copies `structured_workout` verbatim (`plan_import.py:133`) — no
normalisation. Delivery then expands one fuzzy block into one flat SteadyState
(`_expand_step` minutes branch, `workout_delivery.py:645`), and `_power_pct`
(`workout_delivery.py:756`) resolves the target. Running the real parser over the plan:

| Type | Authored target | **Delivered to Zwift (all flat, no ramps)** |
|---|---|---|
| `bike_vo2` | `"VO₂ (see prescription)"` | **55% / 154 W** — unparseable → the `return 55` fallback |
| `bike_endurance` | `"Zone 2 ~65–72% FTP"` | **72% / 202 W** — the en-dash defeats band-averaging → grabs the top |
| `bike_sweet_spot` | `"Sweet Spot ~89% FTP"` | 89% / 249 W flat for 88 min |

Two parser defects make it silent and wrong:

- **The `return 55` fallback (`workout_delivery.py:782`)** turns an unparseable target
  into a plausible-looking easy ride instead of erroring — this *is* Mark's flat 154 W
  VO2 (observation 2a). Because every step lands at 55%, it's also Z1 100% and has no
  ramps (2b).
- **The band regex only matches an ASCII hyphen** (`workout_delivery.py:757`). The plan
  uses an en-dash (`–`), so `"65–72%"` misses the midpoint branch and the single-`%`
  branch grabs **72**. The interval grader then does its job *correctly on a wrong
  target*: `_adherence(64.9, 72, 72)` → **"under"** (`ride_intervals.py:253`). That is
  observation 1 exactly — not a "grades against the top" philosophy, a parse bug.

Observation 11 (duration) is the same collapse: `minutes: 60` / `duration_min: 60` is a
hand-typed total that drifted from the real prescription (~47 min of ramps + intervals +
recoveries). Authoring real steps makes duration a sum, not a guess.

Observation 5 ("still thinks I did the VO2") has a second, independent cause covered
below in Batch 68.

## What the code does today (per area)

1. **Delivery has no auto warm-up/cool-down.** `build_structured_workout_ir`
   (`workout_delivery.py:158`) emits exactly the authored steps; ramps exist only if a
   step is authored as a ramp. With single-block authoring, there are never any.
2. **The multi-step engine already works when fed real steps.** `_expand_pattern`
   (`workout_delivery.py:661`) already expands `"5 x 2min / 2min"` into work/recovery
   pairs, `_step` marks ramps when start≠end, and `build_zwo_xml`/`_intervals_description`
   already render ramps and intervals. So the fix is mostly **data**, not new engine —
   the pattern grammar the authoring must target already exists and is tested.
3. **The post-workout read grades the *planned* row, never the *delivered* one.**
   `_planned_ride_ir` (`post_workout_analysis.py:626`) builds the IR from
   `planned_workouts[].structured_workout`. When a verdict adjustment, Red substitution,
   or manual override is accepted, `executable_coaching.py` writes a new **delivery
   proposal** IR (`adjust_ir_for_verdict:154`, `apply_manual_override_to_ir:214` →
   `propose_from_ir`) but **never updates the planned row**. So the analysis always
   grades against the original VO2 (observation 5), and its narration still calls it a
   VO2 session because the row's `intensity_target`/`summary` still say so.
4. **The "Changed it" capture doesn't reach the analysis.** The session logger writes
   `PlannedWorkoutAdherence` via `PUT …/planned-workouts/{id}/adherence`
   (`CheckInPage.tsx:198`). The post-workout packet reads only the `ManualEntry`
   post-ride check-in keyed to `activity_id` (`post_workout_analysis.py:233`) — it never
   reads adherence, so `changeSummary` ("dropped the VO2") is invisible to the read
   (observation 3b, 5). The `intensity` field is even defined in state and sent to the
   API (`CheckInPage.tsx:79,194`) but **has no input rendered** — so structured capture
   is effectively minutes + RPE + feel.
5. **The session logger lives on the morning check-in.** "How did your sessions go?"
   renders inside the `/check-in` "More" disclosure (`CheckInPage.tsx:384`), which is
   framed as the morning read — hence being asked pre-ride how the ride went
   (observation 3 preamble).
6. **Accepting a recommendation logs nothing.** There is no path from "accept the app's
   eased/substituted ride" to a recorded adherence — so he's asked to re-describe what
   the app itself prescribed (observation 3a).
7. **There is no weekly-mix accounting.** `workout_categories.py` lumps every bike type
   into one "cycle" category; a repo-wide search for any quota / rebalance / make-up
   concept is empty. The nearest behaviour is **Batch 66 swap-first**, which *moves* a
   hard session to a later bike day on a low-readiness morning (`weekly_restructure.py`)
   — readiness-driven rescheduling, not "you're one VO2 short this week" accounting
   (observation 4). The week itself already carries his intended mix: **VO2×1,
   Sweet-Spot×1, Z2×3** (Tue/Wed/Thu/Sat/Sun in `plan_no2.json`).

## What we build

### Batch 67 — Real structured workouts + harden delivery parsing (🔴 High, data + backend)

The trunk fix. Turns every bike prescription into real steps and closes the two parser
holes so a malformed target can never again ship a flat easy ride. Resolves 1, 2, 11.

- **67.1 Re-author the bike prescriptions in `plan_no2.json`.** Every `bike_*` workout
  becomes a real `steps` array — warm-up ramp, work interval(s) with an **explicit %**
  (using the existing `pattern`/`repeats`/`target` grammar `_expand_pattern` already
  parses), recovery valleys, cool-down ramp — with `duration_min` equal to the summed
  step durations. VO2 → `5 x 2min / 2min @ 120%` with a `10min ramp 55-80%` warm-up and
  `10min ramp 70-45%` cool-down (the structure already sitting in its `summary`); Z2 →
  warm-up ramp + steady main + cool-down; Sweet-Spot → `2 x 25min / 3min @ 89%`. The
  `summary` string stays as the human read, now consistent with the steps.
- **67.2 Kill the silent 55% fallback.** `_power_pct` (`workout_delivery.py:782`) no
  longer returns 55 for an unresolvable target; it raises a 422 (like the other
  `_expand_*` guards) so an un-authorable step fails loudly at import/propose instead of
  delivering a flat Z1 ride. Add an importer-time validation pass so a bad plan is caught
  before it reaches Zwift.
- **67.3 Fix band handling.** Accept en-dash / unicode range separators in the band regex
  (`workout_delivery.py:757`) and collapse a band to its **midpoint** for steady
  delivery. With the ±5 `ADHERENCE_TOLERANCE_PCT` this makes "65–72%" deliver ~68% and
  grade his 65% floor as **"on"**, not "under" — resolving observation 1 without a new
  band type. (His literal ask — a fixed FTP % per work interval — is already available
  via the manual-override intensity dial; a per-interval editor is out of scope here and
  noted as a later option.)
- **67.4 Re-import forward + reconcile Zwift.** Re-import **forward from the resume
  Monday** (`import_plan` `start_date` override) so the reset/holiday weeks aren't
  clobbered, then `reconcile_deliveries` re-pushes the corrected bike rows. Explicit
  closeout step, not a blind re-run (mirrors Batch 65.4).
- **67.5 Tests + gates.** Parser: en-dash band → midpoint, unresolvable target → 422 (no
  silent 55), authored VO2/SS/Z2 expand to the expected multi-step IR with ramps;
  plan-JSON shape guard (no single-block bike step survives; `duration_min` == summed
  steps); a delivered-ZWO snapshot shows ramps + interval structure. Full gates; closeout
  prod smoke + a Zwift spot-check that the VO2 shows intervals, not a flat block.

### Batch 68 — Grade what he actually rode (🔴 High, backend / analysis)

Make the post-workout read reflect the **delivered/accepted** workout, not the stale
planned VO2. Resolves 5 and the analysis half of 3b.

- **68.1 Prefer the delivered IR as the grading target.** `_planned_ride_ir`
  (`post_workout_analysis.py:626`) resolves the day's grading IR from the **latest
  pushed delivery proposal** for that ride (the eased/substituted/overridden IR that
  actually went to Zwift), falling back to the planned row only when no proposal exists.
  So an accepted "drop VO2 → easy Z2" is graded as an easy Z2.
- **68.2 Carry the substitution into the packet.** Include the accepted adjustment's
  origin (`amber_regeneration` / `red_substitution` / `manual_override`) and the morning
  `planAdjustments` already in the packet, plus the adherence `changeSummary`, so the
  narration says "you did the eased ride we recommended" rather than "you attempted a
  VO2". Bump `PROMPT_VERSION` (regenerates stale reads via `_analysis_is_current`).
- **68.3 Tests + gates.** A ride whose delivered proposal was Red-substituted grades
  against the easy IR, not the planned VO2; the read names the substitution; planned-row
  fallback still holds for an un-adjusted ride; the whole-ride-context and
  grade-work-intervals guardrails are unchanged. Full gates; closeout prod smoke.

### Batch 69 — Accept = logged; move session-logging post-ride (🟢 Mid, backend + web)

Close the loop so accepting a recommendation records itself, and stop asking pre-ride
how the ride went. Resolves 3a, 3 preamble, and the capture half of 3b.

- **69.1 Accepting a recommendation auto-logs adherence.** When Mark approves the app's
  eased/substituted ride, write the `PlannedWorkoutAdherence` (`status='modified'`,
  `changeSummary` = the adjustment the app made) automatically, so "Changed it" is
  pre-filled from what he accepted instead of re-typed (3a/6).
- **69.2 Relocate the session logger to a post-ride surface.** Move "How did your
  sessions go?" out of the morning `/check-in` and onto the **completed-ride Today card**
  / post-ride check-in (the Batch 60 completed-row flow already exists), so logging is
  offered *after* the ride, not in the morning read.
- **69.3 Capture the substitution structurally.** Render the missing `intensity` control
  and let "Changed it" record a structured "what I did instead" (type + target), not just
  free text — the field Batch 68 reads.
- **69.4 Tests + gates.** Accept-a-recommendation writes adherence once (idempotent);
  the morning check-in no longer shows session logging; the post-ride surface does;
  structured change persists and round-trips. Full web + backend gates; closeout smoke.

### Batch 70 — Weekly-mix maintenance & dynamic rebalancing (🔴 High, verdict)

The one genuinely new feature (observation 4). Proposed default: a **soft,
readiness-gated quota** (see Proposed defaults) — the mix is a target the app protects,
readiness governs when the quality sessions happen, and a shortfall is explained rather
than forced or hidden. Subject to Mark's sign-off.

- **70.1 Track the weekly mix.** A pure helper reads the week's planned + completed bike
  sessions by sub-category (Z2 / VO2 / Sweet-Spot, derived from `workout_type`) against
  the target mix (Z2×3 / VO2×1 / SS×1) and reports what's done, due, and at risk.
- **70.2 Account for a dropped hard session.** When readiness drops a VO2/SS, the verdict
  either proposes **re-patching it into a later slot the same week if the metrics allow**
  (reusing the Batch 66 `weekly_restructure` spacing engine) or, when they don't,
  **explicitly says so** ("no VO2 this week — that's the right call on this week's
  recovery") instead of silently losing it. Surfaced in the week view + verdict.
- **70.3 Keep it advisory + safe.** Recommends, never auto-schedules; the ≥2-day no-stack
  rule and Red-never-VO2 hold for any re-patched session; softening stays the fallback.
- **70.4 Tests + gates.** Quota accounting (done/due/at-risk); a readiness-dropped VO2
  produces a re-patch suggestion when spacing allows and an explicit "not this week"
  otherwise; invariants preserved. Full gates; closeout smoke.

## System interactions & safety

- **No schema migration in any batch.** 67 is data + parser; 68 reads an existing
  proposal table; 69 reuses the adherence table + Batch 60 surfaces; 70 is derived
  read-only accounting over existing rows.
- **Verdict invariants untouched.** None of these change the Green/Amber/Red rules, the
  #133 soft-sleep override, the #135 Poor-readiness gate, or Red-never-VO2. 68 changes
  *what the read grades against*; 70 changes *what the recommendation notices* — neither
  touches the gate.
- **67 is the dependency.** 68 (grade the delivered IR) and 70 (mix accounting) are only
  meaningful once workouts are real structured sessions; 67 ships first.
- **Batch 66 swap-first composes with 70.** Swap-first already moves a hard session to a
  later day; 70 is the accounting that decides whether a *dropped* one is made up. They
  share the `weekly_restructure` engine.

## Boundaries (non-goals)

- 67 does **not** build a per-interval workout editor UI (his literal "fixed % per
  interval" ask); the manual-override intensity dial already covers the escape hatch, and
  real authored steps remove the need. Flag as a later option if he still wants it.
- 68 does **not** rewrite the grading maths — it only changes the **source IR** the
  existing interval grader reads.
- 69 does **not** remove the morning check-in — only the *session-logging* card moves; the
  quick "how are you feeling" read stays.
- 70 does **not** auto-schedule anything and does **not** hard-enforce a quota — it's
  advisory accounting; the fixed-mix-vs-metric-driven call is Mark's.

## Verification plan

- **67:** parser unit tests (en-dash midpoint, no silent 55, multi-step expansion) +
  plan-JSON shape guard + delivered-ZWO snapshot; then prod re-import forward from the
  resume Monday and a Zwift check that VO2/SS show real intervals and ramps.
- **68:** delivered-IR-preferred grading tests (Red-substituted ride graded easy;
  planned fallback intact) + a regenerated read that names the substitution.
- **69:** accept→adherence idempotency, logger relocation render guards, structured
  change round-trip; web + backend gates.
- **70:** quota accounting + re-patch/"not this week" branch tests; invariants preserved.
- Each batch: backend pytest/ruff/mypy, shared typecheck, web vitest/tsc/lint/build
  (Node 20), closeout prod smoke on the merge SHA.

## Proposed defaults (subject to Mark's sign-off; `/batch-start` may adjust)

- **Reset question (observation 10) → fix the existing plan (Batch 67), not regenerate.**
  The defect is **transcription, not design**: each bike workout's `summary` already holds
  the correct, detailed prescription (VO2 = "10 min ramp 55→80% … 5×2 min @120% … 10 min
  cooldown 70→45%") — it was simply never written into machine `steps`. So re-authoring
  preserves Mark's own curated content and Batch 65's split-day work, authors to the **same
  structured-step standard `block_generator` already uses** (its fidelity without
  discarding the plan), fits the reset window, and avoids handing him a fresh *generic*
  plan to find fresh "AI errors" in (the exact observation-11 frustration). Regenerating via
  `block_generator` is the right tool only when he later wants hands-off auto-progression
  (FTP bumps, VO2 30/30→30/15) — fixing now doesn't foreclose that. Author the steps as a
  **faithful transcription of each `summary`**, get Mark's one-pass sign-off on the five
  session shapes, and re-import **forward from the resume Monday** so the off week is
  untouched.
- **Mix philosophy (observation 4 / Batch 70) → soft, readiness-gated quota** (neither pure
  extreme). Treat the mix as a **target the app tracks and protects**, derived from his own
  plan (already Z2×3 / VO2×1 / SS×1 — not a hardcoded number), but let **readiness veto
  when/whether** the quality sessions happen and make any shortfall **visible and
  explained** rather than forced or hidden. *Not* pure metric-driven: with no target it
  can't even answer "did I miss my VO2?", and with no memory it risks the "too easy" drift
  he fears. *Not* a hard quota: forcing a VO2 onto a bad-recovery day contradicts #133 /
  #135 / Red-never-VO2 / Batch 66 swap-first — the burnout he fears. For masters
  *maintenance* the small quality dose is what preserves top-end, so it's worth
  **protecting, not forcing** — the version that composes with the existing guardrails and
  is exactly Batch 70's "re-patch if readiness allows, else say so plainly".
- **The two reinforce each other.** Fixing the plan keeps the explicit weekly mix in the
  JSON, which is the target the soft-quota reads — fix + soft-quota is the combination where
  each piece feeds the next.
- **Proposed Decisions #140 (Batch 67), #141 (Batch 68), #142 (Batch 69), #143 (Batch
  70).** Sequencing: 67 → 68 → 69 → 70 (70 can start once Mark confirms the soft-quota
  default).
