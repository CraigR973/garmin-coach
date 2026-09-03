# Batch 250 — The REM premise, audited

**Date:** 2026-09-03 · **Sources:** `HS240-05`, `HS240-10`, `HS240-14`
**Data:** Mark's production database, read-only. Nothing was written.

That Mark has a chronic REM deficit is the most persistent thing this app says
about his body. It has motivated Batch 61's band model, Batch 72's twelve-lever
intervention library, Batch 227's personal baseline, Batch 230's framing rule and
Batch 231's lever engine, and `REM_FRAMING_RULE` deliberately forbids the model
from softening it. Every one of those was built on a premise nothing had ever
tested: that `rem_sleep_sec` from a wrist device measures REM.

This is the test. Both halves were run on stored data, cost nothing, and wrote
nothing.

---

## The answer, first

**Neither hypothesis the review offered is right, and the truth is more useful
than either.**

The REM in Mark's stage series is **architecturally real** — it clusters in the
back half of the night, emphatically and on almost every night. Noise does not do
that. But **the total is probably under-counted**, because the first REM episode
is detected a median of *239 minutes* into the night against a physiological norm
of 70–120, and that first detected episode already averages 17 minutes where
physiology expects the night's shortest. Those are the fingerprints of a detector
that fires only on long, unambiguous REM.

So: the **pattern** is real and may be reported. The **magnitude** has never been
established and should not be reported as though it had been.

---

## Test (a) — Episode architecture

**Method.** Garmin already stores a per-night stage series in
`sleep.raw_payload['sleepLevels']`. Each segment carries `startGMT`, `endGMT` and
an unlabelled `activityLevel` float. Contiguous REM segments are merged into
episodes, and each night's REM minutes are apportioned across the four quarters
of its own span. Implemented in `services/rem_architecture.py`, so the analysis is
re-runnable rather than a one-off script.

**The encoding was proved before it was used.** `activityLevel` is unlabelled, so
the seconds per level were summed and reconciled against the `deep_sleep_sec` /
`light_sleep_sec` / `rem_sleep_sec` / `awake_sleep_sec` columns the app already
trusts. Across the twelve most recent nights every stage agreed to within
rounding — deltas of **0.0 to 0.6 minutes** — fixing the mapping as
**0 = deep, 1 = light, 2 = REM, 3 = awake**. Reading it the wrong way round would
have inverted the entire finding.

**Coverage, and its limit.** The series exists on **215 of 437 nights**, all from
**2026-02-01 onward**; on the other 222 it is JSON `null`. That is not a random
sample — it is everything after a sync change. It is, however, *representative on
the outcome in question*: mean REM is **10.47 %** on the nights with a series
against **9.69 %** on the nights without.

### Results (212 nights carrying at least one REM episode)

| measure | value |
|---|---|
| REM episodes per night | **2.74** (median 3, range 0–6) |
| mean episode length | **19.0 min** (SD 6.5) |
| longest episode | 26.5 min |
| **median REM latency** | **239 min** (physiological norm **70–120**) |
| **mean *first* episode** | **17.2 min** (physiology expects the night's shortest, 1–10) |

**REM by quarter of the night, as a share of that night's REM:**

| quarter | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| mean share | 4.4 % | 11.1 % | **33.6 %** | **50.9 %** |

- **Back half (Q3+Q4): 84.5 %.** **198 of 212 nights are back-loaded.**
- Last episode is the longest: 98/212 (46 %).
- Episodes lengthen through the night: 113/212 (**53 % — a coin flip**).

### Reading

**The clustering settles the noise question.** A monotonic 4.4 → 11.1 → 33.6 →
50.9 ramp across 212 nights, with half the REM in the final quarter, is not
something a random detector produces. The review's rule was "clusters in the back
half **and** lengthens"; the clustering is emphatic and the lengthening is
absent, so the code deliberately decides on the clustering alone —
`architecture_is_real` does not require the lengthening criterion, because
requiring both would discard the signal the data states clearly in order to
honour one the data cannot answer.

**But three facts share one parsimonious explanation, and it is not a deficit.** A
median latency of 239 minutes, a 17-minute "first" episode, and no lengthening
trend are exactly what you would see if short early-night REM episodes were being
missed: the first *detected* episode would be a later, longer one; the night would
look heavily back-loaded; the ramp would be truncated; and the total would be low.

**Part of the long latency is genuine physiology, and it is measured rather than
waved at.** REM latency correlates with the deep-sleep minutes preceding it at
**r = +0.387, 95 % CI +0.266 to +0.496** (n = 212, calendar-adjusted via the Batch
249 gate). High early slow-wave pressure really does delay REM, and Mark's deep
sleep runs high — 17.1 % against the ~11 % Ohayon's own regression predicts at
50–59. But that explains roughly **a sixth** of the variance in latency, not the
gap.

**Evidence label:** `proved` (episode geometry computed from the stored stage
series by the shipped module) + `observed` (coverage, representativeness and the
latency/deep-sleep correlation from production).

---

## Test (b) — Sleep-window truncation

**Question.** Does REM % track sleep end-time and total duration? This also tests
the app's own carried action, *"protect the final 90-minute cycle"*, which has
never been validated.

**Method.** All **437** nights with a REM figure, using stored `sleep_start_utc` /
`sleep_end_utc` and the measured-sleep denominator. Correlations carry the 95 %
intervals Batch 249 installed.

| predictor | outcome | r | 95 % CI | verdict |
|---|---|---|---|---|
| total measured sleep (h) | REM % | −0.021 | −0.115 … +0.073 | crosses zero |
| total measured sleep (h) | REM minutes | **+0.131** | **+0.037 … +0.222** | excludes zero |
| sleep end time | REM % | +0.003 | −0.091 … +0.096 | crosses zero |
| sleep end time | REM minutes | +0.035 | −0.059 … +0.128 | crosses zero |
| sleep start time | REM % | −0.006 | −0.099 … +0.088 | crosses zero |
| sleep start time | REM minutes | +0.032 | −0.062 … +0.125 | crosses zero |

### Reading

**Truncation is not the explanation.** REM % is flat against wake time and against
night length. The only surviving relationship — longer nights contain more REM
*minutes*, r = +0.131 — is arithmetic, and explains 1.7 % of the variance.

**But the lever is not refuted, it is unfalsifiable on his data, and that is a
more useful result.** Mark's sleep end hour has an SD of **0.78 h — 47 minutes** —
and his night length an SD of 0.56 h. There is almost no truncation in the record
to detect. Meanwhile test (a) *confirms the mechanism directly*: **50.9 % of his
REM is in the final quarter of the night**, so cutting the night short really
would cost him REM disproportionately.

The honest statement is therefore: **the mechanism behind `protect_last_cycle` is
confirmed for the first time, and the lever is one Mark already keeps.** It is
graded **A** on evidence and should be read as a standing habit rather than a
change to make.

**Evidence label:** `proved` (correlations with intervals over the full 437-night
record) + `observed` (the dispersion that explains the null).

---

## What was already known, and not re-derived

The composition test was re-checked in one query and **matches the record
exactly**: over **437 nights**, deep **17.1 %**, light **65.5 %**, REM **10.1 %**,
awake **7.4 %**. `remSleepData` is `true` on **all 437** nights, so this is not a
device-capability gap. The prior correlations (light −0.414, awake −0.452, deep
+0.072 against REM %) stand as recorded: awake↔REM being as negative as
light↔REM fits *fragmented nights lose REM* rather than a light/REM labelling
swap, and light being 65 % of the total makes a negative correlation partly
arithmetic. That remains evidence **against** the simple complementarity
hypothesis, not a clean bill of health.

---

## HS240-14 — the band denominator, and why the arithmetic fix was not taken

The Batch 227 close-out recorded the Ohayon gap as "~0.73 points". **That figure
is true of REM alone.** The displacement is proportional to each stage's own
share. Measured across all 437 nights at Mark's mean awake share of **7.37 %**:

| stage | displacement |
|---|---|
| REM | +0.8 |
| deep | +1.4 |
| awake | +0.9 |
| **light** | **+4.7 points on a 14-point band** |

**The arithmetic correction was computed and deliberately not applied.** Rescaling
a band by (1 − awake share) is the *same operation* as moving the value onto the
total-sleep-time denominator — and Batch 229 already measured that swap and
rejected it. Re-measured here on all 437 nights, it degrades the same three flags
again:

| stage | in-band nights, now | in-band, rescaled | change |
|---|---|---|---|
| light | 133 | **66** | halved; above-ceiling 296 → 369 |
| deep | 214 | 218 | above-ceiling 129 → **152** |
| awake | 387 | 368 | above-ceiling 50 → **69** |
| REM | 63 | 75 | below-band 372 → 359 (the only improvement) |

The Batch 61 bands and the measured-sleep denominator are a **calibrated pair**,
and correcting one half of a matched pair is not a correction. So the mismatch is
**stated** rather than silently rescaled — which is the only honest option while
HS240-05 stands, because these are polysomnography norms applied to a wrist
device's stage estimates regardless of which denominator wins.

`age_norms.SLEEP_BAND_BASIS_NOTE` now says so, and travels in the packet beside
the values it judges.

**Evidence label:** `proved` (both classifications computed over the full record).

---

## HS240-10 — the twelve levers, graded

Each lever now carries an `evidence_grade` and a `grade_note` giving the reason.
The grade is on the **stated REM mechanism**, not on whether the action is
sensible — several C and D levers are perfectly good sleep hygiene, and **none was
deleted**.

| grade | levers |
|---|---|
| **A** | `wake_time_anchor`, `protect_last_cycle`, `room_cool_late_cycles`, `rem_rebound_recovery` |
| **B** | `bedtime_hard_stop`, `alcohol_free_evenings` |
| **C** | `caffeine_cutoff`, `evening_light_down`, `wind_down_consistency` |
| **D** | `late_meal_timing`, `stress_offload`, `late_training_guard` |

**Six mechanism claims were rewritten because they were not true:**

- **`caffeine_cutoff`** — caffeine robustly cuts total sleep, efficiency and deep
  sleep, but pooled analyses show no significant REM reduction. Now says so.
- **`wind_down_consistency`** — "REM responds to a steady routine more than to any
  single trick" was invented. Now hedged and marked untested.
- **`late_meal_timing`** — diet-induced thermogenesis cannot "warm your core
  through the REM-heavy early morning"; it dissipates in 3–4 hours.
- **`stress_offload`** — the supporting RCT measured sleep-onset latency, and
  stress is classically linked to *shortened* REM latency. The claim may be
  backwards.
- **`evening_light_down`** — "shallower" REM describes nothing; REM has no depth
  dimension. Now states the circadian-delay mechanism, which is real.
- **`alcohol_free_evenings`** — "even one drink" outran the evidence; low-dose REM
  effects are inconsistent.
- **`late_training_guard`** — contradicted the meta-analytic evidence outright.
  Now asks only for an hour's gap after a hard ride, and says later training is
  otherwise fine.

**The rotation is no longer blind.** Strong (A/B) and weak (C/D) levers rotate on
separate cursors and each week is filled strong-first, so **every week now carries
at least one lever whose mechanism is established** — where previously a week
could hand Mark two invented ones. The full library is still walked before
repeating.

**Evidence label:** `implemented` (library read in full and graded against the
literature).

---

## Open, and deliberately not closed here

**1. The decision that is Craig's, not the app's.** The deficit has *not* proved
to be substantially an artefact — but it has proved **substantially uncertain**,
and that is a materially different message from the one Mark has been given every
morning for months. The app now states the limitation wherever the band is
applied. Whether Mark should be *told explicitly* that the figure it has been
flagging is probably understated by an unknown amount, or whether the wording
should simply become more careful from here, is a judgement about him rather than
about the data.

**2. The organic differential is still missing, and it is still not in this
batch.** HS240-10's sharpest point stands: twelve behavioural levers, and not one
of them is "a chronically low measured REM fraction in a man in his late fifties
is worth mentioning to a GP once." Obstructive sleep apnoea, REM-suppressing
medication and periodic limb movements are absent from the library, the knowledge
base and every prompt. That is clinical-escalation copy of exactly the kind Group
C required Craig to sign off before Batch 246 could ship it, so it is **flagged,
not written**.

**3. Firmware step-change and external EEG validation** were considered and not
taken, as the ledger row specified. The two tests did not disagree — (a) found
real architecture, (b) eliminated truncation as the cause — so the trigger for
revisiting them has not fired. What (a) *did* surface, the latency signature, is
better answered by a single night of external validation than by any further
analysis of this data, and that remains available if Craig wants it.
