# Nights away on the chronic cards (Decision #429): wording for Craig's sign-off

**Status: DRAFT, waiting for Craig's exact sign-off. Not merged, not deployed.**

These are the new fixed lines Mark can see on the chronic-pattern cards ("Patterns to work on"). The cards appear under Sleep on Home and on the Sleep page. The morning brief's model also reads them from the morning packet, but it writes its own sentences; no prompt changes. Nothing here quotes Mark.

## What changes, in one line each

- Every chronic card gains one line saying how many of its misses fell on nights he recorded as away (a holiday window or a travel check-in), and how the nights at home compare.
- When most of a card's misses were away, its summary says so and names no lever. This drops the bedroom check, and the temperature link is not presented as the main driver.
- The 7-day HRV card counts mornings, not nights: each of its readings is a morning's 7-day average.
- Three bedroom drivers get plain labels; "bedroom mean temp c" was a raw key showing through.
- The driver correlation leaves the bedroom and the weather out of recorded away nights. The template wording is unchanged; its numbers move.
- As a result, the REM card names "bedroom temperature" instead of "time above 20C" (both in Mark's present 120 days).

## Exact wording

`{n}` marks a number filled in from the data.

| When | Exact wording |
|---|---|
| 7-day HRV card, its count (always, replacing "{misses} of {samples} measured nights missed …") | "On {misses} of {samples} mornings the 7-day average missed personal floor {floor}." |
| 7-day HRV card, some misses away | "{a} of those {misses} averages still included nights you recorded as away (a holiday or travel); of the {h} mornings whose whole week was at home, {hm} missed it." |
| 7-day HRV card, none of the misses away | "None of those {misses} averages included nights you recorded as away (a holiday or travel); of the {h} mornings whose whole week was at home, {hm} missed it." |
| Any other card, some misses away | "{a} of those {misses} were nights you recorded as away (a holiday or travel); of the {h} nights at home, {hm} missed it." (one miss: "1 of those {misses} was a night you recorded as away …") |
| Any other card, none of the misses away | "None of those {misses} were nights you recorded as away (a holiday or travel); of the {h} nights at home, {hm} missed it." |
| Summary, 7-day HRV, most misses away | "{label} has repeatedly missed its personal baseline, but mostly around time away: {a} of the {misses} missed averages still included nights you recorded as away. A pattern made mostly of time away says little about home, so no single lever is named." |
| Summary, any other card, most misses away | "{label} has repeatedly missed its {age norm / personal baseline}, but mostly on nights away: {a} of the {misses} misses were nights you recorded as away. A pattern made mostly of time away says little about home, so no single lever is named." |
| Driver label, `bedroom_mean_temp_c` | "bedroom temperature" (was "bedroom mean temp c") |
| Driver label, `bedroom_min_temp_c` | "the bedroom's overnight low" (was "bedroom min temp c") |
| Driver label, `bedroom_max_temp_c` | "the bedroom's overnight peak" (was "bedroom max temp c") |

- **When the line appears:** only when at least one reading in the 28-day window includes a recorded night away. Otherwise every card reads exactly as today, apart from the 7-day count line and the labels.
- **Where it sits:** directly under the count line. It is never cut by the card's three-line limit, the same rule the confounds follow.

## The 18 Oct 2026 cards, replayed through the new code

Replayed from production rows read with SELECT only. The replay first reproduced the stored 18 Oct counts exactly: REM 22 of 28, HRV 18 of 28, latest values 1.2 and 48.

### Protect recovery markers (7-day HRV)

Before, as Mark saw it:

> 7-day average HRV has repeatedly missed its personal baseline; of everything measured, bedroom mean temp c tracks it most closely once the time of year is accounted for — an association in your own data, not a proven cause.
>
> 18 of 28 measured nights missed personal floor 45.
> Latest value: 48.
> Measured over 116 nights: the link is 0.40 on a 0-1 scale, and the range the data still allows (0.23 to 0.54) stays on one side of no effect.
>
> ✓ Check Bedroom before the 22:00 seal point and let Auto hold the pre-cool.
> ✓ Pair the suggestion with today's call; do not chase load.

After:

> 7-day average HRV has repeatedly missed its personal baseline, but mostly around time away: 11 of the 18 missed averages still included nights you recorded as away. A pattern made mostly of time away says little about home, so no single lever is named.
>
> On 18 of 28 mornings the 7-day average missed personal floor 45.
> 11 of those 18 averages still included nights you recorded as away (a holiday or travel); of the 13 mornings whose whole week was at home, 7 missed it.
> Latest value: 48.
>
> ✓ Pair the suggestion with today's call; do not chase load.

On 21 Oct the same card would read "On 15 of 28 mornings …", then "11 of those 15 averages … of the 10 mornings whose whole week was at home, 4 missed it."

### Protect REM consistency (REM, age norm)

8 of its 22 misses were nights away. That is not most, so it keeps a lever and gains one line. The corrected correlation also changes which lever it names: "time above 20C" was the strongest only because of the holiday nights. On 11 of the 13 holiday nights the empty bedroom spent 60+ minutes above 20 °C.

| | REM's closest driver | Nights | Link (range) |
|---|---|---|---|
| Before (stored 18 Oct) | time above 20C | 116 | 0.25 (0.07 to 0.41) |
| After | bedroom temperature | 103 | 0.25 (0.06 to 0.43) |
| After, time above 20C | (now 4th) | 103 | 0.22 |

After:

> REM has repeatedly missed its age norm; of everything measured, bedroom temperature tracks it most closely once the time of year is accounted for — an association in your own data, not a proven cause.
>
> 22 of 28 measured nights missed healthy 50–59 range 15–23%.
> **8 of those 22 were nights you recorded as away (a holiday or travel); of the 19 nights at home, 14 missed it.**
> Latest value: 1.2.
> Measured over 103 nights: the link is 0.25 on a 0-1 scale, and the range the data still allows (0.06 to 0.43) stays on one side of no effect.

- The "Nights with 60+ min above 20C …" line goes: it belongs to a threshold driver, and an average temperature has no threshold.
- The actions keep the same thermal REM lever, because bedroom temperature carries the same affinity.
- The weekly REM rotation already issued for the current week stays as issued (Batch 221).

For the HRV card the corrected link is 0.28 (0.09 to 0.45) over 103 nights, down from 0.40 over 116. It isn't shown while most of the misses are away.

## Decisions made on Craig's behalf (overrule any)

1. **Every card, not just HRV.** The coordinating session approved this on 21 Oct.
2. **What counts as a 7-day reading away:** a morning's 7-day average counts as away if any of the seven nights it averages was away, because that is what the number contains.
3. **Holiday nights:** the evenings from the start date to the day before the end date (Decision #213). He wakes away on 28 Sep–6 Oct; the night he comes home is a home night.
4. **What counts as a travel check-in:** only a reading that says now or last night. There is no paid re-read of notes from before 1 Oct, so the 20→21 Sep night still counts as home.
5. **"Most" means more than half** of the card's misses.
6. **Nothing is subtracted.** The count, the Protect/Watch tone and the deload trigger still use every night, so no caution is removed.
7. **Most misses away → no lever named.** Training load is not named either, because it would come from the same nights.
8. **The correlation leaves out** the bedroom and weather readings on recorded away nights. Load, stress, resting heart rate and the outcomes stay.

## Sign-off

Craig: reply "sign off as written", or give the exact changes.
