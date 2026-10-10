# Batch 331 — Strength, mobility and the whole athlete (audit wave #5, R5)

Reviewed SHA `42a6a98` (production). Lens: a strength and fitness coach for a 57-year-old
lifelong endurance cyclist. Read-only. Paid spend: **$0** (no Anthropic call).
Probes and extracts are in `scratchpad/wave5/r5/` (gitignored); nothing from production is
copied here beyond counts and short phrases.

## 1. Summary

**Verdict: C+.** Off-the-bike work is protected and read after the fact, and Plan No. 3 is the
first plan that loads and progresses it on paper. But the app cannot deliver the new
legs session to the watch where Mark lifts, cannot tell whether he did it, never records a
weight, and on a Red morning tells him three different things about it.

| Question | Grade | In this lens |
|---|---|---|
| 1. Correct and safe | B | Nothing unsafe is pushed; but strength is never eased on any floor short of "no training", and Plan No. 3 puts the first loaded leg session 24 h before the FTP test that sets 13 weeks of targets (FC331-03). |
| 2. Honest with Mark | C | A Red strength morning reads "As planned · today's plan already suits it" while the brief's plan line says "Substitute recovery, mobility, or rest" and the session says "one weight up" (FC331-02, proved). Post-strength reads call 9-minute RPE-2 circuits "strong" strength frequency (FC331-06). |
| 3. Fitter off the bike | C+ | Two loaded, progressing sessions a week is right (WHO 2020; Rønnestad & Mujika 2014). Legs are loaded once a week, sessions do not fit their minutes, nothing loads bone (FC331-04, -05). |
| 4. Failure noticed | D | If he keeps doing his old upper-body watch workout, the app records Plan No. 3's legs session as done (proved); no weight is ever recorded, so "one weight up" can never be checked (FC331-01). |
| 5. Cheap to run and change | B+ | Most fixes are plan content (no code) or small: the strength rule is one action, Garmin already sends the exercise sets and the app already stores them. |

## 2. What optimal looks like

For a 57-year-old well-trained cyclist, optimal off-the-bike coaching is small and specific:

1. **Two loaded sessions a week that train every major muscle group, legs heavily twice**
   (WHO 2020: all major muscle groups on 2 or more days a week; Rønnestad & Mujika 2014: two
   heavy sessions a week, 4–10 RM, 2–3 sets, 2–3 min rest, for 12 weeks, then about one a
   week to maintain). Each session fits the time it is given.
2. **Placed so it does not spoil the key ride**: heavy legs after a hard ride or 48 h before
   the next one, and a light start in the first 2–3 weeks (Rønnestad & Mujika: "heavy" and
   "sore" legs in the first days; Doma et al. 2017: residual fatigue for hours to days). Never
   the day before an FTP test.
3. **Something for bone**: heavy axial loading and some impact (LIFTMOR-M), because cycling
   does not provide it (Nichols 2003; Rector 2008). Evidence here is weaker (see FC331-05).
4. **The session reaches where he does it** (his watch) and **what he did comes back**: which
   moves, sets, and one top weight. Garmin already sends the first two.
5. **On a bad morning the strength session changes too**, in the same words on every
   surface: hold the weight, take the recovery-week dose.
6. **The post-session read grades against the prescription** and says when to go up a weight
   (Mark's own 19 Jun ask: "keep a watching brief").

**Already near-optimal (keep it):** the weekly no-stack rule now treats strength as load
(CI239-07 item 1, proved fixed); the Amber plan line for strength ("Keep strength
submaximal…"); recovery weeks and the taper lighten strength; the coach chat's own answer
about his daily bodyweight circuit was honest (4 Sep: movement maintenance, not strength
building); walk reads correctly spot stop-and-go sightseeing walks; Batch 278 stops a
bodyweight session completing a dumbbell row; post-strength v7 fixed the "high HR" read
Mark challenged on 24 Sep.

**Smallest set of changes:**

| # | Change | Cost | When |
|---|---|---|---|
| a | Plan No. 3 content: move Dumbbells A to Thursday after the sweet spot (Mark can do this himself in the builder; proved valid, no week over his longest), or at least move week 1's A after Tuesday's ramp test | none (content) | Before Mon 19 Oct, Craig's call (not a safety item) |
| b | One strength action on Red/Amber (and the symptom floors): the recovery-week dose at last week's weight; the call line and the plan line say the same | half a day + words | Fold into 321.3; before week 4 (Mon 9 Nov), the first "one weight up" |
| c | Read Garmin's `summarizedExerciseSets` (already stored) and ask one top weight at the strength check-in; grade the post-strength read against the prescription | 1–2 days + post-strength v8 | Fold into 322 (extend "record what he did" to strength) |
| d | Tell Mark how to get A and B onto his watch (a one-off Garmin Connect workout each), or deliver them as text to intervals.icu | an hour (words) to a day | Before 19 Oct for the words; delivery after G8 |
| e | Table edit: fit sets to minutes (or minutes to sets), 2 min rest on the heavy moves, a squat or hinge in B, a small impact element | an hour + regenerate (revision 0, untouched) | Craig's call; before Mark accepts, or as Plan No. 4 |

## 3. Findings

Counts: 0 High, 2 Med-High, 4 Medium, 1 Low.

### FC331-01 · Med-High · The new legs session has no way onto his watch, and his old routine counts as done

*Evidence: `implemented` + `proved` + `observed`.*

- **Where he lifts.** Mark runs strength and mobility as Garmin watch workouts (Decision #108
  withdrew the in-app players for exactly that reason). Every strength activity since 1 Aug
  is a named watch workout: "Dumbbell Workout" (upper body only), "Daily Bodyweight
  Workout", "Weekly Bodyweight Workout", "Recovery Morning Routine" (observed).
- **What Plan No. 3 changes.** Dumbbells A (goblet squat, Romanian deadlift, reverse lunge,
  row, calf raise, side plank) is the plan's main new stimulus: Garmin's exercise categories
  for his six most recent dumbbell workouts (10 Aug–14 Sep) hold no squat, deadlift or lunge (observed,
  `raw_summary.summarizedExerciseSets`). Strength is never delivered anywhere: the delivery
  rail is bike-only (`workout_delivery.py` week-ahead docstring; strength IR raises 422,
  implemented). Nothing in the draft or its signed-off words tells him to build A and B on
  the watch (`docs/drafts/2026-10-07-batch-323-wording.md`, read).
- **What the app would record.** `workout_match.strength_material_difference` compares only
  weighted against bodyweight by name. Planned "Dumbbells A (legs and back)" against his
  existing "Dumbbell Workout" returns no difference, so the legs row is completed (proved,
  `probe_load.out` §5). The history already holds one false completion from before Batch 278:
  22 Sep "Dumbbells (full-body)" is `completed` though that week held no dumbbell workout,
  which Mark flagged himself (observed).
- **Weights are never recorded.** `maxWeight` is 0 on every exercise of those six dumbbell
  workouts and of every bodyweight circuit read (observed); the check-in has no weight field; the app never reads
  `summarizedExerciseSets` at all (implemented: no reference in `apps/api/src`). "One weight
  up" (weeks 4, 7, 10) cannot be checked by anyone.
- **What Mark and Craig experience.** The likeliest path is that he keeps doing the routine
  already on his watch, the app ticks the legs session, the post-read praises consistency,
  and nobody learns that the plan's leg work never happened.
- **Fix.** (1) Before 19 Oct: one sentence in the builder or "why this plan" telling him to
  save A and B as watch workouts (or Craig sets them up). (2) After G8: name-or-category
  matching on Garmin's exercise categories (SQUAT, DEADLIFT, LUNGE → A), and one "top weight"
  number at the strength check-in. **Cost:** words, an hour; matching and the field, about a
  day. **Where:** words before 19 Oct (Craig); the rest folds into **322**, which already
  records "what he rode" and adds a "legs" answer.

### FC331-02 · Med-High · On a Red strength morning the call, the brief's plan line and the session say three different things

*Evidence: `proved` (crafted mornings through the real functions) + `observed` (frequency).*

- **The engine.** `verdict_grading._session_action` returns `as_planned` for every non-bike
  session unless the floor is "no training" ("Not a ride; the verdict's ride changes do not
  apply"). Driven with Plan No. 3's week-10 Monday (`3 × 6–8, one weight up; 1–2 reps in
  reserve`) on a Red morning (`probe_redstrength.out`):
  - **Call:** "As planned · Your body's still recovering, and today's plan already suits it.
    Keep it comfortable." Look: `go` (green tick).
  - **Plan line the brief is written from** (`morning_verdict.graded_plan_adjustments`, which
    falls back to the ladder's Red line): "Substitute recovery, mobility, or rest."
  - **The session:** one weight up, 1–2 reps in reserve.
- On Amber the call says "As planned … today's plan already suits it" while the plan line
  says "reduce the sets and stop well short of failure".
- Craig's 5 Oct line ("today's plan already suits it") was written when Monday was a
  22-minute upper-body session; under Plan No. 3 it is no longer true. The same `as_planned`
  holds on the symptom floors (an easy day back after a fever; an open chest follow-up), which
  R6 found for the chest case (HS332-05).
- **How often.** Since 1 Aug, 3 Red and 1 Amber mornings fell on a planned strength day
  (observed: 22 Sep, 26 Sep, 3 Oct, 5 Oct; the last two while he was away, the first two
  decided by the ladder). Plan No. 3 puts strength on 2 of 7 days.
- **What Mark experiences.** A green "As planned" headline above a brief that may tell him to
  rest, beside a card asking for a heavier weight. The 6 Oct review's invariant (every
  surface reads the one stored call) holds for the headline but not for the plan line.
- **Fix.** One strength action, `lighter`, on Red, on a marked Amber and on the symptom
  floors: the recovery-week dose already in the table (`next_plan._LIGHT_STRENGTH_8`), last
  week's weight; the call line and `graded_plan_adjustments` use the same words. Adds caution
  only. **Cost:** half a day, one signed-off line, tests. **Where:** fold into **321.3** (it
  is the third DV-14 line, which 321 dropped); before Mon 9 Nov, the first "one weight up".

### FC331-03 · Medium · The first loaded leg session is 24 h before the FTP test, and heavy legs precede every VO₂ day

*Evidence: `implemented` (draft) + `proved` (load model) + literature.*

- **Placement.** Plan No. 3 keeps Plan No. 2's days (Mon strength, Tue VO₂), but Monday's
  content changes from upper-body to legs. Week 1: Dumbbells A Mon 19 Oct, the ramp test Tue
  20 Oct, and the new FTP sets every target for 13 weeks. Build weeks: heavy legs (up to
  `4 × 6–8`, 1–2 RIR) on Monday, the week's hardest ride on Tuesday.
- **The engine cannot see it.** His heaviest strength session on record (22 min, Garmin load
  14) and a hypothetical 45-minute heavy leg session (load 40) both rate yesterday "easy"
  (`_yesterday_load_packet`, proved); only "hard" counts, and only before a hard ride. Across
  49 strength sessions Garmin's load never exceeded 14 (observed). So nothing will ever
  soften a VO₂ day for Monday's legs; that is correct for the engine (wrist-HR load is
  meaningless for lifting), so the fix belongs in placement, not in the load model.
- **Evidence.** Rønnestad & Mujika 2014 (full text read): "heavy" and "sore" legs are common
  in the first days, so start low with concurrent endurance in the first 2–3 weeks; two
  heavy sessions a week. Doma, Deakin & Bentley 2017 (abstract read): residual fatigue from a
  resistance session can impair a later endurance session for hours to days; they advise
  managing order and recovery between modes. Effect size for a light week-1 session on a
  ramp test is uncertain; week 1 is deliberately light (2 × 12, 3–4 RIR), which mitigates.
- **What Mark experiences.** Possibly a ramp test on sore legs (an FTP set low for 13 weeks)
  and VO₂ sessions that feel harder than written.
- **Fix (no code).** Put A on Thursday after the sweet spot: proved valid in the builder
  (`apply_change` days, `probe_changes.out`), no week over his longest, Friday is then rest
  and Sunday's long ride is 72 h later. At minimum, move week 1's A after the test. **Cost:**
  none; Mark can do it in the builder, or Craig suggests it. **Where:** before Mon 19 Oct,
  Craig's call (a content choice, not a safety item).

### FC331-04 · Medium · The dumbbell sessions do not fit their minutes, and legs are loaded heavily once a week

*Evidence: `computed` (from the stored draft) + `proved` + literature.*

- **Time.** At the draft's own "about a minute between sets" and 3 s a rep, build-week
  sessions need 30–35 min (A) and 34–40 min (B) against the 25 planned; week 8's B is 27
  sets (`strength_time.out`). At Rønnestad's 2–3 min rest for heavy work, week 11's A would
  take about an hour. There is no warm-up in either session.
- **Mark's edit moves only the clock.** Changing week 8's A to 10 minutes leaves "4 × 8 on
  the first three moves, 3 × 8 on the rest" untouched (proved, `probe_changes.out`).
- **Dose.** A is legs and back; B is eight upper-body moves plus step-ups. Heavy leg work is
  once a week, where the cycling evidence is two (Rønnestad & Mujika 2014), and WHO 2020 asks
  for all major muscle groups on 2 or more days. Loads reach roughly 8–10 RM only in weeks
  7–11, a gentle ramp that is defensible for someone new to loaded legs.
- **Fix.** Either two shorter full-body sessions (a squat or hinge plus a push and a pull in
  each, 4–5 moves), or minutes that match the sets (35–40), with 2 min rest on the first three
  moves; and a minutes edit that scales the sets with it. **Cost:** a table edit and a
  regenerate (the draft is revision 0, untouched) or carry to Plan No. 4. **Where:** Craig's
  call; content only.

### FC331-05 · Medium · Nothing in the plan or the app addresses bone

*Evidence: `implemented` + literature (weak to moderate).*

- **What the plan holds.** No impact, no heavy axial loading (goblet squat and dumbbell RDL
  are limited by dumbbell weight); his walks are Zone 1 (observed, walk reads 3–5 Oct). The
  app holds no bone data and no surface mentions bone.
- **Evidence.** Master cyclists who only rode had lower spine and hip BMD than age-matched
  controls, 15% with T-scores under −2.5 (Nichols et al. 2003, abstract read); 63% of
  recreational cyclists against 19% of runners had spine or hip osteopenia (Rector et al.
  2008, abstract read). Both are cross-sectional and small. LIFTMOR-M (Harding et al. 2020,
  abstract and protocol read): men over 50 with low bone mass, twice-weekly 5 × 5 at
  80–85% 1RM deadlift, squat and press plus jumping chin-ups with drop landings, improved
  spine and hip BMD and function, with few minor adverse events. It is a low-bone-mass
  population (mean age about 67), supervised; extrapolating to Mark is a judgement.
- **What Mark experiences.** Nothing; that is the point.
- **Fix.** Add a small impact element (for example a few sets of low jumps or hops, built up
  over weeks) and one heavier hinge, and let Craig decide whether Mark asks his GP about a
  DXA scan (R6's area). **Cost:** content. **Where:** after G8, or Plan No. 4.

### FC331-06 · Medium · The post-strength read counts circuits as strength and never sees the load

*Evidence: `observed` (stored reads) + `implemented`.*

- **What it reads.** The v7 prompt asks for frequency against trend, wrist HR against his
  usual range, and "one light next step" (`post_strength_analysis.SYSTEM_PROMPT`). The
  rollup counts every `strength_training` activity: the 9–11-minute RPE-2 bodyweight circuit
  and the 20-minute dumbbell workout are the same unit.
- **What Mark read.** 20–24 Sep: about 6 sessions a week, "strong", "a big step up in volume",
  "this daily short-strength habit has really taken hold" — while the loaded dumbbell work was
  one a week up to 14 Sep and none since (observed weekly counts). 8 Oct's next step: add
  "one more light bodyweight session". The coach chat on 4 Sep had told him the same circuit
  is "movement maintenance, not strength building", which is the honest read; the two
  surfaces disagree.
- **What it cannot see.** Garmin's `summarizedExerciseSets` (exercise, sets, reps) is stored
  on every strength activity and never read; the plan's prescription is in the packet
  (`plannedWorkouts`) but the prompt never asks the model to compare. Under Plan No. 3 the
  read will not say whether he did A's moves, the sets, or went up a weight.
- **Mark's own ask** (19 Jun): "keep a watching brief and suggest whether I should do more or
  less strength / resistance work". Partly met by Plan No. 3; there is still no feedback loop.
- **Fix.** Split the rollup into loaded and bodyweight; pass the exercise sets and the top
  weight (FC331-01); prompt v8 compares against the prescription and says "go up a weight"
  when two sessions in a row hit the reps at the stated reserve. **Cost:** 1–2 days and a
  prompt bump (about $0.014 a read, R3's cost table). **Where:** fold into **322**, beside
  319's "ready to progress" note for rides.

### FC331-07 · Low · Plan No. 3 leaves out the routines he actually does most

*Evidence: `observed` + `implemented`.*

- Since 1 Aug he logged 27 sixteen-minute mobility sessions and 24 daily bodyweight circuits
  (observed). Plan No. 3 holds neither (26 strength sessions, no mobility type), and "It keeps
  your week from Plan No. 2" while Saturday's bodyweight session became Dumbbells B.
  Plan No. 2's "Dumbbells (full-body)" title was upper-body only (Garmin categories, observed).
- Harmless while the app reads unplanned sessions, but the plan does not describe his week,
  and on Mondays and Saturdays the morning circuit is checked against the dumbbell row first
  (Batch 278 records a deviation, proved by `strength_material_difference`), so his
  post-read may tell him he did the wrong session.
- **Fix.** One line in "why this plan" naming the daily circuit and mobility as his own, kept
  as they are. **Cost:** words. **Where:** with (d) above, or Plan No. 4.

### Not findings (checked, near-optimal)

- **Walks.** His longest walk (245 min recorded, 71 min moving, all Zone 1, Garmin load 2)
  rates yesterday "moderate" on duration alone, which nothing reads; Garmin load across 123
  walks never exceeded 5.6 (observed, proved). Right for his walks. A genuinely hard hill day
  would also be invisible; no such walk exists in the data.
- **The no-stack rule.** VO₂ Tue / strength Wed / sweet spot Thu is now a conflict, mobility
  is not (proved, `probe_spacer.out`). CI239-07 item 1 is fixed.
- **Companion gate.** Under the graded engine, Amber ignores a same-day strength session (the
  ride keeps full length, by Batch 296's design: Amber eases only the hard work) and Red
  withdraws the Zone 2 allowance when strength shares the day (120 → 60 min substitution)
  (proved). Consistent with the rule as written.
- **Removing a dumbbell session** is one tap in the builder and the coach can offer it
  (proved: week 8's A removed with no warning, `probe_changes.out`). R3 already reports the
  coach's steerability on protected work (AI329-02); not re-reported here.

## 4. Follow-through

Wave #4 had no strength lens; these are the wave #4 findings and later findings that touch
strength, mobility, walks or the whole athlete, each re-verified on `42a6a98`.

| ID | Finding | Status | Evidence (this pass) |
|---|---|---|---|
| CI239-05 | Amber instruction bike-only, emitted on strength/mobility/walk days | **fixed** for Amber; residue on Red | `implemented` + `proved`: `graded_plan_adjustments` gives strength, mobility and walk their own Amber lines (`probe_redstrength.out`). On Red a strength day still gets the ladder's "Substitute recovery, mobility, or rest", against a call of "As planned" (FC331-02). |
| CI239-07 | Strength invisible to load rules, but counted as a spacer | **partly fixed** | Item 1 fixed (`proved`, `probe_spacer.out`: strength between VO₂ and sweet spot is now a conflict). Item 2 open: the graded action keeps strength `as_planned` on every floor short of no training (FC331-02). Item 3 unchanged by design (`weekly_mix.mix_bucket` is bike-only). The follow-through table's "fixed" is too strong. |
| DV-10 | Strength protected but never coached | **shipped differently** (sound in direction, incomplete) | `implemented`: `next_plan.WEEKS` gives two loaded, progressing sessions a week, lighter in recovery weeks and the taper. Not yet accepted (draft, revision 0). It cannot reach the watch or be verified (FC331-01); legs once a week, minutes too short (FC331-04); no bone stimulus (FC331-05). |
| DV-14 (third line) | A still-recovering strength-only day shows the green "go" look | **shipped differently; decayed** | `proved`: Craig's 5 Oct line "today's plan already suits it", look `go`. True for Plan No. 2's light upper-body session; untrue for Plan No. 3's heavier weeks (FC331-02). 321.3 carries only the other two lines. |
| HS240-18 | `workload_budget.py` is not a physiological budget | **accepted-and-closed**, still true | `implemented`: it bounds concurrent Anthropic and Piper work (4/1 and 1/1 slots). The R5 lens prompt repeated the misreading. |
| CI239-09 | The generator never produced a plan | **fixed** (R4 owns) | `observed` via R4's stored copy: the draft exists with progressions, revision 0. |
| CI239 (positive) | "The whole athlete is reviewed" | **still true** | `observed`: since 1 Sep, 23 post-strength, 7 post-walk and 4 post-flexibility reads. Reads are made only when he checks in on the activity (4 of about 13 mobility sessions in September). |
| Mark, 19 Jun | "Remember my Monday dumbbell and Saturday bodyweight sessions and green light these" | **fixed** | `implemented`: the call covers strength-only days. Plan No. 3 drops the Saturday bodyweight session (FC331-07). |
| Mark, 19 Jun | "Keep a watching brief and suggest whether I should do more or less strength" | **partly** | Plan No. 3 adds load; nothing reads load or suggests a change (FC331-06). |
| Mark, 7 Sep | "Unclear from morning brief if should still do planned 22 minute dumbbell session today?" | **fixed** (313), with FC331-02 | `implemented`: a strength-only Green reads "Green light · Today's session is on as written"; Red and Amber read "As planned". |
| Mark, 9/14/22 Sep | His bodyweight circuit "allocated to dumbbell workout" | **fixed forward** (278) | `implemented` + `proved`: a bodyweight activity against a dumbbell row records a deviation. Not observed since (no circuit has landed on a dumbbell day since 23 Sep). The 22 Sep row is still `completed` (observed). The matcher cannot tell Dumbbells A from his old upper-body workout (FC331-01). |
| Mark, 24 Sep | HR "as a high bump … why the change?" | **fixed** (post-strength v7) | `observed`: the 7 and 8 Oct reads compare against his usual range for that workout, as v7 instructs. |
| Mark, 4 Sep | "What benefits will these daily short but progressing … workouts provide?" | **answered honestly** | `observed`: the chat said movement maintenance, not strength building. The post-strength reads say otherwise (FC331-06). |

## 5. G8 and parked rows re-verified

| Row | In this lens | State |
|---|---|---|
| **321** Three small fixes | 321.3 is where FC331-02 belongs | **Decayed by omission:** DV-14 named three lines; 321.3 carries two. Under Plan No. 3 the strength line is the one that matters. 321.1's `morning_analysis.py:1301` is now `:1335` (the off-the-bike swap withhold). |
| **322** Record what he rode | The natural home for FC331-01 and FC331-06 | **Accurate for rides; silent on strength.** Extending "what he did" to strength (Garmin's exercise sets, one top weight) is the same idea. |
| **319** Progress has a signal | Bike-only | **Accurate** in its own terms (R4 re-verifies its references). No strength equivalent of "ready to progress"; FC331-06 proposes one. |
| **316** Load ratio and recovery time | Strength never reaches Garmin's load (load ≤ 14 across 49 sessions) | **Still accurate.** `_load` is at `verdict_grading.py:953`, not `:948`. Monday's legs will not show in recovery time either; placement (FC331-03) is the fix, not 316. |
| **320** Tonight's advice | Mobility before bed is one of his own levers (7 Sep check-in) | Not in this lens beyond that; no decay found. |
| **308, 311, 317, 318** | No strength, mobility or walk content | Not re-verified beyond that. |
| Parked **208, 209, 210, 276** | Not in this lens | — |

## 6. For reconsideration

1. **Decision #108 (2 Jul): no in-app strength player; strength is read, not guided.** Still
   right for running the session. New evidence: once the plan prescribes new moves and loads,
   "read, not guided" leaves no route for the prescription to reach his watch and no record of
   load (FC331-01). Proposed: not a player, but either a one-off set-up of A and B as Garmin
   watch workouts, or text workouts sent through intervals.icu, plus one top-weight number at
   the check-in.
2. **Batch 303 / Decision #375 and the symptom floors: "Zone 2, strength and mobility stay as
   planned".** Written when strength was light. With Plan No. 3's loads, an easy day back
   after a fever should not include a 1–2 RIR leg session. Proposed with FC331-02: strength
   takes the recovery-week dose on those floors. R6 makes the same point for the chest
   follow-up (HS332-05, Decision #386).

## 7. Hypotheses (unverified)

- Mark will keep doing his upper-body "Dumbbell Workout" on Mondays under Plan No. 3 unless
  someone sets up A on his watch. Testable from 19 Oct: Garmin categories on Monday strength
  activities (SQUAT, DEADLIFT, LUNGE present or not).
- His dumbbells may be too light for 6–8 RM goblet squats and RDLs by week 10; the plan never
  asks what he owns. If so, "one weight up" stalls and single-leg variants (rear-foot-elevated
  split squat, single-leg RDL) are the usual substitute.
- A ramp test 24 h after the first loaded leg session may read a few per cent low. Size
  unknown; the evidence is about residual fatigue in general, not this test.
- His bone density is unknown. The cross-sectional cyclist data and his decades of riding
  make a DXA conversation with his GP reasonable; that is R6's and Craig's call.

## 8. Limitations

- **Lens premises that did not hold.** "Workload budget" is a concurrency limiter
  (HS240-18). The "guided strength player" and "flexibility player" were withdrawn on 2 Jul
  (Decision #108); there is nothing to play, so item 4 reviewed the post-session reads only.
- **No real Plan No. 3 strength session exists yet**; everything about it is the stored draft
  (R4's copy, read, not re-fetched) and crafted inputs through the real functions.
- **No graded Red morning has yet fallen on a strength day while he was home**; FC331-02 is
  proved by probe, not observed.
- **Primary sources:** Rønnestad & Mujika 2014 read in full; Doma et al. 2017, Nichols 2003,
  Rector 2008 and Harding (LIFTMOR-M) 2020 abstracts only, plus the LIFTMOR-M protocol paper
  (BMJ Open 2017, PMC5541517) read; WHO 2020 (Bull et al., BJSM) recommendations read.
  The NSCA 2019 older-adult position statement was paywalled and is not cited.
- **Not checked:** what Home shows for a strength session on a Red morning (R7's surface);
  the paid brief's actual wording on such a morning (none exists).
- No paid calls; no `railway run`; no write anywhere but this file and the scratch folder.

## 9. Probe log

| # | What | Result size |
|---|---|---|
| 1 | SQL: `coach.activities` by type since 1 Jun (count, minutes, Garmin load, TE, excluded flag) | 6 rows |
| 2 | SQL: activity names for strength, other and walking since 1 Aug | 13 rows |
| 3 | SQL: weekly counts of dumbbell, other strength, mobility, walks and rides since 15 Jun | 17 rows |
| 4 | SQL: `information_schema.columns` for `coach.analyses` | 14 rows |
| 5 | SQL: post-strength/walk/flexibility reads since 1 Sep by prompt version | 4 rows |
| 6 | SQL: post-strength reads since 20 Sep with activity name, minutes, HR, load, output text | 6 rows, about 8 KB |
| 7 | SQL: strength activities since 20 Aug, `totalSets`, `totalReps`, first 400 chars of `summarizedExerciseSets` | 8 rows, about 3 KB |
| 8 | SQL: "Dumbbell Workout" exercise categories, sets, reps, `maxWeight` since 1 Jul | 6 rows, about 3 KB |
| 9 | SQL: active non-bike planned workouts 6 Jul–18 Oct, grouped | 7 rows |
| 10 | SQL: Red/Amber morning analyses since 1 Aug joined to planned strength that day | 4 rows |
| 11 | SQL: text columns of `manual_entries`, `brief_messages`, `feedback` | 18 rows |
| 12 | SQL: Mark's check-in notes, chat turns and feedback since 1 Sep matching strength/mobility/walk words (260 chars each) | 30 rows, about 8 KB |
| 13 | SQL: the coach's replies of 4 Sep on his bodyweight circuit | 2 rows, about 3 KB |
| 14 | SQL: latest post-walk and post-flexibility reads | 3 rows, about 3 KB |
| 15 | Local: `probe_load.py` — yesterday-load status, graded load domain, strength actions by colour, companion gate, modality matcher (real functions) | `probe_load.out` |
| 16 | Local: `probe_spacer.py` — no-stack conflicts with strength and mobility between VO₂ and sweet spot | `probe_spacer.out` |
| 17 | Local: `probe_changes.py` — Batch 324 minutes, days and remove changes on the stored draft, in memory | `probe_changes.out` |
| 18 | Local: `probe_redstrength.py` — call and plan line on a Red and an Amber Plan No. 3 Monday | `probe_redstrength.out` |
| 19 | Local: `strength_time.py` — sets and minutes per strength session from the stored draft | `strength_time.out` |

Total production read: about 40 KB. Paid calls: none.
