# Batch 361 — R6 Sports medicine and sleep science (wave #6)

Pass R6 of wave #6 · reviewed SHA `083e012` · Opus 5.5 · high · 1 Nov 2026 (started 11:05 GMT).
Role: a sports-medicine doctor working with a sleep scientist. Read-only; production read through
the Supabase MCP (SELECT only, projected and windowed). Data judged to 31 Oct; Garmin has refused
the app's login since 00:25 GMT on 1 Nov (R2's DS357-01), treated here as an input outage.

_Status: done, 1 Nov 2026._

## 1. Summary

**Grade: B** (= wave #5). The medical floors are A−: proportionate thresholds, plain non-alarming
words, a symptom anywhere can only add caution, and the day's notice survives a failed brief. What
holds the grade at B is what surrounds them: the bedroom alert (the app's most frequent message)
grades a normal room "critical" and still says cool to 17 °C; the brief keeps grading wrist-measured
REM against polysomnography age bands, with misquoted figures; and the follow-up after a symptom
depends on a stored brief, which an outage (like today's) removes.

1. **Correct and safe?** The floors fire at sound thresholds and beat every other signal (tests
   pass; code read). Gaps: a symptom tapped on a no-brief morning starts no follow-up, and a fever
   ends on the next morning's preselected "None" (HS361-02, proved); BP has no rule (HS361-06).
2. **Honest with Mark?** Not on sleep environment and stages: 20 °C called a "disruption threshold"
   when the literature puts 20–25 °C as best for his age (HS361-01); "below the healthy range for your
   age" for a REM figure the watch cannot measure, with bands the packet does not hold (HS361-03).
3. **Doing its job?** Tonight's advice and its evidence lines are good. 60 bedroom pushes in 25
   evenings, half graded critical, teach him to ignore pushes (HS361-01; R7).
4. **Would a failure be noticed?** A heart-rate spike on the bike is classed as "data talk" and the
   ride trace is never read (HS361-05); the chest report still alerts nobody (339.5 not built).
5. **Cheap to change?** Yes: every fix is caution-only or wording, half a day to a day each; the
   thermal fix removes a false alarm, not a medical caution.

**Counts:** 1 High, 1 Med-High, 3 Medium, 1 Low. **Paid spend: $0.** Not fast lane (no symptom other
than "None" has ever been stored; the 1 Nov check-in answered "None").

## 2. Findings (at most ten, Highs first)

### HS361-01 — High — The bedroom "critical" push tells a 57-year-old that 20 °C disrupts sleep, from an evening reading, and still tells him to cool towards 17 °C
- **Evidence: observed + implemented + primary sources.**
  - *Observed (7–31 Oct, `coach.analyses`, `sentCount` read per row):* **42 thermal pushes and 18
    evening sleep nudges were sent to his phone in 25 days** (`sentCount` 1 on every row). The bedroom alert
    was graded `critical` on **13 of 25 evenings**, the evening nudge `critical` ("Protect tonight") on
    **8**. The critical alert fired at **19:00–19:30 London on 11 of 13 evenings** (one 20:30, one
    22:15), from the first reading of the evening, hours before bed.
  - *Computed (sleep-window temperatures, `temperature_readings` between `sleep_start_utc` and
    `sleep_end_utc`):* on the 12 critical evenings with a measured night, the room **while he slept
    averaged 20 °C or more on 1 night** (27 Oct, 20.6 °C); it peaked at 20 °C or more on 4. Typical
    sleep-window mean 18.4–19.8 °C. The 20 °C "disruption threshold" is a property of his early
    evening, not of his night.
  - *Implemented:* the rule (`nudge_alerts.evaluate_thermal_alert`) grades any fresh reading at or
    above 20.0 °C `critical` ("above the 20C disruption threshold") and 19.5 °C `warning` ("risks
    thermal sleep disruption") whenever the evaluator runs; nothing restricts it to the hours he
    sleeps. The `pre_cool_17c` push ("Start pre-cooling toward 17C") was sent **8 times, the last on
    28 Oct**. The sleep projection's "warm room" line is the same 19.5 °C.
  - *Ledger (corrects the pack):* HS332-04 was **not built** — Decision #454 says it "is left for its
    own change", and no ledger row holds it. HS240-08 (thresholds arbitrary, below the WHO minimum)
    is open through two waves.
- **What the evidence says (abstracts read):**
  - Baniassadi et al., *Sci Total Environ* 2023;899:165623 (PMID 37474050), 50 community-dwelling
    older adults, ~11,000 nights: sleep was **most efficient and restful at 20–25 °C** night-time
    ambient; efficiency fell 5–10% from 25 to 30 °C. Mark's "disruption threshold" is the bottom of
    the best range for his age group.
  - WHO Housing and Health Guidelines 2018: at least **18 °C** in the cold season for health; the
    review behind it says older people and those with cardiorespiratory disease may need more (the
    1987 WHO guidance gave 20–21 °C for rooms used by older people). A target of 17 °C is below it.
  - Haskell et al., *Electroencephalogr Clin Neurophysiol* 1981;51:494–501, and the
    Okamoto-Mizuno & Mizuno review (*J Physiol Anthropol* 2012;31:14): heat disrupts sleep (more
    wake, less slow-wave and REM), but the laboratory effects sit at 29 °C and above for lightly
    covered sleepers; with bedding, cold is what disrupts at the low end. Obradovich et al. (*Sci
    Adv* 2017) concerns outdoor night-time anomalies, worst in summer and in older adults; it gives
    no indoor threshold. **No primary source supports 20 °C as a disruption threshold or a
    "critical" grade for an older sleeper with bedding.** Where evidence is weak: individual optimum
    varies (Baniassadi's own caveat), so a personal threshold learned from his own nights is
    defensible — a fixed 20 °C "critical" is not.
- **What Mark experiences:** about 2.4 bedroom pushes an evening, one in two graded critical, about a
  room that will be in the healthy range by the time he sleeps; on some evenings three in a row with
  falling grades (9 Oct: critical at 19:00, warning at 21:30, "seal it" at 21:45). Alert fatigue (R7)
  and a medically wrong direction: cooling an older man's bedroom towards 17 °C in a Scottish
  November.
- **Fix and cost:** (1) drop `critical` from the room alert; a warm room is advice, not an alarm
  (`info`, or `warning` only above about 24 °C in the sleep window, Baniassadi's upper bound);
  (2) evaluate it against the expected sleep window (from 21:30, the app's own night window), not
  19:00; (3) replace "toward 17C" with "keep it at or above 18 °C" (HS332-04's own fix); (4) at most
  one bedroom push an evening; (5) the evening nudge's "warm room" input moves with it. One small
  batch, Mark-facing words for Craig's sign-off; it removes no medical caution, so it is a
  "remove a false alarm" change, not a "remove caution" one. Half a day plus sign-off.
- **Why High:** it is the most frequent Mark-facing message the app sends (more than the briefs), it
  has been flagged twice (HS240-08, HS332-04) and not changed, and its advice points the wrong way
  for his age.

### HS361-02 — Med-High — A symptom reported on a morning with no stored brief starts no follow-up, and a fever ends the next morning on the preselected "None"
- **Evidence: proved + implemented + observed.**
  - *Implemented:* what follows a symptom (the chest-or-heart follow-up, Batch 315; the two easy days
    after a fever, Batch 303) is read **only from stored morning analyses**
    (`MorningAnalysisService._symptom_easing` and `_previous_morning_symptoms` query `analyses`, never
    the check-in rows). A morning is stored only when the paid brief succeeds and its inputs are
    ready (Decision #300's gate; R3's AI358-01).
  - *Proved (real functions, crafted rows):* a chest-or-heart tap on a day with no stored morning
    → the next morning's `chest_follow_up` returns **None**: no Home question, no eased hard session.
    The same for a fever: next morning `illness_return` returns **None**. With the stored morning, both
    work as designed.
  - *Proved:* fever reported Monday; Tuesday he taps the preselected "None" (or skips the check-in) →
    no floor, "the first of two easy days back: easy riding at most"; Thursday → nothing. "No training
    until the symptoms have gone" is enforced only on mornings he re-taps "Fever or aches"; there is no
    "is the fever gone?" question as there is for the chest.
  - *Observed:* such mornings are not rare — 1 Nov has no stored morning (Garmin), and the app has had
    Anthropic credit and cap outages before (memory incident). Mark's check-in on 1 Nov answered
    "None", so nobody is affected today. No symptom answer other than "None" has ever been stored
    (29 answers since 28 Sep).
  - *What does survive:* on the day itself, Home shows the floor's notice (999 / 111 / GP, no
    training) straight from his tap when the brief failed (Batch 301, implemented); the test
    "a day without a stored morning does not end the follow-up" covers a gap *after* a report, not a
    report *on* the gap day.
- **Clinical basis:** training during a febrile illness is the classic setting for viral myocarditis
  and the ESC 2020 sports-cardiology guideline (Pelliccia et al., *Eur Heart J* 2021) and the IOC 2022
  consensus on acute illness (Schwellnus et al., *Br J Sports Med* 2022) both ask for exercise to
  resume only after symptoms (fever above all) have resolved, then graded. Two calendar mornings from
  the report, ended by a default tap, is weaker than either.
- **Fix and cost:** (1) seed the follow-up and the fever return from the check-in's own symptom answer
  (and "Still there") when no stored morning carries it; (2) give fever the chest's one-tap question
  ("Gone for a day, no paracetamol?" / "Still there") and start the two easy days from his "gone"
  answer, not from the report date; (3) a Postgres test for each. Caution-only, about a day; the
  wording needs Craig's sign-off (the floors' words were signed off with no clinician check).

### HS361-03 — Medium — The brief still grades his wrist-measured sleep stages against age bands every few days, and quotes bands that are in neither the packet nor the literature
- **Evidence: observed + implemented.**
  - *Observed (`analyses.output_markdown`, pattern search, 7–31 Oct):* **10 of 25 briefs** put REM
    beside an age band ("for your age", "healthy range", "age band"), **including the v65 brief of
    30 Oct**: REM "sits within your own usual range… But it's still below the healthy range for your
    age band (15–23%)… REM has repeatedly landed below that age band". HS332-03 ("every brief says REM
    is below the healthy range") is claimed fixed by 318; 318 put his own pattern first but left the
    band claim in.
  - *Observed (figures):* the packet's `ageComparison.sleepRows` gives deep sleep a healthy band of
    **12–20%** and Garmin's target of 16–33%. The 27 Oct brief called deep sleep of 24.4% "**above the
    healthy range for your age (15–33%)**" — a band in neither source, and a value inside the band it
    quotes. The 31 Oct brief called 18.3% "healthy for your age (50–59 range **16–20%**)" — half
    Garmin's target, half the age band. The brief check (318) checks length and colour words, not
    figures (R3's AI358-03), so neither was caught.
- **Clinical basis:** the bands are polysomnography norms (Ohayon et al., *Sleep* 2004, meta-analysis
  of 65 studies). Consumer wrist devices including Garmin agree poorly with polysomnography on REM
  and deep sleep minutes night by night (Chinoy et al., *Sleep* 2021;44:zsaa291, which tested two
  Garmin models), and Decision #322 already says the watch cannot support a daily REM verdict. A
  nightly "below the healthy range for your age" is a population PSG claim made from a device that
  cannot measure it, repeated often enough to worry him (HS240-05 and REM250-O1/O2 remain open).
- **Fix and cost:** (1) drop the age-band comparison of stage percentages from the daily brief; keep
  his own usual range, and keep the bands for the weekly read with one sentence on what a watch can
  and cannot see; (2) until then, add every band figure the brief quotes to the deterministic check
  (a figure must equal a packet figure). Prompt change, morning v66, a replay and Craig's sign-off;
  about half a day. Decision #322 is the basis; nothing to re-argue.

### HS361-04 — Medium — R3's symptom-word list for the memory filter is the wrong shape: it misses most clinical red flags and blocks ordinary heart-rate facts (answers R3's AI358-04)
- **Evidence: proved** (the real `statement_is_durable`, 25 crafted statements; R3's six words as a
  regex beside it).
  - **18 health-dismissing "facts"**, crafted as if a reader had extracted them from his words (none
    is his; synthesis edit for the public repo) (chest tightness "always
    his asthma", fluttering on climbs "normal for him", skipped beats "harmless", left-arm or jaw ache
    on efforts put down to an old injury or clenching, light-headed after rides "fine", a blackout put
    down to dehydration, breathless on the stairs "fitness dropping", HR jumping to 190 on easy rides
    "a strap glitch", AF "managed", BP over 160 "white-coat", a beta-blocker, low overnight oxygen "just
    the watch", a raised resting HR "can be ignored", wheeze, stomach pain on hard rides): **today's
    filter passes 18 of 18; R3's list would block 4.**
  - **7 ordinary statements** (a chest-strap HR monitor, HR drift in a warm room, Zone 2 at about 120,
    breathless on VO₂ intervals): **R3's list would block 6**, because "heart" and "chest" are everyday
    training words for a cyclist.
  - A broader medical vocabulary combined with a dismissal cue ("always", "just", "normal for",
    "harmless", "can be ignored", "glitch", "the watch", "put down to") blocked 15 of 18 and 1 of 7 in
    the same probe — better, still leaky (missed: the blackout, "never goes to his chest", stomach pain).
- **Is the list clinically right and complete?** No. The red flags for an endurance athlete in his
  late fifties (ESC 2020 sports cardiology; the AHA/ACC pre-participation warning signs) are: chest
  pain, pressure or tightness; pain spreading to the arm, jaw, neck or back on effort; palpitations,
  racing, fluttering, pounding or skipped beats, or a heart rate out of keeping with the effort;
  faintness, light-headedness or **any blackout or collapse**, above all during or just after
  exercise; breathlessness out of keeping with the effort or at rest, or wheeze; unusual fatigue on
  effort; and, for this app, raised blood pressure, low oxygen readings, a raised resting heart rate,
  atrial fibrillation and any heart medicine. R3's six words cover about a third of these, and a
  word list cannot tell "his HR monitor" from "his heart flutters".
- **Recommended shape:** a coaching memory is never the place for a health attribution. Any candidate
  that names a symptom, diagnosis, medicine or medical reading from the list above is not stored as a
  memory at all (no dismissal cue needed); it is routed to Craig as a profile question, the way the
  medication fact was set (Batch 315.6). Keep plain "heart rate"/"HR" out of the trigger so training
  facts still pass. Tests: the 25 statements above. About two hours (as R3 sized it), plus the
  Craig-routing, which reuses the existing proposal queue.

### HS361-05 — Medium — A heart-rate spike on the bike is ruled out by design: the note reader treats any figure as "data talk", and nothing reads the ride's own trace
- **Evidence: observed + implemented.**
  - *Observed (24 Sep indoor ride, `activity_timeseries`, aggregate and a 90-second window):* at
    30 minutes, steady at 136 bpm and 250 W, his heart rate read **186 → 197 → 191 → 181 within
    about 9 seconds with no change in power or cadence**, was back at 136 about 25 seconds later, and
    **he stopped pedalling at the same moment** (power 0 from 15 seconds after onset). It is the only
    ride since March over 163 bpm. His note blamed the strap; the stored post-ride read (v18, before
    Batch 339) called the 197 "very likely a sensor artifact, not a real physiological spike" and asked
    him nothing.
  - *Implemented:* the note reader's prompt (v2, which since 339 also reads ride notes) says "Numbers
    are not symptoms. Heart rate, resting HR, HRV, zones, Garmin, Zwift or any figure is data talk:
    absent for chest_heart"; a note like "HR shot to 190 on an easy spin" is therefore classed absent.
    The post-ride chest rule triggers only on felt symptoms. Nothing in the code looks at the ride's
    heart-rate trace for an abrupt step, a rate above his known maximum, or a rate out of keeping with
    the power.
- **Clinical reading:** most such spikes are a dry or slipping strap, and this one probably was. But
  abrupt onset and offset at a steady effort is also the pattern of a re-entrant tachycardia, and
  lifelong endurance athletes carry about 2.5 times the risk of atrial fibrillation (Newman et al.,
  *Br J Sports Med* 2021;55:1233, meta-analysis of 13 studies). The sports-medicine question is "did
  you feel anything, and did you stop because of the number or because of how you felt?" — asked
  once, neutrally. The app's own symptom rule forbids explaining a possible heart symptom away with
  the numbers; the post-ride read did exactly that, from the numbers, before 339 existed, and nothing
  added since would ask today.
- **Fix and cost:** a deterministic ride check (a jump of 30 bpm or more within about 5 seconds with
  no rise in power, or a rate above his recorded maximum plus 10) that adds one neutral question to the
  next check-in, with "Chest or heart" among its answers; and in the reader, "a heart rate he says
  jumped, raced or would not come down" is `unclear`, not absent. Caution-only; about a day including
  tests; Craig signs off one line of wording. Not alarming if worded as a question.

### HS361-06 — Low — Blood pressure and medication have no rule: a dangerous reading would reach only the model's judgement, and "takes nothing for his heart" is never re-asked
- **Evidence: observed + implemented.**
  - *Observed:* 49 of his check-ins since 1 Jul carry a blood pressure; the highest is 111/71 (normal
    for his age). Nothing is wrong today.
  - *Implemented:* `bp_systolic`/`bp_diastolic` travel to the morning read and the chat as data
    (`coach_sections`); no rail, floor or prompt rule reads them. A reading of 185/115, or 85/50 with
    "dizzy" in his note, would be judged by the model alone. The profile's medication fact
    (described, not quoted, in the public copy; `asOf` 6 Oct) is seeded once and nothing asks
    again; a beta-blocker started later would leave
    every HR zone, the resting-HR rail and the HRV floor reading against the wrong normal.
- **Clinical basis:** the ESC 2020 sports-cardiology guideline asks that high-intensity exercise wait
  until uncontrolled hypertension is treated; very high resting pressures (around 180/110 and above)
  warrant a same-day medical view, and a low reading with faintness is a chest-or-heart symptom by the
  app's own definition.
- **Fix and cost:** (1) one deterministic BP line: a reading at or above 180 systolic or 110
  diastolic sets the chest-or-heart notice's "speak to your GP or 111 today" and no hard session; a
  reading at or above 160/100 adds a one-line "worth mentioning to your GP" with no training change;
  (2) a quarterly one-tap "Any new medicines?" on Home that, on "yes", passes to Craig. Half a day;
  Craig signs off the wording.

### Near-optimal (checked, no finding)
- **The floors themselves.** Chest-or-heart and fever floors (no training of any kind), head cold
  (easy riding), the illness-grade HRV drop (the higher of 2.5 SD or 30% under his 84-night median,
  morning-phase rows only), resting HR +7 bpm off the bike with a conditional GP line, SpO₂ as
  surveillance with "if it repeats", respiration only beside a heart reading that is off, and a night
  of implausibly high HRV treated as the watch or his rhythm, not recovery (Peltola 2012 on ectopy and
  AF inflating HRV). Thresholds are proportionate and their wording does not alarm. The 107 floor tests
  in the five symptom suites pass locally (14 Postgres tests skip here; R1 ran the full suite with
  0 skips). A symptom in a note or a ride note can only add caution; "None" is never read as well.
- **Survives a failed paid call, on the day:** the floor's notice (999 / 111 / GP) shows on Home from
  his tap when the brief fails (Batch 301). Only the next-day chain does not (HS361-02).
- **Tonight's advice (320):** each line carries a plain evidence line ("standard sleep advice; the app
  hasn't measured it for you yet", 31 Oct, observed). Graded REM levers (A–D, Batch 250) unchanged.
- **The chat's symptom rule (v29/v30)** forbids easing, diagnosing or explaining a symptom away, and
  R3's paid probe saw it hold on a chest ask.

## 3. Follow-through corrections (rows of the pack's table in this lens)

| Row | Pack says | Corrected to | Evidence |
|---|---|---|---|
| HS332-04 | shipped differently; 18 °C floor claimed | **open, not built**: Decision #454 "left for its own change"; no ledger row holds it; "toward 17C" pushed 8 times to 28 Oct | implemented + observed |
| HS332-03 | fixed (318), claimed | **open in what Mark reads**: REM against the age band in 10 of 25 briefs 7–31 Oct, incl. v65 on 30 Oct; band figures misquoted (HS361-03) | observed |
| HS240-08 | open | open; now with primary sources against the threshold and the grade (HS361-01) | observed + sources |
| HS332-01 | fixed (334.8, 339); 339.5 not built | fixed for a stored morning; **not on a morning with no stored brief** (HS361-02); 339.5 still not built | proved |
| HS332-05 | fixed (339.3), claimed | fixed (tests pass), with HS361-02's gap | implemented + proved |
| HS332-06 / -07 / -08 | fixed (339.4), claimed | **fixed (implemented)**: high-HRV watch notice; respiration needs a heart reading off; one low SpO₂ night says "if it repeats" | implemented |
| HS240-12 / 0928-MD-5 | open (sudden HRV rise not treated) | **fixed by 339.4** (implausibly high = watch notice, kept out of the 7-day reading) | implemented |
| 1001-MD-5 | open (respiration never grades alone) | **accepted by design**: speaks only beside a heart reading that is off (Esmaeilpour 2024 false alarms); sound | implemented |
| REM250-O1 / O2 | open | open: no "mention low REM to a GP once" copy; the band claim it would replace is still made (HS361-03) | observed |
| AI329-07 (R3's lead AI358-04) | partly | the proposed word list is the wrong shape (HS361-04) | proved |

## 4. Queued and parked items in this lens, re-verified

| Item | Verdict |
|---|---|
| 339.5 (alert Craig on a chest/heart report) | Not built; needs Mark's consent. Still the right item: no symptom other than "None" has ever been stored, so the first one will be the one that matters. Pair it with HS361-02's seeding so an outage-day report also reaches Craig |
| HS332-04 / HS240-08 (thermal) | **Homeless**: no row. Make HS361-01 its row |
| 337 (deferred alerting) | Out of lens; note that a Garmin outage now also suspends the symptom follow-up chain (HS361-02), one more reason AI358-02's `inputs` alert matters |
| Decision #322 (watch cannot support a daily REM verdict) | Sound and settled; the briefs drift from it (HS361-03), which is a prompt fix, not a re-argument |

## 5. For reconsideration · Hypotheses · Limitations · Probe log

**For reconsideration.**
- **Decision #300 (no authoritative no-data brief)** — not re-argued for the paid read. New evidence
  in this lens: the symptom chains hang off the stored morning, so #300 also suspends the medical
  follow-up on outage days (HS361-02). R3's code-only "insufficient data" call would fix both, provided
  it carries the acute rail's symptom record; otherwise seed the chains from the check-in rows.
- **Decision #454's deferral of HS332-04** — the deferral reason ("it moves the thermal targets, a rule
  the morning reads") stands, but the alerts and the 17 °C push do not feed the call; the push wording
  and the grade can change without touching the morning's rule.

**Hypotheses (not verified).**
- A note naming a heart-rate figure with a felt symptom ("heart racing, HR 180") may still be read
  `present` by the model despite the "numbers are data talk" rule; not tested (would be a paid call).
- Garmin may suppress or blank overnight HRV during sustained AF, in which case the implausibly-high
  notice would never fire for the case it was written for; Garmin does not document this.
- The early-October nights at 20–21 °C with 49–79 awake minutes are mostly holiday nights in an empty
  bedroom (STATUS, 21 Oct), so they say nothing about his sleep at that temperature; a personal
  temperature–wake relation at home needs R8's confound handling.

**Limitations.** Garmin down since 00:25 GMT 1 Nov: no night of 31 Oct–1 Nov, no 1 Nov brief. No paid
call made (none needed; the note-reader hypothesis above stays untested). Full texts of Haskell 1981,
Chinoy 2021 and Baniassadi 2023 not read, abstracts and indexed summaries only; the ESC 2020 and IOC
2022 statements are cited from their recommendations, not re-read in full this pass. Web app not
driven (R7). Sentry not read.

**Probe log** (1 Nov, between about 11:05 and 11:15 GMT by `date`; all read-only; Supabase MCP SELECTs on schema `coach`, projected, windowed; local
probes with the main checkout's venv against the worktree's code; no transaction left open — MCP
statements are single autocommit SELECTs).
- `analyses` thermal_alert 7–31 Oct: date, grade, time, `temperatureC`, `rule` (two passes; the
  first mis-converted a naive UTC column, corrected).
- sleep-window temperatures 20 Sep–31 Oct: `sleep` start/end joined to `temperature_readings`
  (aggregates only) with sleep stage minutes.
- evening_nudge critical rows (title, first 140 characters of the app's own push body).
- `sentCount` per rule, thermal and evening nudge; `fan_state_readings` per day (autopilot off).
- `manual_entries` symptom answers since 28 Sep (counts only); morning acute rail per day since
  15 Aug (answer, triggered, status, signals; no text).
- briefs 7–31 Oct: pattern flags only; three 380-character windows of the app's brief text
  around "healthy range"; `ageComparison.sleepRows` bands for 27 and 31 Oct.
- `manual_entries` blood pressure aggregate (count, max); `activities` max-HR distribution
  since Jun; the 24 Sep ride's timeseries aggregate and a 90-second window (HR, power, cadence); the
  post-ride read's 700-character window around its HR flag.
- Local: `probes/memfilter.py` (25 statements through `statement_is_durable`, plus two regex
  shapes); `probes/floors.py` (`illness_return`, `morning_easing`, `symptom_signal`,
  `chest_follow_up` on crafted rows); pytest on the five symptom suites (107 passed, 14 skipped).
- Paid calls: **none ($0).**

**Cross-lens leads for the synthesis (not chased).**
- **R7:** 60 bedroom pushes in 25 evenings (42 thermal, 18 nudges), up to three a night with falling
  grades; judge the push budget as a whole.
- **R8:** whether his own nights show any temperature–wake relation at home once away nights,
  load and season are handled (HS361-01's personal threshold); the REM band statistics (HS361-03).
- **R4:** if Garmin is still down on Tue 3 Nov (VO₂), R3's AI358-01 and HS361-02 meet: no call, and a
  symptom tapped that morning would start no follow-up.
- **R3 / synthesis:** the brief check verifies no figures, so misquoted bands pass (HS361-03).
