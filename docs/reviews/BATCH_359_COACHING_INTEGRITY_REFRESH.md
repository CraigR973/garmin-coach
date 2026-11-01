# Batch 359 — Coaching-Integrity Refresh (6th)

**Status: done 1 Nov 2026 (main part 11:40 GMT; the v14 weekly-review check, §9, 18:35–18:55 GMT).** · **Lens:** cycling coach who trains masters athletes · **Reviewed SHA:**
`083e012` · **Grade entering:** B+ (Batch 330) · **Grade leaving: A−** ·
**Paid spend: $0.** Internal: this report names how inputs and the plan can be gamed; not for Mark.

Method: `COACHING_INTEGRITY_AUDIT.md`'s two prongs. **Prong A** drove the real functions in memory
from scratch scripts in `scratchpad/wave6/r4/` (`grade()` over the 295 test grid with Plan No. 3's
own rows, the no-data morning per session type, `plan_changes.apply_change` on Mark's documented VO₂
progression, `progress_signal.hard_work_on_target` on his real October sessions). **Prong B** read
production read-only: the repo's replay through `railway run` inside a `SET TRANSACTION READ ONLY`
wrapper (asserted on every transaction) with a watchdog; Supabase SQL, projected and windowed.

## 1. Summary

**Verdict.** The daily call is now the best it has been: the replay reproduces production on
**31 of 31** graded mornings; over **1,596,672** one-step comparisons on the 295 grid with Plan
No. 3's real sessions, a worse input never gave a less cautious colour, and all **865** less
cautious *actions* are the one named light-week exception (a held Zone 2 or long ride read "as
planned": the same ride, Decision #373). Wave #5's three Med-Highs in this lens are closed and
proved, and the plan is working: **since the ramp test, 5 of 5 key sessions were ridden in full and
on target** (wave #5: 0 of 5). What a coach would not stand behind is the morning with **no call at
all** — live this morning (Garmin refused from 00:25 GMT until the call landed Green at 12:04): the engine's own missing-data rule never runs,
Zwift keeps the full pre-pushed session, Home says only that the brief failed, and the coach says
ride as planned. And the new "ready to progress" note measures what ERG holds fixed and counts a
Zone 2 sprint ride as a hard session — its first live firing, in tonight's weekly review, rested on
exactly that ride and invited "a ramp test, or one small step up" on the eve of a recovery week
the same review says needs no changes. **Grade A− (up from B+)**, held off A by CI359-01 and
CI359-02.

| Question | In this lens |
|---|---|
| 1. Correct and safe? | The call: yes (replay 31/31, grid clean, floors win). A no-call morning: no call, full session on Zwift (CI359-01). |
| 2. Honest with Mark? | Yes on every graded morning; post-ride reads now grade at 267 W and record call vs ride honestly (31 Oct). The progress note fired on a sprint ride on 1 Nov and offers more load into a recovery week (CI359-02). |
| 3. Helping him get fitter? | Yes: Plan No. 3 progresses and he is riding it in full (SS 2×25 → 2×30 at 89 %, 30/30s 22/22 on target, RPE 6). Legs the day before VO₂ on 9 Nov (CI359-03, with R5). |
| 4. Would failure be noticed? | The call: replay + grid would catch it. A no-call morning: Mark sees "Couldn't finish your brief"; the cause is filed `inputs`, which alerts nobody (R3's AI358-02). |
| 5. Cheap to run and change? | Yes. One engine, rule switches replayable; CI359-01's fix reuses an existing rule (about a day). |

## 2. What optimal looks like, and the smallest path

**Optimal for this athlete** (57, well-trained, ERG on Zwift, two dumbbell sessions, 13-week
block): one deterministic call every morning **including the mornings the watch data does not
arrive**; the session on the trainer is the session the call describes; the test result flows into
every grade (done); a test is ridden fresh or moved (done); no edit can make a session unsafe (done
for VO₂ dose); a progress signal built on evidence ERG cannot fake (heart rate and effort at fixed
power), not on targets ERG holds.

**Near-optimal already (keep):** the graded engine and its floors; 316's load lines (the ratio
from 1.5; recovery time only before a hard session); 336's move-never-ease test; the 30-minute VO₂
dose bound on all three edit paths; post-ride grading at the current FTP with the call-vs-ride
record (322); the daily live-ride check (6 runs to 1 Nov, found 0).

**Smallest set of changes, in order:**
1. **CI359-01** — on a morning with no overnight data, store a code-only call from what *is*
   present (his check-in, yesterday's load, the plan) through the existing missing-data rule, with
   no paid brief: Amber "Insufficient data", the per-session actions in §3, a Home line, the chat
   told why. Caution-only. **Before Tue 10 Nov** (first full VO₂ of the build) at the latest; Tue
   3 Nov is a recovery-week VO₂ Light, where the rule changes nothing material.
2. **CI359-02** — count only key-session work (VO₂, threshold, sweet spot) toward "ready to
   progress", and add an effort/heart-rate test ERG cannot fix; hold the note in a recovery week and within ~4 weeks of a test. It
   fired on 1 Nov; fix before the 8 Nov review.
3. **CI359-03** — move 9 Nov's Dumbbells A off the day before VO₂ (one plan edit; R5 owns the
   strength side).

## 3. Findings

Counts: **0 High · 2 Med-High · 1 Medium · 2 Low.** (CI359-02 raised from Medium after §9.)

### CI359-01 — Med-High · A morning with no overnight data gets no call: Zwift keeps the full session, Home says only that the brief failed, and the engine's own missing-data rule never runs

**Evidence: observed + proved + implemented.** Builds on R3's AI358-01 (the chat's answer) and
R6's HS361-02 (the symptom follow-up); this is the coaching side: what each kind of day should get.

- *Observed (1 Nov):* `brief_generation_status` for 1 Nov = failed, reason `inputs` (last 11:01
  UTC); every activity poll since 00:25 UTC failed; no morning row. Every Plan No. 3 ride to 14 Nov
  was **pre-pushed to Zwift at full on 15 Oct** (14 proposals `pushed`, one `intervals_event_id`
  each), so today's 120-min Long Z2 and Tue 3 Nov's VO₂ Light sit on his trainer as planned.
- *Implemented:* the pipeline refuses to grade unless a morning `daily_metrics` row exists
  (`MorningBriefPipeline._inputs_ready`; Decision #300). With no stored morning nothing runs
  downstream: no session actions, no delivery proposals (stage 2 reads the stored row), no Home
  call. Home's hero shows "Couldn't finish your brief … Try again" and, below it, the day's plan
  rows as planned with the Zwift line; nothing tells him how to ride.
- *Implemented:* the engine *has* a rule for this (Batch 321.2: a whole missing Garmin or sleep row
  holds a Green at Amber, "Insufficient data to judge today"), but it can only fire when a Garmin
  row exists and the sleep row is missing after 11:00. *Computed:* across 132 replayed mornings it
  fired **0** times.
- *Proved* (`probe_nocall.py`, the real `grade()` with only the check-in present, on Plan No. 3's
  own rows): what that rule would call, if it ran —

| Kind of day | On Zwift now | Engine's rule, build week | Engine's rule, recovery week |
|---|---|---|---|
| Rest day / strength only | — / on watch on tap | as planned | as planned |
| Zone 2 (60 min) | full | Amber · as planned | Amber · hold targets |
| Long Z2 (120 min, today) | full | Amber · as planned | Amber · hold targets |
| VO₂ 30/30 (10 Nov), sweet spot 3×20 (12 Nov) | full | Amber · **ease hard a zone** | Amber · hold targets |
| VO₂ Light (Tue 3 Nov, recovery week) | full | Amber · ease hard | Amber · **hold targets** |
| Ramp test | full | Amber · **move the test** | Amber · move the test |

**Corrections to the leads.** (a) On 1 Nov the coach's "ride it as planned" (AI358-01) is what the
engine's own rule says for a Long Z2 in a build week; the defects are no call, nothing on Home, and
the coach's false "checking in may trigger the read". (b) **Tue 3 Nov is lower-risk than the lead
says:** it is the recovery week's VO₂ Light (3 × 2 min at 115 %, 6 minutes of work), and the
engine's rule would only hold its targets. The exposure is **Tue 10 Nov** (VO₂ 30/30, 2 × 12 at
130 %) and **Thu 12 Nov** (sweet spot 3 × 20) if an outage recurs then. (c) If he taps a symptom on
a no-call morning, Home shows the floor's notice from his tap (Batch 301), but Zwift still holds the
session and the next morning forgets it (HS361-02).

**What Mark should be told, as his coach, by kind of day** (the recommendation):

| Kind of day | Told |
|---|---|
| Rest, strength, mobility | "No overnight data today; nothing about today changes." |
| Zone 2 or long ride | "Ride it as planned. Keep the first 15 minutes easy; if your heart rate sits higher than usual or it feels harder than it should, cut it to an hour." |
| Hard session, build week | Today's safe default is the engine's: the hard efforts a zone easier, full length. The relaxed version ("ride it in full if your check-in is your usual and the warm-up feels normal") is for later, from evidence (§5). |
| Hard session, recovery week | "Ride it as planned; it is already light." |
| Ramp test | "Move it to a morning with data; a test without a fresh-morning read gives a false FTP." |
| Any symptom tapped | The floor as on any day, and the next morning keeps it (HS361-02's fix). |

**Why this matters to a coach.** Missing data is not evidence of fatigue: the HRV-guided trials ran
the planned session when no low reading was present (Javaloyes 2019; Vesterinen 2016), and
subjective wellness tracks training stress at least as well as objective markers (Saw 2016). So the
call should not turn Red or rest him for an outage. But "no call" is not "as planned" either: on a
hard day it removes the only check he has, and on a test day it wastes the test.

**Fix and cost.** At the backstop (or on his check-in), when inputs are missing, store a code-only
morning from what is present through the existing missing-data floor — no paid brief — so stage 2
proposes the eased or moved session, Home shows the call and why, and the chat can say so (AI358-01
(a)). About a day plus Craig-signed wording; caution-only. It amends Decision #300 (§5).

### CI359-02 — Med-High · "Ready to progress" counts Zone 2 sprint rides as hard sessions and measures targets ERG holds fixed; its first live firing (1 Nov) rested on a sprint ride and invited more load into a recovery week

*Raised from Medium after §9: the prediction below came true on the first v14 review.*

**Evidence: proved + observed + implemented.**
- *Implemented:* 319's note fires when his last three "hard sessions" each landed ≥ 90 % of their
  work intervals on target and the next morning was Green. A hard session is any ride with a work
  interval targeted ≥ 84 % FTP — which includes the **six 12-second neuromuscular sprints at 185 %**
  in his Saturday "Z2 + Neuromuscular" ride, and every primer.
- *Observed:* his last hard-tagged rides are 27 Oct (VO₂ 30/30, 22 of 22 on target), 29 Oct (sweet
  spot 2 × 30, 4 of 4) and **31 Oct (Z2 + sprints, 6 of 6)**; 31 Oct has no next morning (Garmin).
- *Proved* (`probe_progress.py`, the real `hard_work_on_target`, as of 1 Nov): with 1 Nov missing
  → not ready; **1 Nov Green → ready**; sprint rides left out → not ready in every case (the third
  key session back, 22 Oct, was followed by an Amber). So the first "you look ready for a little
  more" can rest on a Zone 2 ride with 72 seconds of sprints.
- *Implemented + observed:* he rides in ERG, so "on target" is near-automatic for a completed
  session (every Plan No. 3 key session so far: 100 %), and a sprint is peak-graded and "can never
  be over". What the signal reads is "completed, and a Green next morning". The evidence a coach
  would use is stored and unused: on 29 Oct he held 2 × 30 min at 238 W with **RPE 6** and heart
  rate drifting only 129 → 133 bpm (≈ 3 %); on 27 Oct the 30/30s plateaued at ≈ 130 bpm, RPE 6.
- *Observed (1 Nov 18:00 weekly review, §9):* the 1 Nov morning landed Green at 12:04, so the
  signal fired with `readyToProgress: true` on 27, 29 and **31 Oct**. The review tells Mark his
  "last three hard sessions" landed clean and that he looks ready for "a ramp test, or one small
  step up in your next hard session" — in the same Recommendations block that says the coming week
  is his scheduled recovery week and "No training changes needed". His next hard session is Tue
  3 Nov's recovery-week VO₂ Light; his last ramp test was 20 Oct, 12 days earlier. The note is
  opt-in ("Nothing changes unless you choose it") and plan changes stay propose-confirm, so nothing
  moves on its own — but it is the app inviting extra load where the plan and the same page say
  none, built on a Zone 2 ride. The review also calls that ride one of "2 threshold-type rides".
- *Coaching:* a coach would say nothing about progression this week, and at the end of it say "the
  plan's next step looks right" — Plan No. 3 already steps up each build week, and a retest belongs
  after a recovery week several weeks from the last one (§8).
- **Fix and cost:** count only sessions whose workout type is VO₂, threshold or sweet spot; add a
  headroom test from stored data (session RPE at or under his usual for that session type, and
  heart-rate drift under about 5 % across the main set — a practitioner rule, weak evidence); word
  it as "the plan's next step looks right" or "consider a retest", and hold it in a recovery week.
  Half a day; the note's words need Craig's sign-off anyway (Decision #459 calls it provisional).

### CI359-03 — Medium · Legs the day before the build's hardest VO₂ so far (9 → 10 Nov) — with R5

**Evidence: observed.** Plan No. 3's live rows put Dumbbells A (squat, Romanian deadlift, lunge;
25 min) on **Mon 9 Nov** and **VO₂ 30/30 2 × 12 at 130 %** (24 efforts, ERG) on **Tue 10 Nov**
(also Mon 2 → Tue 3 Nov, but that pair is a light-weight session before a 6-minute VO₂ Light in a
recovery week: low cost). Batch 340 stopped the generator doing this; it does not move live rows
(FC331-03). Eccentric-heavy leg work reduces next-day power for 24–48 h in untrained-to-the-movement
lifters (DOMS literature); in ERG he cannot "ride by feel" a 130 % target. **Fix:** move 9 Nov's
Dumbbells A to Wed 11 Nov (or after the ride on 10 Nov). One edit, Mark's or Craig's call; R5
judges the strength side.

### CI359-04 — Low · On an "off the bike" morning, loaded leg strength stays "as planned"

**Evidence: proved + implemented.** On the grid, Dumbbells A is `as_planned` on all **12,960**
mornings where an acute signal (illness-grade HRV drop, resting HR + 7) takes him off the bike
(`_session_action`: "Not a ride; the verdict's ride changes do not apply"). Only a reported symptom
(`no_training`) or an open chest follow-up (`mobility_instead`) touches strength. A coach treating
an illness-like autonomic signal as "no riding" would not load squats and deadlifts that day. The
Red plan line ("Substitute recovery, mobility, or rest") covers it in words on mixed days, so the
structured action and the words disagree. **Fix:** under the bike-rest floor, loaded strength →
mobility (reuse 339's action). Small; lead for R5 and R6.

### CI359-05 — Low · A no-call morning also stops the progress note and the call-vs-ride record

**Evidence: implemented + observed.** The 319 note needs the next morning's colour (`None` blocks
it) and the 322 call-vs-ride record needs the morning's action, so every outage morning both hides
the progress signal and leaves the ride unrecorded against a call (31 Oct's ride has no "morning
after"; 1 Nov's ride, if any, will have no call to compare). Fixed by CI359-01's stored code-only
morning; listed so the synthesis does not count it twice.

## 4. The eight rule changes since wave #5, and the invariants, on today's code

| Check | Result | Evidence |
|---|---|---|
| Replay reproduces production | **31 of 31** graded mornings (132 stored, 21 Jun–31 Oct); 36 of 132 differ from what the old ladder showed before 30 Sep, as expected | computed (`replay_all.md`) |
| A worse input never gives a less cautious colour | **0** in 1,596,672 one-step comparisons (VO₂ + Z2, VO₂ 30/30, sweet spot 3×20 + long Z2, ramp test, VO₂ Light, Dumbbells A + Z2; normal and light weeks) | proved (`probe_invariants.out`) |
| …nor a less cautious session action | **865, all the named light-week exception** (Z2 or long ride `hold_targets` → `as_planned`; Decision #373). Wave #5: 505 on fewer sets | proved |
| Floors win | No replayed morning is less cautious where a floor applies, with or without the rule switches | computed |
| 308 ladder deleted | Mornings before 30 Sep replay as the graded engine would have called them; no ladder code path left in the replay | computed |
| 311 (b) + 316 (both lines) + 336, forced on vs off | **14 of 132** mornings change, **all toward less caution**, none under a floor; Red 8 → 6. In October: 13, 23, 26, 28, 30 Oct. Sound: the ACWR is contested (Impellizzeri 2020) and after a holiday it mostly measures the holiday | computed |
| 336 test moved, never eased | Over the grid the test is `as_planned` 2, `move_test` 513, `recovery` (Red) 7,261, `off_the_bike` 12,960; never eased or picked | proved |
| 321.2 missing-data floor | 0 firings in 132 mornings; never reachable on a no-Garmin morning (CI359-01) | computed + implemented |
| 317 one usual HRV | One window (84 nights) in the replay's line table and the rail | implemented (R6/R8 judge the number) |
| 339 symptom anywhere, 343 No plan loaded | Not re-tested here (R6, R7) | — |

**Plan No. 3 in practice (observed).** Key sessions since the 20 Oct test: SS 2 × 25 (22 Oct), Long
Z2 (25 Oct), VO₂ 30/30 2 × 10 (27 Oct), SS 2 × 30 (29 Oct) — all ridden in full, every work
interval on target, graded at 267 W (SS held 237.6 W = 89 %), on Green mornings. October before the
test: 0 of 4 key sessions due 29 Sep–6 Oct ridden (holiday); the three 11–17 Oct primers in full. The
31 Oct Amber offered "easy Zone 2 or tempo" for his Z2 + sprints ride; he rode the original,
the post-ride read recorded "did not take the call" and judged his reasons sound (legs and feel
high, clean execution). That is the record Batch 322 asked for, working.

## 5. Follow-through corrections (this lens)

| ID | Pack says | Now | Evidence |
|---|---|---|---|
| CI330-01 VO₂ dose | fixed (implemented) | **fixed, proved** | Mark's 28 Aug progression on Plan No. 3: 4 of 7 entries refused at the 30-min bound with plain words; accepted ones ≤ 24 min; `dose_refusal` on the builder, `/refine` and live edits (implemented) |
| CI330-02 grading after the test | fixed (claimed) | **fixed, observed** | post-ride `gradingTarget` and on-target counts at 267 W (22, 27, 29 Oct) |
| CI330-03 test eased | fixed (claimed) | **fixed, proved** | grid above |
| CI330-04 protections removable | fixed (implemented) | **fixed at lock; live edits unalerted** | lock-time diff + `admin_alert` (implemented); a Skip/Remove of a VO₂ in the locked plan alerts nobody, and `admin_alert` reaches no one yet (DS357-02). Accepted as his autonomy |
| CI330-06 no key session at full | shipped differently | **resolved by the athlete** | 5 of 5 since the test (observed); the 319 signal itself is CI359-02 |
| R0922-14 pre-pushed hard session after a Red | open | **open, re-verified** | `regenerate_for_verdict` only proposes; the pre-pushed event stays full until he approves (implemented). No Red since 8 Oct to observe. A no-call morning is the same gap with no proposal at all (CI359-01) |
| CR327-01 / CI239-02 the ride on Zwift | fixed | **fixed (observed)** | `live-ride-check` found 0 on every run to 1 Nov 03:15 |
| DV-6/7, DV-8, CO-6, VR0929-5, VR1004-3 | fixed (claimed) | **fixed, computed** | rule-effect replay above |
| HS240-15 resting-HR drift (§E) | not in 311 | **open (implemented)** | the RHR rail reads the nightly baseline median and upper quartile; no judged-week or nights-away leave-out as 311 (e) has for HRV, and (e) is off in production anyway |
| FC331-03 legs before VO₂ | open (live plan) | **open (observed)** | 2 → 3 Nov low cost; 9 → 10 Nov is CI359-03 |

## 6. Queued and parked items re-verified

- **337** (a failure reaches Craig): CI359-01's outage is filed `inputs`, which raises nothing
  (AI358-02); 337's "newest job_runs age" would not catch it either (the jobs run and fail).
- **345** (coach voice): its pass-to-Craig alert has no route (unchanged); not this lens.
- **209, 338**: not this lens.

## 7. For reconsideration

- **Decision #300** (no authoritative brief without inputs). New evidence: the gate also withholds
  the *deterministic* call, which costs nothing and would be cautious; on 1 Nov this left Mark with
  a full session on Zwift and "ride as planned" from the coach. Proposal: keep #300 for the paid
  brief, and let the backstop store a code-only "insufficient data" morning (CI359-01).
- **Decision #459** (319 provisional thresholds). New evidence: CI359-02's proof; the thresholds are
  not the problem, the session set and the measure are.
- **Later, from evidence:** whether a no-data hard day in a build week should be "ride it if your
  check-in is your usual" rather than eased (removes caution, so not first; Craig's 3 Oct rule).

## 8. Hypotheses (unverified)

- **His FTP of 267 W may be conservative.** Sweet spot at 89 % for 2 × 30 min at RPE 6 with ≈ 3 %
  heart-rate drift, and 30/30s at 130 % at RPE 6, suggest headroom; the ramp test's 75 % of the best
  minute tends to under-read riders with little anaerobic reserve, typical of masters riders. No max
  HR, lactate or 20-min test exists to check it; a retest after the 23–29 Nov recovery week would.
- The 31 Oct "tempo" alternative for a Z2 + sprints ride may be more metabolic load than the
  original; the tempo transform's IR was not read.
- 1 Nov: Garmin returned by noon (morning stored Green 12:04 GMT; strength read 14:04, post-ride
  read 15:24). The 1 Nov ride itself was not read.

## 9. The first v14 weekly review (1 Nov 18:00 London; read 18:35 GMT)

One row, `reviews-v14-2026-10-29`, `claude-sonnet-5`, generated 18:00:57 GMT for the week
26 Oct–1 Nov, 3.1 KB, plus its push at 18:00:58. **Full week, no short-week caveat:** Garmin was
back before noon and the packet counts 7 days (5 recovered, 2 some fatigue).

| Check | Result | Evidence |
|---|---|---|
| `progressSignal` vs CI359-02's prediction | **As predicted:** 1 Nov landed Green, so `readyToProgress: true` on 27, 29, 31 Oct (31 Oct = Z2 + sprints), each 100 % on target, `provisional: true` | observed |
| Adherence | Honest on completion ("every key session … got done"; 4 of 4) but labels the Z2 + sprints ride a "threshold-type" ride; the declined 31 Oct Amber offer is not mentioned (no harm: he rode the plan and woke Green) | observed |
| Recovery week 2–8 Nov | **Framed well:** "scheduled recovery week", lighter targets "by design, not a shortfall", hardest session Tue VO₂ Light with Monday night named as the night that protects it | observed |
| Contradiction | The last recommendation offers "a ramp test, or one small step up" into that same recovery week, on the strength of the sprint ride → **CI359-02 raised to Med-High** | observed |
| Fitness drift line | Honest: heart rate at a fixed 184 W 111.1 → 112.7 bpm, "basically steady" | observed |
| Paid spend | $0 by this pass (the review is the app's own scheduled call) | — |

Cross-lens lead (R5/R2): the review says Saturday's Dumbbells B "is still showing as planned";
a strength read was stored 14:04 on 1 Nov — whether completion detection matched it was not checked.

## 10. Limitations

- No paid calls; the coach's answers are R3's probe. Primary sources for the no-data paragraph
  (Javaloyes 2019, Vesterinen 2016, Saw 2016, Impellizzeri 2020) were not re-read this pass; they are
  the app's own cited sources, read by earlier waves. The DOMS point in CI359-03 is general
  physiology, not read here (R5's lane).
- The probe for CI359-01 grades "only the check-in present" as the test grid's empty-acute input; a
  real code-only morning would carry yesterday's load and his feel too (both would only add caution).
- Home's text on a no-call morning is read from code, not rendered (R7).
- Live drift: Garmin was still refused at 11:22 UTC and was back by 12:04 (how is R3/R6's lane);
  §1's "live this morning" describes the 00:25–12:04 window.

## 11. Probe log (all read-only)

| # | What | Size |
|---|---|---|
| 1 | `railway run` replay (`replay_ro.py` wrapping `scripts/replay_verdicts.py`; every transaction `SET TRANSACTION READ ONLY`, asserted; watchdog 900 s; script rolls back) with `--rule-effect` 311 (b), 316 × 2, 336 | 132 mornings, `replay_all.md` 450 lines |
| 2 | SQL: brief status 30 Oct–1 Nov; recent activity-poll and morning-sync runs; 31 Oct morning | 8 rows |
| 3 | SQL: column names (6 tables) | 6 rows |
| 4 | SQL: delivery proposals 26 Oct–14 Nov joined to plan rows (no IR) | 15 rows |
| 5 | SQL: 8 plan rows' structured workouts (Plan No. 3, no health data) | 8 rows, ~8 KB |
| 6 | SQL: key sessions 1 Sep–31 Oct with ride summaries and the day's colour | 23 rows |
| 7 | SQL: post-workout packet keys 20–31 Oct (no bodies) | 10 rows |
| 8 | SQL: grading target, call-vs-ride, execution summary (truncated) 22/27/29/31 Oct | 4 rows |
| 9 | SQL: hard-interval counts per post-ride read 4–31 Oct (aggregated in SQL) | 19 rows |
| 10 | SQL: 31 Oct post-ride read text | 1 row, 3.6 KB |
| 11 | SQL: work-interval power/HR and post-ride check-in, 22/27/29 Oct | 3 rows |
| 12 | SQL: non-pushed proposals since 7 Oct; proposal-expiry / live-ride-check / baseline runs 31 Oct–1 Nov | 2 + 6 rows |
| 14 | SQL (18:35): analyses since 29 Oct (type, date, verdict, time only) | 15 rows |
| 15 | SQL: the v14 review's text, `progressSignal`, `weekAhead`, `dayCount`, data guardrails (one row) | 1 row, ~12 KB |
| 13 | Prong A in memory: `probe_nocall.py`, `probe_invariants.py` (1,596,672 comparisons), `probe_mark_vo2.py`, `probe_progress.py` | scratch outputs |

Paid calls: **none ($0).** Total production reads well under 1 MB. After the replay, `pg_stat_activity`: 0 idle in a transaction (1 active, 9 idle). No process left running.

## 12. Summary block for `COACHING_INTEGRITY_AUDIT.md` (the synthesis pastes it)

## 2026-11-01 Refresh (Batch 359)

**Full report:** `docs/reviews/BATCH_359_COACHING_INTEGRITY_REFRESH.md` (5 findings, `CI359-01…05`:
0 High / 2 Med-High / 1 Medium / 2 Low). Wave #6 (Batches 356–363); siblings CR356, DS357, AI358,
HS361. Reviewed SHA `083e012`; $0 spent.

**Grade: A− (up from B+).** The call is the best this audit has graded: replay **31 of 31**; **0**
less cautious colours in **1,596,672** grid comparisons on Plan No. 3's real sessions; the only less
cautious actions are the named light-week exception (865). CI330-01 (dose bound), CI330-02 (grading
at 267 W) and CI330-03 (test moved, never eased) are closed and proved; CR327-01's ride mismatch has
not recurred (live-ride check, 0 found). Mark rode **5 of 5** key sessions since the ramp test in
full and on target. Held off A by the **no-call morning** and the **progress note's first firing**:

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| **CI359-01** | Med-High | No overnight data → no call: Zwift keeps the full pre-pushed session, Home says only "Couldn't finish your brief", the engine's missing-data rule (Amber; hard work eased, test moved) never runs. Live 1 Nov. Exposure: 10 Nov VO₂, 12 Nov sweet spot; 3 Nov (recovery-week VO₂ Light) is low | observed + proved |
| **CI359-02** | Med-High | "Ready to progress" counts Z2 + sprint rides as hard sessions and reads ERG-held targets; it fired in the first v14 review (1 Nov) on a sprint ride and offered "a ramp test, or one small step up" into the recovery week the same review says needs no changes | proved + observed |
| CI359-03 | Medium | Dumbbells A (legs) the day before VO₂ 30/30 2 × 12 on 9 → 10 Nov (live plan) | observed |
| CI359-04 | Low | Off-the-bike mornings leave loaded leg strength "as planned" | proved |
| CI359-05 | Low | A no-call morning also blocks the progress note and the call-vs-ride record | implemented |

**To A:** CI359-01 shipped (a code-only "insufficient data" morning through the existing floor),
CI359-02's session set, headroom test and recovery-week hold, and one outage morning watched end to end: the call,
Home, the coach and Zwift all say the same eased or moved ride.

