# Graded verdict replay, 21 Jun – 5 Oct 2026

> **Batch 313's replay, 5 Oct 2026.** Every stored morning, read-only from production, through the code on its branch, then again without the new rest-day rule (`scripts/replay_verdicts.py --compare-without planned_rest_day`). The last section is the batch's acceptance check: the 16 mornings with nothing planned inside a plan week become rest days, and no colour moves under either engine.

Generated 5 Oct 2026 19:41 UTC · read-only replay of 106 stored mornings through today's ladder and the graded verdict, each from the inputs it saw.

## Totals

- **Shown to Mark:** 61 Green, 0 Green (held), 22 Amber, 23 Red
- **Today's ladder:** 55 Green, 5 Green (held), 29 Amber, 17 Red
- **Graded:** 55 Green, 16 Green (held), 28 Amber, 7 Red
- **Changed (ladder → graded):** 30 of 106 mornings
- **Replay reproduces production:** 5 of 5 graded mornings
- **Red rate, graded:** 7% (7)
- **Floors:** no morning is less cautious where a floor applies.

### Ladder → graded

| Ladder \ graded | Green | Green (held) | Amber | Red |
|---|---|---|---|---|
| Green | 50 | 5 |  |  |
| Green (held) | 2 | 2 | 1 |  |
| Amber | 3 | 9 | 17 |  |
| Red |  |  | 10 | 7 |

### What drives the graded colour

- **Autonomic:** marked 14, mild 12
- **Sleep:** marked 17, mild 11 (readiness confirmed 7)
- **Load:** marked 9, mild 5 (readiness confirmed 6)
- **Subjective:** marked 1, mild 2
- **Floors:** bike_rest 2
- **Rough check-ins:** 1
- **Age-credit guard:** 2
- **Missing-data floor:** 0

### Key sessions (VO₂, threshold-type, long ride)

| Outcome | Ladder | Graded |
|---|---|---|
| as planned | 27 | 26 |
| hold targets | 0 | 2 |
| move or hold | 0 | 6 |
| ease hard | 0 | 2 |
| amber cut | 12 | 0 |
| recovery | 2 | 1 |
| off the bike | 1 | 1 |
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
- Autonomic marked: 7-day HRV 42.8 ms is under his usual 47.2 ms by more than the smallest worthwhile change, and last night's 38 ms is under his acute floor of 38.6 ms.
- Sleep mild: Sleep score 62 is fair.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 38 ms is below the acute personal floor of 38.6 ms.

**Tue 21 Jul** — ladder Red → graded Amber
- Autonomic mild: 7-day HRV 42.7 ms is still under his usual 46.8 ms after his holiday, but his last two nights (47 and 47 ms) are back at or above 44.0 ms: the average is catching up, so it counts as a little off.
- Sleep marked: Sleep score 54 is very poor.
- Ladder's reasons: Garmin readiness is Low without complete recovery evidence and a proved-benign load signal to downplay it.; Age-adjusted sleep is below 60.

**Wed 22 Jul** — ladder Amber → graded Green (held)
- Autonomic mild: 7-day HRV 42.9 ms is still under his usual 46.9 ms after his holiday, but his last two nights (47 and 46 ms) are back at or above 44.1 ms: the average is catching up, so it counts as a little off.
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

**Sat 8 Aug** — ladder Green (held) → graded Green
- No domain is raised.
- Ladder's reasons: Garmin moved its HRV floor to 45 ms from a usual 44 ms while last night's reading held at 44 ms, and no other signal disagrees, so the moved floor alone does not cut the session.

**Thu 13 Aug** — ladder Amber → graded Green (held)
- Sleep mild: Sleep score 67 is fair.
- Ladder's reasons: Age-adjusted sleep is below the 74+ green target.

**Sat 15 Aug** — ladder Green → graded Green (held)
- Sleep mild: Sleep score 70 is fair.
- Ladder's reasons: Age-adjusted sleep is soft, but measured HRV, resting HR, readiness, and the current check-in hold the day Green.

**Wed 2 Sep** — ladder Amber → graded Green
- Age credit lifts the sleep score from 68 to 76 (mild to none).
- Ladder's reasons: Sleep, measured HRV, and the current subjective signal clear the green rule.; Age-adjusted sleep reaches the Green line, but the raw Garmin sleep score is below 74 without complete measured recovery and check-in evidence.

**Mon 7 Sep** — ladder Red → graded Amber
- Sleep marked: Sleep score 53 is very poor.
- Ladder's reasons: Age-adjusted sleep is below 60.

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
- Autonomic marked: 7-day HRV 43.6 ms is under his usual 47.4 ms by more than the smallest worthwhile change, and last night's 37 ms is under his acute floor of 39.7 ms.
- Age credit lifts the sleep score from 70 to 74 (mild to none).
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 37 ms is below the acute personal floor of 39.7 ms.

**Tue 22 Sep** — ladder Red → graded Amber
- Autonomic marked: 7-day HRV 43.1 ms is under his usual 47.2 ms by more than the smallest worthwhile change, and last night's 39 ms is under his acute floor of 39.6 ms.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 39 ms is below the acute personal floor of 39.6 ms.

**Wed 23 Sep** — ladder Green (held) → graded Amber
- Autonomic marked: 7-day HRV 43.3 ms has been under his usual 47.1 ms by more than the smallest worthwhile change for 3 mornings in a row.
- Ladder's reasons: Garmin's 7-day HRV average (43 ms) is under its 45 ms floor, but last night's own reading (45 ms) is not, and no other signal disagrees, so the HRV flag alone does not cut the session.

**Fri 25 Sep** — ladder Red → graded Amber
- Autonomic marked: 7-day HRV 43.3 ms has been under his usual 47.1 ms by more than the smallest worthwhile change for 5 mornings in a row.
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.

**Fri 2 Oct** — ladder Red → graded Amber
- Autonomic mild: Last night's HRV 36 ms is under his acute floor of 39.7 ms.
- Sleep marked: Sleep score 55 is very poor.
- Ladder's reasons: Age-adjusted sleep is below 60.; Overnight HRV sets an Amber ceiling: 36 ms is below the acute personal floor of 39.7 ms.

**Mon 5 Oct** — ladder Red → graded Amber
- Autonomic marked: 7-day HRV 39.9 ms is more than 1 SD under his usual 46.3 ms.
- Age credit lifts the sleep score from 71 to 75 (mild to none).
- Ladder's reasons: HRV is below baseline and marked low/unbalanced.; Overnight HRV sets an Amber ceiling: 38 ms is below the acute personal floor of 39.4 ms.

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
| 19 Jul | Red | Red | Amber | MARKED | mild | · | · |  |
| 20 Jul | Red | Green (held) | Green (held) | mild | · | · | · |  |
| 21 Jul | Red | Red | Amber | mild | MARKED | · | · |  |
| 22 Jul | Red | Amber | Green (held) | mild | · | · | · |  |
| 23 Jul | Amber | Amber | Amber | mild | MARKED | · | · |  |
| 24 Jul | Green | Amber | Amber | mild | · | · | · |  |
| 25 Jul | Green | Green | Green | · | · | · | · |  |
| 26 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 27 Jul | Green | Amber | Amber | · | · | MARKED | · |  |
| 28 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 29 Jul | Amber | Amber | Amber | · | · | MARKED | · |  |
| 30 Jul | Green | Green | Green (held) | · | · | mild | · |  |
| 31 Jul | Red | Red | Amber | · | · | MARKED | · |  |
| 1 Aug | Red | Red | Red | mild | MARKED | MARKED | MARKED | bike_rest |
| 2 Aug | Green | Green | Green | · | · | · | · |  |
| 3 Aug | Green | Green | Green | · | · | · | · |  |
| 4 Aug | Green | Green | Green | · | · | · | · |  |
| 5 Aug | Green | Green | Green | · | · | · | · |  |
| 6 Aug | Green | Green | Green | · | · | · | · |  |
| 7 Aug | Red | Red | Red | MARKED | MARKED | · | mild |  |
| 8 Aug | Red | Green (held) | Green | · | · | · | · |  |
| 9 Aug | Green | Green | Green | · | · | · | · |  |
| 10 Aug | Green | Green | Green | · | · | · | · |  |
| 11 Aug | Green | Green | Green | · | · | · | · |  |
| 12 Aug | Amber | Amber | Amber | · | MARKED | · | · |  |
| 13 Aug | Amber | Amber | Green (held) | · | mild | · | · |  |
| 14 Aug | Green | Green | Green | · | · | · | · |  |
| 15 Aug | Green | Green | Green (held) | · | mild | · | · |  |
| 16 Aug | Amber | Amber | Amber | · | MARKED | mild | · |  |
| 17 Aug | Green | Green | Green | · | · | · | · |  |
| 18 Aug | Green | Green | Green | · | · | · | · |  |
| 19 Aug | Green | Green | Green | · | · | · | · |  |
| 20 Aug | Green | Green | Green | · | · | · | · |  |
| 21 Aug | Amber | Amber | Amber | · | · | MARKED | · |  |
| 22 Aug | Green | Green | Green | · | · | · | · |  |
| 23 Aug | Green | Green | Green | · | · | · | · |  |
| 24 Aug | Green | Green | Green | · | · | · | · |  |
| 25 Aug | Green | Green | Green | · | · | · | · |  |
| 26 Aug | Green | Green | Green | · | · | · | · |  |
| 27 Aug | Green | Green | Green | · | · | · | · |  |
| 28 Aug | Red | Red | Red | · | MARKED | MARKED | · |  |
| 29 Aug | Green | Green | Green | · | · | · | · |  |
| 30 Aug | Amber | Amber | Amber | · | MARKED | · | · |  |
| 31 Aug | Green | Green | Green | · | · | · | · |  |
| 1 Sep | Green | Green | Green | · | · | · | · |  |
| 2 Sep | Amber | Amber | Green | · | · | · | · |  |
| 3 Sep | Green | Green | Green | · | · | · | · |  |
| 4 Sep | Amber | Amber | Amber | · | · | MARKED | · |  |
| 5 Sep | Green | Green | Green | · | · | · | · |  |
| 6 Sep | Green | Green | Green | · | · | · | · |  |
| 7 Sep | Red | Red | Amber | · | MARKED | · | · |  |
| 8 Sep | Green | Green | Green | · | · | · | · |  |
| 9 Sep | Green | Green | Green | · | · | · | · |  |
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
| 21 Sep | Red | Red | Amber | MARKED | · | · | · |  |
| 22 Sep | Red | Red | Amber | MARKED | · | · | · |  |
| 23 Sep | Red | Green (held) | Amber | MARKED | · | · | · |  |
| 24 Sep | Red | Amber | Amber | MARKED | · | · | · |  |
| 25 Sep | Red | Red | Amber | MARKED | · | · | · |  |
| 26 Sep | Red | Amber | Amber | MARKED | · | · | · |  |
| 27 Sep | Red | Red | Red | MARKED | MARKED | · | · |  |
| 28 Sep | Green | Green | Green | · | · | · | · |  |
| 29 Sep | Green | Green | Green | · | · | · | · |  |
| 30 Sep | Green | Green | Green | · | · | · | · |  |
| 1 Oct | Amber | Amber | Amber | mild | · | · | mild |  |
| 2 Oct | Amber | Red | Amber | mild | MARKED | · | · |  |
| 3 Oct | Red | Red | Red | MARKED | MARKED | · | · |  |
| 4 Oct | Red | Red | Red | MARKED | MARKED | · | · |  |
| 5 Oct | Amber | Red | Amber | MARKED | · | · | · |  |

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
| `hrv_swc_sd` | 0.5 SD of nightly HRV | the smallest worthwhile change in the HRV-guided trials (Plews 2013; Javaloyes 2019) | A 7-day mean more than half a standard deviation under his normal is a real shift, not noise: mild. For him that is about 2.5 ms. Once it lasts, it is marked (the persistence line below). |
| `hrv_week_marked_sd` | 1 SD of nightly HRV | set just past his worst observed value; no trial source | A week this far down is marked. It was set past his lowest 7-day mean of his first three months (0.83 SD under his normal, 22 Sep), and first fired on 4 Oct 2026, on his holiday's low week (41.3 ms against a line of 41.5). A week-long dip is usually marked by the persistence line first. |
| `hrv_persistence_mornings` | 3 mornings in a row | Javaloyes 2019 and Vesterinen 2016 (a 7-day mean under the smallest worthwhile change made that day low-intensity); Kiviniemi 2007 (a 2-day fall did too); softened by the 1 Oct review | A 7-day mean under his smallest worthwhile change on this many mornings in a row is marked: the dip has lasted. So is one under it with last night under his acute floor, where the week and the night agree. The trials eased the first such morning; he moves or holds for two, then eases (Batch 304). |
| `hrv_catch_up_nights` | 2 nights back in his range | an engineering choice: one night swings about 5 ms; it departs from the trials, which judge the same lagging 7-day mean, only in the 7 days after a holiday | After a holiday the 7-day mean lags his nights. Once his last this-many nights are each at or above the line the reading uses (his normal, or recovery-week normal, minus the smallest worthwhile change), last night was at home and the week holds a night he slept away, a marked week counts as a little off, so a hard session is held at its targets rather than eased (Batch 310, Craig, 4 Oct 2026). It never takes a little off to nothing, and one night under the line ends it. |
| `hrv_recovery_min_nights` | 7 nights | Batch 275 (his recovery-week HRV averages 45.3 ms against 48.1 ms) | In a recovery or taper week his HRV is judged against earlier recovery and taper nights, so the expected dip is not read as strain. With fewer earlier recovery nights than this, his ordinary normal applies. |
| `resting_hr_rise_mild_bpm` | 4 bpm over his median | his own spread: about 1.7 bpm, so 4 is about 2.4 SD | One morning this far up is mild; so are two mornings above his usual range (the review, MD-3), which on its own is no longer a cap. |
| `resting_hr_rise_marked_bpm` | 5 bpm over his median | about 3 SD for him | Marked. 7 bpm or more stays the off-the-bike floor (Batch 293). |
| `sleep_score_mild_below` | 74 age-adjusted sleep score | the app's Green line for sleep (Batch 61) | A fair night is mild. |
| `sleep_score_marked_below` | 60 age-adjusted sleep score | the app's Red line for sleep (Batch 61) | A very poor night is marked, and on its own that is Amber, not Red: easy riding is fine after a poor night and helps rebuild sleep pressure (Batch 215; the review, CO-3). |
| `sleep_duration_window_days` | 84 days | the app's personal-baseline window | His usual total sleep is the nights before this morning over 84 days. |
| `sleep_duration_min_nights` | 21 nights | the app's personal-baseline minimum | Fewer nights than this and total sleep rates nothing. |
| `sleep_duration_mild_sd` | 1.5 SD of his total sleep | set from the replay | About 6.4 hours for him (usual 7.5 ± 0.75 h): mild. Replayed, 11 of 99 nights. |
| `sleep_duration_marked_sd` | 2.5 SD of his total sleep | set from the replay | About 5.6 hours for him: marked. Replayed, 5 of 99 nights, four of them already very poor by the score. |
| `acwr_mild` | 1.3 acute:chronic load ratio | the top of the balanced range the app already uses (Batch 201); the ratio comes from a team-sport injury model (Gabbett 2016) and is contested (Impellizzeri 2020), and Garmin calls up to 1.4 optimal | A ramp above the balanced range is mild. Moving it to 1.5, Garmin's 'high', waits until after 20 Oct 2026, so it does not change his first fortnight back from a holiday unseen (Craig, 3 Oct). |
| `acwr_marked` | 1.5 acute:chronic load ratio | the app's load cap (Batch 167), where Garmin's 'high' starts; contested evidence, as above | A fast ramp is marked, and on its own makes the day Amber. |
| `recovery_time_mild_hours` | 24 hours | Garmin's own estimate, no trial source; the line is the app's load cap (Batch 167) | More than a day of Garmin recovery time left is mild: fine for an easy session, a reason to move a hard one. |
| `recovery_time_marked_hours` | 48 hours | set just past his worst observed value; Garmin's own estimate, no trial source | More than two days left is marked. His highest at wake in three months was 47 hours, so this line has never fired; it is for an unusual debt. |
| `yesterday_hard_mild` | 1 hard day before a hard session | engineering choice, no trial source; it overlaps Garmin's recovery time | A hard day yesterday is mild only when today's session is hard too (Batch 305). Before an easy day it is the recovery his plan set, not something off. Replayed on 3 Oct 2026 it was mild on 17 of 103 mornings; on 5 the day's session was easy, and those now count for nothing. |
| `readiness_confirms_domains` | 1 domain | deliberate extra weight (Craig, 3 Oct 2026); readiness restates his sleep (r 0.69) and recovery time (r -0.72), so it is not independent evidence | Low readiness (Garmin's Low or Poor, or under his own lower quartile) turns this many mild sleep or load domains marked, sleep first, and never votes on its own. It counts that night twice on purpose; replayed on 3 Oct 2026 it decided 3 of 103 colours (21 and 28 Aug, 4 Sep). |
| `feel_window_days` | 84 days | the app's personal-baseline window | His usual feel is his morning check-ins over the 84 days before this one. |
| `feel_min_check_ins` | 14 check-ins | engineering choice | With fewer scored check-ins than this his spread is not yet known, and the fallback lines below apply. |
| `feel_mild_sd` | 1 SD of his feel | the review (his feel tracks his physiology, r 0.4-0.6; Saw 2016) | Feeling a standard deviation below his usual is mild. For him (6.6 ± 1.0) that is 5 or lower. |
| `feel_marked_sd` | 2 SD of his feel | the review | Two standard deviations below is marked: 4 or lower for him. |
| `feel_rough_max` | 3 feel score (0-10) | the check-in's own word for 0-3 (Batch 146) | Rough on its own makes the day Red: only his own taps may relax the day, and this one never relaxes it. |
| `feel_fallback_mild_max` | 5 feel score (0-10) | his own lines on 28 Sep 2026 | Mild when his spread is not yet known. |
| `feel_fallback_marked_max` | 4 feel score (0-10) | his own lines on 28 Sep 2026 | Marked when his spread is not yet known. |
| `long_ride_minutes` | 120 minutes | his plan's long endurance rides (up to 150 minutes) | A ride this long is a key session even at Zone 2. |

## What the rule changes: Batch 313, a day with nothing planned inside a plan week is a rest day

- **Changed:** 0 of 106 mornings
- **Red, without → with:** 7 → 7
- **Ladder (the rollback) changed:** 0 mornings
- **Rest days, without → with:** 11 → 27 (24 Jun, 26 Jun, 29 Jun, 1 Jul, 3 Jul, 24 Jul, 31 Jul, 7 Aug, 14 Aug, 21 Aug, 28 Aug, 4 Sep, 11 Sep, 18 Sep, 21 Sep, 25 Sep)

