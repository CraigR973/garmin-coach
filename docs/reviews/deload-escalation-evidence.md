# Deload escalation — what Mark's own data says

**Date:** 2026-08-01 · **Amended:** 2026-08-04 · **Status:** question answered; Finding 3 withdrawn
**Feeds:** Batch 182 (`docs/phase-batches.md`, 2026-08-01 section)

> ## Amendment — 2026-08-04
>
> **Mark answered, and the answer withdraws the actionable half of this document.**
> **Eight of the nine low-training stretches below were holidays** (only 18–21 Jul
> 2025 was a plain training break). The confound flagged in the caveats was not
> hypothetical — it was dominant.
>
> - **Finding 3 (the day-4 inflection) is withdrawn as a basis for action.** It is
>   substantially a travel effect: different bed, later nights, alcohol, broken
>   routine. It should not be used to size a deload.
> - **Finding 2 is weakened for the same reason** — those holiday days populate
>   the low-load bucket that produced the "rest is worse" contrast.
> - **Finding 1 stands untouched.** It concerns one day's physiology and has
>   nothing to do with the stretches.
>
> Mark's own reading is the disciplined one and is recorded here in preference to
> a cleaner conclusion: *"don't think right to say 100% of impact was holiday and
> expect not training would at least have been a factor. In saying this accept
> impossible to establish what % due to holiday and what % to not training which
> means it is more something to monitor going forward."*
>
> Two further corrections came with it, both to readings of Mark's position rather
> than to the data — see **Corrections** at the end.

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

## Answered 2026-08-04 — what these nine stretches were

**The app records no reason for a low-training period.** There is no
holiday/illness/absence table (all 28 `coach` tables checked); holidays exist as
plan state, not as a cause. The entire basis of Finding 3 was therefore nine
stretches whose cause was unknown to the app and to us — so Mark was asked
directly. His answers are in the right-hand column.

| Period | Days | Avg sleep | Avg HRV | Mark's answer |
|---|---|---|---|---|
| 2025-07-18 → 07-21 | 4 | 63.5 | 46.8 | **Not holiday — training break** |
| 2025-08-08 → 08-13 | 6 | 67.0 | 52.0 | Holiday (3 days) |
| 2025-09-13 → 09-17 | 5 | 69.4 | 44.0 | Holiday (14–17 Sep) |
| 2025-09-28 → 10-05 | 8 | 67.8 | 44.6 | Holiday (7 days) |
| **2025-11-16 → 11-25** | **10** | **58.4** | 48.5 | Holiday (7 days) |
| 2026-02-25 → 03-01 | 5 | **75.4** | 44.4 | Holiday |
| 2026-03-11 → 03-15 | 5 | **75.2** | 48.8 | Holiday |
| 2026-04-27 → 05-05 | 9 | 74.0 | **40.2** | Holiday (7 days) |
| 2026-07-12 → 07-17 | 6 | 71.5 | 45.0 | Holiday (4 days) |

**Eight of nine were holidays.** One stretch — the shortest, and the one with the
second-worst sleep — was a plain training break, which is not enough to carry the
finding. The spread that looked like "too wide to be one phenomenon" is better
explained as *different holidays*, not different causes.

Finding 3 is therefore withdrawn as a basis for sizing an intervention. What
remains true and worth keeping: **the question was unanswerable from the data and
had to be asked**, which is itself the argument for recording a reason against
low-training stretches in future (Batch 182.5).

## Corrections — 2026-08-04

Two readings of Mark's position were wrong, both mine, both corrected by him with
evidence. Recorded because each changed the batch design.

**1. "Rearrange" is not "reduce".** His objection was read as being about
week-scale changes in general. It is not — rearranging a week is a tool he uses
deliberately: *"a key tool I currently use so I'm totally bought into it… If I
feel a bit below par on Tues when scheduled to do VO2 I'll swap it with a Z2
workout as doing so preserves integrity of my weekly mix but makes sure I'm doing
each type of workout when my personal feel & metrics support it."* The app's only
chronic lever is a **deload** — 75% duration, a zone drop, no HIT. He is bought
into the intervention we do not offer and objects to the one we do. This became
Batch 182.4.

**2. The assumption that he would train at all costs.** He named it directly:
*"I do think need to be careful that your view that I'll train at all costs
doesn't colour the app."* His counter-evidence: when Copilot designed his current
13-week block it dropped several of the "1" recovery weeks, and **he challenged
it and argued for keeping them** — the AI pushed for more load, not him. This is
corroborated in `plan_blocks`, where W04–W08 run as five consecutive BUILD weeks
with no recovery week between them.

He also clarified that his questions on 31 July were not an attempt to be allowed
to train more, but a check on whether the app understands the 2121 structure —
*"if we are moving into a '1' lighter week anyway, then plan already allowing for
this and it doesn't need to change anything."* That is Batch 182.3, and the 1
August proposal was indeed redundant: `plan_blocks` already scheduled **PN2 W03
RECOVERY for 2026-08-03 → 08-09**, starting two days later.

The design principle these were weighed against still holds — a safety backstop
should not be removable by preference, and the sustained-marker path stays
untouched. Applying that caution *to Mark specifically*, as though he were
looking for permission, was not supported.

**3. He already tells the app.** Asked whether it should prompt for an
explanation on a bad morning: *"Yes it can ask although I'm always likely to tell
it in morning check (which I did on Saturday morning)."* Verified — Saturday's
`manual_entries` row at 08:44 carried `subjective_score` 3, feel *"Have a bit of
a hangover today"* and notes naming 13 UK units and poor sleep; the morning
analysis generated at 08:45:49, **one minute later**, and the escalation used
none of it. Friday's check-in likewise attributed the poor night to *"a harder
day's training yesterday and cumulative 3 day training load"*. The planned
capture surface was therefore dropped: both Reds were already explained in Mark's
own words before either brief ran.

## What this implies for Batch 182

*Revised 2026-08-04 after Mark's answers.*

1. **Read *why* a Red happened** — recovery-debt-with-healthy-markers (expected,
   post-block) vs markers-crashed (genuine acute), **plus the check-in text Mark
   already writes**. Only genuinely unexplained Reds should feed chronic
   escalation. Derivable from stored fields. → Batch 182.2
2. **Know where he is in the plan.** Suppress or narrow a chronic proposal when
   `plan_blocks` already schedules a recovery/taper/consolidation week across the
   horizon. The 1 August proposal was redundant on this test alone. → Batch 182.3
3. **Propose a rearrange, not a reduction.** Swap a hard session for an easier one
   within the week, preserving the weekly mix — the intervention Mark uses and
   wants. Reserve the deload for the sustained path. → Batch 182.4
4. **Leave the sustained-marker path untouched** (≥70% miss over ≥10 samples in a
   ≥21-night window). Genuine chronic evidence, and the backstop stays.
5. **Record why a quiet period happened**, so this question is answerable from
   data next time. → Batch 182.5

**Withdrawn:** scaling the deload to a ~3-day cap (the evidence collapsed), and a
new capture surface for "explained" days (the check-in already carries it).

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
