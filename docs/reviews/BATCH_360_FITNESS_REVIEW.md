# Batch 360 — Strength and the whole athlete (wave #6, R5)

Reviewed SHA `083e012` (production; `main` = `083e012` + review docs, no code drift). Lens: a strength
and fitness coach for older endurance athletes. Read-only. Run 1 Nov 15:45–15:55 GMT.
Paid spend: **≈ $0.03** (one post-strength read probe, nothing stored; §9). Probes and outputs are in
this session's scratchpad, not copied here; Mark is described, not quoted.

## 1. Summary

**Grade: C+ (= wave #5).** The parts Batch 340 built work: Dumbbells A and B can reach his watch, and
the new strength read (v8) tells a circuit from a lifting session and says plainly when a planned move
is missing (proved, §FC360-01). But the loop around the strength plan is still open. In Plan No. 3's
first two weeks he did **no** loaded leg session, while the plan row, a strength read and the weekly
review told him Dumbbells A was done; the plan's progression ("one weight up") cannot be followed with
the 5 kg and 10 kg dumbbells the app knows he owns; and every remaining Dumbbells A still falls the day
before VO₂.

| Question | Grade | In this lens |
|---|---|---|
| 1. Correct and safe | B | Nothing unsafe is pushed. Loaded legs sit the day before VO₂ on 11 of 11 remaining weeks (FC360-03), and an off-the-bike morning keeps them "as planned" (FC360-05); both low-to-moderate risk at his loads. |
| 2. Honest with Mark | C | 21 and 26 Oct: his old upper-body routine completed "Dumbbells A (legs and back)"; the 26 Oct read said "legs and back… no material differences", the 25 Oct weekly review said A "was completed" (observed). v8 now says the truth in its prose, but the status still says done (proved). |
| 3. Fitter off the bike | C | 0 of 4 Plan No. 3 dumbbell sessions done as written (observed). The prescription assumes weights he does not have (FC360-02). Nothing for bone in the live plan (FC360-06). His own circuit, mobility and walks are kept and read. |
| 4. Failure noticed | C− | The deterministic record (row status, Week, weekly review) cannot tell A from his old routine; no weight is ever recorded, so the progression cannot be checked; the watch push keeps no record. |
| 5. Cheap to run and change | B+ | Most fixes are one condition or plan content: the generator's own rule (`legs_rested`) already exists; the bike-rest fix is one line; category matching reads data already stored. |

## 2. Findings

Counts: **1 High, 1 Med-High, 2 Medium, 3 Low** (7).

### FC360-01 · High · Two weeks of Plan No. 3 with no leg session, recorded and reported as done

*Evidence: `observed` (production rows) + `proved` (v8 read, one paid run) + `implemented`.*

- **What he did (observed, `activities`, 19 Oct → 1 Nov).** Strength work: his 9–14-minute bodyweight
  circuit 7 times, and his long-standing upper-body "Dumbbell Workout" on 21 and 26 Oct (Garmin's
  exercise categories: shoulder press, flye, lateral raise, row, curl, triceps; no squat, deadlift or
  lunge). No session with a loaded squat, hinge or lunge. Every recorded weight is 0.
- **What the app recorded (observed, `planned_workouts`).** "Dumbbells A (legs and back)" Wed 21 Oct
  (moved from Mon 19) and Mon 26 Oct are both `completed`, each by the upper-body routine. Both B rows
  (24, 31 Oct) stay `planned`: the circuit is correctly refused for B (Batch 278's bodyweight rule).
- **What Mark read (observed).** 26 Oct strength read (v7): A done "(legs and back) — logged as finished
  against plan with no material differences". 25 Oct weekly review: A "was moved to Wednesday… and it
  was completed there". Exactly wave #5's predicted path (FC331-01).
- **What v8 changes (proved, 15:50 GMT).** Re-running the 26 Oct read on today's v8 code with the real
  packet: it says the logged moves are "a different exercise set entirely" and that none of A's leg moves
  appear. Good. But the packet's `plannedMatch` still says `materiallyDifferent: false`, the row stays
  `completed`, and Week, the weekly mix and the weekly review read the row, not the prose.
- **Why (implemented).** `workout_match.strength_material_difference` compares only weighted vs
  bodyweight words in the names. Batch 340's acceptance "Monday's activity matched only when it is A" was
  moved into 322 (ledger correction, 29 Oct) and 322 built neither it nor the top weight ("his watch
  records no weights" — which is the reason to ask for one, not against it). `followthrough.md` marks
  FC331-01 "fixed (claimed)": delivery is fixed; matching and weight are not.
- **Why it matters now.** Week 4's A (Mon 9 Nov) says "one weight up from week 2": a week 2 that did not
  happen at a weight never recorded. A · Mon 02 Nov is on his watch (Decision #457); if he runs his old
  routine instead, it is ticked again tomorrow.
- **Fix (smallest).** (1) Category matching on the stored `summarizedExerciseSets`: A is done only if a
  SQUAT, DEADLIFT or LUNGE category appears; B only with SHOULDER_PRESS or BENCH_PRESS or the B moves;
  otherwise a deviation (the v8 read then agrees with the row). (2) One optional "heaviest dumbbell
  today (kg)" field on the strength check-in. **Cost:** about a day plus tests; adds caution (refuses a
  false completion). **Where:** a small batch before Mon 9 Nov; (2) can follow.

### FC360-02 · Med-High · The plan progresses in weights he does not have

*Evidence: `observed` (his learned context and chat) + `implemented` (generator) + literature.*

- **The constraint (observed).** His active learned context (accepted from chat, Oct): dumbbells only, no
  barbell, **5 kg now, 10 kg the most he expects to have**. The coach repeated it on 24 Oct.
- **The prescription (observed, live rows).** Recovery weeks: "an easier weight than last week" (he is
  already on his lightest); weeks 4, 7 and 10: "one weight up" (with 5 and 10 kg only one step exists,
  and 10 kg is the ceiling); weeks 10–11: 6–8 reps at 1–2 reps in reserve. A goblet squat or Romanian
  deadlift at 10 kg is nowhere near 6–8 reps from failure for a lifelong cyclist's legs.
- **The generator (implemented).** `next_plan` writes the same "one weight up" doses for the next plan
  and never reads the equipment fact (no reference to it in `next_plan.py`).
- **Evidence.** Heavy loads (4–10 RM) carry the cycling-economy evidence (Rønnestad & Mujika 2014, read
  at wave #5). Light loads build similar muscle if sets go close to failure, but less maximal strength
  (Schoenfeld et al. 2017, meta-analysis, abstract). NSCA's position for older adults (Fragala et al.
  2019, abstract): progressive loading, 2–3 sets, 2–3 days a week, plus power and balance work.
- **What Mark experiences.** Instructions he cannot follow, so the plan quietly stops progressing; the
  app cannot tell (no weight recorded, FC360-01).
- **Fix.** Progress by what 5–10 kg allows: harder variants (split squat → rear-foot-elevated split
  squat; single-leg Romanian deadlift; higher step-up), slower lowering (3 s), and sets taken to 1–2 reps
  from failure at 12–20 reps; or Craig and Mark decide on adjustable dumbbells (to about 20 kg each).
  Feed the equipment fact into the generator. **Cost:** a table edit (content) for Plan No. 3's
  remaining rows or Plan No. 4; Craig's call on equipment.

### FC360-03 · Medium · Every remaining Dumbbells A is the day before VO₂ (CI359-03, widened)

*Evidence: `observed` (live rows) + `implemented` + literature (moderate to weak).*

- **Placement (observed).** All 11 remaining A sessions (2 Nov → 11 Jan) sit the day before a VO₂
  session, including the build's hardest: 30/30 2 × 12 at 130 % (10 Nov), 3 × 10 (17 Nov), 30/15
  3 × 12 and 4 × 10 (8 Dec, 22 Dec, 29 Dec), the heavier A doses landing on the same Mondays. R4's lead
  named 9 → 10 Nov; it is the whole plan. The generator's rule (`next_plan.legs_rested`, Decision #457)
  would move A to the sweet-spot day; it was not applied to Plan No. 3's rows.
- **How big the risk is, at his loads.** Small for the load (5–10 kg), real for the novelty: he has
  never recorded a loaded lunge or Romanian deadlift, and unaccustomed eccentric work is what produces
  next-day soreness. One light bout protects for about 2–3 weeks (repeated-bout effect; Bridgeman et al.,
  Nosaka & Aoki, review abstracts), so if 2 Nov's light A is done, 9 Nov carries less risk; if it is
  not, 9 Nov is his first loaded leg session, 24 h before 24 efforts at 130 % in ERG. Doma et al. 2017
  (wave #5): residual fatigue from resistance work can blunt endurance work for hours to days.
- **Strength coach's call.** Hard days hard: A after the key ride on the same day (Tuesday, a few hours
  after VO₂) or on Thursday after the sweet spot (the generator's choice; Friday is rest, Saturday's
  sprints are 48 h later). 2 → 3 Nov can stay (recovery week, VO₂ Light, and it is the needed first
  light bout).
- **Fix.** Move A from 9 Nov onward to Thursdays (10 rows), through the app's own move path, before Mark
  taps "Put this week's dumbbells on your watch" for that week: a moved row goes up under a new name and
  the old Monday workout stays on his Garmin calendar (FC360-07). **Cost:** content, no code; Mark's or
  Craig's call.

### FC360-04 · Medium · The strength read and weekly numbers still count the circuit as strength frequency

*Evidence: `observed` (31 Oct, 1 Nov v8 reads) + `implemented`.*

- v8 now calls the circuit "maintenance work rather than strength building" (good), but its
  frequency block still counts every strength activity: "16 sessions over the last 4 weeks… solid,
  steady habit… trend increasing", in a fortnight with no loaded leg session. The rollup
  (`strength_brief.compute_strength_rollup`) never split loaded from bodyweight (FC331-06's first fix).
- **Fix.** Count loaded sessions (`sessionLoad.kind == lifting`, after FC360-01's matching) and circuits
  separately in the rollup and in the weekly review's strength line. **Cost:** half a day, packet only.

### FC360-05 · Low · An off-the-bike morning keeps loaded legs "as planned" (CI359-04)

*Evidence: `implemented` (+ R4's `proved` grid: 12,960 mornings).*

- On the bike-rest floor (illness-grade HRV drop, resting HR +7), `_session_action` returns
  `as_planned` for Dumbbells A ("Not a ride"). On a Monday (A only) Mark reads "Take today off the bike"
  as the call; the plan line is the Amber or Red strength line (the floor keeps the day at least
  Amber: "Keep strength submaximal…" or "Keep today's strength easy: the weight you used last time…");
  and the session card still asks for, say, 3 × 10 one weight up. Three messages, all of which still
  load his legs.
- **What a strength coach for older athletes prescribes.** An autonomic signal of systemic stress is
  treated like a below-the-neck symptom: no loaded training that day; 15–20 minutes of his own mobility
  routine or an easy walk; resume A when the signal clears, at last week's dose, not a step up.
- **Fix.** Under `FLOOR_BIKE_REST`, `_loaded_strength` → `mobility_instead` (the action Batch 339 built
  for the chest follow-up), with its words. One condition and a test; adds caution only.

### FC360-06 · Low · No bone or power element in the plan he is on

*Evidence: `implemented` + `observed` + literature (weak to moderate).*

- Batch 340.3 put "low hops (2 × 10, soft landings)" into the *next* plan's A; Plan No. 3's rows hold
  none, and `strength_watch` strips the hops from what it sends when the row names none (implemented).
  So the bone element starts in mid-January at the earliest. With 5–10 kg dumbbells, impact is the only
  realistic bone stimulus he has (LIFTMOR-M's 80–85 % 1RM lifts are out of reach); his walks are Zone 1.
- Cycling-only masters show lower spine and hip bone density (Nichols 2003; Rector 2008: cross-sectional,
  small). NSCA 2019 also asks for power and balance work for older adults; nothing plans either.
- **Fix.** Add the two sets of low hops to A from week 4 (content, rows already carry the move list),
  starting at 2 × 5, and a single-leg balance hold to the warm-up. Craig's call; see "For reconsideration".

### FC360-07 · Low · The watch push leaves no trace, and a moved session stays on his watch

*Evidence: `implemented`.*

- `strength_watch` "keeps no record of its own" and the route returns placed / failed to the screen
  only: no audit row, no `job_runs` row (a failure is a `log.warning`). Neither Craig nor the app can
  say which week's A and B are on his watch. A moved row goes up under a new dated name; the old one is
  never unscheduled, so after FC360-03's move he would see A on both Monday and Thursday.
- The watch steps carry the move and the reps but not the effort ("2 reps in reserve", "easier weight"):
  on the watch, the session is reps only.
- **Fix.** One audit row per placed or failed upload; unschedule the superseded dated workout on a move
  (Garmin's schedule id is returned on upload); put the row's effort words in each step's description.
  **Cost:** half a day.

### Checked and near-optimal (not findings)

- **v8 strength read.** Honest on circuits (31 Oct, 1 Nov) and, proved, on the wrong dumbbell session.
  Heart rate only against his own range; never judges an unrecorded weight. Keep it.
- **Red strength-only morning (FC331-02).** 321.3's line ("the weight you used last time, no step up,
  fewer sets") now matches the call's intent; the open chest follow-up turns loaded strength into
  mobility (339). Only the bike-rest floor is left (FC360-05).
- **His own routines.** Circuit, 16-minute mobility (4–5 a week) and walks are read, not overridden;
  the circuit is correctly refused for a dumbbell row (Batch 278).
- **Walks and strength in the load model.** Unchanged since wave #5 (Garmin load ≤ 5 on all walks and
  strength in October; observed): correct not to soften rides for them. Placement, not the load model,
  is where strength must be protected (FC360-03).
- **Generator (next plan).** `legs_rested`, honest minutes in the description, hops, his routines named:
  right, except the equipment blind spot (FC360-02).

## 3. What optimal looks like (for this athlete)

A 57-year-old lifelong cyclist with 5–10 kg dumbbells at home: two short sessions a week that load
legs (squat, hinge, lunge or step-up) and upper body, progressed by variant, tempo and reps to near
failure rather than by weight; placed after a key ride, never the day before one; a few minutes of
hops and balance; recorded as what he actually did (moves, and one weight number when he has one); and
on a bad morning, mobility instead. The app has most of the parts. The missing ones are the matching
(FC360-01), progression that fits his kit (FC360-02) and the placement edit (FC360-03).

## 4. Follow-through corrections (wave #5 R5 rows)

| Row | Pack says | R5 finds |
|---|---|---|
| FC331-01 | fixed (claimed) | **partly**: delivery to the watch built; category matching and top weight not built (moved to 322, not done); false completions observed 21 and 26 Oct → FC360-01 |
| FC331-02 | fixed (claimed) | **fixed** for Red and the chest follow-up (implemented); bike-rest floor open → FC360-05 |
| FC331-03 | open (live plan) | **open, wider**: 11 of 11 remaining A sessions before VO₂ → FC360-03 |
| FC331-04 | fixed (claimed) | **next plan only**: live rows still 20–25 min with no real-time line; build-week A at 3 × 10 with 60 s rests is about 30–35 min (computed from the row's own dose); minor |
| FC331-05 | fixed (claimed) | **next plan only**: no hops in Plan No. 3 → FC360-06 |
| FC331-06 | fixed (claimed) | **mostly fixed** (v8 sees load, proved); rollup still counts circuits → FC360-04 |
| FC331-07 | fixed (claimed) | **next plan only** (its "why this plan" names his routines; implemented); harmless, since his routines are read |

CI239-07 (strength counts in the no-stack rule) and DV-10: no change seen; not re-proved here.

## 5. Queued and parked items re-verified

None of 209, 337, 338 or 345 touches strength. 337's "every operator `log.error` reaches Sentry" would
not catch the watch push's `log.warning` (FC360-07).

## 6. For reconsideration (settled decisions, new evidence)

- **#457, "Plan No. 3's rows are not rewritten".** New evidence: all 11 remaining A sessions precede
  VO₂ (not two), the first two As were never done, and the hops the decision calls for will not reach
  him before mid-January. A one-off move of A to Thursdays (and hops from week 4) through the app's own
  edit path is content, not code. Craig's call.
- **#457, minutes stay at 20/25.** Unchanged view: honest description in the next plan is enough; the
  live rows lack it (minor).
- **#108 / #457 (watch workouts, not an in-app player).** Holds: he lifts from the watch, and the push
  works. The gap is recording, not delivery.

## 7. Hypotheses (not verified)

- If the 2 Nov A is skipped, the 9 Nov A is his first loaded lunge and RDL and next-day soreness is
  likely; whether it costs power at 130 % in ERG is unmeasured for him.
- The chat's strength lane ("keep the plan's sets, reps and effort as written", `GENERAL_SCIENCE_RULE`)
  would coach 9 Nov's "one weight up from week 2" as written, and holds no "no legs before VO₂" rule; no
  such chat has happened yet, so untested (lead for R3/R7, no paid run spent on it).
- Why he ran the old routine on 21 and 26 Oct (habit, the watch, or the plan unclear) is unknown; the
  31 Oct read suggests he meant to set the new one up.

## 8. Cross-lens leads (for the synthesis)

- **R4/CI359-03** → widened to 11 of 11 weeks (FC360-03); the placement fix is one plan edit series.
- **R4/CI359-04, R6** → FC360-05; R6's floors view should confirm "mobility instead" on the bike-rest
  floor.
- **R7 (UX)** → Week shows Dumbbells A ticked on 21 and 26 Oct; whether Mark sees the v8 "different
  exercise set" prose next to a green tick is a one-story question.
- **R8 (statistics)** → the strength "sessions per week, trend increasing" figure mixes circuits with
  lifting (FC360-04).
- **R3** → the chat strength-lane hypothesis above.

## 9. Limitations

- Garmin's library and calendar were not read (no Garmin call; read-only rule), so "A · Mon 02 Nov is on
  his watch" rests on Decision #457's close-out note.
- No crafted-morning run for FC360-05 of my own: the call words are read from code and R4's grid proof.
- Primary sources new to this pass were read as abstracts or summaries only (NSCA 2019, Schoenfeld
  2017, repeated-bout reviews); wave #5's sources (Rønnestad & Mujika 2014, Doma 2017, Nichols 2003,
  Rector 2008, LIFTMOR-M) not re-read.
- The first v14 weekly review (18:00 today) came after this pass; whether it repeats "A completed" for
  26 Oct is for R4's §9 or R7.

## 10. Probe log

| When (GMT) | What | Result |
|---|---|---|
| 15:47 | SQL: columns of activities, planned_workouts, garmin_workout_deliveries, manual_entries | schema |
| 15:47 | SQL: non-ride activities 1 Oct → 1 Nov, exercise categories and `maxWeight` (projected from `raw_summary`) | 0 loaded leg sessions; weights all 0 |
| 15:48 | SQL: strength plan rows 12 Oct → 15 Nov with check-ins and deliveries | A 21, 26 Oct `completed`; B 24, 31 Oct `planned`; no strength delivery rows |
| 15:48 | SQL: post-strength reads since 19 Oct (packet projections) + 4 outputs read | v7 26 Oct false match; v8 31 Oct, 1 Nov honest |
| 15:49 | SQL: strength rows 2 Nov → 17 Jan (titles, doses) | doses and "one weight up" wording |
| 15:49 | SQL: chat messages since 19 Oct naming dumbbells (read, not copied) | equipment 5 kg / 10 kg; 24 Oct exchange |
| 15:49 | SQL: active knowledge base sections naming dumbbells / kg (matched phrases only) | learned context holds the equipment |
| 15:49 | SQL: weekly reviews since 18 Oct, strength sentences | 25 Oct review: A "completed" |
| 15:49 | `railway run` probe, count mode (READ ONLY asserted, rolled back) + free `count_tokens` | 6,104 tokens |
| 15:50 | **Paid**: same probe, one v8 post-strength read of 26 Oct, `claude-sonnet-5`, 6,104 in / 525 out, 0 thinking; nothing stored | **≈ $0.03** (est. at $3 / $15 per M) |
| 15:51 | SQL: each remaining A and the next day's ride | 11 of 11 before VO₂ |

No transaction was left open (the probe's session was rolled back and closed inside its own context).
| 15:53 | SQL: connections idle in a transaction | 0 |
