# Nights away in the 04:00-waking experiment (Decision #431): what Mark would read, for Craig's sign-off

**Status: DRAFT, waiting for Craig's sign-off. Not merged, not deployed.**

No template wording changes. The fix changes the numbers inside sentences Mark already sees, and in one case which driver the sentence names. Nothing here quotes Mark.

## Where Mark sees it

- **Morning brief, "Experiment update" section (every morning).** The model is told to state the first supplied reason when a result is inconclusive. It paraphrases the reason, for example "the strongest measured driver is your sleep-period stress average".
- **Experiments page, "Evaluate evidence".** It shows the reasons word for word.
- **Coach message "Something changed".** This fires only if the result moves to supported or refuted. Not affected now: the result stays inconclusive.
- **Handover export.** It lists the same reasons.

## The change

Mark's bedroom sensor at home and the weather at home are left out of nights he is on record as away: holiday windows, and check-ins the notes reader read as travel now or last night. The driver correlation already does this (Decision #429). His own measurements (awake time, sleep stress) keep every night.

Replayed from production rows, SELECT only. The replay first reproduced the stored 21 Oct evaluation exactly.

### First reason, as the Experiments page shows it

| | Exact text |
|---|---|
| Today | "Strongest measured driver is sleep_stress_avg (r=+0.41, range +0.25 to +0.55) — a real but weak association, not strong enough to call an identifiable trigger." |
| After the fix, until 3 Nov | "Strongest measured driver is bedroom_peak_fan_speed (r=-0.45, range -0.90 to +0.46) — this window cannot separate it from no association." |
| After the fix, from 4 Nov | Back to sleep stress, unless the fan runs at speed 5 or more again. |

**Why it flips.** The evaluator ranks drivers by the size of their correlation and ignores how many nights each one rests on. Fan peak speed has 10 nights in the window. Two of them (13 and 14 Jul) were July holiday nights, when the fan ran in the empty room. Without them it has exactly the 8-night minimum, and its estimate grows from −0.27 to −0.45, past sleep stress's +0.41 on 121 nights. On 4 Nov, 6 Jul leaves the 120-day window, the driver drops below 8 nights, and sleep stress comes back.

The verdict stays **inconclusive** either way. The brief would say the strongest driver is the fan peaking at 5 or more, and that the window cannot tell it apart from nothing, instead of naming his sleep stress.

### The other candidates (adjusted for time of year)

| Driver | Today | After the fix |
|---|---|---|
| Sleep stress | +0.41 (0.25 to 0.55), 121 nights | unchanged |
| 60+ min above 19.5C | +0.31 (0.13 to 0.46), 118 | +0.08 (−0.12 to 0.27), 104 |
| Bedroom overnight peak | +0.30 (0.12 to 0.46) | +0.11 (−0.09 to 0.30) |
| Bedroom temperature | +0.29 (0.12 to 0.45) | +0.10 (−0.09 to 0.29) |
| 60+ min above 20C | +0.28 (0.10 to 0.44) | +0.05 (−0.15 to 0.24) |
| Bedroom overnight low | +0.27 (0.09 to 0.43) | +0.08 (−0.11 to 0.27) |
| Outdoor overnight low | +0.03, 121 | +0.06, 107 |

The bedroom's apparent link with his awake time was mostly the holidays. The house sat shut and empty at 24–26C on 13–16 Jul while his sleep was measured elsewhere. Every bedroom candidate's range crossed zero once those nights were out.

The grouped sentence the brief can quote changes too: "Nights with 60+ min above 20C average 12.7 min more overnight awake time (42 such nights vs 76 without)" becomes "… 7.8 min more … (31 such nights vs 73 without)".

## What Craig is asked

1. **Sign off the flip as it is.** From the deploy until 3 Nov, the reason names the fan instead of sleep stress, at "cannot separate it from no association". This is my recommendation: it is honest under the current rule, temporary, and the verdict is unchanged.
2. **Or ask for a follow-up batch** that ranks drivers with sample size in mind, for example ranking only drivers whose range excludes zero first. That changes the evaluator beyond nights away, so it is not in this PR.

## Not Mark-visible, changed in the same PR

- **Nightly observation.** On the 10 away mornings since 25 Aug, the 04:00 experiment's nightly entry carried the empty room's 18.6–21.1C and the forecast for home into the morning packet. No brief quoted them. Nights away now record neither. The 10 stored entries are left as they are; nothing reads them.
- **Monthly longitudinal packet.** It is paid, and it goes into an experiment record, not to Mark. The 4 Oct run had 10 away nights among its 101 bedroom nights, including all four of its 24–26C nights; it ignored bands under 5 nights. Without them, the 21–22C band's awake time falls from 34.7 to 25.8 minutes, below the cool bands. As of 22 Oct, the next run (November) would have 14 away nights among 118. No version change, so October's run is not re-bought.
