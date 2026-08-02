# Deload escalation — what Mark's own data says

**Date:** 2026-08-01 · **Status:** findings complete, one question outstanding with Mark
**Feeds:** Batch 182 (`docs/phase-batches.md`, 2026-08-01 section)

## Why this exists

On 2026-08-01 the app proposed a seven-day easier week off two adjacent Red
mornings. Mark pushed back — not on being told to ease off, which he says he is
"100% bought into", but on the *scale* of the response:

> To totally reschedule a week after the last 2 days just seems severe. […]
> yesterday morning was red as I just completed a block of 3 hard days back to
> back so that was expected, the plan allows for this with rest day […] to
> recommend reschedule after 1 unexpected set of poor metrics for an explainable
> reason that should resolve itself in 24 hours seems severe.

He declined to name a replacement threshold, asking instead that the app work it
out from what it already knows:

> Without copping out I would hope the app could effectively tell me from it's
> knowledge and maybe it's actually right.

And he raised a counter-hypothesis that cuts *against* easing:

> what has factually happened in past is my stats often drop / sleep
> deteriorates when I don't train which then creates a vicious circle. Also
> sometimes pushing to train has in past actually improved stats and sleep
> creating a positive circle / momentum.

This document tests both claims against 404 days of his data (2025-06-24 →
2026-08-01) so Batch 182 is designed on evidence rather than on a guessed
constant. **Sleep, HRV, RHR and readiness are unaffected by the Batch 180
truncation defect** — that defect corrupts `stress_avg` and the Body-Battery
fields only — so the series used here are sound.

## Finding 1 — the two Reds have opposite signatures, and we already store both

| | Tue 28 Jul | Wed 29 | Thu 30 | **Fri 31** | **Sat 1 Aug** |
|---|---|---|---|---|---|
| Training load | 214 (VO2) | 66 (Z2) | 198 (SS) | **0 — planned rest** | **0** |
| Verdict | Green | Amber | Green | **Red** | **Red** |
| Readiness | 76 HIGH | 43 LOW | 65 MOD | **20 POOR** | **27 LOW** |
| Recovery debt | 1 min | 1472 | 831 | **2584 min (43 h)** | 1370 |
| HRV | 53 | 53 | 51 | **52 BALANCED** | **35** |
| RHR | 44 | 44 | 44 | **43 — lowest of window** | **48 — highest** |
| Sleep score | 85 | 70 | 86 | 68 | 51 |
| Sleep stress | 12 | 13 | 13 | 12 | **28** |

Mark's account is accurate in every particular: three consecutive training days
(WO1 VO2 / WO2 Z2 / WO3 sweet-spot), then the plan's rest day, which he took.

- **Friday's Red is entirely training debt.** Readiness 20 is driven by a 43-hour
  recovery timer earned on Thursday. The systemic markers were *good* — HRV 52
  (balanced, mid-to-high for him) and RHR 43, his lowest of the fortnight.
- **Saturday's Red is a genuine systemic hit.** HRV collapsed 52 → 35 (his lowest
  in the window by a distance), RHR jumped 43 → 48, sleep stress 12 → 28. Cause
  known to Mark (drinking), invisible to the app.

**Neither indicates chronic overreaching, and the two are trivially separable
from fields already on `daily_metrics`.** `_chronic_action_signal`
(`chronic_patterns.py:636-691`) reads none of them — it counts the string "Red"
twice inside seven days (`CHRONIC_ACTION_RED_THRESHOLD = 2`) and escalates. This
is the clearest actionable finding here and needs nothing further from Mark.

## Finding 2 — his recovery markers are *worst* after rest, not after training

Every day bucketed by mean training load over the preceding three days:

| Prior 3-day load | Days | Sleep | HRV | RHR | Readiness |
|---|---|---|---|---|---|
| Rest-ish (<30) | 55 | **68.5** | **44.7** | **45.0** | 56.9 |
| Light (30–90) | 243 | **73.3** | **49.0** | 44.4 | 55.5 |
| Moderate (90–150) | 96 | 72.5 | 48.2 | 44.8 | 44.2 |
| Hard (150+) | 9 | 69.4 | 52.4 | 44.0 | 35.4 |

His worst sleep and lowest HRV follow *rest*; his best follow *light training*.

**Readiness moves the opposite way (57 → 44 → 35) and this is mechanical, not
physiological** — readiness is dominated by the recovery timer, so it falls with
load by construction. This matters a great deal: **readiness measures training
debt, while HRV/RHR/sleep measure systemic state, and for Mark they point in
opposite directions.** The Red verdict keys off the former; the escalation then
prescribes more of exactly the thing the latter says costs him.

The `hard` row (n=9) is too small to lean on.

## Finding 3 — within a low-training stretch, day 4 is where it turns over

Runs of ≥4 consecutive days with training load <30, indexed by position in the run:

| Day of stretch | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| n | 9 | 9 | 9 | 9 | 8 | 5 |
| Sleep | 69.1 | 69.9 | **74.4** | 67.3 | **61.5** | 71.2 |
| HRV | 48.8 | 47.7 | **49.0** | 45.7 | **43.4** | 43.8 |
| RHR | 44.4 | 43.7 | **43.4** | 44.6 | 44.9 | 44.0 |

Days 1–3 read as genuine recovery — sleep and HRV rise, RHR falls. From day 4 it
reverses: sleep −13 points and HRV −5.6 ms by day 5. The inflection sits exactly
where a seven-day easier week would be doing its work.

This cut is less vulnerable to reverse causality than Finding 2 (the run has
already begun; the decline happens as it continues) but see the caveats.

## Caveats — read before acting on any of this

1. **Correlation, not causation**, throughout.
2. **Reverse causality is live.** Mark may train less *because* he already feels
   poor. Worse for Finding 3: a run may *extend* because he is still unwell, so
   later days are enriched for "still ill" rather than "harmed by rest".
3. **n is 5–9 per cell in Finding 3.** Suggestive, not conclusive.
4. **The stretches are heterogeneous** — see below. Averaging them into one curve
   may be blending three different phenomena.

Findings 2 and 3 are *consistent with* Mark's belief, and nothing in the data
supports the opposite. That is the honest summary; it is not proof.

## Outstanding question for Mark — what were these nine stretches?

**The app records no reason for a low-training period.** There is no
holiday/illness/absence table (all 28 `coach` tables checked); holidays exist as
plan state, not as a cause. So the entire basis of Finding 3 is nine stretches
whose cause is unknown to the app and to us.

| Period | Days | Avg sleep | Avg HRV |
|---|---|---|---|
| 2025-07-18 → 07-21 | 4 | 63.5 | 46.8 |
| 2025-08-08 → 08-13 | 6 | 67.0 | 52.0 |
| 2025-09-13 → 09-17 | 5 | 69.4 | 44.0 |
| 2025-09-28 → 10-05 | 8 | 67.8 | 44.6 |
| **2025-11-16 → 11-25** | **10** | **58.4** | 48.5 |
| 2026-02-25 → 03-01 | 5 | **75.4** | 44.4 |
| 2026-03-11 → 03-15 | 5 | **75.2** | 48.8 |
| 2026-04-27 → 05-05 | 9 | 74.0 | **40.2** |
| 2026-07-12 → 07-17 | 6 | 71.5 | 45.0 |

The spread is too wide to be one phenomenon: November has his worst sleep of the
set, the two spring stretches his best. **If most were illness or travel, the
deterioration is caused by being ill or away from home and Finding 3 collapses.**

Raised with Mark 2026-08-01; he asked to discuss in person rather than by
message. **Do not encode a duration cap until this is answered.**

A second, scope-level question is also outstanding: whether he ever wants a
week-scale proposal at all, or would rather the app flag "this looks like more
than a blip" and leave the decision to him.

## What this implies for Batch 182

1. **Read *why* a Red happened** — recovery-debt-with-healthy-markers (expected,
   post-block) vs markers-crashed (genuine acute). Only the second should feed
   chronic escalation. Derivable from stored fields; **unblocked**.
2. **Scale the intervention to the evidence.** Findings 2–3 suggest the useful
   deload for Mark is short, not a week. **Blocked** on the stretch question.
3. **Leave the sustained-marker path untouched** (≥70% miss over ≥10 samples in a
   ≥21-night window). That is genuine chronic evidence. Softening it on the
   strength of "Mark believes rest hurts him" would convert a safety mechanism
   into a lever for avoiding recovery — the integrity line this work must hold.
4. **Keep a manual "explained" marker** for what the app cannot see. Saturday
   needed one; Friday did not.
5. **Prefer showing the reasoning to hiding a constant.** Mark asked the app to
   tell him from its knowledge. A proposal that shows him this curve is both more
   honest and closer to what he asked for than a silent `3`.

Nothing here may alter today's deterministic Green/Amber/Red verdict — this
governs *chronic escalation only* (verdict-engine safety rule).

## Reproduction

Read-only against prod (`coach` schema). Finding 2:

```sql
with days as (
  select m.calendar_date as d, m.user_id,
         coalesce((select sum(a.training_load) from coach.activities a
                   where a.user_id=m.user_id and (a.start_utc)::date = m.calendar_date),0) as load,
         m.readiness_score, m.hrv_last_night_avg_ms as hrv, m.resting_heart_rate_bpm as rhr
  from coach.daily_metrics m
), ctx as (
  select d.*, s.score as sleep,
         (select round(avg(x.load)::numeric,0) from days x
          where x.user_id=d.user_id and x.d between d.d - 3 and d.d - 1) as prior3_avg_load
  from days d
  left join coach.sleep s on s.calendar_date=d.d and s.user_id=d.user_id
)
select case when prior3_avg_load < 30 then 'rest-ish' when prior3_avg_load < 90 then 'light'
            when prior3_avg_load < 150 then 'moderate' else 'hard' end as bucket,
       count(*), round(avg(sleep),1), round(avg(hrv),1), round(avg(rhr),1),
       round(avg(readiness_score),1)
from ctx where prior3_avg_load is not null group by 1 order by 1;
```

Finding 3 uses the same `days` CTE with a gaps-and-islands grouping on
`load < 30` (`row_number()` difference), filtered to runs of length ≥4, then
averages by `row_number()` within each run.
