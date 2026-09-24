# Wording to sign off — two new features

Nothing here is live yet. For each part, "fine as is" or say what you'd change.
Where there's a choice, pick one.

---

## Part 1 — Testing a hunch

*Example: "my HRV drops in recovery weeks."* The app can now compare your recovery
weeks with your build weeks on six measures: sleep score, overnight HRV, resting
heart rate, time in bed, REM, and time awake overnight. It only calls a difference
real when it is big enough to matter **and** the data rules out "no difference".

### 1a. What the Experiments page will say

The numbers below are examples, but the wording is exact.

**When it finds a difference**
> Recovery-week overnight HRV averages 40.5 ms vs 47.1 ms on build weeks (−6.6 ms,
> range −10.0 to −3.1) — recovery weeks are worse. Standardised effect −1.15.

**When it's the other way round**
> Recovery-week overnight HRV averages 51.3 ms vs 48.2 ms on build weeks (+3.1 ms,
> range +0.4 to +5.9) — recovery weeks are better, not worse. Standardised effect
> +0.70.

**When it can't tell yet**
> Recovery-week overnight HRV averages 42.9 ms vs 46.7 ms on build weeks (−3.9 ms,
> range −8.9 to +1.2) — the gap is large enough to matter but the range still
> includes no difference, so this window cannot call it. Standardised effect −0.80.

**When the gap is too small to matter**
> Recovery-week overnight HRV averages 46.5 ms vs 47.0 ms on build weeks (−0.5 ms,
> range −1.4 to +0.3) — under the 1.5 ms that would count as a meaningful gap for
> overnight HRV (0.3 of its measured 5.16 ms night-to-night spread), so no
> meaningful difference either way. Standardised effect −0.38.

**When there isn't enough data**
> Need ≥7 nights in each group; have 3 recovery / 7 build.

**Choice:** keep **"Standardised effect"** at the end of each line? It scores the
size of the gap against your normal night-to-night swing: about ±0.5 is modest and
±1 or more is large. Keep it, or drop it?

### 1b. What counts as a meaningful difference

Each measure's cut-off is 0.3 of your own night-to-night swing, measured over your
last 120 days.

| Measure | Smallest gap that counts |
|---|---|
| Sleep score (age-adjusted) | 3 points |
| Overnight HRV | 1.5 ms |
| Resting heart rate | 0.5 bpm (lower is better) |
| Time in bed | 10 min |
| REM sleep | 6 min |
| Time awake overnight | 5 min (lower is better) |

**Question:** do these look sensible to you?

### 1c. What the coach will say in chat (for a later update)

**When it can test something you've said**
> You've said that a few times now, and it's the kind of thing we can actually test
> rather than argue about. I can set it up as a proper **before-and-after**: your
> recovery weeks against your build weeks, on overnight HRV. It needs seven nights
> in each before it'll say anything — that's one full week an arm, because anything
> shorter compares a week against a different part of the same cycle.

**Choice:** "a proper before-and-after" or **"a proper side-by-side"**? It's really a
side-by-side comparison, not a sequence.

**When it can't tell yet**
> Your recovery-week HRV averages 44.0 ms against 47.0 ms on build weeks. That's a
> 3 ms drop, and it's in the direction you described — but the range this window
> still allows runs from −8 to +2 ms, which includes no difference at all. Three
> milliseconds is about six tenths of a typical night-to-night swing for you, so I
> can't call it yet. More cycles would narrow it.

**When it finds a difference**
> Your recovery-week HRV averages 41.4 ms against 47.0 ms on build weeks — a 5.6 ms
> drop, and the range this window allows (−6.8 to −4.4 ms) stays below zero
> throughout. That's a real difference, not noise. You were right.

**When it can't measure what you asked about**
> I can't turn that one into a *test*, though I can still track it — I've no way to
> measure it from what gets synced. I can compare recovery weeks against build weeks
> on your sleep score, HRV, resting heart rate, time in bed, REM, or time awake
> overnight — or look for what a given night's disruption tracks with. Anything
> outside that I'd be guessing at, and a guess dressed up as a result is worse than
> no result.

**Choice:** keep the list of what it *can* measure, or just say "I can't measure
that one" and stop there?

---

## Part 2 — "How these numbers were worked out"

A panel under the brief or weekly review, collapsed until you tap it. It has one
row for each of these numbers that appears on that screen, saying which readings
were used, over which window, and by what rule.

### 2a. Which numbers get it first

These are the numbers that have been argued about:

1. Bedroom peak overnight temperature
2. Average bedroom peak (weekly review)
3. Nights the bedroom disrupted your sleep
4. Your personal HRV floor
5. Work intervals on target

**Question:** are these the right five? Is there any other number you'd want
explained? The sleep-credit ceiling and the readiness floor were left out for now.

### 2b. What the panel says

**Bedroom peak, on a night it got wrong (8–9 Sep)**
> **Bedroom peak overnight — 21.4 °C**
> - **Readings used:** 17 from your bedroom sensor
> - **Window:** 14:07 on 8 Sep → 06:00 on 9 Sep — *a clock window, not your sleep*
> - **Rule:** the highest reading inside the window. No sleep times were recorded for
>   this night, so the window falls back to the clock and **may include hours you
>   were awake**.
> - **Compared against:** 20.0 °C, your disruption threshold
>
> ⚠️ **The first reading in this window is from 14:07** — an afternoon sample, not
> part of your night.

**Bedroom peak, on a normal night**
> **Bedroom peak overnight — 19.1 °C**
> - **Readings used:** 16 from your bedroom sensor
> - **Window:** 22:00 → 06:00 — *the night you actually slept*
> - **Rule:** the highest reading between sleep onset and wake
> - **Compared against:** 20.0 °C, your disruption threshold

**Choices for the bedroom panel:**
- *"a clock window, not your sleep"* (blunt) or *"an estimated window"* (softer, but
  it hides the problem)?
- Keep the ⚠️ warning when a reading falls outside sleeping hours, or drop it?
- Say *"17 readings used"*, or *"17 of 41 readings used"* (more honest, busier)?

**Your HRV floor**
> **Acute personal HRV floor — 39.6 ms**
> - **Nights used:** 47 of your own overnight readings
> - **Window:** the 84 days before this morning, excluding it
> - **Rule:** your own median (46.0 ms) minus 1.5 standard deviations of it. **This
>   is your own floor, not a population band and not Garmin's.**
> - **This morning:** 36 ms — below it

**Choice:** keep *"not a population band and not Garmin's"*? It answers a question
you've asked before, but it reads a little defensive.

**Interval grading**
> **Work intervals on target — 11 of 16**
> - **Boundaries:** the planned-duration clock (Garmin supplied no usable step laps,
>   so a boundary can be out by a few seconds)
> - **Rule:** a sustained effort is graded on **the average power it held across its
>   window, not its peak**. A short effort is graded on its peak and can never be
>   "over". An interval that recorded below the recovery next to it is a
>   segmentation failure, so its grade is withheld rather than counted.
> - **This session:** 11 on target, 2 over, 3 under, 0 ungraded
