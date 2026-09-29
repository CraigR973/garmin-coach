# The graded verdict, replayed on every stored morning

29 Sep 2026 · Batch 295 · for Craig's review on Mark's behalf before Batch 296 switches
the colour · read-only: nothing live changed, nothing was written, no paid calls.

**What this is.** The graded verdict (`services/verdict_grading.py`) and today's ladder,
run over all 99 stored mornings (21 Jun to 28 Sep), each from the inputs that morning saw.
"Shown" is the colour Mark got at the time. "Ladder" is today's rules on the same inputs.
"Graded" is what 296 would switch to.

## The answer in numbers

- **Red:** 13 of 99 mornings on today's ladder, **4** graded (21 Jun, 1 Aug, 7 Aug, 28 Aug).
  Each has two domains marked, or he said Rough. That is under one morning in ten, so no
  rule needs naming.
- **Amber:** 28 on the ladder, 24 graded.
- **Green with the targets held:** 5 on the ladder, 23 graded. This is the new middle: one
  mild concern moves a hard session to a better day if there is one, and otherwise keeps
  it with the targets held. An easy day is untouched.
- **Key sessions** (VO₂, threshold-type, long rides), 42 planned. The ladder cut 12 and
  swapped 3 for recovery rides. Graded: 7 move or hold, 4 eased a zone, 2 held, 1 recovery.
- **Floors:** no morning is less cautious where a floor applies. 16 Jul (33 ms, the
  illness-grade night) is still off the bike.

## What changes for him, in his own mornings

- **22 Sep (ladder Red → graded Green, targets held).** Last night's HRV (39 ms) and his
  7-day mean (43 ms against a usual 47) are the same autonomic evidence, one mild domain.
  Sleep 82, feel 7 and load were fine.
- **7 Sep (Red → Amber).** Sleep 53 on its own. One very poor night is marked, which means
  Amber: skip the intensity, keep easy riding.
- **21 Sep (Red → Amber).** HRV mild, plus a sleep score of 70 that only age credit lifts
  to 74. Age credit may not be the only thing between Amber and Green, so it stays Amber.
- **23 Jun and 24 Jun (Amber → Green, targets held).** Resting heart rate above his usual
  range two mornings running is now mild. It no longer caps the day on its own.
- **9 mornings go the other way (Green → Green, targets held):** a hard day yesterday, a
  load ratio above 1.3, or a fair night. Each is one mild concern, noted rather than
  ignored.

## The calls to review before 296 (decided in the build, all in the lines table)

1. **One low HRV night is mild, not marked.** At 1.5 SD it fired on 6 of 75 mornings,
   three by under 1 ms. The illness grade stays marked and a floor.
2. **His 7-day HRV:** mild below 0.5 SD of his normal (the trials' smallest worthwhile
   change, about 2.5 ms), marked below 1.0 SD. Marked has not happened in three months.
3. **Resting HR:** mild at two mornings above usual or +4 bpm, marked at +5, floor at +7.
4. **Total sleep:** mild under about 6.4 h, marked under about 5.6 h (1.5 and 2.5 SD).
5. **Load:** load ratio mild from 1.3, marked from 1.5. Recovery time mild over 24 h,
   marked over 48 h. A hard day yesterday is mild.
6. **Feel:** mild at 5 or less, marked at 4 or less (1 and 2 SD under his 6.6), Red at
   Rough.
7. **Readiness** confirms at most one mild domain (sleep first, then load) and never votes
   alone. It did so on 13 mornings.
8. **Recovery-class weeks hold the session.** That includes consolidation, as the app
   already defines it. **Mark's first two weeks back are W12 CONSOLIDATION and W13
   TAPER,** so from 7 to 20 Oct a mild or marked concern holds a session rather than
   moving or easing it. Red and the floors still apply.

## What the outcomes suggest (directional: one person, about 100 mornings)

- On the 6 mornings where the graded verdict would have eased or moved a hard session
  and he rode it, he hit **58%** of intervals on target, against **72%** on the other 16
  hard sessions. The mornings it flags were weaker mornings.
- The morning after a hard session looked no different whether that morning was flagged
  or not (HRV and resting HR within 1 ms and 1 bpm of his median either way).
- No dissents are recorded yet: the button shipped on 27 Sep and he has been away.

## Limits

- One person and about 100 mornings; correlations and proxies are uncertain.
- The ladder column is today's code on stored inputs, which reproduces the stored colour
  except where later batches changed a rule (mostly Batch 269's).
- A morning's stored packet is the input; rows since re-synced from Garmin are not.

## Running it again

The same tool is the shadow for 296: it replays any window from the stored mornings,
read-only.

```bash
PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python scripts/replay_verdicts.py --start 2026-10-07 --end 2026-10-07
```

---


## Totals

- **Shown to Mark:** 59 Green, 0 Green (held), 19 Amber, 21 Red
- **Today's ladder:** 53 Green, 5 Green (held), 28 Amber, 13 Red
- **Graded:** 48 Green, 23 Green (held), 24 Amber, 4 Red
- **Changed (ladder → graded):** 32 of 99 mornings
- **Red rate, graded:** 4% (4)
- **Floors:** no morning is less cautious where a floor applies.

### Ladder → graded

| Ladder \ graded | Green | Green (held) | Amber | Red |
|---|---|---|---|---|
| Green | 44 | 9 |  |  |
| Green (held) | 2 | 3 |  |  |
| Amber | 2 | 10 | 16 |  |
| Red |  | 1 | 8 | 4 |

### What drives the graded colour

- **Autonomic:** marked 2, mild 19
- **Sleep:** marked 14, mild 11 (readiness confirmed 5)
- **Load:** marked 11, mild 12 (readiness confirmed 8)
- **Subjective:** marked 1, mild 1
- **Floors:** bike_rest 1
- **Rough check-ins:** 1
- **Age-credit guard:** 4
- **Missing-data floor:** 0

### Key sessions (VO₂, threshold-type, long ride)

| Outcome | Ladder | Graded |
|---|---|---|
| as planned | 27 | 28 |
| hold targets | 0 | 2 |
| move or hold | 0 | 7 |
| ease hard | 0 | 4 |
| amber cut | 12 | 0 |
| recovery | 3 | 1 |
| **key sessions planned** | 42 | 42 |

## Every changed morning

**Tue 23 Jun** — ladder Amber → graded Green (held)
- Autonomic mild: Resting heart rate 48 bpm has been above his usual range two mornings.
- Ladder's reasons: Sleep clears the green rule; missing HRV/check-in data is neutral and did not provide positive evidence.; Resting heart rate sets an Amber ceiling: it has been above the personal upper quartile of 45 bpm for two mornings.

**Wed 24 Jun** — ladder Amber → graded Green (held)
- Autonomic mild: Resting heart rate 47 bpm has been above his usual range two mornings.
- Ladder's reasons: Sleep clears the green rule; missing HRV/check-in data is neutral and did not provide positive evidence.; Resting heart rate sets an Amber ceiling: it has been above the personal upper quartile of 45 bpm for two mornings.

**Sat 27 Jun** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 68 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Mon 29 Jun** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 72 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Sat 4 Jul** — ladder Red → graded Amber
- Sleep marked: Sleep score 57 is very poor.
- Ladder's reasons: Age-adjusted sleep is below 60.

**Sun 5 Jul** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 72 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Tue 7 Jul** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 71 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Thu 9 Jul** — ladder Amber → graded Green
- Age credit lifts the sleep score from 66 to 74 (mild to none).
- Ladder's reasons: Sleep and measured HRV clear the green rule; no current subjective check-in was used as positive evidence.; Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score is below 74 without complete measured recovery and check-in evidence.

**Sun 12 Jul** — ladder Green → graded Green (held)
- Sleep mild: Total sleep 6.5 h against his usual 7.5 h.
- Age credit lifts the sleep score from 67 to 75 (mild to none).
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Sun 19 Jul** — ladder Red → graded Amber
- Autonomic mild: Last night's HRV 38 ms is under his acute floor of 38.6 ms.
- Sleep mild: Sleep score 62 is fair.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 38 ms is below the acute personal floor of 38.6 ms.

**Tue 21 Jul** — ladder Red → graded Amber
- Autonomic mild: 7-day HRV 42.7 ms is under his usual 46.8 ms by more than the smallest worthwhile change (2.8 ms).
- Sleep marked: Sleep score 54 is very poor.
- Ladder's reasons: Garmin readiness is Low without complete recovery evidence and a proved-benign load signal to downplay it.; Age-adjusted sleep is below 60.

**Wed 22 Jul** — ladder Amber → graded Green (held)
- Autonomic mild: 7-day HRV 42.9 ms is under his usual 46.9 ms by more than the smallest worthwhile change (2.8 ms).
- Ladder's reasons: HRV is not cleanly in range.; Resting heart rate sets an Amber ceiling: it has been above the personal upper quartile of 45 bpm for two mornings.

**Sun 26 Jul** — ladder Green → graded Green (held)
- Load mild: Load ratio 1.48.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Tue 28 Jul** — ladder Green → graded Green (held)
- Load mild: Load ratio 1.33.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Thu 30 Jul** — ladder Green → graded Green (held)
- Load mild: Load ratio 1.48.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Fri 31 Jul** — ladder Red → graded Amber
- Load marked: Load ratio 1.59.
- Age credit lifts the sleep score from 68 to 76 (mild to none).
- Ladder's reasons: Garmin readiness is Poor; keep the day cautious.; Garmin readiness is Poor and a second recovery signal is negative.; Training load sets an Amber ceiling: acute:chronic load ratio 1.59 is at or above 1.50.; Training load sets an Amber ceiling: Garmin recovery time 43.1 hours is beyond 24 hours.

**Mon 3 Aug** — ladder Green → graded Green (held)
- Load mild: Yesterday was a hard day.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Sat 8 Aug** — ladder Green (held) → graded Green
- No domain is raised.
- Ladder's reasons: Garmin moved its HRV floor to 45 ms from a usual 44 ms while last night's reading held at 44 ms, and no other signal disagrees, so the moved floor alone does not cut the session.

**Thu 13 Aug** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 67 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Sat 15 Aug** — ladder Green → graded Green (held)
- Sleep mild: Sleep score 70 is fair.
- Ladder's reasons: Age-adjusted sleep is soft, but measured HRV, resting HR, readiness, and the current check-in hold the day Green.

**Wed 19 Aug** — ladder Green → graded Green (held)
- Load mild: Yesterday was a hard day.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Wed 26 Aug** — ladder Green → graded Green (held)
- Load mild: Yesterday was a hard day.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Mon 7 Sep** — ladder Red → graded Amber
- Sleep marked: Sleep score 53 is very poor.
- Ladder's reasons: Age-adjusted sleep is below 60.

**Wed 9 Sep** — ladder Green → graded Green (held)
- Load mild: Yesterday was a hard day.
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.

**Fri 11 Sep** — ladder Amber → graded Green (held)
- Load mild: 26 h recovery left.
- Ladder's reasons: Sleep and measured HRV clear the green rule; no current subjective check-in was used as positive evidence.; Training load sets an Amber ceiling: Garmin recovery time 26.2 hours is beyond 24 hours.

**Sun 13 Sep** — ladder Amber → graded Green
- Age credit lifts the sleep score from 68 to 76 (mild to none).
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.; Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score is below 74 without complete measured recovery and check-in evidence.

**Fri 18 Sep** — ladder Green (held) → graded Green
- No domain is raised.
- Ladder's reasons: Garmin moved its HRV floor to 46 ms from a usual 44.5 ms while last night's reading held at 48 ms, and no other signal disagrees, so the moved floor alone does not cut the session.

**Mon 21 Sep** — ladder Red → graded Amber
- Autonomic mild: Last night's HRV 37 ms is under his acute floor of 39.7 ms.
- Age credit lifts the sleep score from 70 to 74 (mild to none).
- Age credit alone would have made the day Green; on the raw sleep score it is Amber, so it stays Amber.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 37 ms is below the acute personal floor of 39.7 ms.

**Tue 22 Sep** — ladder Red → graded Green (held)
- Autonomic mild: Last night's HRV 39 ms is under his acute floor of 39.6 ms.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 39 ms is below the acute personal floor of 39.6 ms.

**Fri 25 Sep** — ladder Red → graded Amber
- Autonomic mild: 7-day HRV 43.3 ms is under his usual 47.1 ms by more than the smallest worthwhile change (2.5 ms).
- Load mild: Yesterday was a hard day.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.

**Sat 26 Sep** — ladder Amber → graded Green (held)
- Autonomic mild: 7-day HRV 43.4 ms is under his usual 46.9 ms by more than the smallest worthwhile change (2.4 ms).
- Ladder's reasons: HRV is not cleanly in range.; Resting heart rate sets an Amber ceiling: it has been above the personal upper quartile of 45 bpm for two mornings.

**Sun 27 Sep** — ladder Red → graded Amber
- Autonomic mild: 7-day HRV 43.7 ms is under his usual 46.8 ms by more than the smallest worthwhile change (2.4 ms).
- Sleep marked: Sleep score 51 is very poor.
- Ladder's reasons: Garmin readiness is Low without complete recovery evidence and a proved-benign load signal to downplay it.; Age-adjusted sleep is below 60.; Resting heart rate sets an Amber ceiling: it has been above the personal upper quartile of 45 bpm for two mornings.

## Every morning

| Date | Shown | Ladder | Graded | Auto | Sleep | Load | Feel | Floor |
|---|---|---|---|---|---|---|---|---|
| 21 Jun | Red | Red | Red | MARKED | MARKED | MARKED | · |  |
| 22 Jun | Amber | Amber | Amber | mild | · | MARKED | · |  |
| 23 Jun | Green | Amber | Green (held) | mild | · | · | · |  |
| 24 Jun | Green | Amber | Green (held) | mild | · | · | · |  |
| 25 Jun | Green | Green | Green | · | · | · | · |  |
| 26 Jun | Amber | Amber | Amber | · | MARKED | · | · |  |
| 27 Jun | Amber | Amber | Green (held) | · | mild | · | · |  |
| 28 Jun | Green | Green | Green | · | · | · | · |  |
| 29 Jun | Amber | Amber | Green (held) | · | mild | · | · |  |
| 30 Jun | Green | Green | Green | · | · | · | · |  |
| 1 Jul | Green | Green | Green | · | · | · | · |  |
| 2 Jul | Green | Green | Green | · | · | · | · |  |
| 3 Jul | Green | Green | Green | · | · | · | · |  |
| 4 Jul | Red | Red | Amber | · | MARKED | · | · |  |
| 5 Jul | Amber | Amber | Green (held) | · | mild | · | · |  |
| 6 Jul | Amber | Amber | Amber | · | mild | · | · |  |
| 7 Jul | Amber | Amber | Green (held) | · | mild | · | · |  |
| 8 Jul | Amber | Amber | Amber | mild | MARKED | · | · |  |
| 9 Jul | Green | Amber | Green | · | · | · | · |  |
| 10 Jul | Green | Green | Green | · | · | · | · |  |
| 11 Jul | Green | Green | Green | · | · | · | · |  |
| 12 Jul | Green | Green | Green (held) | · | mild | · | · |  |
| 14 Jul | Green | Green | Green | · | · | · | · |  |
| 15 Jul | Green | Green | Green | · | · | · | · |  |
| 16 Jul | Green | Amber | Amber | MARKED | mild | · | · | bike_rest |
| 17 Jul | Green | Green | Green | · | · | · | · |  |
| 18 Jul | Green | Green | Green | · | · | · | · |  |
| 19 Jul | Red | Red | Amber | mild | mild | · | · |  |
| 20 Jul | Red | Green (held) | Green (held) | mild | · | · | · |  |
| 21 Jul | Red | Red | Amber | mild | MARKED | · | · |  |
| 22 Jul | Red | Amber | Green (held) | mild | · | · | · |  |
| 23 Jul | Amber | Amber | Amber | mild | MARKED | · | · |  |
| 24 Jul | Green | Amber | Amber | mild | · | MARKED | · |  |
| 25 Jul | Green | Green | Green | · | · | · | · |  |
| 26 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 27 Jul | Green | Amber | Amber | · | · | MARKED | · |  |
| 28 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 29 Jul | Amber | Amber | Amber | · | · | MARKED | · |  |
| 30 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 31 Jul | Red | Red | Amber | · | · | MARKED | · |  |
| 1 Aug | Red | Red | Red | mild | MARKED | MARKED | MARKED |  |
| 2 Aug | Green | Green | Green | · | · | · | · |  |
| 3 Aug | Green | Green | Green (held) | · | · | mild | · |  |
| 4 Aug | Green | Green | Green | · | · | · | · |  |
| 5 Aug | Green | Green | Green | · | · | · | · |  |
| 6 Aug | Green | Green | Green | · | · | · | · |  |
| 7 Aug | Red | Red | Red | mild | MARKED | MARKED | mild |  |
| 8 Aug | Red | Green (held) | Green | · | · | · | · |  |
| 9 Aug | Green | Green | Green | · | · | · | · |  |
| 10 Aug | Green | Green | Green | · | · | · | · |  |
| 11 Aug | Green | Green | Green | · | · | · | · |  |
| 12 Aug | Amber | Amber | Amber | · | MARKED | mild | · |  |
| 13 Aug | Amber | Amber | Green (held) | · | mild | · | · |  |
| 14 Aug | Green | Green | Green | · | · | · | · |  |
| 15 Aug | Green | Green | Green (held) | · | mild | · | · |  |
| 16 Aug | Amber | Amber | Amber | · | MARKED | mild | · |  |
| 17 Aug | Green | Green | Green | · | · | · | · |  |
| 18 Aug | Green | Green | Green | · | · | · | · |  |
| 19 Aug | Green | Green | Green (held) | · | · | mild | · |  |
| 20 Aug | Green | Green | Green | · | · | · | · |  |
| 21 Aug | Amber | Amber | Amber | · | · | MARKED | · |  |
| 22 Aug | Green | Green | Green | · | · | · | · |  |
| 23 Aug | Green | Green | Green | · | · | · | · |  |
| 24 Aug | Green | Green | Green | · | · | · | · |  |
| 25 Aug | Green | Green | Green | · | · | · | · |  |
| 26 Aug | Green | Green | Green (held) | · | · | mild | · |  |
| 27 Aug | Green | Green | Green | · | · | · | · |  |
| 28 Aug | Red | Red | Red | · | MARKED | MARKED | · |  |
| 29 Aug | Green | Green | Green | · | · | · | · |  |
| 30 Aug | Amber | Amber | Amber | · | MARKED | · | · |  |
| 31 Aug | Green | Green | Green | · | · | · | · |  |
| 1 Sep | Green | Green | Green | · | · | · | · |  |
| 2 Sep | Amber | Amber | Amber | · | · | mild | · |  |
| 3 Sep | Green | Green | Green | · | · | · | · |  |
| 4 Sep | Amber | Amber | Amber | · | · | MARKED | · |  |
| 5 Sep | Green | Green | Green | · | · | · | · |  |
| 6 Sep | Green | Green | Green | · | · | · | · |  |
| 7 Sep | Red | Red | Amber | · | MARKED | · | · |  |
| 8 Sep | Green | Green | Green | · | · | · | · |  |
| 9 Sep | Green | Green | Green (held) | · | · | mild | · |  |
| 10 Sep | Green | Green | Green | · | · | · | · |  |
| 11 Sep | Amber | Amber | Green (held) | · | · | mild | · |  |
| 12 Sep | Green | Green | Green | · | · | · | · |  |
| 13 Sep | Amber | Amber | Green | · | · | · | · |  |
| 14 Sep | Green | Green | Green | · | · | · | · |  |
| 15 Sep | Green | Green | Green | · | · | · | · |  |
| 16 Sep | Green | Green | Green | · | · | · | · |  |
| 17 Sep | Green | Green | Green | · | · | · | · |  |
| 18 Sep | Red | Green (held) | Green | · | · | · | · |  |
| 19 Sep | Red | Green (held) | Green (held) | · | mild | · | · |  |
| 20 Sep | Green | Green | Green | · | · | · | · |  |
| 21 Sep | Red | Red | Amber | mild | · | · | · |  |
| 22 Sep | Red | Red | Green (held) | mild | · | · | · |  |
| 23 Sep | Red | Green (held) | Green (held) | mild | · | · | · |  |
| 24 Sep | Red | Amber | Amber | mild | · | · | · |  |
| 25 Sep | Red | Red | Amber | mild | · | mild | · |  |
| 26 Sep | Red | Amber | Green (held) | mild | · | · | · |  |
| 27 Sep | Red | Red | Amber | mild | MARKED | · | · |  |
| 28 Sep | Green | Green | Green | · | · | · | · |  |

## Outcome proxies — directional only

One person, about 100 mornings: these suggest, they do not prove.

- **Hard sessions ridden on mornings the graded verdict would ease or move:** 6.
  - 8 Jul VO₂ (5 × 2 min @ 120%): 1 of 1 work intervals on target, 0 under, 0 faded
  - 23 Jul Sweet Spot (2 × 25 min @ 89%): 0 of 4 work intervals on target, 4 under, 1 faded
  - 28 Jul VO₂ (5 × 3 min @ 119%): 5 of 7 work intervals on target, 2 under, 0 faded
  - 30 Jul Sweet Spot (2 × 25 min @ 89%): 3 of 4 work intervals on target, 1 under, 0 faded
  - 15 Aug Sweet Spot (2 × 30 min @ 89%): 2 of 4 work intervals on target, 2 under, 0 faded
  - 24 Sep Sweet Spot (3 × 20 min @ 89%): 3 of 4 work intervals on target, 0 under, 1 faded
- **On-target share:** 14/24 (58%) on those mornings, 89/123 (72%) across the other 16 hard sessions.
- **The morning after a hard session:** HRV +1.0 ms and resting HR +0.3 bpm against his median when that morning was flagged (7); HRV +0.1 ms and resting HR +0.1 bpm when it was not (15).
- **Dissents recorded:** 0

## The lines

| Line | Value | Source | Why |
|---|---|---|---|
| `hrv_baseline_window_days` | 84 days | the acute HRV rail's window (Batch 246) | His HRV normal is the nights before this morning over the same window the acute rail uses, so there is one definition of his normal. Replayed, 28, 56 and 84 days put 16, 15 and 13 of 75 mornings below the smallest worthwhile change: the choice barely matters, and 84 is the most stable. |
| `hrv_baseline_min_nights` | 21 nights | the acute HRV rail (Batch 246) | Fewer nights than this and his normal is not yet known, so HRV rates nothing. |
| `hrv_week_nights` | 7 nights | Plews 2013; Javaloyes 2019 | The HRV-guided trials judge a 7-day rolling mean, not a single night, because one night swings several ms around his normal. |
| `hrv_week_min_nights` | 4 nights | engineering choice | A week with fewer readings than this is too thin to call a trend. |
| `hrv_swc_sd` | 0.5 SD of nightly HRV | the smallest worthwhile change in the HRV-guided trials (Plews 2013; Javaloyes 2019) | A 7-day mean more than half a standard deviation under his normal is a real shift, not noise: mild. For him that is about 2.5 ms. |
| `hrv_week_marked_sd` | 1 SD of nightly HRV | twice the smallest worthwhile change; set from the replay | A week this far down is marked. His lowest 7-day mean in three months was 0.83 SD under his normal (22 Sep), so this has not fired yet; it is for a genuinely suppressed week. |
| `hrv_recovery_min_nights` | 7 nights | Batch 275 (his recovery-week HRV averages 45.3 ms against 48.1 ms) | In a recovery or taper week his HRV is judged against earlier recovery and taper nights, so the expected dip is not read as strain. With fewer earlier recovery nights than this, his ordinary normal applies. |
| `resting_hr_rise_mild_bpm` | 4 bpm over his median | his own spread: about 1.7 bpm, so 4 is about 2.4 SD | One morning this far up is mild; so are two mornings above his usual range (the review, MD-3), which on its own is no longer a cap. |
| `resting_hr_rise_marked_bpm` | 5 bpm over his median | about 3 SD for him | Marked. 7 bpm or more stays the off-the-bike floor (Batch 293). |
| `sleep_score_mild_below` | 74 age-adjusted sleep score | the app's Green line for sleep (Batch 61) | A fair night is mild. |
| `sleep_score_marked_below` | 60 age-adjusted sleep score | the app's Red line for sleep (Batch 61) | A very poor night is marked, and on its own that is Amber, not Red: easy riding is fine after a poor night and helps rebuild sleep pressure (Batch 215; the review, CO-3). |
| `sleep_duration_window_days` | 84 days | the app's personal-baseline window | His usual total sleep is the nights before this morning over 84 days. |
| `sleep_duration_min_nights` | 21 nights | the app's personal-baseline minimum | Fewer nights than this and total sleep rates nothing. |
| `sleep_duration_mild_sd` | 1.5 SD of his total sleep | set from the replay | About 6.4 hours for him (usual 7.5 ± 0.75 h): mild. Replayed, 11 of 99 nights. |
| `sleep_duration_marked_sd` | 2.5 SD of his total sleep | set from the replay | About 5.6 hours for him: marked. Replayed, 5 of 99 nights, four of them already very poor by the score. |
| `acwr_mild` | 1.3 acute:chronic load ratio | the top of the balanced range the app already uses (Batch 201) | A ramp above the balanced range is mild. |
| `acwr_marked` | 1.5 acute:chronic load ratio | the app's load cap (Batch 167) | A fast ramp is marked, as it caps the day at Amber today. |
| `recovery_time_mild_hours` | 24 hours | the app's load cap (Batch 167) | More than a day of Garmin recovery time left is mild: fine for an easy session, a reason to move a hard one. |
| `recovery_time_marked_hours` | 48 hours | set from the replay | More than two days left is marked. His highest at wake in three months was 47 hours, so this is for an unusual debt. |
| `feel_window_days` | 84 days | the app's personal-baseline window | His usual feel is his morning check-ins over the 84 days before this one. |
| `feel_min_check_ins` | 14 check-ins | engineering choice | With fewer scored check-ins than this his spread is not yet known, and the fallback lines below apply. |
| `feel_mild_sd` | 1 SD of his feel | the review (his feel tracks his physiology, r 0.4-0.6; Saw 2016) | Feeling a standard deviation below his usual is mild. For him (6.6 ± 1.0) that is 5 or lower. |
| `feel_marked_sd` | 2 SD of his feel | the review | Two standard deviations below is marked: 4 or lower for him. |
| `feel_rough_max` | 3 feel score (0-10) | the check-in's own word for 0-3 (Batch 146) | Rough on its own makes the day Red: only his own taps may relax the day, and this one never relaxes it. |
| `feel_fallback_mild_max` | 5 feel score (0-10) | his own lines on 28 Sep 2026 | Mild when his spread is not yet known. |
| `feel_fallback_marked_max` | 4 feel score (0-10) | his own lines on 28 Sep 2026 | Marked when his spread is not yet known. |
| `long_ride_minutes` | 120 minutes | his plan's long endurance rides (up to 150 minutes) | A ride this long is a key session even at Zone 2. |

