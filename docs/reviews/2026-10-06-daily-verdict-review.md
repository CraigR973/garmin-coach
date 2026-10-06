# Review — how the daily call is worked out, explained and used (6 Oct 2026)

> **Work in progress.** This first commit holds only section F, the predictions for the
> 7–20 Oct side-by-side, so they are on record before Mark's first check-in back
> (Wed 7 Oct). The rest of the review follows on this branch. The predictions are not
> edited after this commit; any correction is added below them, dated.

Reviewed at `44274a1` (production health reports the same SHA, 6 Oct 08:2x UTC).
Read-only: no code, production, Railway, Vercel or Supabase change; no paid model call;
nothing sent to Mark.

**Evidence labels** (as in `COACHING_INTEGRITY_AUDIT.md` and the 1 Oct review):
*observed* (production rows, logs or CI), *computed* (arithmetic over production rows),
*proved* (the app's own code run on production inputs, or a test that shows it),
*implemented* (read in the code, not run).

---

## F. Predictions for 7–20 Oct, written before the trial

### How they were made

The real engine was run read-only over Mark's real history to 6 Oct (every morning-phase
HRV and resting-HR row, sleep, check-in feel, baselines, plan blocks, the holiday window
and the plan rows for 7–20 Oct), with hypothetical nights appended from 7 Oct, through the
real acute rails (`_hrv_rail`, `_rhr_rail`), `grade()` and `todays_call()`. The script is
kept beside this review (`docs/reviews/2026-10-06-daily-verdict-review/predict.py`; it reads
only, and its session rolls back). Simplifications, each stated: resting HR, readiness,
sleep and feel are set per scenario; recovery time is 0 and yesterday's load is not hard;
the load ratio is a rough projection of Garmin's (proprietary) model, so it is varied
separately below.

What the engine does **given** a night is *proved*: it is the code's own output. Which
nights he will have is not knowable, so the scenarios bracket it, and the probabilities
in P1–P12 are my judgement, stated so they can be scored.

**Where he starts (observed, 6 Oct):** nightly HRV 38, 36, 39, 37, 38, 38 ms on 1–6 Oct
against a usual of about 46 (his lowest week on record); resting HR 44–47; readiness 50–60
against a lower quartile of 53.8; Garmin's chronic load 291 and falling about 27 a day;
acute load 8. His acute floor for a single night is about 39.3 ms and his illness line
about 34.2 ms. His highest night on record is 60 ms.

### The scenarios, through the real engine (*proved* on hypothetical inputs)

| Morning (plan) | A: nights back to 47 from 7 Oct | B: gradual 41, 43, 45, 47 | C: nights stay 40 to 13 Oct | D: as A, poor night before 8 Oct | E: fair night + readiness 50 on 7 Oct |
|---|---|---|---|---|---|
| Wed 7 (Z2 60) | As planned · Some fatigue | As planned · Some fatigue | As planned · Some fatigue | As planned · Some fatigue | **Short and easy · Still recovering** (Red) |
| Thu 8 (Sweet Spot 1×30 @ 89%) | **As planned — hold the targets** (310 fires) | Take the edge off (89% → 76%) | Take the edge off | **Easy or tempo — your call** (306's card) | As planned — hold the targets |
| Fri 9 (nothing) | Rest day · Recovered | Rest day · Some fatigue | Rest day · Some fatigue | Rest day · Recovered | Rest day · Recovered |
| Sat 10 (Easy Z2 45) | As planned — hold the targets | As planned — hold the targets | As planned · Some fatigue | As planned — hold the targets | As planned — hold the targets |
| Sun 11 (Easy Z2 90) | Green light | As planned — hold the targets | As planned · Some fatigue | Green light | Green light |
| Mon 12 (strength) | Green light | Green light | As planned · Some fatigue | Green light | Green light |
| Tue 13 (VO₂ primer 3×1 @ 120%) | Green light | Green light | **Take the edge off** (120% → 94%) | Green light | Green light |
| Wed 14 (Z2 45) | Green light | Green light | As planned · Some fatigue | Green light | Green light |
| Thu 15 (SS primer 1×12 @ 89%) | Green light | Green light | **Take the edge off** | Green light | Green light |
| Fri 16 (nothing) | Rest day | Rest day | Rest day · Some fatigue | Rest day | Rest day |
| Sat 17, Sun 18 (Z2 40, optional 45) | Green light | Green light | Green light | Green light | Green light |
| Mon 19, Tue 20 (no plan) | **No session planned** | No session planned | No session planned | No session planned | No session planned |

Load ratio sensitivity: with A's nights and a load ratio of 1.35 on 12–15 Oct, those four
mornings become "Green, targets held" and the VO₂ and sweet-spot primers are held at their
targets (no change to what he rides). With C's nights and 1.55 on 12–15 Oct, 12–15 Oct go
Red: the VO₂ primer and the sweet-spot primer become recovery spins and the Z2 is shortened.

### Deterministic predictions (the engine, given his nights)

- **E1. Wed 7 Oct cannot be "Recovered".** His normal for 7 Oct is 46.05 ms, SD 5.13
  (84 nights). His 7-day mean stays under the 1 SD line (40.9 ms) for any night under
  60.4 ms, and under the smallest-worthwhile-change line (43.5 ms), with a streak well past
  three mornings, for any night under 78 ms; his highest night on record is 60. So 7 Oct is
  at least "Some fatigue". The Z2 ride stays at full length unless a second domain is
  clearly off (a sleep score under 60, about 5.6 h or less, a fair night with readiness
  under 53.8, feel 4 or less, resting HR +5): then Red, "Short and easy", Z2 shortened.
- **E2. Thu 8 Oct's sweet spot turns on two nights.** If his HRV on the nights dated 7 and
  8 Oct is each at least about 43.5 ms and nothing else is clearly off, Batch 310 fires for
  the first time: "As planned — hold the targets", ridden at 89%, and the summary reads
  "your HRV is back to normal, but your 7-day average is still catching up after your
  holiday". If either night is under that line, the sweet spot is eased to 76% at full
  length ("Take the edge off"), or, after a poor night or a flat feel, Home shows the pick
  card for the first time ("Easy or tempo — your call").
- **E3. Fri 9 and Fri 16 read "Rest day"** with his reading, never "No session planned".
- **E4. Mon 19 and Tue 20 read "No session planned"** whatever his numbers, because no plan
  is loaded after 18 Oct. The reading chip still shows.
- **E5. The holiday catch-up can act only on 8–12 Oct** (the mornings whose 7-night week
  holds a night away). From 13 Oct a lagging 7-day mean is judged as any other dip: if his
  nights are slow to return (C), the taper's VO₂ and sweet-spot primers are eased on the
  average alone, with a "13 mornings running" streak that counts his holiday.
- **E6. In the taper (12–18 Oct) his HRV is judged against his recovery-week normal**
  (about 45.3 ms, not 46), so the lines sit about 0.8 ms lower.
- **E7. An off-the-bike morning needs a night at or under about 34 ms**, or under about
  39 ms with resting HR up 4 bpm or more, or a symptom. "No training" needs a symptom.

### Probabilistic predictions (my judgement, to be scored)

| # | Prediction | Probability |
|---|---|---|
| P1 | 0–2 Red mornings in 7–20 Oct | 80% |
| P2 | Any Red falls on 7–10 Oct and has readiness confirming a fair night, or a sleep score under 60 | 70% |
| P3 | 8 Oct's sweet spot is held at its targets by the holiday catch-up (E2) | 45% |
| P4 | Autonomic is clear (no HRV concern) on at least one morning by 12 Oct | 70% |
| P5 | 13 Oct's VO₂ primer and 15 Oct's sweet-spot primer are each "Green light" | 65% each |
| P6 | The load ratio never reaches 1.5 in 7–20 Oct, and changes no hard session's action | 85% |
| P7 | Ladder and graded disagree on 2–5 mornings, all one step, the ladder the more cautious; no two-step (ladder Red, graded Green) alert | 70% |
| P8 | The replay reproduces production on every morning he checks in | 95% |
| P9 | Every written brief's "Today's call" opens with the stored headline and reading | 95% |
| P10 | His nightly HRV is back at or above 44 ms on two nights in a row by 9 Oct | 60% |
| P11 | Hard sessions ridden at their targets on "Recovered" or held mornings hit at least 70% of work intervals on target (his norm is 72%) | 65% |
| P12 | No off-the-bike or no-training morning | 90% |

### What would show the engine is wrong, not just unlucky

- A "Recovered" call before a hard session he then fails (under 50% of intervals on target,
  or a post-ride feel 2 or more below his usual), followed by a worse next morning.
- An eased or picked session he rides as written and executes at or above his norm, with a
  normal next morning, two or more times: the caution cost stimulus.
- A Red that rests only on readiness confirming a fair night (311's double count) on a
  morning his own nights are back.
- Any surface (Home, brief, chat, calendar, weekly review) showing a call that differs from
  the stored `todaysCall`.

### The checks a short addendum after 20 Oct should run

1. Replay 7–20 Oct (`scripts/replay_verdicts.py --start 2026-10-07 --end 2026-10-20`):
   "reproduces production N of N", and the disagreements table in STATUS.md.
2. Score E1–E7 and P1–P12 above, one line each: right, wrong, or not tested (and why).
3. For each morning: the stored call, its domains, and which rule decided it (`--compare-without`
   for `hrv_holiday_catch_up` and `hrv_persistence`), so 311 is decided on his return.
4. For each hard session: the call, what he rode (power against target per interval), his
   post-ride feel and effort, and the next morning's HRV and resting HR.
5. Whether readiness confirmation decided any colour (311's question a).
6. Whether the stored brief, Home, chat and the calendar said the same call on every morning.

---

*The rest of the review (sections A–E and G) follows in later commits on this branch.*
