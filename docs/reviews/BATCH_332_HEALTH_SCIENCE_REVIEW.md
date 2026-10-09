# Batch 332 — Health, sleep and medical-safety review (audit wave #5, pass R6)

**Pass R6 of seven in the Batch 327–333 audit wave.** Scope and guardrails:
`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`. Reviewed SHA `42a6a98` (production and
`main`; the checkout's `2aff0bc` adds only review docs). Lens: a sports-medicine doctor
working with a sleep scientist. Read-only throughout: no code, data, Railway, Vercel,
Supabase or Sentry change; one read-only `railway run` (rolled back); **no paid Anthropic
call (budget $0, spent $0)**. Evidence labels: `observed` (production data), `computed`
(derived from production data by a script), `proved` (the real function driven with
crafted inputs, or a test), `implemented` (read in the code). Predecessor:
`BATCH_240_HEALTH_SCIENCE_REVIEW.md` (HS240-01..19). Two earlier runs of this pass were
stopped by usage limits; their probe (`probe_floors`) is reused here and its output
re-read against the code.

Scratch work (gitignored, not committed): `scratchpad/wave5/r6/` — `probe_floors.py/.out`
(28 crafted mornings through the real chain), `probe_notes.py/.out` (the notes reader),
`probe_experiment.py`, `probe_cache.py`, `probe_drivers_live.py/.out` (the read-only
production drivers run), `epmc.py` (the literature search), `ci_42a6a98.log`.

---

## 1. Summary

**Verdict: the medical floors are sound, rare and robust; what sits around them is less
honest than the floors.** Every floor fires at the right line, beats every other signal,
survives a failed brief and a re-saved check-in, and has never fired falsely. The gaps
are a symptom that happens on the bike (no route to any floor), statistics that are
about to tell Mark a sleep lever works from a September-against-October contrast, a REM
verdict repeated every morning that the app's own audit says the watch cannot support,
and October pushes to cool his bedroom towards 17 °C while he is heating it. **Grade: B**
(wave #4's lens had no grade; the floors alone would be A−).

1. **Correct and safe:** yes for what he taps or writes in the morning (28 crafted
   mornings, *proved*; CI 2,721 passed, 0 skipped). No route for a symptom felt during a
   ride or told to the coach (HS332-01).
2. **Honest:** mostly. Four places say more than the evidence: the daily REM band
   verdict (03), an experiment about to read "supported" (02), "Recovered" the morning
   after a chest report (05), "sustained" low oxygen after one night (08).
3. **Helping him get fitter:** 8 Oct's "Recovery day" was right by the HRV trials the
   engine cites; the recovery advice still chases REM, and no lever has yet been shown to
   help.
4. **Would a failure be noticed:** floors are stored before the paid call and pinned by
   tests; nothing has fired on a real morning (0 symptoms in 110 mornings), and a chest
   report reaches only Mark.
5. **Cheap to run and change:** yes. The medical layer is pure, table-driven and small;
   the notes reader costs about 0.8 cents a noted morning. Near-optimal.

---

## 2. What optimal looks like

**For the medical layer**, optimal is: one question that catches any red-flag symptom
since the last check-in wherever he mentions it (check-in, note, post-ride note, chat);
floors that are deterministic, stored before any paid call and pinned by tests; words
that never say more than the engine knows; and an honest "not a medical device" line.
**Most of this exists and is near-optimal**: the three floors (chest or heart, fever or
aches, head cold), 315's chest follow-up, 303's two easy days after a fever, the +7 bpm
and illness-grade HRV floors, the stored-first morning (302), the notes reader that can
only add caution (297/303), and S1's standing line. The smallest changes to reach
optimal:

1. **Widen the question to "since your last check-in, including on a ride"**, and give
   the post-ride read and the coach the chest-or-heart rule (HS332-01). The wording
   change alone is caution-only: **before 21 Oct?** — Craig's call.
2. **Calm, true words on the edge cases:** a neutral call while a chest follow-up is open
   (05), "a low reading" rather than "sustained" (08), and the two 321.3 lines (already
   queued).
3. **A high-side HRV check** that treats an implausibly high night as unusual, not as
   recovery, and asks about a racing or irregular heartbeat (06).

**For sleep and recovery advice**, optimal is advice whose evidence grade is stated,
whose effect is measured against a fair comparison, and that never tells a healthy man a
measurement is "below the healthy range" when the app's own audit says the watch
undercounts it. Smallest path: guard the REM-intervention comparison against calendar
time (02), lead the REM paragraph with the pattern and his own baseline and drop the
laboratory-band verdict (03), put an 18 °C floor under the thermal advice (04), fix the
drivers cache (09). All of these fold into G8's 318 and 320 or sit after G8; none is a
safety gap.

**Already near-optimal, proved on the real chain:** a racing or irregular heartbeat or
faintness he taps or writes goes straight to "no training, GP or 111 today, 999 now"
(the right path for a felt AF episode or symptomatic bradycardia; his resting HR of
40–49 is athlete's bradycardia and correctly never flagged); the +7 bpm floor sits about
4–5 SD above his day-to-day spread (SD 1.3–1.7 bpm), and +5 eases; the HRV illness line fired
once in his history; a felt cold is easy riding with the neck check, a fever is no
training then two easy mornings; alcohol in his note is context, never a reason to
discount a low HRV night, which matches its dose-dependent suppression of overnight
vagal activity (Pietilä 2018, *JMIR Ment Health*, 4,098 people). Every floor outranks
every other signal, also on a rest day or holiday (`todays_call` reads the health
warning first).

**One decision for Craig, outside any finding:** whether a chest-or-heart report should
also reach him (an admin alert), which needs Mark's consent. Today it reaches only Mark
(*implemented*: no symptom path in `admin_alerts`).

---

## 3. Findings

**Counts: 0 High · 1 Med-High · 4 Medium · 5 Low.**

### HS332-01 · Med-High · A symptom felt on the bike has no route to any floor

*Evidence: `proved` + `implemented` + `observed`.*

- **The question is about today.** The check-in asks "Any symptoms today?"
  (`apps/web/src/lib/symptoms.ts`, `SYMPTOM_QUESTION`). Chest tightness on an interval
  that settled with rest, or a run of irregular beats on the climb, is honestly "None"
  the next morning.
- **The notes reader reads only morning check-ins.** `notes_reader.morning_check_ins`
  drops any entry tied to a workout or activity. Driven with a post-ride note "Heart
  racing and chest tight on the last interval": it is excluded and the day's effects read
  `no_notes` (*proved*, `probe_notes.out` case 4). A morning note with the same words
  sets the chest floor (case 1).
- **The post-ride reads and the coach have no symptom rule.** Neither the coach's system
  prompt (`brief_chat.SYSTEM_PROMPT`, whose floors are `coach_policy.FLOORS`: VO₂ on Red,
  power balance, clock times, etc.) nor `post_workout_analysis.py` names chest pain,
  palpitations, faintness, breathlessness, GP, 111 or 999 (*implemented*, grep). What
  either says is the model's own judgement, and nothing carries it to the next morning.
- **He writes where the gap is.** He filed 6 noted post-session entries on 7–8 Oct
  (43–128 characters each) and sent the coach 22 messages on 5 days since 25 Sep, 11 of
  them on 8 Oct (*observed*). No symptom has appeared anywhere since 1 Sep (*observed*,
  keyword scan of notes and chat).
- **Why it matters at 57.** Exertional chest discomfort that settles with rest is the
  classic presentation of coronary disease, and lifelong endurance athletes carry more of
  it, not less: men with over 2,000 MET-min a week had more coronary calcium (68%,
  adjusted OR 3.2) and plaque (Aengevaeren 2017, *Circulation*, 284 men aged 55 ± 7);
  male masters endurance athletes with a low risk profile had more plaques than sedentary
  men (44% vs 22%), 11% had calcium ≥ 300 and years of training was the only independent
  predictor (Merghani 2017, *Circulation*). Atrial fibrillation is commoner in endurance
  athletes (Andersen 2013, *EHJ*: HR 1.29 for ≥ 5 vs 1 Vasaloppet; Newman 2021, *BJSM*
  meta-analysis: OR 2.46). These are associations in cohorts, not his risk.
- **What Mark experiences.** If he tells the app after a ride that his heart raced or
  his chest felt tight, the post-ride read may or may not advise a doctor; the next
  morning is an ordinary day with VO₂ as planned.
- **Fix and cost.** (a) Reword the question to "Any symptoms since your last check-in,
  including on a ride?" — web copy only, signed-off wording; adds caution only
  (**before 21 Oct?**, Craig's call). (b) Add a `chest_or_heart_report` floor to
  `coach_policy.FLOORS` so the coach and every post-session read give the signed-off
  chest notice and ask him to tap "Chest or heart" in tomorrow's check-in; pinned by the
  existing drift test; prompt-version bumps (the close-out's regeneration rule applies;
  not checked here). About half a day. (c) Later: let the notes reader read noted post-session entries (about 0.8
  cents each) and raise 303's chest question the next morning. **Where:** (a) before
  21 Oct if Craig agrees; (b) and (c) a new row after G8.

### HS332-02 · Medium · The REM-intervention loop is three nights from calling a lever "supported" on a September-against-October contrast

*Evidence: `computed` (production rows) + `proved` (the real evaluator).*

- **The arms are different months.** For `room_cool_late_cycles` the applied nights are
  1–7 Sep (seven) and 8 Oct; the not-applied nights are 1, 5, 7 and 9 Oct, his holiday
  and the return, with REM 4.8–6.6% (*computed*, `coach.analyses` `experiment_update`
  rows, matching `manual_entries.rem_intervention_feedback_json`). Every applied night was
  also a `protect_last_cycle` night (the week's two levers are issued together).
- **The evaluator compares means with no time control.** `experiment_evaluation.
  evaluate_rem_interventions` requires 7 nights per arm and an interval that excludes
  zero (Batch 249's fix for HS240-07), and lists "weekly rotation" as a confound in its
  evidence, but does not check that the arms overlap in time.
- **Proved on the real function.** Today: inconclusive, "needs 3 more not-applied
  nights". Add three October-like not-applied nights (REM 5.5–6.5%): **supported**, "REM
  +4.4 percentage points (range +0.5 to +8.3)". Add three at his September median (~10%):
  inconclusive (`probe_experiment.py`).
- **It is likely.** In October he is heating the room, not cooling it (his 9 Oct note),
  so the next nights are likely to be "not applied" and October-level.
- **What Mark experiences.** The state-change coach posts into his thread: "REM
  intervention rotation now has enough evidence to read as supported. room_cool_late_
  cycles is directionally better…" (`state_change_coach._experiment_snapshot`). The
  difference is September against October, a holiday and a co-issued lever.
- **Fix and cost.** Refuse a supported or refuted reading unless the two arms' date
  ranges overlap (or the difference is adjusted for calendar time, as `driver_levers`
  does), and name the co-issued lever in the reasons. A few lines plus tests. **Where:**
  fold into G8 320 (whether advice helped, "labelled weak evidence"); Craig may want the
  overlap guard sooner, because it can fire within a week (it removes no caution).

### HS332-03 · Medium · Every morning tells him his REM is "below the healthy range", which the app's own audit says the watch cannot show

*Evidence: `observed` + `implemented`.*

- **What he read on 9 Oct** (*observed*, the stored brief): "REM: 4.8% is below the
  healthy range for your age band (15–23% for 50–59), and also below your own usual
  range… this isn't a one-off", then the measurement caveat ("probably understated by some
  unknown amount — … not a reason to wave off the low reading"), then "24 [of 28 nights]
  missed the healthy age-band range" and the cooling advice.
- **The prompt requires it.** `age_norms.REM_FRAMING_RULE` says "ALWAYS give the age
  band too, with its numbers" and "Never conclude 'no concern'"; the caveat is "not
  reassurance" (*implemented*).
- **The audit says otherwise.** Decision #322 (Batch 250) found the shape real and the
  first detected REM a median 239 minutes in, and concluded "the pattern may be reported
  and the magnitude may not". A comparison with a laboratory band is a magnitude
  comparison. 23 minutes of REM in a 455-minute night would be extraordinary if true.
- **Two loose phrases from the lever.** The same brief says bedroom minimum temperature
  "tracks REM more closely than anything else measured (r=0.26…)": the sign is dropped
  (it is −0.26) and two concurrent measures track it more closely (overnight stress −0.44,
  resting HR −0.31; *computed*), though neither is a lever.
- **What Mark experiences.** A daily statement that a body measure is below the healthy
  range, which he cannot change and the app cannot verify, driving a twelve-lever
  library. His own notes already doubt the stage data (5 Sep).
- **Fix and cost.** Lead with the pattern and his own baseline; replace the band verdict
  with "the watch undercounts early REM, so it can't be compared fairly with laboratory
  ranges"; keep the band as context only. Prompt change (morning and trends prompts share
  the constant). Separately, REM250-O2 is still open: one, signed-off, once-only line
  that persistent low REM with repeated overnight oxygen dips under 88% (15 of 108 nights,
  6 Oct review) is worth one GP conversation about sleep apnoea. **Where:** a decision for
  Craig (see section 6, #307/#322/#360), then fold into G8 318.

### HS332-04 · Medium · October pushes still tell him to cool towards 17 °C while he is heating the room (HS240-08 open)

*Evidence: `observed` + `computed` + `implemented`.*

- **Observed, 8 Oct:** three pushes — "Start pre-cooling toward 17C", "Above 19.5C risks
  thermal sleep disruption", "above the 20C disruption threshold" (`thermal_alert` rows;
  77 since 1 Sep). The 9 Oct brief repeats "pre-cool to 17°C". His notes on 7 and 9 Oct
  say the room felt colder than normal and now needs preheating.
- **Unchanged since wave #4:** `sleep_protocol` v1 still holds `preCoolTemperatureC: 17`
  and `thermalDisruptionThresholdC {19.5, 20.0}`; `fan_control.ON_THRESHOLD_C` 19.5; no
  lower bound anywhere (*implemented*).
- **His data now supports the direction, not the target.** On 107 nights, calendar-
  adjusted, warmer bedrooms go with more awake time (r +0.33, 95% CI +0.15 to +0.49) and
  lower overnight HRV (r −0.44) (*computed*, `probe_drivers_live.out`). That supports
  "not warm", not 17 °C or the word "disruption" at 19.5 °C.
- **Evidence.** WHO's Housing and Health Guidelines (2018) recommend at least 18 °C in
  cold seasons (a strong recommendation for the general population, on moderate
  evidence; read via the guideline's recommendation table summary, not the full text).
  He is 57 and healthy, so the risk is small; the message is incoherent.
- **Fix and cost.** An 18 °C floor under the pre-cool target and the fan; no pre-cool
  push when the room is already under 19 °C; call 19.5 °C "your comfort line", not a
  disruption threshold. Knowledge-base edit plus a small code change and signed-off
  words. **Where:** no G8 row covers it (HS240-08 was never placed); after G8, or fold
  into 320.

### HS332-05 · Medium · The morning after a chest report, a day with no hard session reads "Green light · Recovered"

*Evidence: `proved`.*

- Driven with an open chest follow-up (reported the day before, not yet answered) and a
  60-minute Zone 2 planned: "Green light. You're recovered. Today's session is on as
  written. Keep the easy riding easy." (`probe_floors.out`). With a hard session it is
  "Easy day", as 315 intended.
- This is by design (Decision #386, item 3: "the day is never made 'still recovering' for
  it"), and Home's follow-up card does ask him. But "You're recovered" and "Green light"
  sit beside a card about unexamined chest symptoms, and Plan No. 3's two loaded
  dumbbell sessions a week would also proceed unchanged.
- **Evidence.** The guidance 315 cites is that symptoms suggesting heart disease are
  assessed before exercise resumes (Pelliccia 2021, ESC sports cardiology; abstract only
  available to this pass). Easy riding is a reasonable middle; "recovered" is not a claim
  the engine can make about an unexamined symptom.
- **Fix and cost.** A neutral call while the follow-up is open ("Easy riding only until
  you've spoken to your GP or 111 — today's ride is already easy"), and loaded strength
  treated like hard work (mobility instead) until he answers "Gone, and I've spoken to my
  GP or 111". Caution-only, signed-off words; a few lines in `todays_call` and
  `verdict_grading`. **Where:** before 21 Oct only if Craig wants it (it has never
  happened); otherwise with 321.3's call lines. See section 6.

### HS332-06 · Low · An implausibly high HRV night reads as full recovery

*Evidence: `proved` + literature.*

- Driven with last night 85 ms against a usual 47 (SD 5.2; about +7 SD), resting HR
  normal: "Green light. You're recovered. Make it count." With RHR +4: "Green light — hold
  the targets", the HRV ignored (`probe_floors.out`). Nothing in the acute rail or the
  graded engine reads the high side (0928-MD-5, open).
- **Why it matters for him.** Ectopic beats and atrial fibrillation are physiological
  artefacts that inflate beat-to-beat variability (Peltola 2012, *Front Physiol*). AF is
  commoner in veteran endurance athletes (HS332-01's sources), and in endurance athletes
  with paroxysmal AF (mean age 57) episodes were not more frequent during or after
  exercise than at other times (Apelland 2026, *JAHA*, implantable monitors) — overnight
  episodes are plausible. Marine omega-3 modestly raised AF risk in cardiovascular trials
  (Gencer 2021, *Circulation*: HR 1.25; 1.12 at ≤ 1 g a day, 1.49 above); his fish oil
  is a point for his GP, not the app. Whether Garmin reports an overnight HRV at all
  during AF is unknown (Hypotheses).
- **His history would not trip a line.** His highest night is 60 ms (6 Oct review); a
  line at median + 3 SD (about 63 ms) has never been crossed.
- **Fix and cost.** A night above median + 3 SD counts as unusual, not recovery: neutral
  to the grade, left out of the 7-day mean, and Home asks the symptom question naming
  "a racing or irregular heartbeat". Caution-only; small. **Where:** after G8, beside
  311's HRV-normal work (311.2(e)).

### HS332-07 · Low · Respiration rate never speaks on its own; a prodrome-like pattern is "Make it count"

*Evidence: `proved` + literature.*

- Respiration counts only alongside two SpO₂ nadirs under 88% (`_oxygen_respiration_
  rail`). Driven with respiration 15 against his usual 11–12 for two nights, HRV 40
  against 47 and resting HR +3: "Green light. You're recovered. Make it count", no notice
  (`probe_floors.out`). 1001-MD-5 is still open (*implemented*).
- **Evidence is mixed.** Nightly respiratory rate rose before symptoms in COVID-19 (Miller
  2020, *PLoS One*, WHOOP: 20% flagged two days before onset, 80% by day 3), but a
  combined RHR, respiration and HRV alerting system had a positive predictive value of
  4–10%, with false alarms from hard exercise, poor sleep, stress and alcohol
  (Esmaeilpour 2024, *JMIR Form Res*). Garmin's respiration estimate had a 4.2 breaths a
  minute error against a ward monitor (Knevels 2026, preprint).
- **Fix.** A "watch" notice (no training change) when respiration is two or more above
  his usual for two nights alongside any autonomic concern: "your breathing rate has been
  up two nights; if you feel a cold coming, tell me in your check-in". **Where:** after
  G8, with 321.

### HS332-08 · Low · One low SpO₂ night is called "sustained", beside "Make it count"

*Evidence: `proved`.* A single night averaging 91% gives the `watch` notice ending
"Sustained low overnight oxygen has causes worth checking properly — a chest infection,
or disrupted breathing during sleep… Mention this to your GP if it happens again", while
the call reads "Green light. You're recovered… Make it count" (`probe_floors.out`).
Surveillance-only is right for a wrist oximeter (Garmin Venu: 2.96% mean error; 62% of
readings within ±3% of a hospital monitor, Knevels 2026, preprint). The word is wrong:
one night is not sustained. **Fix:** "A low reading like this is often the watch; if it
repeats…" (signed-off). **Where:** with 321.3.

### HS332-09 · Low · The drivers cache drops the calendar adjustment, so cached surfaces name no lever where live ones do

*Evidence: `proved` + `computed`.*

- `insights._drivers_packet` stores `coefficient`, `sampleCount` and `summary` but not
  `adjusted_coefficient`, `interval_low` or `interval_high`; `_drivers_report_from_packet`
  rebuilds them as `None`, and `driver_levers` refuses a lever without an interval. A
  passing lever on the live path is `None` after the round trip (`probe_cache.py`).
- **It is now real, not latent.** On 9 Oct the live path names a lever for all five
  flags (bedroom temperature; REM r −0.26, CI −0.43 to −0.07, n 107) (*computed*,
  read-only `railway run`). Wave #4's follow-through note "no lever currently passes" is
  out of date.
- **Who reads the cache:** `morning_analysis` (a regrade after the morning's drivers step
  has run) and `sleep_projection_context`. `cached_drivers`' docstring says "the fallback
  returns the identical report"; it no longer does. Fail-closed (fewer claims).
- **Fix.** Carry the three fields in the packet and bump the insights version so old rows
  are recomputed. An hour. **Where:** after G8 (R1's lens may also report it).

### HS332-10 · Low · A note the reader fails on is never read again once the brief is written

*Evidence: `implemented` + `observed`.* `grade_and_store` lets a stored morning stand
when its brief is written, so a note the reader failed on (a transient error) is retried
only while the brief is unwritten. A symptom only in that note sets no floor that day;
the only disclosure is a model-written sentence (`NOTES_READING_RULE`), because Home's
`NOTE_UNREAD_LINE` shows only while the brief is pending. Production has 5 readings, all
read, and every tapped answer since 30 Sep was None (*observed*). **Fix:** re-read a
failed note on the next trigger whatever the brief's state, or show the unread line on a
written morning. **Where:** after G8.

### The 8 Oct "Recovery day" — was it right?

*Evidence: `observed` (stored packet, `daily_metrics`, `sleep`).* **Yes, and it was
predicted.** The two clearly-off domains: his 7-day HRV 38.9 ms against a usual 46.0
(SD 5.2), 1.4 SD under, after his holiday dip (nights 36–40 ms from 2 to 7 Oct); and a
fair night (Garmin 69, 73 age-adjusted; 6.45 h against 7.5) that readiness (53, Garmin
"LOW" HRV status) confirmed as clearly off. Feel 7, no symptom, no note flag. Batch
310's holiday catch-up could not apply: the night of 7 Oct was 40 ms, under the
~43.5 ms line. The HRV-guided trials the engine cites prescribe low intensity or rest
whenever the rolling HRV is outside the smallest worthwhile change (Kiviniemi 2007;
Vesterinen 2016; Javaloyes 2019, which used 0.5 SD of baseline), so easing the sweet
spot was right by them; whether it was Red (recovery spin) or Amber (sweet spot at 76%)
was decided by readiness confirming the sleep domain, which is 311's (a)/(c) question
(DV-6) and the 6 Oct review's prediction P2. The best option offered was the swap
(sweet spot to Saturday); he rode 45 minutes at 178 W (64% FTP). "Still recovering"
describes the 7-day average truthfully; his single nights were already near normal (44
and 43 ms). Nothing medical was in play.

---

## 4. Follow-through

Every wave #4 finding in this lens, and every later health or statistics finding.
Status: fixed (observed/proved) · open · shipped differently · superseded · dropped ·
queued.

### Wave #4 (`BATCH_240_HEALTH_SCIENCE_REVIEW.md`)

| ID | Finding | Status | Evidence |
|---|---|---|---|
| HS240-01 | RHR 40 bpm above his ceiling gave Green | **Fixed (proved)** | +5 bpm Amber, +7 off the bike, +12 off the bike, independent of readiness (`probe_floors`) |
| HS240-02 | One-night HRV collapse invisible | **Fixed (proved)** | 32 ms against 47 → off the bike (2.5 SD / 30% line) |
| HS240-03 | SpO₂ and respiration never evaluated | **Shipped differently** | SpO₂ average < 92% or two nadirs < 88% with respiration up → a `watch` notice, no training change (proved); respiration never alone (HS332-07); 0 of 110 mornings triggered (observed) |
| HS240-04 | No medical boundary where Mark reads | **Fixed (implemented)** | `MEDICAL_BOUNDARY_STANDING_LINE` rendered by `AcutePhysiologyNotice`; symptom notices name GP, 111, 999 |
| HS240-05 | Chronic REM deficit probably artefact | **Shipped differently, partly unsound** | #322: pattern real, magnitude uncertain; the brief still gives the band verdict daily (HS332-03) |
| HS240-06 | Lever gate indefensible | **Fixed (computed)** | Calendar-adjusted, interval-gated; levers now pass live for every flag (bedroom temperature); the cache drops them (HS332-09) |
| HS240-07 | Experiment loop concludes from noise | **Shipped differently, confound open** | 7 nights per arm and an interval (implemented); arms in different months can still read "supported" (HS332-02, proved) |
| HS240-08 | Thermal thresholds at his median, below WHO minimum | **Open** | Unchanged; October pushes to cool towards 17 °C (HS332-04, observed) |
| HS240-09 | Exposure window is a clock window | **Open** | `bedroom_overnight.night_window` still 21:30–09:00 (implemented) |
| HS240-10 | REM levers mix A-grade and folk mechanisms | **Fixed (implemented)** | `evidence_grade` on all 12 levers: 4 A, 2 B, 3 C, 3 D |
| HS240-11 | `sleep_projection` names an ungated driver | **Fixed, now fails closed** | Gate applied; but it reads the cache, so it names no lever (HS332-09) |
| HS240-12 | Band classification one-sided | **Shipped differently** | Display bands two-sided (254); the graded engine still ignores a high HRV night (HS332-06) |
| HS240-13 | Outcome descriptors false for lower-is-better | **Fixed (claimed)** | Not re-driven this pass |
| HS240-14 | Ohayon denominator gap | **Shipped differently, sound** | Rescaling rejected as self-cancelling (#322); stated in `SLEEP_BAND_BASIS_NOTE` |
| HS240-15 | RHR and HRV rails self-recalibrate | **Queued (311), partly** | 311.2(e) covers the HRV normal only. The RHR rail's 84-day median still drifts: a rise of 6 bpm over 84 days makes 57 bpm read "+7 against 50", not +13 (proved) |
| HS240-16 | VO₂ target below VO₂max intensity | **Fixed (claimed)** | 252; R4's lens |
| HS240-17 | Age credit a flat +4 | **Superseded (claimed)** | Graded verdict's age-credit guard |
| HS240-18 | `workload_budget` not physiological | **Accepted** | Scope correction |
| HS240-19 | SpO₂ survived the model swap | **Accepted** | Correction |

### The REM premise (`BATCH_250_REM_PREMISE.md`)

| ID | Finding | Status | Evidence |
|---|---|---|---|
| REM250-1 | Pattern real, magnitude under-counted | **Fixed in the packet** | `REM_ARCHITECTURE_NOTE`; the brief states it (observed 9 Oct) |
| REM250-2 | Truncation rejected; protect-last-cycle confirmed | **Fixed** | `protect_last_cycle` graded A |
| REM250-3 | Rescaling self-cancelling | **Fixed (sound)** | As HS240-14 |
| REM250-4 | Six mechanism claims untrue | **Fixed (implemented)** | Grades and rewritten notes |
| REM250-O1 | Tell Mark the REM figure is uncertain? | **Decided in practice, never recorded** | The prompt now makes the brief say it every morning (observed); still listed as Craig's open call |
| REM250-O2 | No "mention to a GP once" differential | **Open** | No such copy in `apps/api/src` (implemented); see HS332-03 |
| REM250-O3 | External EEG validation | **Deferred** | Trigger not fired |

### Later reviews, health and statistics findings

| ID | Finding | Status | Evidence |
|---|---|---|---|
| R0922-1/2 | HRV Red on the acute rail; overnight reading primary | **Superseded** | 294–296: illness grade only; own baseline |
| R0922-4 | 275 comparator: fixed threshold, no variance | **Shipped differently** | Per-metric threshold, Welch interval; `GROUP_THRESHOLD` 3.0 remains for sleep (implemented) |
| 0928-MD-1 | Floors for harm, not performance | **Fixed (proved)** | Three symptom floors, illness-grade HRV, +7 RHR |
| 0928-MD-2 | HRV alarm on noise | **Fixed (proved)** | 38 ms (1.7 SD) alone: hold the targets, not off the bike |
| 0928-MD-3 | Two-mornings RHR rule on noise | **Fixed (implemented)** | Mild only; 305 corroboration at +4 |
| 0928-MD-4 | Symptoms the biggest gap | **Fixed for the morning; open for rides** | HS332-01 |
| 0928-MD-5 | A sudden HRV rise isn't always good | **Open (proved)** | HS332-06 |
| 0928-MD-6 | Stages the least reliable measure | **Open** | The brief still leads its sleep section with stage percentages (observed 9 Oct); 318 may reorder |
| 0928-AI-5 / 322 | A replay shows change, not benefit | **Queued (322)** | — |
| 1001-MD-1 | 999/111/GP depends on the model | **Fixed (implemented)** | `SymptomNotice` on the check-in; parity test passes in CI |
| 1001-MD-2 | No graded return after fever | **Fixed (proved), shorter than IOC** | Two easy mornings, then Green with VO₂ (proved); Craig's #375; see section 6 |
| 1001-MD-3 | Breathlessness missing | **Fixed (implemented)** | In the answer's detail and the reader's flag |
| 1001-MD-4 | Unclear chest mention only asks | **Fixed (implemented)** | `chest_question` eases a hard session until answered |
| 1001-MD-5 | Respiration never grades | **Open (proved)** | HS332-07 |
| 1001-MD-6 | Two-mornings RHR corroborates bike rest | **Fixed (proved)** | RHR +4 with HRV 38 → off the bike; two mornings above Q3 alone no longer does |
| 1001-SE-4 / 303.5 | A re-save clears a note's symptom | **Fixed (proved)** | A later re-save keeps the note's chest floor; only an explicit Home answer clears it (`probe_notes` cases 2–3). STATUS's "Still open after 302" line is stale |
| 1001-AI-5 | 275's "supported" rests on three recovery weeks | **Open** | Four light weeks now; not re-computed |
| 1001-AI-7 | Chat extractor never run | **Open** | Still waits for Mark's tap (STATUS) |
| NR0930-3, NR1002-1..3 | Reader false alarms; "woke gasping" | **Accepted** | Unchanged; 303's easing covers the ask-only path |
| DV-3 | The morning after a chest report is ordinary | **Fixed (proved)** | Hard session → easy spin until "Gone, and I've spoken to my GP or 111"; "Still there" → no training; "Gone, not seen" keeps it open. Wording gap on easy days (HS332-05) |
| DV-11 | Recovery advice generic, effect never measured | **Queued (320)** | 320 should carry HS332-02's overlap guard |
| DV-13 | A missing HRV or sleep score counts as normal | **Queued (321.2)** | Not re-probed |
| DV-14 | Three call lines say more than the engine knows | **Queued (321.3), reproduced** | Head cold → "Recovery day · Your body's still recovering"; data blackout → "Take the edge off · There's some fatigue about" (proved) |
| 6 Oct G.3 | Repeated SpO₂ dips; medication | **Medication answered; SpO₂ open** | Profile v3 records it (observed); dips folded into HS332-03's GP line |

---

## 5. G8 and parked rows re-verified (step 4)

| Row | Touches | Verdict |
|---|---|---|
| **311** | 8 Oct's Red; HRV normal | **Accurate for HRV, incomplete for HS240-15.** 8 Oct is exactly 311.1(a): readiness 53 confirming a fair night while Garmin's HRV status was "LOW". 311.2(e) leaves the judged week out of the HRV normal only; the RHR rail's 84-day median (`_rhr_rail`, `baselines["resting_heart_rate_bpm"]`) drifts the same way and is not named. Add it, or say why not. |
| **316** | Load ratio, recovery time | Not in this lens beyond 8 Oct (load domain clear that morning). |
| **317 / 318** | What Mark reads | Accurate. 318 is the natural home for HS332-03 (the REM paragraph) and 0928-MD-6 (stages lead). |
| **320** | Recovery advice and whether it helped | **Accurate but missing the comparison's confound.** 320.1's "all four experiments read inconclusive" is still true today (observed) but the REM rotation is three nights from "supported" on a calendar contrast (HS332-02). 320.3's "next-morning change, labelled weak evidence" needs the same overlap guard, or it repeats the defect. No mention of the thermal target (HS332-04). |
| **321** | Small fixes | **321.1's line reference has decayed:** the off-the-bike swap rule is at `morning_analysis.py:1335` (`_requires_bike_rest`), not `:1301`. 321.3 is accurate (both lines reproduced). |
| **322** | Record what he rode | Accurate; not re-probed. |
| **308** | The ladder goes | Rollback note still true: 305's 4 bpm corroboration lives in the shared acute rail. |
| Parked **276** | Contest suppression | Unchanged; a dispute still changes no floor (claimed by the 274 row; not driven). |

---

## 6. For reconsideration

1. **Decision #386 (315), item 3 — "the day is unchanged when no hard session is
   planned".** New evidence: on such a day the call reads "Green light · You're
   recovered", and Plan No. 3's loaded strength proceeds (HS332-05, proved). Proposed: a
   neutral call and strength eased too, until the follow-up is cleared. Caution-only.
2. **Decision #375 (303) — two easy mornings after a fever.** Morning three is "Green
   light" with VO₂ (proved). The IOC consensus on acute respiratory infection (Schwellnus
   2022, *BJSM*, abstract read; full text not reachable) sets out a graded return to
   sport, and the 1 Oct and 6 Oct reviews both called two mornings shorter than it. A
   third morning of "Z2 only, no VO₂" (hard work held, not cut) would sit closer. Craig
   chose two on 2 Oct; this is the evidence, not a re-argument.
3. **Decisions #307 / #322 / #360 — `REM_FRAMING_RULE` "ALWAYS give the age band…
   never conclude no concern".** #322's own finding (magnitude unreportable) contradicts
   a daily band verdict (HS332-03, observed). Proposed: pattern and personal baseline
   lead; the band becomes context with the measurement caveat first; "no concern" stays
   forbidden, "can't be judged" becomes allowed.

---

## 7. Hypotheses (unverified)

- **Whether Garmin reports an overnight HRV during atrial fibrillation at all**, or
  discards the night, is unknown; HS332-06's line only matters if it reports one.
- **His October REM drop** (about 10–14% in September to 5–7% from 1 Oct) coincides with
  the holiday, the HRV dip and the change of season; it is not evidence about any lever.
- **The 4 Oct monthly longitudinal finding** ("cooler bedroom bands show higher sleep
  scores", `evidenceStatus` supported, moderate) was produced by the model with training
  phase named as a confound but no calendar adjustment; the deterministic adjusted
  associations agree in direction (computed), so it is probably not wrong, but it is not
  gated like the levers.
- **Blood pressure he logs is read by no rule.** 40 readings since July average 106/66,
  maximum 111/71 (observed), so nothing would have fired; a surveillance line for a
  very high reading may be worth a sourced proposal.
- **Mark's own heart-rate monitor during rides** (chest strap or optical) could show
  exercise-time arrhythmia that the overnight wrist data cannot; not examined.

---

## 8. Limitations

- **No paid call.** The post-ride read's and the coach's actual response to a chest
  mention (HS332-01) were not observed; the finding rests on the prompts and the absence
  of any carry-forward, not on a model output.
- **Full texts not reachable** for the IOC 2022 consensus, the ESC 2020 guideline and
  WHO 2018 (403 or bot checks); their abstracts or recommendation summaries were read.
  Knevels 2026 is a preprint. PubMed was unreachable; abstracts came from Europe PMC.
- **Several wave #4 rows are carried as "claimed"** (HS240-13, -16, -17) and were not
  re-driven.
- **The crafted mornings** use a synthetic 84-night history shaped like his (RHR median
  44, SD 1.3; HRV median 47, SD 5.2; respiration 11–12), not his stored rows.
- **Sentry could not be read**; whether any health-related alert reaches Craig was
  established from code only.
- **Not examined:** post-ride statistics (interval grading, drift), the sleep projection's
  arithmetic beyond its lever source, 275's recovery-week comparison (1001-AI-5), and
  heat on indoor rides.

---

## 9. Probe log

| # | What | Size |
|---|---|---|
| 1 | SQL: 7–9 Oct morning packets — status, graded summary, domains, triggers, escalations, symptom | 3 rows |
| 2 | SQL: keys of 8 Oct `verdict` | 26 keys |
| 3 | SQL: 8 Oct reasons, actions, plan lines, notes reading, feel, readiness | 1 row |
| 4 | SQL: `daily_metrics` × `sleep`, 18 Sep–9 Oct (HRV, RHR, readiness, score, hours, respiration, SpO₂, REM %) | 43 rows |
| 5 | SQL: `information_schema.tables` (coach) | 32 rows |
| 6 | SQL: 21 Jun–9 Oct latest mornings — counts of triggered signals, symptom answers, easings, bike rest | 1 row |
| 7 | SQL: `manual_entries` since 27 Sep — symptoms, answered, feel, note length | 14 rows |
| 8 | SQL: `check_in_readings` by status and prompt | 2 rows |
| 9 | SQL: column lists for four tables | 56 rows |
| 10 | SQL: keyword scan of notes and user chat since 1 Sep (snippets only) | 19 rows |
| 11 | SQL: one 1 Sep note snippet | 1 row |
| 12 | SQL: profile keys, medication note; BP summary since July | 2 rows |
| 13 | SQL: analyses by type since 1 Sep | 24 rows |
| 14 | SQL: `experiment_update` keys; titles, actions and samples | 5 + 6 rows |
| 15 | SQL: the 4 Oct longitudinal observation | 1 row |
| 16 | SQL: `experiments` (title, status, criteria) | 4 rows |
| 17 | SQL: `rem_intervention_feedback_json` × sleep | 39 rows |
| 18 | SQL: REM-rotation observations naming `room_cool_late_cycles` | 13 rows |
| 19 | SQL: 9 Oct `driver_correlation` packet | 56 rows |
| 20 | SQL: `thermal_alert` texts since 25 Sep; KB thermal settings | 8 + 4 + 1 rows |
| 21 | SQL: 9 Oct brief, REM lines only | 1 row |
| 22 | `railway run` `probe_drivers_live.py`: `InsightsService.drivers` + `select_lever`, read-only, rolled back, 90 s watchdog; exit 0 | ~60 lines |
| 23 | Pure probes: `probe_floors` (28 mornings), `probe_notes` (4 cases), `probe_experiment` (3 cases), `probe_cache` (1) | local |
| 24 | `gh run view 37696581593 --log` (CI on `42a6a98`): 2,721 passed, 0 skipped; 294/301/302/303/315 files all pass | 4,200 lines |
| 25 | SQL: `pg_stat_activity` after the `railway run` — 0 idle in transaction of 11 | 1 row |
| 26 | SQL: user chat messages per day since 25 Sep | 5 rows |

Total production reads: well under 1 MB. Paid calls: none ($0.00).
