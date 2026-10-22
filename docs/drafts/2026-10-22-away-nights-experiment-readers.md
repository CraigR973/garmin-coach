# Nights away in the 04:00-waking experiment (Decision #431): what Mark would read, for Craig's sign-off

**Status: DRAFT, waiting for Craig's sign-off. Not merged, not deployed.**

No template wording changes. The fix changes some numbers in the evidence the brief can draw on. The first reason Mark reads is word for word unchanged. Nothing here quotes Mark.

## Where Mark sees it

- **Morning brief, "Experiment update" section (every morning).** The model is told to state the first supplied reason when a result is inconclusive. It paraphrases that reason, for example "the strongest measured driver is your sleep-period stress average". The full list of candidates is in the packet the model reads.
- **Experiments page, "Evaluate evidence".** It shows the reasons word for word.
- **Handover export.** It lists the same reasons.
- **Coach message "Something changed".** This fires only if the result moves to supported or refuted. Not affected: the result stays inconclusive.

## The change

1. **Nights away.** The bedroom sensor at home and the weather at home are left out of nights he is on record as away: holiday windows, and check-ins the notes reader read as travel now or last night. The driver correlation already does this (Decision #429). His own measurements (awake time, sleep stress) keep every night.
2. **Order.** A candidate whose range excludes zero is named ahead of one whose range spans zero, however large the second one's estimate. This is the Batch 249 principle: a range across zero cannot say which way it points. Without it, change 1 would have put an 8-night fan link first; see below.

Replayed from production rows, SELECT only. The replay first reproduced the stored 21 Oct evaluation exactly.

### First reason, as the Experiments page shows it

| | Exact text |
|---|---|
| Today | "Strongest measured driver is sleep_stress_avg (r=+0.41, range +0.25 to +0.55) — a real but weak association, not strong enough to call an identifiable trigger." |
| After both changes | Identical: "Strongest measured driver is sleep_stress_avg (r=+0.41, range +0.25 to +0.55) — a real but weak association, not strong enough to call an identifiable trigger." |
| Change 1 without change 2 (not shipped) | "Strongest measured driver is bedroom_peak_fan_speed (r=-0.45, range -0.90 to +0.46) — this window cannot separate it from no association." |

Why the last row would have happened: fan peak speed has 10 nights in the window. Two of them (13 and 14 Jul) were July holiday nights, when the fan ran in the empty room. Without those two it has exactly the 8-night minimum, and its estimate grows from −0.27 to −0.45. That is past sleep stress's +0.41 on 121 nights, but its range still spans zero, so it cannot lead under change 2.

### The other candidates in the evidence (adjusted for time of year)

| Driver | Today | After |
|---|---|---|
| Sleep stress | +0.41 (0.25 to 0.55), 121 nights | unchanged, still first |
| 60+ min above 19.5C | +0.31 (0.13 to 0.46), 118 | +0.08 (−0.12 to 0.27), 104 |
| Bedroom overnight peak | +0.30 (0.12 to 0.46) | +0.11 (−0.09 to 0.30) |
| Bedroom temperature | +0.29 (0.12 to 0.45) | +0.10 (−0.09 to 0.29) |
| 60+ min above 20C | +0.28 (0.10 to 0.44) | +0.05 (−0.15 to 0.24) |
| Bedroom overnight low | +0.27 (0.09 to 0.43) | +0.08 (−0.11 to 0.27) |
| Fan peaked at speed 5+ | −0.27 (−0.79 to 0.48), 10 | −0.45 (−0.90 to 0.46), 8 |
| Outdoor overnight low | +0.03, 121 | +0.06, 107 |

The bedroom's apparent link with his awake time was mostly the holidays. The house sat shut and empty at 24–26C on 13–16 Jul while his sleep was measured elsewhere. Every bedroom candidate's range crosses zero once those nights are out.

The grouped sentence the brief can quote changes: "Nights with 60+ min above 20C average 12.7 min more overnight awake time (42 such nights vs 76 without)" becomes "… 7.8 min more … (31 such nights vs 73 without)".

## What else change 2 can do, now or later

- **It never creates a refutation.** In a window of at most 121 nights, no range that excludes zero is narrow enough to rule out the moderate line.
- **It can give new support only in one case:** a candidate at 0.5 or more with a range clear of zero, sitting behind a larger-looking candidate whose range spans zero. That would now read supported rather than inconclusive, and the "Something changed" message would follow. It does not happen in today's data: sleep stress is +0.41.
- A 4,000-case random check of the old and new orders found exactly these two kinds of difference: the named candidate changed with the verdict staying inconclusive (85 cases), and inconclusive became supported (14 cases).

## What Craig is asked

Sign off that Mark keeps reading the same first reason, with the evidence beneath it no longer counting nights he was away.

## Not Mark-visible, changed in the same PR

- **Nightly observation.** On the 10 away mornings since 25 Aug, the 04:00 experiment's nightly entry carried the empty room's 18.6–21.1C and the forecast for home into the morning packet. No brief quoted them. Nights away now record neither. The 10 stored entries are left as they are; nothing reads them.
- **Monthly longitudinal packet.** It is paid, and it goes into an experiment record, not to Mark. The 4 Oct run had 10 away nights among its 101 bedroom nights, including all four of its 24–26C nights; it ignored bands under 5 nights. Without them, the 21–22C band's awake time falls from 34.7 to 25.8 minutes, below the cool bands. As of 22 Oct, the next run (November) would have 14 away nights among 118. No version change, so October's run is not re-bought.
