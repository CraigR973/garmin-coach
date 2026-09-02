# Batch 240 — Health & Sleep-Science Review

**Pass 5 of 6 in the Batch 236–241 audit wave.** Scope and guardrails:
`docs/reviews/BATCH_236-241_AUDIT_SCOPE.md`.

**Auditor lens:** sleep medicine + exercise physiology. The question is not "does
the code run" but "are the physiological claims this app makes to a real
57-year-old man defensible, and is anyone at risk."

**Read-only throughout.** No code changed, no production row written, no
Anthropic call made. Every production read was column-projected and windowed
against the egress cap. Evidence is labelled `observed` (seen in live production
data), `proved` (demonstrated by executing the real function), or `implemented`
(read in code but not exercised) — the convention
`COACHING_INTEGRITY_AUDIT.md` already uses.

**Subject.** Mark, male, 50–59 band. Measured from production over 185 nights
since 2026-03-01: resting HR median **44** (range 40–49, own Q3 **45**),
overnight respiration mean **11.35** (max 13), overnight SpO₂ mean **96.4 %**,
VO₂max ~55, FTP 280. By every conventional marker this is an exceptionally
healthy, well-trained man. That fact is load-bearing on several findings below.

---

## Bottom line

The deterministic scaffolding is better than most consumer sleep products and
the epistemic discipline in the newer modules (`driver_levers`, `REM_FRAMING_RULE`,
`REM_PCT_BASIS`) is genuinely good — better than the science it is being applied
to. Three things are wrong at the level of physiology rather than code:

1. **The verdict has no acute-illness rail.** It is a *sleep and readiness* gate
   wearing the clothes of a health gate. A resting heart rate 40 bpm above
   Mark's own ceiling, a one-night HRV collapse, and severe overnight hypoxaemia
   all produce **Green** (all three `proved`).
2. **The single most persistent claim the app makes about Mark's body — a
   chronic REM deficit — is more likely a wearable stage-classification artefact
   than a physiological finding**, and no code path has ever considered that
   hypothesis. It drives a 12-lever intervention library, a correlation engine,
   an experiment loop, and a line in every morning brief.
3. **The statistics that turn correlations into advice are not strong enough to
   carry the advice.** The one lever production has ever issued fails the app's
   own threshold once calendar date is controlled for (`proved`, by independent
   replication against production data).

Nothing here is an emergency. Nobody is being told to do something dangerous.
The risk profile is *silence where there should be a signal*, and *confidence
where there should be a caveat*.

**Findings: 19.** 4 safety (3 High, 1 Med-High) · 3 High scientific · 8 Medium ·
4 Low. Safety first regardless of technical severity, as briefed.

---

# SAFETY FINDINGS

## HS240-01 — SAFETY · HIGH · A resting heart rate 40 bpm above his own ceiling produces Green

**The claim the app makes.** The morning verdict is presented to Mark as the
day's readiness judgement — a Green/Amber/Red light rendered "big and static"
(`VerdictHero.tsx`), with the deterministic gate deliberately not the model's to
set. Mark reasonably reads Green as "nothing in my numbers is wrong today."

**Where.** `morning_analysis.py:2543` (`_morning_verdict`);
`morning_analysis.py:2480` (`_resting_hr_elevated`); `morning_analysis.py:2698`
(the only branch that consumes it).

**What is wrong.** `_resting_hr_elevated` compares today's RHR against Mark's own
84-day upper quartile and returns a clean boolean. That boolean is surfaced in the
packet as `restingHeartRateElevated` — and then feeds exactly one consumer:
`cumulative_escalation`, which is gated behind `if readiness_level == "poor"`.
Elevated resting heart rate is otherwise **not an input to the light at all**.

**Proved.** Driving the real `_morning_verdict` with Mark's own baseline
(`upper_quartile_value = 49`) and everything else clean:

| resting HR | verdict |
|---|---|
| 52 | Green |
| 60 | Green |
| 70 | Green |
| **85** | **Green** |

**Observed, and it is worse than the probe suggests.** Mark's real RHR
distribution is extraordinarily tight — median 44, Q3 45, full range 40–49
across 185 nights. An RHR of 60 is a 36 % elevation and roughly four standard
deviations outside his own record. The app computes that it is outside the band
and discards the result. And the escape hatch is essentially closed: across all
72 morning `daily_metrics` rows, Garmin has emitted `readiness_level = 'POOR'`
on **2** (readiness scores 3 and 20). So the one path on which an elevated
resting heart rate can influence the light has been reachable on **2.8 % of
mornings**.

**Physiological consequence for Mark.** An overnight resting-heart-rate rise of
5–15 bpm against a stable personal baseline is the single most useful early
signal a wrist wearable produces, and its main causes in a 57-year-old man are
febrile illness, systemic infection, dehydration, alcohol, and new-onset atrial
fibrillation. It typically precedes subjective symptoms by 12–36 hours. This is
the classic "don't train today, you're getting ill" signal, and it is the one
input the app measures accurately and then throws away. Training hard through
the prodrome of a viral illness is the mechanism behind viral myocarditis —
rare, but the specific reason sports medicine has a "neck check" rule at all.

**Evidence label.** `proved` (function driven) + `observed` (production
distribution and readiness-level counts).

**Fix shape.** Promote `restingHeartRateElevated` to a first-class Amber cap
independent of `readiness_level`, on a two-sided test against his own
distribution *and* an absolute delta (e.g. ≥ +7 bpm over the 84-day median, or
above Q3 for two consecutive mornings). Do not key it to Garmin's readiness
category — that category is not a health signal and, on his data, barely varies.

---

## HS240-02 — SAFETY · HIGH · An acute one-night HRV collapse is invisible to the verdict

**The claim.** The prompt tells Mark the verdict rests on "measured HRV"; the
Red rail is *"HRV is below baseline and marked low/unbalanced."* Both read as
statements about last night.

**Where.** `morning_analysis.py:2941-2946`:

```python
def _hrv_below_baseline(daily_metric: DailyMetric | None) -> bool:
    value = daily_metric.hrv_weekly_avg_ms or daily_metric.hrv_last_night_avg_ms
```

**What is wrong.** `hrv_weekly_avg_ms` is populated on every established
morning, so the `or` never falls through. **`hrv_last_night_avg_ms` is dead code
on the verdict path.** Both limbs of the Red HRV rail are therefore
seven-day-smoothed: the app's own limb by this line, and Garmin's `hrv_status`
because Garmin itself derives Balanced/Unbalanced/Low from a 7-day average
against a rolling baseline. The app has **no unsmoothed autonomic input at all**.

**Proved.** Real `_morning_verdict`, everything else clean:

| scenario | verdict |
|---|---|
| last-night HRV 42 → **18 ms**, weekly 42 | Green |
| last-night HRV 42 → **12 ms**, weekly 40, Garmin still `Balanced` | Green |
| weekly 30 ms (below `hrv_baseline_low_ms` 35), status `Balanced` | Amber |
| weekly 30 ms **and** status `Unbalanced` | Red |

**Observed.** On 2026-08-30 the live row read `hrv_last_night_avg_ms = 44`
against `hrv_baseline_low_ms = 44` — exactly at the floor, so `44 < 44` is
False — with `hrv_status = BALANCED`, on a night Garmin graded **all four sleep
stages POOR** and readiness 43. The HRV rail contributed nothing.

**Physiological consequence for Mark.** A single-night RMSSD collapse of the
magnitude probed (−60 to −70 %) is not training fatigue; it is the autonomic
signature of acute infection, fever, heavy alcohol, or an arrhythmic night. It
takes roughly 5–7 nights for a 7-day mean to move far enough to trip a rail
keyed on it, by which point the acute event has resolved or declared itself. The
app is structurally incapable of seeing the day that matters most.

**Evidence label.** `proved`.

**Fix shape.** Read the nightly value as a *separate* input rather than as a
fallback: an Amber cap when `hrv_last_night_avg_ms` falls more than ~1.5 SD
below his own 84-day distribution, independent of the weekly average and
independent of Garmin's category. Keep the weekly limb for chronic drift.

---

## HS240-03 — SAFETY · HIGH · Overnight SpO₂ and respiration are collected, baselined, and never evaluated by anything

**The claim.** The app presents itself as a sleep coach and shows Mark an
overnight SpO₂ figure alongside metrics that *do* carry judgements, which
implies it is being watched.

**Where.** Synced at `garmin_sync.py:575-576` (`average_spo2_pct`,
`lowest_spo2_pct`); baselined at `metric_baselines.py:161`; surfaced at
`morning_analysis.py:1474-1476`. A grep for any numeric threshold, alert, flag or
comparison on SpO₂ across the entire backend returns **one** hit, and it is a
data-*reliability* date cutoff (`daily_loop.py:851`), not a physiological
threshold. There is none for `average_respiration` either.

**Proved.** Real `_morning_verdict` with `lowest_spo2_pct = 78`,
`average_spo2_pct = 86`, `average_respiration = 22`, everything else clean →
**Green**, no reason, no safety rule, no comment.

**Observed (and the honest version).** Mark's real data over 83 reliable nights:
mean overnight SpO₂ **96.43 %** (min nightly mean 93), which is *reassuring* and
argues strongly against a significant untreated hypoxic burden. But the nightly
**nadir** falls below 88 % on **21 of 83 nights (25 %)**, minimum 82 %. I am
deliberately not calling that a finding about Mark's health: wrist reflectance
pulse oximetry is unreliable at the nadir — motion artefact, poor peripheral
perfusion and cold hands all manufacture spurious single-point lows, and Garmin
does not present Pulse Ox as a medical measurement. **The finding is that
neither the reassuring number nor the ambiguous one has ever been looked at by
any rule.** 83 nights of a signal whose entire clinical purpose is to detect
nocturnal desaturation have been stored and never read.

The 88 % line is not arbitrary: it is the threshold at which sustained nocturnal
desaturation becomes clinically actionable in most guidelines, and it is the
qualifying threshold for nocturnal oxygen supplementation.

**Physiological consequence for Mark.** This is the same organ system as
HS240-05. A middle-aged man with a chronically low measured REM fraction and
recurrent SpO₂ nadirs is the textbook screening picture for obstructive sleep
apnoea — REM-related events are the most desaturating, and REM-predominant OSA
is common and frequently missed. His mean SpO₂ and respiration rate argue
against it, which is exactly why *someone should look once and close it*, rather
than the app storing both halves of the question and asking neither.

**Evidence label.** `proved` (verdict behaviour) + `observed` (83-night
distribution).

**Fix shape.** Two separate things, and they must not be conflated. (a) A
deterministic data-quality-aware surveillance rule: flag when average SpO₂ falls
below ~92 % or when nadirs below 88 % cluster across a rolling window, and route
it to HS240-04's escalation copy rather than to the verdict. (b) Say plainly on
the surface where the number appears that a wrist SpO₂ nadir is a noisy
estimate, so a single 82 % does not frighten him.

---

## HS240-04 — SAFETY · MED-HIGH · There is no medical boundary anywhere Mark reads, and no statement of what the app cannot see

**The claim.** The app speaks in a confident clinical register — "disruption
threshold", "healthy range for your age", "keep the day cautious" — and now has
a live conversational surface (92+ user turns as of Batch 211). Mark is
reasonably going to ask it a health question.

**Where.** `coach_policy.py:108` — `FLOORS` holds ten floors:
`never_vo2_on_red`, `no_power_balance`, `local_clock_times`,
`no_skipped_as_live`, `recorded_data_honesty`, `training_load_cap`,
`sleep_credit_ceiling`, `cumulative_escalation`, `readiness_baseline_trend`,
`chronic_action`, `no_invented_derivation`. **None is a health-safety floor.**
`GENERAL_SCIENCE_RULE` (`coach_policy.py:349`) opens a lane for "established
exercise physiology" and bounds it to training principles — it defines a lane, it
does not close the medical one. The only "do not diagnose disease" instruction in
the entire codebase is `longitudinal_analysis.py:80`, in the batch analyst
prompt, which Mark never reads. Two "not medical advice" footnotes exist, both on
comparison tables (`MetricComparisonTable.tsx:412`,
`SleepStageAgeTable.tsx:124`).

**What is missing, specifically:**

- No red-flag escalation. Nothing in the system says "this is beyond what I can
  see — talk to your GP" for *any* input, at *any* value.
- No statement of the app's blind spots. It cannot see illness, medication,
  alcohol, caffeine actually consumed, chest pain, palpitations, breathlessness,
  syncope, or a change in symptoms — and it never says so. Several of those
  (SSRIs, SNRIs, lipophilic beta-blockers) are potent REM suppressants and are
  common in this age band; the app's entire REM narrative would change if one
  were on the list, and nothing has ever asked.
- No asymmetry rule. Every deterministic floor in the codebase protects against
  the *coach being talked down*. None protects against the *coach reassuring
  Mark about a symptom*.

**Physiological consequence for Mark.** The realistic failure is not the app
telling him to ignore chest pain. It is the chat answering "my heart's been
doing a funny fluttery thing at night, should I ride?" from the training-science
lane, in the app's confident register, and Mark taking that as an answer. The
app also has, in `restingHeartRateElevated` and the SpO₂ nadirs, exactly the
kind of data a person brings to a GP — and no mechanism that would ever suggest
he do so.

**Evidence label.** `implemented` (floors enumerated in code; no live incident
observed — Prong B found 0 sycophancy attempts at Batch 191 and the chat has not
been tested against a symptom question).

**Fix shape.** Add an eleventh floor with a recognizer and a failing negative
control, in the shape the other ten already use: *never answer a symptom
question as a coach; name it as outside what the app measures and say it is a
question for his GP.* Separately, add a standing "what I cannot see" line to the
knowledge base — illness, medication, alcohol, symptoms — so the model's own
uncertainty is grounded rather than improvised.

---

# SCIENTIFIC-VALIDITY FINDINGS

## HS240-05 — HIGH · The chronic REM deficit is more likely a device artefact than a physiological finding, and nothing in the app has ever considered that

**The claim.** That Mark has a chronic REM deficit is the most persistent thing
this app says about his body. It has been raised in three separate feedback
waves, motivated Batch 61's band model, Batch 72's 12-lever intervention
library, Batch 227's personal baseline, Batch 230's framing rule and Batch 231's
lever engine. `REM_FRAMING_RULE` (`age_norms.py:404`) now requires the brief to
say *"it is normal for him AND below the band"* and forbids concluding "no
concern".

**Where.** `age_norms.py:160-170` (`_SLEEP_BANDS['rem_sleep_pct']`, 50–59 =
15–23 %), applied to Garmin's `rem_sleep_sec`.

**What is wrong.** The band is anchored to Ohayon et al. 2004 (*Sleep*
27(7):1255), a meta-analysis of **polysomnography**. It is being applied to a
wrist device's accelerometer-plus-PPG stage estimate as though the two measure
the same quantity. Consumer wrist devices show moderate-to-poor epoch-by-epoch
agreement with PSG on stage classification, with REM detection the weakest and
systematically biased (Chinoy et al. 2021, *Sleep* 44(5):zsaa291, comparing seven
consumer trackers against PSG; de Zambotti et al. 2019; Menghini et al. 2021).
No Garmin-specific PSG validation in a 50–59 male cohort was used to calibrate
this band, and the module's docstring does not raise the question.

**Observed — and the app's own data is the evidence.** Over 185 nights since
2026-03-01, stage shares of measured sleep:

| stage | Mark's mean | app's 50–59 band | nights outside |
|---|---|---|---|
| REM | **10.43 %** | 15–23 | **152 / 185 below the floor (82 %)** |
| Light | **64.39 %** | 48–62 | **111 / 185 above the ceiling (60 %)** |
| Deep | 18.13 % | 12–20 | 68 / 185 **above** the ceiling |
| Awake | 7.06 % | 0–12 | 19 / 185 above |

The REM shortfall and the Light excess are equal, opposite, and simultaneous.
And Garmin itself grades his `deepPercentage` **EXCELLENT** on 4 of the last 8
nights (`factors_json.deepPercentage.qualifierKey`, observed 2026-08-25 → 09-01),
while Ohayon's own regression predicts SWS *around 11 %* at age 50–59 — so his
measured deep sleep is running high against the same literature the REM band
comes from. A device that resolves REM poorly and defaults ambiguous epochs to
light/deep would produce exactly this pattern.

Set against his physiology: RHR 44, overnight respiration 11.35, mean SpO₂
96.4 %, VO₂max ~55, no medication on file. **A genuine 8-percentage-point REM
suppression has a short differential — REM-suppressing medication, heavy
alcohol, severe OSA, narcolepsy spectrum — and every other marker in his record
argues against all of them.** "Healthiest man in the dataset has a profound REM
deficit" is not a coherent clinical picture; "the wrist device under-calls REM
in this individual" is.

I am not asserting the artefact hypothesis is true. I am asserting it is at
least as likely as the deficit hypothesis, that it is cheap to test, and that
**the app has never entertained it** — every downstream module treats
`rem_sleep_sec` as a measurement of REM.

**Physiological consequence for Mark.** He is told most mornings that a
structural feature of his brain's sleep is deficient, and is issued behavioural
interventions to correct it. If the deficit is instrumental, the app is
generating persistent low-grade health anxiety and behaviour change on a
measurement error — and, worse, `REM_FRAMING_RULE` correctly forbids the model
from softening it, so the one escape valve has been deliberately welded shut.
Batch 230 was right to close that valve *given the premise*; the premise is what
was never audited.

**Evidence label.** `observed` (185-night stage distribution, Garmin qualifiers,
his full marker set) + `implemented` (the band's provenance and its application
to device data).

**Fix shape.** Three steps, in order. (1) State the measurement basis wherever
the band is applied, in the same way `SLEEP_STAGE_PCT_BASIS` states the
denominator: *this is a wrist-device estimate of REM, not a laboratory
measurement, and consumer devices disagree with laboratory scoring most on REM.*
(2) Test the complementarity hypothesis directly — if `REM% + Light%` sits
inside the combined Ohayon expectation for REM + N1 + N2 while the split does
not, the split is the suspect, and the honest reframe is "your REM/light split
is where this device is least reliable" rather than "your REM is low".
(3) Gate any *new* REM intervention behind that test. Do not remove the flag on
suspicion; make it say what it actually knows.

---

## HS240-06 — HIGH · The lever gate is not statistically defensible, and the one lever ever issued does not survive the most obvious confound

**The claim.** Batch 231's chronic-suggestion card tells Mark: *"REM has
repeatedly missed its age norm; of everything measured, time above 19.5 C tracks
it most closely so far (64 nights) — an association in your own data, not a
proven cause"*, with `confidence: moderate`
(`chronic_patterns.py:1431-1453`, `driver_levers.py:_confidence`). This is
Batch 231's headline deliverable and it replaced a genuinely false statement, so
it is the right direction. The statistics underneath it are not strong enough
to carry it.

**Where.** `insights.py:100-119` (14 drivers) × 4 outcomes = **56 Pearson
correlations computed per run**, no p-values, no confidence intervals, no
multiple-comparisons control, ranked and selected by `max |r|`
(`insights.py:443-484`). Gates: `driver_levers.py:108` `MIN_LEVER_SAMPLES = 20`,
`driver_levers.py:112` `LEVER_MIN_ABS_R = 0.15`. The general prose/packet path is
looser still: `insights.py:93` `MIN_CORRELATION_SAMPLES = 8`.

**Proved — what the gate lets through.** Executing the real `select_lever` and
computing the corresponding test statistics:

| n | critical \|r\| at α=.05 (two-tailed) | p at the app's 0.15 gate | 95 % CI at r=0.15 |
|---|---|---|---|
| 8 | 0.705 | 0.723 | — |
| **20** | **0.444** | **0.528** | **[−0.313, +0.556]** |
| 64 | 0.246 | 0.237 | — |
| 120 | 0.179 | 0.102 | — |
| 346 | 0.105 | 0.005 | — |

At its own floor the gate admits an association with **p = 0.53** — a coin flip
— whose confidence interval spans a moderate negative to a moderate positive
relationship, and labels it `moderate` confidence. `r = 0.15` is 2.2 % of
variance. Bonferroni across the 56 tests gives α = 0.00089, which at n = 64
requires **|r| ≥ 0.405**.

**Proved — the lever production actually issued.** `bedroom_warning_minutes` vs
`rem_sleep_min`, r = −0.2388, n = 64 (Decision #308, deployed-container smoke
2026-08-27):

- p = **0.057** uncorrected — not significant at α = .05 before any correction
- 95 % CI **[−0.458, +0.007]** — **crosses zero**
- r² = **5.7 %** of night-to-night variance in REM minutes

**Observed — and it does not survive calendar date.** I replicated the
correlation independently from production columns (69 nights, 2026-05-01
onward, reconstructing `bedroom_warning_minutes` from `temperature_readings` over
the same 21:30–09:00 window):

| statistic | value |
|---|---|
| r(warn_min, REM min) — my replication | **−0.2346** (the app's −0.2388, reproduced) |
| r(warn_min, **calendar date**) | **−0.5722** |
| r(REM min, **calendar date**) | **+0.2063** |
| **partial r(warn_min, REM min) controlling for date** | **−0.1452** |
| r(warn_min, sleep duration) | −0.0099 |

**The partial correlation is below the app's own 0.15 gate.** Warm minutes fall
steeply across the window and REM rises across the same window; roughly 40 % of
the raw association is the two variables sharing a season. Had the analysis
adjusted for the passage of time — the most obvious confounder in any 120-day
single-subject time series — **this lever would not have been issued**.

The duration confound, which I expected, is *not* present (r = −0.010) and I say
so rather than leaving the suspicion standing.

**Antecedence — partly right, partly not.** Batch 231's day-alignment fix for
`prev_day_stress_avg` is correct and verified (`insights.py:853-856`, keyed to
`day − 1`). But six of the ten `ACTIONABLE_DRIVERS` — every `bedroom_*` key —
are measured **during the night they are correlated against**
(`driver_levers.py:57-79`), which is precisely what `CONCURRENT_DRIVERS`
exists to exclude. The module's own rule is *"a measurement taken with or after
the night cannot be a lever no matter how strongly it correlates"*, and the
partition then places the concurrent thermal rollups on the actionable side. The
defence — that the room is set before bed — holds for a *setpoint*; it does not
hold for a derived overnight rollup that a restless, warm, or short night
changes.

**Outcome mismatch.** `FLAG_OUTCOMES` maps the `rem_sleep_pct` flag to
`OUTCOME_REM_SLEEP_MIN` (`driver_levers.py:87`). The flag is about a
*percentage* and the lever is ranked against *minutes*. Those are different
quantities that can move in opposite directions on the same night; the card
presents one as the lever for the other.

**Physiological consequence for Mark.** He is told his bedroom is the strongest
measured influence on his REM sleep, and changes his evenings accordingly. The
underlying association explains under 6 % of variance, is not significant, and
mostly reflects the fact that it got colder as summer ended. The advice itself is
benign — keeping a bedroom cool is harmless — but the *epistemic* cost is real:
Batch 231 exists because the app had made a false measurement claim, and the
replacement is a weaker claim made with the same confidence.

**Evidence label.** `proved` (test statistics computed from the real gate and
the real coefficient) + `observed` (independent replication and partial
correlation against production data).

**Fix shape.** Report the interval, not a word: replace `confidence:
moderate|high` with the coefficient's 95 % CI and n, and refuse to name a lever
whose CI crosses zero. Adjust for calendar time before ranking — a partial
correlation on date-detrended residuals is three lines and would have caught
this. Move the `bedroom_*` rollups to `CONCURRENT_DRIVERS` and introduce a
genuinely antecedent thermal driver (the pre-bed setpoint or the 21:30–23:30
mean) if a thermal lever is wanted. Rank the flag's own quantity: REM % flags
should rank REM % drivers.

---

## HS240-07 — HIGH · The experiment loop reaches conclusions from noise

**The claim.** The experiment loop is the mechanism by which the app decides
whether a REM intervention *works*. It emits `supported` / `refuted` /
`inconclusive` with an evidence sentence — *"{intervention} is {direction}: REM
{Δ:+.1f} percentage points and awake time {Δ:+.1f} minutes on applied nights"*
(`experiment_evaluation.py:527`). It reads as a measurement result.

**Where.** `experiment_evaluation.py:113-115` — `REM_MIN_PER_RESPONSE = 3`,
`REM_PCT_DIRECTION_THRESHOLD = 2.0`, `REM_AWAKE_DIRECTION_THRESHOLD_MIN = 10.0`;
`:109-110` — `GROUP_MIN_PER_GROUP = 4`, `GROUP_THRESHOLD = 3.0`.

**Observed — Mark's measured dispersion, from 185 nights:**

| metric | SD |
|---|---|
| REM % of measured sleep | **4.43** points (mean 10.43) |
| awake minutes | 16.47 |
| age-adjusted sleep score | 9.66 |

**The arithmetic.**

- **REM arm.** 3 nights per group against SD 4.43 → SE of the difference of two
  means = 4.43 × √(⅓+⅓) = **3.62 points**. The 2.0-point decision threshold is
  **0.55 SE**. Under the null, a single-condition crossing occurs about **58 %**
  of the time; the compound `and` on awake direction pulls the joint rate down
  to roughly 25–30 %. **The loop reaches a directional verdict from pure noise
  on something like a quarter to a half of evaluations.**
- **Recovery-vs-build arm.** 4 nights per group against SD 9.66 → SE = 6.83;
  the 3.0-point threshold is **0.44 SE**, crossed by noise about **66 %** of
  the time.
- **What would be needed.** To detect a genuine 2-point REM effect (0.45 SD — a
  large effect for a behavioural sleep intervention) at 80 % power and α = .05
  requires roughly **77 nights per arm**. The app uses 3.

**Physiological consequence for Mark.** The mitigation is real and worth
crediting: `experiment_loop` never auto-concludes, and the prompt says so
explicitly. But the human in "human-gated" is Mark, and he is handed a
recommendation with a number attached. The concrete harm is a false negative —
a genuinely useful lever (wake-time regularity, alcohol) declared `refuted` on
three noisy nights and rotated out of the library — and a false positive that
teaches him a folk remedy works.

**Evidence label.** `proved` (constants read and arithmetic performed) +
`observed` (dispersion measured from production).

**Fix shape.** Raise the sample floors to something the dispersion supports, or
— better, because 77 nights per arm is not a realistic n-of-1 design — stop
emitting a directional verdict at all and emit the observed difference with its
interval and an explicit "this window cannot distinguish these" default. The
`inconclusive` branch already exists; it should be the overwhelming default, not
the exception.

---

## HS240-08 — MED-HIGH · The thermal thresholds are arbitrary, sit at Mark's own median, and target below the WHO indoor minimum

**The claim.** *"Above 19.5C risks thermal sleep disruption, so cool it before
bed"* and *"above the 20C disruption threshold"* — pushed to Mark's phone
(`nudge_alerts.py:399-410`, `:384-396`). The production knowledge base carries
`thermalDisruptionThresholdC: {low: 19.5, high: 20.0}` and
`preCoolTemperatureC: 17`, source `batch_5_seed` (observed).

**What is wrong.**

*Direction: right. Location: not supported, and it destroys the signal.* Heat
genuinely degrades sleep, and the REM mechanism is real and well established —
thermoregulatory effector responses are suspended during REM (poikilothermia),
so REM is the state most vulnerable to ambient warmth (Parmeggiani;
Okamoto-Mizuno & Mizuno 2012, *J Physiol Anthropol* 31:14, reviewing heat
exposure increasing wakefulness and reducing SWS and REM). What is not
supported is **19.5 °C as the line**. That figure sits at the top of the popular
sleep-hygiene band (15.6–19.4 °C / 60–67 °F), which is a consensus
recommendation rather than a measured disruption threshold. The best field
evidence in *older adults specifically* — Baniassadi et al. 2023, *Science of
the Total Environment*, bedroom temperature and sleep efficiency in
community-dwelling older adults — puts optimal sleep efficiency at roughly
**20–25 °C** with degradation above ~25 °C. The app's "critical" line sits
inside what that study calls optimal.

*It has no discriminating power on his data.* Observed across 3,208 night-window
ticks (2026-06-24 → 08-31): median bedroom temperature **19.2 °C**, mean 19.59.
**39.8 % of ticks are at or above 19.5 °C.** The threshold has been placed
almost exactly at his own median, so it flags roughly half of every night by
construction — which is the direct mechanical cause of HS240-06's seasonal
confound, because "warm minutes" then behaves as a summer indicator rather than
an exposure. Meanwhile p95 is 24.4 °C and the maximum 28.4 °C — the range where
the literature actually does predict disruption — and the app treats 28.4 and
20.1 as the same category.

*The cold side is unguarded and points the wrong way.* WHO Housing and Health
Guidelines (2018) make a strong recommendation for a **minimum indoor
temperature of 18 °C** in temperate climates, with specific caution for older
adults, on cardiovascular and blood-pressure grounds. The app's pre-cool target
is **17 °C** and its fan turns on at 19.5 °C. Already in *summer*, **15.6 % of
night ticks are below 18 °C** and 2.3 % at or below 17 °C. In a Kilmarnock
winter, a protocol that targets 17 °C and runs a circulating fan from 19.5 °C
would hold a 57-year-old's bedroom below the WHO floor for most of the night.
Nothing in the codebase has a lower bound.

**Physiological consequence for Mark.** Two costs, neither acute. He runs a
fan and a cooling protocol on most nights against a threshold that is not a
threshold, and receives push notifications framing an ordinary 19.6 °C bedroom
as a health risk. And in winter the same protocol pushes in a direction that
mainstream housing-health guidance considers harmful for his age group.

**Evidence label.** `observed` (production KB row, 3,208-tick temperature
distribution) + `implemented` (thresholds and their provenance in code).

**Fix shape.** Re-derive the lines against the literature and his own data
rather than the seed: a warning around ~23–24 °C and critical around ~26 °C
would restore the flag's discriminating power and align it with the evidence.
Add an absolute lower bound at 18 °C that the fan autopilot and the pre-cool
target both respect, and raise `preCoolTemperatureC` to at least 18. If the
19.5 °C line is kept for continuity, stop calling it a "disruption threshold" to
Mark — call it what it is, the app's own comfort target.

---

## HS240-09 — MED · The thermal exposure window is not the sleep window, and REM is back-loaded

**Where.** `bedroom_overnight.py:49-59` — `night_window` is a fixed local-clock
21:30 → 09:00 span; `summarize_overnight` counts every tick above threshold
inside it.

**What is wrong.** Observed: **46.5 ticks per night at 15-minute intervals =
11.6 hours** of exposure window, against a typical sleep period of ~7.5 hours.
Roughly four hours of "warning minutes" are accumulated while Mark is not in
bed. Two consequences: the exposure is diluted by about a third with irrelevant
time, and — because REM concentrates in the final cycles, which is the app's own
stated mechanism (`rem_interventions.py:96-115`) — the hours that would carry the
mechanism are weighted identically to 21:45 in an empty room.

**Physiological consequence.** The one thermal lever the app issues is measured
against an exposure that is systematically mis-specified in the direction that
weakens it, which contributes to the small and fragile coefficient in HS240-06.

**Evidence label.** `observed` (tick count) + `implemented` (window definition).

**Fix shape.** Compute the thermal rollups over the stored sleep period
(`sleepStartUtc` → `sleepEndUtc`, both already on the row) rather than a fixed
clock window, and consider a second rollup restricted to the final third of the
night — the window where the stated mechanism applies.

---

## HS240-10 — MED · The 12-lever REM library mixes A-grade physiology with folk mechanisms at identical confidence

**Where.** `rem_interventions.py:59-186`. Each lever is rendered as a flat
imperative with a mechanism clause, and the rotation treats all twelve as
interchangeable.

**Grading each lever on its evidence, and separately on its stated mechanism:**

| # | id | line | action | stated REM mechanism | grade |
|---|---|---|---|---|---|
| 1 | `wake_time_anchor` | :61 | sound | sound — REM is back-loaded; sleep regularity is a strong independent outcome predictor (Windred et al. 2024, *Sleep*) | **A** |
| 2 | `protect_last_cycle` | :68 | sound | sound — truncating the night selectively removes REM | **A** |
| 3 | `rem_rebound_recovery` | :147 | sound | sound — REM rebound after REM deprivation is among the best-replicated findings in sleep physiology | **A−** |
| 4 | `room_cool_late_cycles` | :96 | sound | sound — REM poikilothermia; warmth reduces REM and SWS (Okamoto-Mizuno & Mizuno 2012). *Its numbers are wrong — see HS240-08* | **A− / thresholds D** |
| 5 | `alcohol_free_evenings` | :82 | sound | mostly sound but **dose-overstated**. Ebrahim et al. 2013 (*Alcohol Clin Exp Res*) systematic review: moderate-to-high doses suppress first-half REM and fragment the second half; low-dose REM effects are inconsistent. "Even one drink" is stronger than the evidence | **B+** |
| 6 | `bedtime_hard_stop` | :75 | sound | loose. Extending sleep opportunity does increase absolute REM; "REM only rebounds when the night is long enough" conflates opportunity with homeostatic rebound. **Also unsafe advice if sleep-maintenance insomnia ever appears** — a hard lights-out is the inverse of CBT-I stimulus control and time-in-bed restriction, and no lever in the library is gated on sleep efficiency | **B−** |
| 7 | `late_training_guard` | :155 | **questionable** | contradicts the weight of the evidence. Meta-analyses (Stutz et al. 2019, *Sports Med*; Frimpong et al. 2021, *Sleep Med Rev*) find evening exercise does **not** harm sleep and often improves it, with the sole exception of vigorous work ending under ~1 h before bed. The REM decrement observed is small (~1–3 points). Telling a cyclist to move training on that basis is a real cost for a marginal mechanism | **C−** |
| 8 | `evening_light_down` | :116 | sound | half-sound. Evening light suppresses melatonin and phase-delays timing (Chang et al. 2015, *PNAS*), which shifts REM propensity later. **"Shallower" REM is not a thing** — REM has no depth dimension; and the effect size for ordinary room/screen light is much smaller than the study doses | **C+** |
| 9 | `caffeine_cutoff` | :89 | sound | **REM claim unsupported**. Caffeine robustly reduces TST, sleep efficiency and **SWS** and increases N1 and WASO (Gardiner et al. 2023 meta-analysis, *Sleep Med Rev*; Drake et al. 2013, *JCSM*) — pooled analyses do **not** show a significant REM reduction. Good general advice, wrong library | **C** |
| 10 | `wind_down_consistency` | :123 | harmless | unevidenced specificity. Slow-paced breathing acutely raises HRV (Lehrer & Gevirtz 2014); there is no evidence it changes REM. "REM responds to a steady routine more than to any single trick" is invented | **C−** |
| 11 | `stress_offload` | :139 | sound | **mechanism is arguably inverted**. The write-the-list intervention has one good RCT (Scullin et al. 2018, *J Exp Psychol Gen*) and it measured **sleep-onset latency**, not REM. Acute stress and depressed mood are classically associated with *shortened* REM latency and *increased* REM density — "unresolved stress preferentially eats REM" is at best contested | **D+** |
| 12 | `late_meal_timing` | :132 | plausible | **mechanism invented**. Diet-induced thermogenesis from an evening meal is small and largely dissipated within 3–4 hours; it does not plausibly "warm your core through the REM-heavy early morning". The evidence linking late eating to sleep architecture is thin and mixed | **D** |

**What is missing entirely.** Twelve behavioural levers, and not one of them is
"a chronically low measured REM fraction in a man in his late fifties is worth
mentioning to a GP once." The organic differential — obstructive sleep apnoea,
REM-suppressing medication (SSRIs/SNRIs, lipophilic beta-blockers), periodic
limb movements — is absent from the library, from the knowledge base and from
every prompt. Combined with HS240-03 and HS240-04, the app owns SpO₂ data, a
chronic REM flag, and no path from either to a clinician.

**Physiological consequence for Mark.** Four of twelve levers (9, 10, 11, 12)
teach him a mechanism about his own body that is not true, in the same voice as
the four that are. Lever 7 asks a cyclist to move training sessions for a
benefit the meta-analytic evidence does not support. Because the rotation is
blind, roughly a third of the advice he receives in any given week is in this
category.

**Evidence label.** `implemented` (library read in full; grading against the
literature).

**Fix shape.** Do not delete the weak levers — several are harmless and
generally good sleep hygiene. Separate the **action** from the **mechanism**:
keep the action, and either drop the mechanism clause or downgrade its register
("some people find…") where the REM-specific claim is not supported. Add a
`confidence` field to `RemIntervention` and bias the rotation toward the A-grade
levers. Add a thirteenth entry that is not a behaviour: the once-only
"worth mentioning to your GP" line, issued a single time and then recorded.

---

## HS240-11 — MED · `sleep_projection` names a "measured driver" with none of Batch 231's protections, on two surfaces plus a push

**The claim.** Every evening, on Home and on `/sleep`, and as a push nudge, the
app prints *"Measured driver: {X} has tracked with lower sleep scores"* plus a
quantified evidence sentence, and turns it into prep actions.

**Where.** `sleep_projection.py:210` (`_risk_drivers` = *any* driver with
`coefficient < 0`), `:7` (`MIN_DRIVER_SAMPLES = 8`), `:294` (`strongest =
drivers[0]`), `:294-300` (the printed sentence), `:309+` (`_prep_actions`).
Reaches `daily_loop.py:1519` → `DashboardPage.tsx:717` and
`SleepPage.tsx:283`; `nudge_alerts.py:563` drives the evening push.

**What is wrong.** This is the exact defect Batch 231 was built to close,
unfixed on the surface Mark sees more often than the chronic card:

- **No strength gate.** Any negative coefficient qualifies. At the module's own
  n = 8 floor, the critical |r| is **0.705**; a driver with r = −0.02 and 8
  nights is printed as "the measured driver".
- **No antecedence partition.** `_DRIVER_LABELS` (`:58-70`) includes
  `resting_heart_rate_bpm` and `sleep_stress_avg` — the two keys
  `driver_levers.CONCURRENT_DRIVERS` exists to forbid — and
  `overnight_wind_max_mph`, which `UNMITIGABLE_DRIVERS` forbids.
- **No causality caveat.** A repo-wide grep for "not a proven cause" returns
  exactly one hit, `chronic_patterns.py:1451`. The projection's sentence carries
  none.
- **No confound.** `DRIVER_CONFOUNDS` is not consulted here at all.
- **The evidence sentence overstates its own n.** `driver_sentence`
  (`insights.py:615`) renders *"Nights with 60+ min above 19.5C average 4.6 min
  less REM sleep (64 nights measured)"* using `correlation.sample_count` — the
  total pairs — where the difference is estimated from a split. Observed for this
  driver: **42 exposed / 27 unexposed**, and the sentence reports neither, nor
  any dispersion.
- **Nor does the chronic card render the confound.** `ChronicSuggestionsCard.tsx`
  renders only `item.summary`; `confidence` and `confounds` reach the model's
  packet and no pixel. With Sonnet 5 now dropping sections (HS240-19), a
  driver-specific confound can reach Mark on neither surface.

**Physiological consequence for Mark.** The careful, correctly-reasoned version
of this claim appears on one card; an uncaveated, ungated version appears on the
dashboard, the sleep page and his lock screen. The looser one wins on exposure.

**Evidence label.** `implemented` (code path traced end-to-end) + `observed`
(the 42/27 split computed from production).

**Fix shape.** Route `sleep_projection` through `driver_levers.select_lever` —
it is already the shared, tested gate — and carry the same summary sentence,
confounds and CI. Render `confounds` on `ChronicSuggestionsCard`. Have
`driver_sentence` report both group sizes.

---

## HS240-12 — MED · Band classification is one-sided: more is always better, so no rebound or hypersomnia signal can ever exist

**Where.** `age_norms.py:314-337` (`_classify_band`): for a `better="higher"`
metric, `if value > high: return "good"`, unconditionally.

**Proved.** Driving the real `build_age_comparison` / `classify_sleep_stage` for
a 57-year-old male:

| input | app's verdict |
|---|---|
| sleep duration 9.0 h | good — "Above the healthy range for your age" |
| sleep duration 10.5 h | good |
| **sleep duration 12.0 h** | **good** |
| REM 30 % | good |
| **REM 45 %** | **good** |
| Deep 28 % | good |
| **Deep 40 %** | **good** |

**What is wrong.**

- **Sleep duration is J-shaped, not monotone.** Long sleep in middle-aged and
  older adults is associated with increased all-cause mortality and
  cardiovascular risk in large meta-analyses (Cappuccio et al. 2010, *Sleep*),
  and the ≥9 h tail is where that signal lives. More immediately for an athlete:
  a sudden +2 h jump against a stable baseline is a classic marker of infection
  onset or functional overreaching — and a 12-hour night in a man who normally
  sleeps 7 is one of the loudest things his data can say.
- **REM and SWS rebound are informative and unflaggable.** A REM fraction at
  45 % is not a good night; it is rebound, and its common triggers — recent REM
  deprivation, alcohol cessation, discontinuation of a REM-suppressing
  medication — are the exact context in which the app's REM narrative should
  change. A deep fraction at 40 % is either profound sleep debt or a device
  artefact. Both read "good".

**Physiological consequence for Mark.** The one direction the sleep model cannot
express is "this is unusually high, and unusually high is a signal." Every
abnormal-high value is congratulated.

**Evidence label.** `proved`.

**Fix shape.** Give the sleep-stage and duration bands a two-sided outer tier:
inside the band → good; modestly outside on the desirable side → good; far
outside → `neutral` with a plain note ("well above your usual and above the
typical range — worth noticing"). This does not require a new statistical model,
only a second tolerance multiple in `_classify_band`.

---

## HS240-13 — MED · Outcome-framed descriptors are literally false for lower-is-better metrics

**Where.** `age_norms.py:291-311` (`_classify`), rendered verbatim at
`MetricComparisonTable.tsx:387` and `SleepStageAgeTable.tsx:93`, and shipped to
the model in `ageComparison.rows[].descriptor`.

**Proved.** For a 57-year-old male against an age average of 71 bpm:

| resting HR | descriptor shown |
|---|---|
| 30 | "Much better than average" |
| 47 | "Much better than average" |
| 85 | **"Well below average"** |
| 110 | **"Well below average"** |

`gap` is deliberately sign-flipped so a green tone always reads as good, and the
docstring says so. But the *warn* descriptors inherit the flip, so a resting
heart rate of 110 is displayed to Mark as "Well below average" next to the value
110 and the age average 71. The tone is correct; the sentence says the opposite
of the fact.

The low side is also unbounded: an RHR of 30 reads "Much better than average"
with no floor. For a trained 57-year-old, 40s is normal and expected; below ~35
with symptoms is a cardiology question.

**Physiological consequence for Mark.** In the rare case that matters, the
sentence contradicts the number beside it — and Batch 230 exists precisely
because *"every figure on the morning brief reconciles from what it shows"*. This
one does not.

**Evidence label.** `proved` (descriptors generated) + `implemented` (render
sites).

**Fix shape.** Split the descriptor vocabulary by direction: for lower-is-better
metrics use "well above average / above average", keeping the tone mapping
unchanged. Add a low-side band to `resting_heart_rate_bpm` so an implausible
value is `neutral` rather than praised.

---

## HS240-14 — MED · The Ohayon denominator gap is stage-dependent and larger than the record says

**Where.** The open question recorded at Batch 227 closeout (STATUS): *"the
age-norm stage bands step from Ohayon et al. 2004, whose percentages are
conventionally % of total sleep time, while Batch 61 calibrated them to measured
sleep including awake — so every stage percentage sits ~0.73 points below its own
band."*

**Proved.** Computed on Mark's real 2026-08-26 night (deep 109 min, light 296,
REM 48, awake 35):

| stage | % of measured sleep | % of TST | gap |
|---|---|---|---|
| REM | 9.84 | 10.60 | **+0.76** |
| Deep | 22.34 | 24.06 | **+1.73** |
| **Light** | **60.66** | **65.34** | **+4.69** |

The "~0.73 points" figure is true of REM only. The gap scales with the stage's
share, so Light — the widest band and the stage that is *already* above its
ceiling on 60 % of nights (HS240-05) — is judged against a band displaced by
**4.69 points on a 14-point band, a third of its width**. On his mean awake
share of 7.06 %, the systematic displacement is proportional to the stage share
throughout.

**Why the decision itself should still stand.** Batch 229 measured that swapping
to Garmin's Duration degrades three of four flags across 429 nights (Light's
in-band nights halve, 130 → 65), because the Batch 61 bands and the
measured-sleep denominator are a matched pair. That is correct and I am not
reopening it. **The right fix is to re-derive the bands on the measured-sleep
denominator, not to change the denominator** — and the deeper problem is
HS240-05: these are PSG norms applied to device stages regardless of which
denominator wins.

**Evidence label.** `proved` (computed on a real stored night).

**Fix shape.** Correct the "~0.73 points" note in STATUS to "stage-dependent,
+0.8 to +4.7 points at his mean awake share", and fold the band re-derivation
into whatever batch acts on HS240-05 — the two are the same piece of work.

---

## HS240-15 — MED · Only readiness got an absolute anchor; the RHR and HRV rails still self-recalibrate, and the trend detector is a step detector

**Where.** `personal_baselines.py:33-38` (`effective_readiness_floor`, anchored
at 60), `:126-137` (`metric_within_baseline_band`, **no anchor**),
`morning_analysis.py:2480-2486` (`_resting_hr_elevated`, keyed on
`upper_quartile_value`, **no anchor**), `morning_analysis.py:2941-2946` (HRV
keyed on Garmin's own rolling `hrv_baseline_low_ms`, **not the app's to anchor**),
`personal_baselines.py:41-101` (`readiness_baseline_trend`).

**This is the health-side reading of coaching finding F1.** Batch 168 closed
half of it: readiness now has an absolute floor of 60 and the code says why. The
other two rails did not get one.

- **Resting HR** is judged entirely against a rolling 84-day Q3. If the
  distribution drifts upward over months — deconditioning, progressing sleep
  apnoea, thyroid, anaemia, a new medication — the ceiling drifts with it and
  `resting_hr_elevated` never fires. Mark's Q3 is currently 45 and his
  distribution is tight, which is exactly the situation in which a drift would be
  most detectable and is not being watched for.
- **HRV** is judged against `hrv_baseline_low_ms`, which is *Garmin's* rolling
  baseline. The app does not own it, cannot anchor it, and does not record when
  it moves.
- **The trend detector is a step detector.** `readiness_baseline_trend` requires
  the recent 42-day median to fall ≥ 5.0 points below the prior 42-day median
  (`READINESS_TREND_DECLINE_POINTS = 5.0`, `personal_baselines.py:14`) with ≥ 21
  samples per half. A steady 4-points-per-42-days slide — 35 points a year —
  never triggers. And it is `verdictImpact: "warning_only"` by design.

**Observed.** Replicating the split over Mark's real data (2026-06-11 → 09-01):
first-half median **59.0** (n = 43), second-half **67.0** (n = 40) — readiness is
*improving* by 8 points, so the detector is correctly quiet. It has never fired,
so nothing about it is `observed` in the positive sense.

**Physiological consequence for Mark.** The classic masters-athlete blind spot
survives on the two rails most likely to carry a genuine multi-year decline. A
slow slide is absorbed as the new normal on the metrics where it would matter
most, and the one alarm that watches for it is designed for a step change and
cannot change the light anyway.

**Evidence label.** `implemented` (anchors absent in code) + `observed` (real
half-window medians, and that the detector has never triggered).

**Fix shape.** Give RHR the same treatment readiness got — a fixed anchor the
personal ceiling cannot rise above, sized from his history (e.g. never treat
above 52 as "in band" regardless of the quartile). Persist Garmin's
`hrv_baseline_low_ms` history so its drift is visible even though the app does
not own it. Add a *ramp* limb to the trend detector — a regression slope over
the 84-day window, not only a half-window step.

---

## HS240-16 — LOW-MED · The VO₂ interval target is probably below the intensity that elicits VO₂max

**Where.** `vo2_progression.py:34` — `VO2_WORK_TARGET = "105-110% FTP"`, applied
to both the 30/30 protocol and the Rønnestad 30/15 (`:47-64`).

**What is questionable.** Rønnestad's short-interval protocol (3 × 13 × 30 s
work / 15 s recovery) is prescribed at *maximal sustainable intensity for the
set*, and in the published work the mean power in the 30-second bouts sits above
the power at lactate threshold and near or above the power at VO₂max — not at
105–110 % of FTP. For a 30-second bout with only 15 seconds of recovery, the
purpose is to accumulate time at ≥ 90 % VO₂max; 105–110 % FTP (294–308 W for
Mark) is roughly 85–92 % of a typical rider's maximal aerobic power, and a
30-second effort at that intensity will not reliably drive VO₂ to maximal values
in the early reps. Common prescriptions for 30/15s sit nearer 115–130 % FTP.

I hold this with genuine uncertainty: the mapping from FTP to MAP varies
20 %+ between riders, and a conservative target for a 57-year-old is a defensible
coaching choice rather than an error. What is not defensible is calling it
"Rønnestad 30/15" while prescribing a materially lower intensity than the
protocol specifies.

**Physiological consequence for Mark.** He may be doing a well-designed
interval *structure* at an intensity that makes it a threshold session rather
than a VO₂ session — a real opportunity cost for the one weekly slot dedicated
to the adaptation that matters most for a masters cyclist.

**Evidence label.** `implemented`. **Hand to Batch 239** for the prescription
half; the physiology half is stated here.

**Fix shape.** Either raise the working target for the short-interval protocols
toward the intensity the protocol specifies, or rename them so the label does
not claim a protocol the prescription does not implement.

**Sound, and worth protecting:** ERG-off on both micro-interval protocols is
correct and well-reasoned — the 30-second surges genuinely arrive faster than a
smart trainer's ERG loop can react.

---

## HS240-17 — LOW · The age credit is a flat +4 on 83 % of nights, and it crossed the Red line on a night Garmin graded every stage POOR

**Where.** `sleep_scoring.py:41-47` (`_POINTS_PER_STEP = 4`,
`_MAX_STEPS_PER_COMPONENT = 2`, `_MAX_CREDIT = 12`).

**Observed** across 182 nights since 2026-03-01:

| credit | nights | mean raw → adjusted |
|---|---|---|
| 0 | 8 | 77.4 → 77.4 |
| **+4** | **151 (83 %)** | 73.9 → 77.9 |
| +8 | 20 | 76.6 → 84.6 |
| +12 | 3 | 67.3 → 79.3 |

Batch 61 replaced the flat +4 with a credit model, and on Mark's real data the
credit model returns **the flat +4 on five nights in six**. That is not a defect
— the structure is principled, the modal answer just happens to coincide — but
it is worth recording that the practical difference is confined to 13 % of
nights.

**Observed — where it matters.** Over the same 182 nights the credit moves
**24 nights (13.2 %) across the Amber→Green line at 74** and **10 nights (5.5 %)
across the Red→Amber line at 60**. Raw-green nights 106 → adjusted-green 130, a
23 % increase.

**The case worth reading.** On **2026-08-30** Garmin graded all four sleep-stage
components **POOR / POOR / POOR / FAIR** and scored the night **57**. The credit
lifted it to **61** — across the app's Red threshold — with morning readiness 43
(LOW) in the same packet. The lift is legitimate on its own terms (his awake
share is age-normal where Garmin's `awakeCount` target is not) but the composite
picture is a night that was bad on every axis being moved off Red by an
age adjustment for having a normal number of awakenings.

**What held.** `sleep_credit_ceiling` (Batch 170/201) is exactly the right
guard and it holds: a raw score below 60 may reach Amber but can never reach
Green, and a raw below 74 needs the complete recovery-plus-check-in bundle. The
24 crossings above are all inside that gate. **This finding is the quantitative
case for why that ceiling must never be relaxed**, not a case against the credit.

**Evidence label.** `observed`.

**Fix shape.** None required to the model. Record the measured crossing rates
next to `sleep_credit_ceiling` so a future batch cannot weaken the ceiling
without seeing what it is holding back.

---

## HS240-18 — LOW · Scope correction: `workload_budget.py` is not a physiological workload budget

`workload_budget.py` is a fail-fast in-process concurrency limiter for paid
Anthropic calls and Piper TTS subprocesses (`_POOL_LIMITS`, `workload_slot`). It
contains no training-load logic. The physiological workload rails this pass was
asked to review live in `morning_analysis._training_load_cap`
(`ACWR_AMBER_CAP_THRESHOLD = 1.5`, `RECOVERY_TIME_AMBER_CAP_MIN = 24 × 60`) and
in `block_progression.py`.

For completeness: `block_progression.py:210-238`'s execution-gated ±3 % FTP
adjustment per 13-week block is physiologically conservative and correctly
signed — it requires the intervals to have actually been ridden (hit-rate ≥ 75 %,
over-rate ≥ 30 %, adherence ≥ 75 %, rising efficiency-factor drift) and pulls
back on poor absorption. `MIN_WORK_INTERVALS = 4` is a thin evidence base for a
block decision, but a 3 % move on 280 W is 8 W, well inside normal
day-to-day variation, so the thinness carries no risk. No finding.

---

## HS240-19 — LOW · Scope correction to the wave's pre-audit finding: SpO₂ survived the model swap; respiration and the experiment section did not

The audit-scope document lists "Respiration, SpO₂, VO₂max, Body Battery charged"
among the content dropped from the first Sonnet 5 brief. Tested directly against
stored `coach.analyses` rows (boolean `ILIKE` probes only — no payload
transferred):

| subject date | model | chars | SpO₂ | respiration | REM | experiments | VO₂ | RHR | awake | deep |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-01 | sonnet-5 | 3,646 | **yes** | **no** | yes | **no** | yes | yes | **yes** | **yes** |
| 2026-08-31 | sonnet-4-6 | 8,482 | yes | yes | yes | yes | yes | yes | yes | yes |
| 2026-08-25 → 08-30 | sonnet-4-6 | 6,836–11,475 | yes (6/6) | yes (6/6) | yes | yes (6/6) | yes | 5/6 | yes | 5/6 |

**Corrections, in the house style.** SpO₂, VO₂max, awake and deep **did** survive
into the 09-01 brief. What did not: **overnight respiration** (present on 7 of 7
preceding briefs, absent on 09-01) and **the entire experiment section** (7 of 7
→ absent). The scope document's characterisation of the sleep-stage loss also
needs narrowing: deep and awake are both present.

This matters to this pass for one reason only: **respiration is one of the two
health signals HS240-03 shows nothing evaluates**, and it has now also stopped
being reported. It went from "shown but unjudged" to "neither shown nor judged"
without anyone deciding that.

---

# What is scientifically sound — protect this

These are the things a future batch must not casually undo. Several of them are
better than the commercial products this app competes with.

**S1 — One denominator, one definition, every consumer.** `REM_PCT_BASIS` and
`SLEEP_STAGE_PCT_BASIS` (`age_norms.py:369-384`) and the single
`rem_sleep_pct()` all consumers take their number from. The Batch 227 reasoning
for choosing measured sleep — *because Batch 61 calibrated all four bands to
it*, not because it is intrinsically better — is exactly the right kind of
argument, and Batch 229 measured the alternative across 429 nights before
rejecting it. Denominator discipline of this quality is rare.

**S2 — `REM_FRAMING_RULE` as one constant, embedded verbatim, pinned by test.**
`age_norms.py:404-416`, imported into both `morning_analysis.py:298` and
`trends.py:130`, asserted identical in `test_batch230_reconcilable_figures.py:229-230`.
The defect it closes is a *cross-surface* one, and the fix is structural rather
than a second paraphrase. The clause forbidding the app from attributing its own
Ohayon band to Garmin is present and correct, and the factual error Batch 230
found — the 08-27 brief calling the app's own 50–59 band "the Garmin flag…a
younger-adult band of 15–23 %" — cannot recur through this path.

**S3 — The credit model's two structural guarantees.** The downgrade guard
(credit is never negative, so the age adjustment can only ever ease a night) and
the calibration guard (an already-optimal night earns exactly zero and
reproduces Garmin's score) are structural rather than bolted-on clamps
(`sleep_scoring.py:30-47`). Swapping the target band without inventing a new
scale is the right move and the docstring explains why.

**S4 — `sleep_credit_ceiling`, quantified.** HS240-17 measures what it holds
back: 24 Amber→Green and 10 Red→Amber crossings over 182 nights. This is the
single most load-bearing sleep guard in the app.

**S5 — Red-never-VO₂ is genuinely hard where it counts.** `blocks_red_vo2`
(`verdict_scaling.py:153-161`) is a pure, unit-testable predicate enforced at
the push gate (`executable_coaching.auto_push_due`) even for
previously-approved proposals. The scoped reversal (Decision #161) — a session
Mark built *himself* is delivered with a warning rather than blocked
(`plan_actions.py:822-849`) — reuses the identical predicate so the threshold
cannot drift. The rule holds exactly as documented: hard for the coach's
prescriptions, advisory for Mark's own builds.

**S6 — Poor readiness really is an unconditional cautious gate.** Verified by
driving the real function: `readiness_level == "poor"` forces at least Amber
before any override can run, and `cumulative_escalation` takes it to Red when a
second recovery signal is negative (`morning_analysis.py:2629, 2650, 2698`).
Batch 61's claim holds. The honest caveat is that Garmin's POOR band on Mark's
data means readiness ≤ 20 — see HS240-01.

**S7 — Refusing to classify what has no defensible band.**
`restless_moments_count` is marked `descriptive_only` with the comment
*"Garmin-proprietary with no defensible population band, so it is shown for
context only and never classified"* (`age_norms.py:128-139`). This is precisely
the posture the rest of the module should adopt toward device-derived stage
percentages, and it shows the judgement already exists in the codebase.

**S8 — `driver_levers`' epistemics, distinct from its statistics.** Everything
in that module *except the thresholds* is right: the antecedence partition as a
concept, `is_unfavourable`, `DRIVER_CONFOUNDS`, and above all the willingness to
return `None` — *"`None` is a real answer and the common one when the evidence
is thin: the caller must then say nothing about levers rather than fall back to
whatever ranked first."* The fan-confound explanation (*"an app that told him
fan speed lifts REM would be worse than one that said nothing"*) is the best
paragraph in the repository.

**S9 — Naming the mechanism honestly where it is real.** The thermal lever's
physiology (`rem_interventions.py:96-115`) is correct: REM is the state in which
thermoregulation is suspended, so late-night warmth is genuinely REM's
vulnerability. The *thresholds* are wrong (HS240-08); the reasoning is not.

**S10 — Personal distribution before population band.** Batch 227's insistence
that a metric with no personal distribution has no honest way to be called low,
and the resulting requirement that a night above his own upper quartile be
described as good even when below the age band, is the correct order of
operations for n-of-1 data and should survive whatever happens to HS240-05.

---

# The three highest-value fixes

**1. Give the verdict an acute-physiology rail, absolutely anchored, independent
of Garmin's readiness category.** One change closes HS240-01, HS240-02 and
HS240-03 and half of HS240-15. Three inputs, all already stored and all already
baselined: (a) resting HR against his own median with an absolute delta floor,
(b) **`hrv_last_night_avg_ms` read as its own signal rather than as a
never-reached fallback**, and (c) an SpO₂/respiration surveillance rule. None of
them should be routed through `readiness_level == "poor"`, which on his data is
reachable on 2.8 % of mornings. This is the difference between a sleep-and-
readiness gate and a health gate, and the app is currently the former while
presenting as the latter.

**2. Audit the REM premise before issuing one more REM intervention.** The
chronic REM deficit is the app's single most repeated claim about Mark's body,
it is 82 % of nights over 185 nights, and it rests on applying PSG-derived
Ohayon norms to a wrist device's stage estimate — while his light sleep runs
above its ceiling by almost exactly the amount his REM runs below its floor, his
deep sleep runs at the *top* of its band, and every other marker he has is
excellent. Test the complementarity hypothesis, state the measurement basis
wherever the band is applied (the same discipline `REM_PCT_BASIS` already
applies to the denominator), and re-derive the bands on the measured-sleep
denominator while you are in there (HS240-14). Do not remove the flag on
suspicion — make it say what it actually knows.

**3. Make the statistics carry the weight the advice puts on them.** Replace the
`moderate`/`high` confidence word with the coefficient's 95 % CI and n, and
refuse to name a lever whose interval crosses zero — which the one lever ever
issued does. Adjust for calendar time before ranking: the partial correlation is
**−0.145** against a raw **−0.235** and a gate of 0.15, so the app's own rule
would have declined to issue it. Apply the same gate on `sleep_projection`,
which today prints an ungated driver to Home, `/sleep` and a push. And raise the
experiment-loop thresholds — 3 nights per arm against a measured SD of 4.43
points cannot distinguish a 2-point effect from nothing, and currently reaches a
directional verdict from noise a quarter to a half of the time.

---

## Limitations

- Every finding about Mark's physiology is drawn from Garmin-derived data, which
  is the point of HS240-05: I am reading the same instrument the app reads, and
  cannot independently verify a single stage percentage.
- The verdict probes drive the real `_morning_verdict` with synthetic inputs
  built to the shape of production rows. They prove what the function does; they
  do not prove any of those inputs has occurred.
- No Anthropic call was made, so nothing about the *prose* the model actually
  produces on any of these packets is tested here — only what the packet
  carries and what the prompt requires. Batch 238 owns that half.
- The production window is constrained by the egress cap. All aggregates are
  server-side; no history window and no JSONB payload column was transferred.
- Literature citations are given to the level of specificity I can support.
  Where the evidence base is genuinely thin — the caffeine/REM link, evening
  exercise, late meals, Garmin-specific PSG validation — I have said so rather
  than inventing precision.
