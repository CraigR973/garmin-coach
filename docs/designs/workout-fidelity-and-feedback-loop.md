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
2. **The step grammar authors intervals but *cannot author ramps*.** `_expand_pattern`
   (`workout_delivery.py:661`) expands `"5 x 2min / 2min"` into work/recovery pairs, but
   `_expand_step` only ever emits **steady** steps (start==end) — there is no raw-step
   form that produces a ramp, so even `build_vo2_structured_workout` (`vo2_progression.py:79`)
   makes a **flat** "easy spin" warm-up. The IR format supports ramps
   (`build_zwo_xml` Warmup/Cooldown), but nothing *authors* them. So Batch 67 is
   **data + a small grammar extension** (ramp authoring), not data alone.
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

The trunk fix, and bigger than a data edit: the delivery engine **cannot author a ramp
today** (proven — even its own VO2 builder emits a flat warm-up), so Batch 67 is **a
small grammar extension + a full transcription of Mark's authoritative plan doc**.
Resolves 1, 2, 11.

**Source of truth:** `~/Downloads/Dad Fitness/Full 13 Wk. 2121 Plan No. 2 Start
06.07.26.docx` — all 13 weeks are fully specified as **fixed %FTP** with ramps, cadences,
and recoveries (the JSON `summary` strings had collapsed weeks 3–13 to bare durations, so
we transcribe from the doc, not the lossy JSON).

- **67.1 Extend the step grammar to author ramps.** Add a ramp raw-step form (e.g.
  `{label, minutes, ramp: [55, 80]}`) that `_expand_step` expands to a ramp IR step
  (`powerStartPct`≠`powerEndPct`). Prerequisite for every warm-up/cool-down in the plan;
  today `_expand_step` can only emit steady steps.
- **67.2 Transcribe all 65 bike workouts into `plan_no2.json`.** Author each `bike_*`
  workout as a real multi-step `steps` array from the source doc — warm-up ramp, priming
  efforts, work interval(s) at an **explicit fixed %**, recovery valleys, cool-down ramp
  — with `duration_min` = summed step durations (fixes the 60-vs-47 drift). Keep the
  `summary` as the human read, now consistent with the steps.
- **67.3 Kill the silent 55% fallback + fix bands.** `_power_pct`
  (`workout_delivery.py:782`) raises 422 on an unresolvable target instead of returning
  55; add an import-time validation pass so a bad plan fails before Zwift. Accept en-dash
  / unicode separators; per Mark, work sets deliver as **fixed** single % (the doc already
  gives fixed values — only a couple of endurance mains are ranges, resolved with Mark).
- **67.4 Re-import forward + reconcile Zwift.** Re-import **forward from the resume
  Monday** (`import_plan` `start_date` override) so the reset/holiday weeks aren't
  clobbered, then `reconcile_deliveries` re-pushes the corrected bike rows. Explicit
  closeout step, not a blind re-run (mirrors Batch 65.4).
- **67.5 Tests + gates.** Grammar: ramp raw-step → a ramp IR step (start≠end), en-dash
  band → midpoint, unresolvable target → 422 (no silent 55), authored VO2/SS/Z2 expand to
  the expected multi-step IR with ramps; plan-JSON shape guard (no single-block bike step
  survives; `duration_min` == summed steps; every bike workout has a warm-up + cool-down);
  a delivered-ZWO snapshot shows ramps + interval structure. Full gates; closeout prod
  smoke + a Zwift spot-check that the VO2 shows intervals, not a flat block.
- **Decided (Mark, 2026-07-09) — no remaining unknowns.**
  (a) **Day placement:** keep the app's current mapping — **Dumbbells Monday, Bodyweight
  Saturday, as separate movable sessions** (Batch 65 stays; no revert). Transcribe workout
  *content* from the doc but keep this placement (it overrides the doc's opposite Mon/Sat
  layout). Monday therefore stays a light Dumbbells day, **not** a rest day; his "Mon & Fri
  are rest days" is taken as a **no-hard-bike constraint for Batch 70's rebalancer**, not a
  change here.
  (b) **Endurance ranges → midpoint:** Long Z2 65–72% → **68%**; easy/recovery Z2 60–65% →
  **62%**. Everything else transcribes as fixed %FTP straight from the doc.
  (c) **Total time must trace plan → app:** `duration_min` and the app-displayed total are
  the **true sum of the delivered steps** (not the doc's erroneous "Total Time" headers),
  identical through JSON → app → Zwift, and asserted in the shape guard.
  (d) **FTP = 280W** (unchanged) — stays the delivery default.

### Batch 68 — Grade what he actually rode (🔴 High, backend / analysis)

Make the post-workout read reflect the **delivered/accepted** workout, not the stale
planned VO2. Resolves 5 and the analysis half of 3b. **Mark independently pinpointed this
as the core defect (2026-07-09):** the flat ride he saw was the *reduced workout he
accepted*, and the bug is that the read still graded him against the original VO2. (The
flat-154W delivery has a separate latent cause — the `_power_pct` fallback — which Batch
67 closes; this batch fixes the grading.)

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
  **Protected days (Mark, 2026-07-09): never re-patch or schedule a hard bike session onto
  Monday or Friday** (Gran's / coffee days) — Monday keeps its Dumbbells; the rebalancer
  only ever uses the other bike days.
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

## Decisions — confirmed by Mark (2026-07-09)

Both decisions below are **confirmed**; the plan is spec-complete and Batch 67 has no
remaining unknowns (see the Batch 67 "Decided" note for the exact day-placement, range,
total-time, and FTP answers).

- **Reset question (observation 10) → fix the existing plan (Batch 67), not regenerate.**
  The defect is **transcription, not design**: the correct, detailed prescription for all
  13 weeks lives in Mark's source doc `Full 13 Wk. 2121 Plan No. 2 Start 06.07.26.docx`
  (every session as fixed %FTP with ramps, cadences, recoveries) — it was simply never
  written into machine `steps` (the JSON `summary` strings collapsed weeks 3–13 to bare
  durations, so we transcribe from the **doc**, not the JSON). So re-authoring preserves
  Mark's own curated content and Batch 65's split-day work, authors to the **same
  structured-step standard `block_generator` already uses** (its fidelity without
  discarding the plan), fits the reset window, and avoids handing him a fresh *generic*
  plan to find fresh "AI errors" in (the exact observation-11 frustration). Regenerating via
  `block_generator` is the right tool only when he later wants hands-off auto-progression
  (FTP bumps, VO2 30/30→30/15) — fixing now doesn't foreclose that. Transcribe faithfully
  from the doc, and re-import **forward from the resume Monday** so the off week is
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
- **Decisions #140 (Batch 67), #141 (Batch 68), #142 (Batch 69), #143 (Batch 70)** —
  assigned at `/batch-start`. Both open questions are now confirmed, so **67 is unblocked
  and spec-complete**; sequencing 67 → 68 → 69 → 70.

## Newly surfaced (2026-07-09) — candidate Batches 71–72

Two items Mark raised while signing off, distinct from 67–70; logged so they aren't lost,
to be specced at `/batch-start`:

- **Batch 71 — Editable quick-add on the Week tab.** Tapping **"+ Cycle / + Weights / +
  Flexibility"** on a day drops a **hardcoded default** (a fixed 45-min Zone-2 ride) with
  **no session picker and no way to edit** it (screenshot, 2026-07-09). Add a choose/edit
  step so the added session is selectable and adjustable. (Proposed Decision #144.)
- **Batch 72 — Chronic-REM coaching depth.** His REM has been low since he got the watch;
  the Batch 59 chronic-pattern card shows the same standing list. He wants a **broader,
  rotating set of REM interventions delivered one or two at a time** (focused, not a static
  list) for a persistent miss. Builds on `chronic_patterns.py`; a separate sleep thread.
  (Decision #145.) **Specced 2026-07-10 — see below.**

## Batch 72 — Chronic-REM coaching depth (🔴 High, backend + shared + web)

A separate sleep thread from 67–71. Mark's REM has run below its age norm since he got
the watch, so the Batch 59 chronic-pattern card flags `rem_sleep_pct` most weeks — but for
that one metric it only ever shows the **same two static lines**. He wants, for a
*persistent* REM miss, a **broader set of interventions handed out one or two at a time**,
rotating so the advice stays focused instead of a list he has already read.

**Root cause (in code).** `chronic_patterns._actions_for` maps `rem_sleep_pct` to exactly
two hardcoded strings ("Make {bedtime} the latest lights-out…", "Avoid moving the wake time
earlier…"), optionally prefixed by one driver-derived line, then `_suggestion` caps
`actions[:3]`. There is no library and no rotation — the same pair surfaces every day the
flag is active. Every other chronic metric is unaffected and stays as-is.

**What we build.**

- **72.1 — REM intervention library.** New pure `services/rem_interventions.py` with an
  **ordered library of REM-specific levers** (≥8; ships with 12), each a short imperative
  action grounded in the sleep protocol values where they exist (`bedtime`, `sealTargetTime`,
  `preCoolTemperatureC`, `coherenceBreathingTime`, `latestSnackTime`) or in standard REM
  physiology (REM is late-cycle heavy and fragile to short sleep, alcohol, warmth, late
  stimulation, and circadian drift): wake-time anchoring, protecting the last cycle, a hard
  bedtime, alcohol-free evenings, an afternoon caffeine cut-off, a cool room in the back half
  of the night, evening light-down, a consistent wind-down, late-meal timing, stress offload,
  REM-rebound recovery after a short night, and keeping hard/late rides off priority nights.
- **72.2 — Deterministic, stateless rotation.** `select_rem_interventions(as_of, …)` hands out
  a **focused window of two**, seeded from the calendar week (ISO-Monday-anchored) so a given
  week always yields the same pair (stable Mon–Sun, advancing across weeks) and the rotation
  **walks the whole library before repeating** (12 levers ÷ 2 = a 6-week cycle). No persisted
  cursor, **no migration** — the codebase's deterministic/read-only default (cf. #132/#143).
  A measured sleep **driver biases** the week: if the strongest driver implicates a specific
  lever (thermal → cool-room, load → late-ride, stress → wind-down/offload), that lever is
  pinned into the week's set even if the blind rotation had not reached it, keeping the advice
  responsive to his real data rather than a blind cycle.
- **72.3 — Wire into the REM suggestion only.** The `rem_sleep_pct` branch of `_actions_for`
  now calls the selector (passing the flag's driver key) instead of the two static lines; the
  existing driver-derived line still leads. `ChronicSuggestion` gains an optional `rotation`
  ({`periodLabel`, `shown`, `total`}) so the surface can show it is a rotating slice of a
  wider set. **No other chronic metric changes** (regression-guarded).
- **72.4 — Surface.** Shared `chronicSuggestionItemSchema` gains an optional nullable
  `rotation`; `ChronicSuggestionsCard` renders a small "Rotating focus — N of M levers this
  week, a fresh set next week" caption under the REM actions. Renders on both Home's "Last
  night's sleep" section and `/sleep` (the card is shared).
- **72.5 — Tests + gates.** Pure `test_rem_interventions.py` (unique ids + rendering, stable
  within a week, walks the whole library before repeating + wraps, driver pins its lever every
  week, no duplicate when already scheduled, protocol values render); `test_chronic_patterns.py`
  (REM rotates week-to-week and carries `rotation`, drops the pre-72 static line; a non-REM
  chronic carries **no** rotation); shared + web tests for the new field/caption. Full gates.

**Boundaries (non-goals).** No migration, no new endpoint. Does **not** touch the
Green/Amber/Red verdict, #133 soft-sleep, #135 Poor-readiness, or Red-never-VO2 — it is
read-only sleep-coaching depth, exactly the Batch 59 contract. Does **not** route through the
Anthropic boundary — the library is deterministic and unit-testable, no `ANTHROPIC_API_KEY`.
Does **not** change any non-REM chronic suggestion. Rotation is intentionally **stateless**
(date-seeded), not a persisted "shown" ledger — simpler, migration-free, and reproducible in
tests; a persisted cursor was considered and rejected as unjustified state for a 1–2-user app.

**Decision #145.** Deterministic, calendar-week-seeded rotation over a curated REM library,
window of two, REM-only, driver-biased, no migration — the version that composes with the
existing Batch 59 read surface and the deterministic/read-only norm of the codebase.
