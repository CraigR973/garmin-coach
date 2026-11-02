# Batch 363 — Statistics and measured effects (wave #6, pass R8)

**Status: done 1 Nov 18:13 GMT** (main part 16:20; weekly review section added 18:10–18:13 after the v14 review stored at 18:00:57).
Reviewed SHA `083e012` (production `caae3c4`, STATUS-only drift). Lens: `domain/statistics-measured-effects.md`
(first run). Opus 5.5 · high. Started 1 Nov 15:59 GMT. Paid calls: none.

## 1. Summary

**Grade: B− (settled after the weekly review; first run of this lens).** The machinery Batch 249 built (calendar adjustment, intervals,
minimum n, "observational, not causal", human-gated conclusions) is sound, and the daily colour is protected by
multi-domain and persistence rules. What fails a noise test is three things Mark reads: the warm-room lever that
backs the bedroom pushes, the REM "missed its age norm" card, tonight's first "ready for a little more" note,
and the weekly review's sleep "trend", which is a coin toss on any week (ST363-09).

Counts: **0 High · 1 Med-High · 7 Medium · 1 Low.**

| Question | Answer in this lens |
|---|---|
| 1. Correct and safe? | The call's lines are the literature's; the claims around it over-read (ST363-01, -02, -06). |
| 2. Honest with Mark? | Partly: "stays on one side of no effect" is a best-of-40 interval; "repeatedly missed its age norm" is true in about 9 of 10 four-week windows by construction. |
| 3. Doing its job? | The experiments correctly say "can't tell"; the progress signal cannot tell anything under ERG. |
| 4. Would failure be noticed? | No: experiment reads are recomputed and not stored, so a passing "supported" leaves no trace (ST363-04). |
| 5. Cheap to change? | Yes: each fix is a gate, a window or a word in pure functions with tests. |

**Smallest path:** (1) a multiplicity allowance and a season window on any lever Mark is shown, with HS361-01;
(2) the REM card against his own distribution; (3) 319's note on key sessions and a measure ERG cannot hold (with
CI359-02); (4) evaluate experiments at fixed points and store changes; (5) "worthwhile" not "real" in the line
reasons; (6) plain words for the readiness medians; (7) a noise floor on the review's sleep trend (ST363-09).

**Weekly review (v14, 1 Nov 18:00):** stored and re-derived (section 11). The progress note fired as ST363-02
predicted; fitness drift and tonight's advice are stated honestly; the sleep "trend" is noise (new ST363-09);
the warm-room recommendation repeats ST363-01; "median" appears twice against the review's own rule.

## 2. Findings

### ST363-01 — Med-High · The warm-room evidence Mark is shown ("102 nights… stays on one side of no effect") is the best of ~40 uncorrected scans, rests on the summer, and shows no link in the season the alerts fire
- **Evidence: observed + computed + implemented.**
- *Observed:* the 31 Oct evening push (`sentCount` 1) carried "Nights with 60+ min above 19.5C average 5.7 points
  lower sleep score (47 such nights vs 55 without)" and "Measured over 102 nights: the link is 0.24 … stays on one side of
  no effect"; the morning packet carries the same kind of lever line on **36 of 66 mornings since 1 Sep** (on 1 Nov:
  bedroom mean temperature, calendar-adjusted −0.21, interval −0.39 to **−0.01**).
- *Implemented:* `compute_drivers` scans 14 drivers against 4 outcomes; `select_levers` then names the strongest
  actionable one whose own 95% interval excludes zero. No correction for picking one of many (the lever gate and
  the experiment evaluator both read the per-driver interval), and the interval assumes independent nights.
- *Computed* (`probe_thermal_stats.py`, the app's own `pearson`/`partial_pearson`/`correlation_interval`, 112 home
  nights 25 Jun–1 Nov, holidays left out, sleep-window mean temperature):
  - all nights: sleep score −0.23 calendar-adjusted (−0.40 to −0.04); with a Bonferroni allowance for 40 scans the
    interval is **−0.48 to +0.06** — it no longer excludes zero. Awake minutes: +0.12 (−0.07 to +0.30), no link.
  - dropping the one 26 Jun heatwave night (26.6 °C) moves score to −0.19 (−0.36 to 0.00).
  - **Sep–Nov, the alert season (48 nights, 17.6–20.6 °C): score −0.14 (−0.41 to +0.15), awake −0.02 (−0.31 to
    +0.27), REM −0.21 (−0.47 to +0.08). No detectable link in the temperature range he now sleeps in.**
  - the sleep-window mean reached 20 °C on **1 of 48** autumn nights; the reading 2–4 h before sleep reached 20 °C on
    10 autumn evenings and the night followed on **0** of them; **12 of 48** autumn evenings sit within 0.5 °C of
    20.0, so the evening grade is decided by sensor noise as often as by the room.
  - the "5.7 points lower" split is the raw (unadjusted) difference; on the 20 °C line itself (sleep-window mean)
    nights at or above it average 4.5 points lower (−10.6 to +1.6) and 7 min more awake (−3 to +18), 14 v 98 nights.
- **Statistician's reading:** the push presents a summer, between-season contrast as a present-tense lever. It is
  the strongest of many scans, its interval sits 0.01–0.05 from zero (so whether Mark sees it at all flips with a
  night or two of data), and within the current season it is indistinguishable from nothing. This is the
  statistical half of R6's HS361-01 (the physiology half is theirs).
- **Smallest fix:** (1) state the lever only when it survives a multiplicity allowance (Bonferroni or Holm over the
  drivers actually scanned) and an effective-n interval; (2) compute it within a rolling season window (e.g. the last
  60 home nights) as well as calendar-adjusted, and say nothing when the two disagree; (3) quote the adjusted
  difference, not the raw split. Caution-neutral (it changes words, not the call); with HS361-01's threshold change.

### ST363-02 — Medium · "Ready to progress" reduces to "three Greens in a row": ERG makes the on-target half automatic, and on shuffled history the note fires as often as it did for real — tonight's first firing included
- **Evidence: computed + proved + observed.** Builds on R4's CI359-02 (session mix); this is the statistics.
- *Observed:* hard work since Plan No. 3 (11–31 Oct): **55 of 55 work intervals on target, 8 of 8 sessions ≥ 90%**
  (Jul–Sep: 133 of 178, 13 of 26 sessions). Mark's 1 Nov morning landed Green (late, 12:05, after the outage).
- *Proved* (`probe_progress_stats.py`, the real `hard_work_on_target`/`progress_signal`, 34 hard sessions and 133
  graded mornings): as of 1 Nov the note is **due tonight** — 27, 29 and 31 Oct, each 100% on target, each followed
  by Green. Of the 14 Sundays 2 Aug–1 Nov it fires on **1** (1 Nov). Forcing every interval on target changes nothing
  (still 1); leaving out the Z2+sprint rides gives 0. On **5,000 shuffles of the morning colours** (which destroy any
  link between a session and the morning after) the note fires on 0.72 of 14 Sundays on average (circular shifts
  that keep runs: 0.77); **P(≥ 1 firing by chance) = 0.53–0.57.**
  - the morning after a hard session was Green 15 of 34 times (44%) against 75 of 133 overall (56%).
- **Reading:** under ERG the on-target test carries no information (it cannot fail when the trainer holds the
  watts), so the note is a run of three Greens, which his own colour base rate produces about once a quarter with
  no change in fitness. A Green is also a cautious-engine output, not a fitness measure. The text "you look ready
  for a little more" over-reads that. Nothing is applied (Decision #459: provisional; changes nothing), so the risk is
  a nudge to test or step up, not a load change.
- **Smallest fix:** as R4 says, count key sessions only; and make the measure one ERG cannot fix — e.g. heart rate or
  RPE at the same key-session power falling versus his last block (the fitness-drift half below has the same
  noise problem, so it needs a longer window), plus wording that says "your recent sessions have gone well" rather
  than "ready". Removes no caution.

### ST363-03 — Medium · The fitness-drift verdict (heart rate at fixed power, ±3 bpm, 3 rides a side) flags a change on about one judged Sunday in seven from noise alone
- **Evidence: computed + proved.**
- *Proved* (`probe_drift_stats.py`, the real `fixed_power_check` + `fitness_drift`, 39 of 40 Z2 ERG blocks since
  20 Jun pass the check): weekly verdicts 30 Aug–1 Nov were "steady" on 9 Sundays and "slipping" on 13 Sep (+3.9 bpm).
- *Computed:* heart rate at his Z2 power has SD **3.56 bpm** ride to ride (it barely moves with power across
  175–192 W: 0.05 bpm per W), so a 3-v-3 comparison has a standard error of 2.9 bpm and the 3 bpm line is ~1 SE.
  With heart rates shuffled across rides (no change in fitness), **13.8% of judged Sundays** say improving or
  slipping; the real rate (1 of 10) is what noise predicts. Overlapping 28-day windows re-looked weekly make a
  run of "changes" more likely still.
- **Smallest fix:** require ≥ 6 rides a side or a line of ~2 × the ride-to-ride SD (≈ 7 bpm), or report the
  difference with its interval and say "steady" unless it excludes zero; note room temperature and FTP resets
  (Z2 power moved 187 → 178 W after the 20 Oct test) beside it. The weekly review is the only reader today.

### ST363-04 — Medium · Every experiment is re-judged on every read with no allowance for repeated looks: a REM lever with no effect gets a direction on some morning in about a quarter of seasons
- **Evidence: proved + observed + implemented.**
- *Implemented:* the evaluators are "deterministic and recomputed on every read" (v2); the REM evaluator calls a
  direction when either outcome (REM % or awake minutes) crosses its threshold and its 95% interval excludes zero,
  for whichever lever has the most nights; the morning packet re-reads it daily (`experimentLoop`). 326
  `experiment_update` rows since 23 Jun; only 21 stored evaluations (all v1, 6–12 Aug) — so what each morning said
  is not kept, and a direction that appears for a day and goes cannot be audited afterwards.
- *Proved* (`probe_rem_looks.py`, the real `evaluate_rem_interventions` on simulated nights with no effect, his own
  dispersions: REM % SD 4.8, awake SD 17 min, interleaved arms so the 21-day calendar guard passes): judged once at
  the end, a direction appears in **0.6%** (120 nights) to **3.3%** (60 nights) of seasons; **looked at daily, in
  27.5% (120 nights) and 24.0% (60 nights) of seasons it says "supported" or "refuted" on at least one morning.**
- *Observed (1 Nov):* all four are `inconclusive` — correctly worded ("this window cannot tell these apart"; "an
  observational comparison … not a causal result"). Four of the REM library's levers have **0 not-applied nights**
  (applied every night), so they can never be compared; HS332-02's calendar guard is in place and passes today
  (`calendarApart` false; room-cool arms 18 v 16 nights).
- **Reading:** the wording and the human-gated conclusion (no auto-conclude) are near-optimal; the gap is the
  decision rule's error rate under daily re-looks, and that a surfaced "supported" leaves no stored trace.
- **Smallest fix:** judge each experiment at a pre-set point (e.g. when both arms reach a fixed n, or monthly) or use
  an always-valid / alpha-spending bound (Pocock-style ≈ 2.4 SD instead of 1.96 for ~10 looks); store an
  evaluation row whenever the recommendation changes; drop levers with no comparison arm from the "closest to a
  result" line. Caution-neutral.

### ST363-05 — Medium · "Sleep stress" is treated as a candidate cause of his waking and the "strongest mover" of HRV and sleep score, but it is computed from the same overnight heart signal
- **Evidence: observed + implemented.**
- *Observed (1 Nov packet):* the 04:00-waking experiment reads "Strongest measured driver is sleep_stress_avg
  (r=+0.38, range +0.21 to +0.52) — a real but weak association"; the driver audit's summary names sleep stress
  the strongest mover of recovery HRV (r −0.69) and sleep score (r −0.59).
- *Implemented:* `EARLY_WAKING_DRIVERS` includes `sleep_stress_avg`, while `driver_levers.CONCURRENT_DRIVERS`
  already rules it out as a lever ("a measurement taken with or after the night"). Garmin derives sleep stress
  from overnight HRV and heart rate, and wake periods raise it; the association is partly the same measurement
  seen twice.
- **Risk:** the experiment's `supported` line is r ≥ 0.5 with an interval excluding zero; the awake-minutes link sits
  at 0.38 (upper 0.52). A drift of the window could make the app recommend "an identifiable trigger" that is a
  by-product of the outcome. Human-gated, so not a call change.
- **Smallest fix:** use the same partition the lever gate uses (`CONCURRENT_DRIVERS` out of every evaluator's
  candidate list); report concurrent measures as "moves with" rather than "driver". Small.

### ST363-06 — Medium · Several lines in the daily call are stated as "real, not noise" when they sit inside the measure's own typical error; one fired 0.1 ms inside its line
- **Evidence: computed + implemented.** (`probe_threshold_sensitivity.py`, the lines read from the real
  `verdict_grading.THRESHOLDS`; 93 mornings 1 Aug–1 Nov; usual = mean of the 84 nights before, as 317.)
- **HRV mild (7-day mean below usual − 0.5 SD):** the line's own reason says such a mean "is a real shift, not
  noise". The 0.5 SD is the smallest *worthwhile* change (Plews 2013; Javaloyes 2019), not the smallest
  *detectable* one: with his nightly SD ≈ 5 ms a 7-night mean has an error of ≈ 1.9 ms, so the line (≈ 2.5 ms) is
  ~1.3 SE. **35% of mornings sit within one SE of it; noise alone would put about 13% of mornings on the other
  side.** The colour is protected (one mild domain is not a colour; persistence and agreement rules exist), so the
  practical risk is wording, but the morning reads "his HRV is down" from a coin-flip on those days.
- **HRV marked (1.0 SD):** "set just past his worst observed value; no trial source" — a line chosen from the
  same data it then judges. It first fired on 4 Oct with the week at 41.3 ms against a line of 41.4 (error of a
  7-night mean 1.9 ms) — within a tenth of the error band, on holiday nights.
- **Resting HR +4/+5:** 0 of 93 mornings reached +4 since 1 Aug; 6 sat one beat from it (integer bpm, SD of daily
  deltas 1.33). Coarse but honest. **Sleep score 74:** 17% of mornings within 3 points.
- **Smallest fix:** keep the lines (they are the literature's), change the words: "below your usual by more than a
  worthwhile amount" instead of "real, not noise"; show the 7-day mean's ± in the provenance; for the marked line,
  record that it is in-sample and re-derive it when 6 months of data exist. No colour change.

### ST363-07 — Medium · The REM card is a near-constant flag: a wrist device judged against a lab age band "misses" on 80% of nights, so "repeatedly missed" says nothing about this month
- **Evidence: observed + computed.** The statistics half of R6's HS361-03 (physiology and the misquoted bands are
  theirs).
- *Observed (1 Nov packet, Home/Sleep card "Protect REM consistency"):* "REM has repeatedly missed its age norm;
  of everything measured, bedroom temperature…", evidence "22 of 28 measured nights missed healthy 50–59 range
  15–23%". The card fires at a 0.7 miss ratio over 28 days (`CHRONIC_ACTION_MISS_RATIO`).
- *Computed (`coach.sleep`, 1 Aug–1 Nov, 93 nights):* REM was below 15% on **74 of 93 nights (80%)**, mean 11.1%
  (SD 4.8). With a base rate of 0.8 a night, a 28-night window reaches 0.7 about **nine times in ten** with nothing
  changing (binomial), so the card is on by default. The band is polysomnography (Ohayon 2004) and wrist
  devices under-read REM against it (Chinoy 2021; Decision #322 already says the watch cannot support a nightly REM
  verdict). His own REM % (SD 4.8) is the honest comparator: "fewer than your own usual on N of 28 nights".
- *And:* the card's "of everything measured, bedroom temperature" is ST363-01's best-of-many lever.
- **Smallest fix:** judge the REM card against his own distribution (personal median and IQR, as every other
  chronic metric), keep the age band as a once-a-month context line at most. Removes no caution from the call (the
  card is advisory); Mark-facing copy, so Craig's sign-off.

### ST363-09 — Medium · The weekly review's sleep "trend" is noise on most weeks, and the review builds advice on it
- **Evidence: observed + computed.** Found in the first v14 weekly review (1 Nov 18:00).
- *Implemented (`reviews.py` `_half_trend_evidence`, sleep call in `compute_review_rollup`):* 3 nights against 4,
  called a trend when the change exceeds 5% of the first half; the sleep call passes no absolute floor
  (`min_absolute_delta` 0), where readiness gets 4 points.
- *Observed (1 Nov review):* sleep labelled "increasing" on 74.0 → 77.8 (+3.8, 5.1%, just over the line). The text
  says sleep "rose through the week" and "climbed back toward your usual range", and recommends "keep whatever
  you did to lift sleep".
- *Computed (112 home nights, SD 10.4):* the SE of a 3-v-4 difference is **8.0 points**, so +3.8 is half an SE. On
  20,000 shuffled weeks of his own nights the rule calls a trend **63%** of the time (up 32%, down 32%); on 106
  real sliding weeks, 74 of 106 (70%). This week's "rise" is one night: without 1 Nov (88) the halves are 74.0 and
  74.3.
- *Why it matters:* the label is shown to Mark as a finding every week and the model is told to ground claims in
  it, so roughly two weeks in three he reads a direction that a coin toss would give, and some weeks advice is
  built on it.
- **Smallest fix:** an absolute floor for sleep scaled to his spread (about one SE of a 3-v-4 split, ~8 points, or
  compare the week to his usual range instead of half to half); test with his shuffled weeks. Adds caution only
  (fewer claims), but changes Mark-facing wording, so Craig's sign-off on the copy.

### ST363-08 — Low · Small statistical-honesty slips in what is stored or written
- **(a) Driver audit sign** (observed): the stored `driver_correlation` summary of 31 Oct says "Strongest mover of
  rem_sleep_min: bedroom_peak_fan_speed (positive, r=0.4484)" — **8 nights**, ranked by its calendar-adjusted
  value (−0.51, the opposite sign) but printed with the raw sign, interval −0.91 to +0.39. Mark does not see this
  row (the lever gate needs 20 nights and an interval off zero), but anyone reading the audit row (Craig, a future pass) can. Fix: rank and
  print the same coefficient; skip drivers under the lever floor in the summary.
- **(b) "median" in the brief** (observed; corroborates R3's AI358-03): every "median" in the v60+ briefs (28, 29,
  30 Oct, 1 Nov — 4 of 6) comes from one source, the readiness-decline paragraph, fed by
  `firstHalfMedian`/`secondHalfMedian`. The warning itself holds up statistically (re-derived through the real
  `readiness_baseline_trend`: 74 → 63, −11 points; on 5,000 shuffles of the same 84 days a fall of ≥ 5 happens 9.7%
  of the time and the shuffled SD is 3.8, so −11 is ~2.9 SD; still −7 with the holiday fortnight left out; it is
  not the build block, since acute load *fell* 563 → 300 between the halves). Fix: pass "usual readiness 63, the
  six weeks before 74" as plain fields.
- **(c) The 120-word call** (seed P1; observed): now **3 of 3** v65 briefs over the cap (159, 126, 156 words; 1 Nov
  also `colour_words`). Three of three is not noise: the content asked for (headline, two or three numbers, a
  Because, a change-trigger, Tonight, the readiness paragraph when it fires) does not fit 120 words, or the prompt
  does not bind; either way the cap as set fails every day. Craig's call (pending on the 1 Nov brief).
- **(d) Tonight's advice** (implemented + observed): the weekly comparison is within-week, ≥ 2 nights a side and
  labelled weak evidence — right. Each arm's figure is a *change* from a cautious morning, so both arms carry
  regression to the mean; only the between-arm difference is interpretable. 1 answer stored so far (1 Nov,
  "followed"), so tonight's review has nothing comparable. Fix: report only the difference between arms.

## 3. Where it is already near-optimal (re-derived, not assumed)
- **One usual HRV (317, #450):** `usualMs` 46.69 on 1 Nov re-derived exactly (mean of the 84 nights before,
  judged night excluded); the metrics table carries the same mean since 29 Oct; the v65 briefs quote one usual
  (47 ms) — no second "usual" figure since 29 Oct (v58 briefs said "median 47"). The acute floor still centres on
  the median (−1.5 SD), which is a different line, not a second usual.
- **Batch 249's machinery:** calendar-adjusted partial correlations, Fisher intervals with a degree of freedom for
  the control, "a lever whose interval crosses zero is not named", minimum 20 nights for a lever, concurrent and
  unmitigable drivers excluded from levers, "unknown application is never not-applied", "observational, not
  causal" wording, human-gated conclusions. This is better than most consumer apps; the gaps are the next layer
  (multiplicity, repeated looks, season windows, effective n).
- **The readiness-decline warning** survives a shuffle test (ST363-08b). **The recovery-week experiment** reports a
  difference with its interval and calls it inconclusive (+2.2, −2.7 to +7.1, 21 v 77 nights) — the right answer.
- **Resting HR lines** are coarse but honest (0 of 93 mornings reached +4 since 1 Aug).

## 4. Follow-through corrections (rows in this lens)
| ID | Pack says | Now | Evidence |
|---|---|---|---|
| HS332-02 REM loop near "supported" on Sep-v-Oct | fixed (claimed) | **fixed, re-run**: guard in place, arms 18 v 16, `calendarApart` false, inconclusive; but daily re-looks give a direction in ~25% of null seasons (ST363-04) | observed + proved |
| HS332-09 drivers cache drops calendar adjustment | fixed (claimed) | **fixed**: the cached 31 Oct packet carries `adjustedCoefficient` and intervals; the stored summary line still prints the raw sign (ST363-08a) | observed |
| HS240-06 / -07 calendar and minimum n | fixed (wave #5) | **holding**; next layer missing: multiplicity, effective n, season window (ST363-01) | implemented + computed |
| DV-5 two usual HRVs | fixed (claimed) | **fixed** since 29 Oct | observed |
| DV-7 a holiday week lowers the 12-week normal | shipped differently | **open, small**: the 9 holiday nights lower his usual by 0.74 ms (47.43 → 46.69) and widen the SD (4.41 → 4.89), so the mild line sits ~1.0 ms lower (less sensitive) until they leave the window on 21–29 Dec | computed |
| 1001-AI-5/6 "supported" on few recovery weeks | open | **resolved by the evaluator**: inconclusive with an interval, 21 recovery nights | observed |
| DV-2 / 319 progress signal | fixed (claimed) | **built, statistically empty under ERG** (ST363-02, ST363-03) | proved |
| P1 v65 length | 2 of 2 over | **3 of 3** (ST363-08c) | observed |

## 5. Queued and parked items re-verified
- **337** (failure reaches Craig): not this lens. **209, 338, 345:** not this lens.
- **HS332-04** (cooling targets): not built and has no row (R6 corrects the pack); ST363-01's fix belongs with it.

## 6. For reconsideration (settled decisions, new evidence)
- **#459 (319 thresholds, provisional):** under ERG the on-target test cannot fail (55 of 55 since 11 Oct), so the
  note equals three Greens; 0.72 firings per 14 Sundays on shuffled mornings v 1 real (ST363-02). The thresholds are
  not the issue; the measure is.
- **#431 (nights away apart; interval-first driver choice):** right, and the next step is a multiplicity allowance
  and a season window (ST363-01).
- **#454 (REM experiment calls no direction across seasons):** the guard works; repeated daily looks are the
  remaining error source (ST363-04).
- **#450 (one usual HRV = 84-night mean):** sound; record that the holiday nights shift it ~0.7 ms until late Dec.

## 7. Hypotheses (not verified)
- Effective n for the driver intervals is close to n for the outcomes (lag-1 autocorrelation of sleep score ≈ 0,
  of bedroom temperature 0.44), so autocorrelation matters less than multiplicity here; for HRV and readiness
  series (more persistent) it would matter more. Not computed for every driver.
- The load ratio from 1.5 (316) was not re-derived: `daily_metrics` holds acute load but not the chronic load
  the ratio needs, and the packet field was not projected in time.
- Garmin's sleep score and sleep stress share inputs with HRV; some "drivers" of sleep score may be the score's own
  components (ST363-05 generalised). Not tested beyond sleep stress.

## 8. Limitations
- Garmin's 1 Nov outage (00:25–12:01 GMT) is treated as missing input; 1 Nov's Green was written at 12:04 and is
  used as stored. The 21–25 Oct Hive gap leaves 5 nights out of the temperature analysis.
- Fixed-power and hard-session inputs are the latest stored post-ride packet per ride, projected by SQL and passed
  to the real functions; reviews code reads the same packets.
- Primary sources read at abstract/listing level: Hopkins 2000 (typical error; *Sports Med* 30:1–15), Plews et al.
  2013 (*Sports Med* 43:773–781; HRV 7-day rolling mean and SWC, Ln rMSSD — the app uses raw ms), Pocock 1977
  (*Biometrika* 64:191–199; repeated significance tests), Kravitz & Duan (eds) 2014 AHRQ n-of-1 guide; Ohayon 2004
  and Chinoy 2021 via R6. Javaloyes 2019 cited from the app's own threshold table, not re-read.
- No paid call; no web app driven (R7).

## 9. Probe log (1 Nov, ~16:00–16:20 GMT; all read-only)
- Supabase MCP SELECTs, schema `coach`, projected and windowed (no `raw_payload`/`output_markdown` in bulk):
  analyses type/version counts; experiments (title, status, criteria keys, observation size); post-ride packets'
  interval adherence counts per ride; morning colours per day (latest); ≥20-min interval fields per ride with
  watch temperature; driver_correlation 29–31 Oct packet keys and 31 Oct correlations; holiday windows (KB);
  per-night sleep aggregates joined to sleep-window and pre-sleep temperature aggregates; lever-line presence counts
  in morning/evening packets since 1 Sep; 1 Nov packet key sizes, HRV rail and metricsVsBaselines (HRV, RHR) 28 Oct–
  1 Nov; "usual … ms" and "median" regex hits in briefs since 20 Oct (short windows of the app's own words);
  readiness, acute load and recovery per day (morning row preferred, as the app); 1 Nov experimentLoop
  evaluations; tonight-advice feedback rows (answer only); REM/deep % summary 1 Aug–1 Nov; 1 Nov chronic card
  fields.
- Local probes (main venv, `-I`, worktree code on `sys.path`; scripts and outputs in `scratchpad/wave6/r8/`):
  `probe_progress_stats.py`, `probe_drift_stats.py`, `probe_thermal_stats.py`, `probe_readiness_trend.py`,
  `probe_rem_looks.py`, `probe_threshold_sensitivity.py`; data extracts `nights_home.psv`, `hrv_rhr_aas.txt`
  (scratch, gitignored, not for commit).
- Weekly review, 18:10–18:13: the one v14 `weekly_review` row (keys, `progressSignal`, `tonightAdvice`, `rollup`
  sleep/thermal/recovery/verdicts, the text once); `probe_weekly_trend.py` (shuffle test of the sleep half-trend
  on `nights_home.psv`). 
- Web: four citation checks (standard search).
- **Paid calls: none ($0).** No transaction opened (MCP statements are single autocommit SELECTs).

## 10. Catalogue notes for `domain/statistics-measured-effects.md` (app-specific, for the lesson step)
- garmin-coach: run the shuffle tests on the real functions (`progress_signal`, `fitness_drift`,
  `readiness_baseline_trend`, `evaluate_rem_interventions`) — they are pure and take plain tuples; seed data from
  projected SQL. `daily_metrics` has two rows a day (`phase`): prefer the morning row.
- Patterns found this wave: an ERG-held target used as evidence; a best-of-many correlation shown with a
  single-test interval; a population band on a biased wearable as a near-constant flag; evaluators recomputed
  on every read (repeated looks) with no stored trace.

## 11. Weekly review (v14, stored 1 Nov 18:00:57 London; re-derived 18:10–18:13)
One `weekly_review` row at `reviews-v14-2026-10-29`, period 26 Oct–1 Nov, 7 days. Read: `progressSignal`,
`tonightAdvice`, `rollup.sleep/thermal/recovery/verdicts` and the 3,086-character text (one row, not copied here).

| Claim in the review | Re-derived | Verdict |
|---|---|---|
| "Ready for a little more" (progress note) | 27, 29, 31 Oct each 100% on target, each next morning fresh; `provisional` true | Fired as ST363-02 predicted; its own shuffle rate (~0.7 a season) stands |
| Heart rate at 184 W 111.1 → 112.7 bpm, "basically steady" | 6 v 8 rides; SE ≈ 1.9 bpm with his SD 3.56; +1.6 is 0.8 SE | Right call, honestly worded |
| Sleep "rose through the week", 74 → 77.8 | Matches stored nights; noise test fails | **ST363-09** |
| Readiness "essentially flat", 60.3 v 59.8 | Matches; 4-point floor applied | Right |
| Mornings 5 recovered · 2 some fatigue · 0 still recovering | 5 Green, 2 Amber, 0 Red; no colour words | Right (Batch 313 words) |
| Bedroom "hit or crossed 20 °C on 3 of 7 nights"; advice to cool the room | Peaks ≥ 20 on 27 Oct, 30 Oct, 1 Nov; share of sleep-window readings ≥ 20 was 100%, 6% and 9%. Those 3 nights scored 73, 77, 88 (mean 79.3) v 73.8 on the other 4 | The count is literal but a single reading of 20.0 makes a "disruption night"; the advice repeats ST363-01's lever against the week's own nights |
| Sleep-window advice "followed once… too little to say it's the cause" | `tonightAdvice` 1 advised, 1 answered, 1 followed, `comparable` false, `evidence` weak | Honest; ST363-08d's arm-difference fix is still untested in production |
| "(69.75–83, median 78)", "(56–77, median 67.5)" | The review's own rule (`REVIEW_PLAIN_WORDS_RULE`, Batch 347) says never quartiles or medians | Rule broken twice; extends ST363-08b and R3's AI358-03 from briefs to reviews; nothing checks it after generation |

**Grade settled at B−.** The review adds one Medium (ST363-09) and confirms ST363-01, -02 and -08 in a second
Mark-facing surface; no High.
