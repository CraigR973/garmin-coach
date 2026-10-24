# Batch 347 — wording for Craig's sign-off (22–23 Oct 2026)

Draft PR #390, stacked on #387. Nothing here merges or deploys until you sign off the exact
words. You chose on 23 Oct to regenerate nothing. Mark's own words are not in this public file;
the replayed reads are in the git-ignored scratchpad (`scratchpad/batch-347-replay/REPORT.md`).

## What Mark will see differently

- **Weekly review:** "Concerns" is renamed **"Worth watching"**, and holds only what is still a
  concern once a recorded holiday, travel or night away, illness or drink is taken into account.
  A dip such a disruption explains goes under Trends, with its cause and the date it should settle by.
  The review stops using quartiles, "n=" counts, "samples" and internal field names.
- **Weekly review and morning brief:** when a dip in HRV, resting heart rate, sleep or readiness
  falls in a recorded disruption's days or the week after it, the read says first and plainly that
  the disruption is the most likely cause, gives the date by which his numbers should be back in
  his usual range, and calls it a concern only if they are not. Today's call, its floors and
  warnings do not change.

## The rule shared by both reads (`coach_policy.KNOWN_DISRUPTION_RULE`)

> recordedDisruptions is what the app has on record as disturbing his recovery
> numbers: a holiday, travel or another night away, illness (a cold, fever or aches,
> never chest or heart symptoms), or alcohol, with the mornings each one covers
> (firstMorning to lastMorning) and settleBy, a week after the last. When a dip in
> his HRV, resting heart rate, sleep or readiness falls between a disruption's
> firstMorning and its settleBy, say first and plainly that it is the most likely
> cause. Do not argue it down from when the dip began, or hedge it with causes no
> record points to. Say what would confirm it, giving the date: his numbers back in
> his usual range by settleBy. Say it as a coach would, never as a rule or a window
> the app applies. If only part of a dip falls in those days, say so and do not
> stretch it to the rest. Raise a dip as a concern only when it is still there after
> settleBy, or when nothing on record covers it, and never name a disruption the
> record does not hold unless his own words in front of you report it, such as a
> late meal. A disruption explains a number; it never changes the computed call, a
> floor or a warning.

Its key sentences follow v27 draft 2 (PR #387).

## The morning brief's extra note (graded prompt only)

> recordedDisruptions is separate from verdict.chronicAction's
> bookkeeping: apply the rule above whenever a disruption covers a dip, whatever
> chronicAction says, and name the disruption itself (his holiday, a night away), never the
> record it came from. A chronic suggestion's count of missed nights is a dip on those
> nights, even when today's numbers are back: when its 28 nights take in a disruption's
> mornings or the week after it, say first that the disruption is the most likely cause of
> that part of the count. Where the call already gives the domain behind a number, such as
> training load for readiness, keep that reason for that number.

## The weekly review's plain-words rule (`reviews.REVIEW_PLAIN_WORDS_RULE`)

> Write to Mark in plain training words. The span from a
> personalBaselines lowerQuartile to its upperQuartile is his usual range: say "below your
> usual range" or "higher than usual for you", never quartiles, percentiles, medians or
> standard deviations. Say in words how many mornings, nights or rides a figure rests on
> ("over four mornings"), never "n=" or "samples", and give a change as a plain figure
> ("about 3% lower across 23 rides"). Say what a count or a status found rather than its
> label: "one morning the plan held as written", never heldDays or an early-warning status.
> Never write deterministic, verdict, UTC, Green, Amber or Red.

The review prompt also embeds the existing read-prompt rule word for word:

> Packet field names are instructions to you, never words for Mark: never print
> a field, key or path in the output and never cite the packet as a source;
> state the fact itself.

## Sentences changed in the weekly review prompt

Removed:

- Then write markdown with four bolded sections — **Trends**, **Wins**, **Concerns**, and **Recommendations** — each a short bullet list grounded in the packet's numbers.
- When sample counts are low or coverage is incomplete, say so rather than overstating a trend.
- Any trend claim must cite the packet's from-to numbers and sample counts.
- Report both plainly — they measure whether caution is costing him training — and never name a cause rollup.cautiousDays does not list.

Added (besides the rules above):

- Then write markdown with four bolded sections — **Trends**, **Wins**, **Worth watching**, and **Recommendations** — each a short bullet list grounded in the packet's numbers.
- Worth watching holds only what is still a concern once recordedDisruptions is taken into account, never a dip a recorded disruption explains (that belongs under Trends, with its cause);
- when nothing is, say so in one line.
- When a figure rests on few mornings or nights, or coverage is incomplete, say so rather than overstating a trend.
- Any trend claim must give the packet's from-to numbers and say in words how many mornings or nights they rest on.
- Report both plainly — they measure whether caution is costing him training — and never name a domain rollup.cautiousDays does not list;
- a recorded disruption that covers those mornings may be named as the likely reason those domains were off.

## What counts as a recorded disruption

- A holiday he entered, by the mornings he woke away (27 Sep–6 Oct covers the mornings of
  28 Sep to 6 Oct). Settle-by: a week after the last morning.
- Travel, alcohol or illness his check-in note reports for now or last night. A note that places
  it earlier ("post holiday") does not count.
- Illness he gives as his answer to the symptom question.
- Illness means a cold, fever or aches, never chest or heart symptoms (your definition, 22 Oct).
  A note that says only that he feels unwell does not count, so such a dip stays a concern.
- A late meal is recorded nowhere: the brief can use one only when today's note mentions it,
  and the review never sees one.

## Replay at no API cost (12 runs, Decision #424's route)

- **Weekly reviews (11 and 18 Oct): fixed.** Every new run gives the holiday first with its
  13 Oct date, uses Worth watching, and has no quartile or "n=" count. One 18 Oct run limits the
  holiday to 12–13 Oct exactly; the other stretches it to the week's first three mornings. The
  old prompt, replayed the same way, repeats production's Concerns, jargon and silence on the holiday.
- **12 Oct brief:** links both 28-night cards to the holiday for part of their count, with the
  13 Oct check, and keeps training load as the call's reason for low readiness.
- **18 Oct brief: not fixed by this batch alone.** No run names the holiday: the recovery-markers
  card still reads as bedroom temperature, with no per-night split, and his HRV was back that
  morning. PR #388's rewrite of that card (signed off) is the missing half. The run testing both
  together was not started: the weekly plan allowance reached your 85% stop.
- **Slips seen once each:** a colour ("a Red morning") in one 12 Oct brief, the holiday dated from
  its first morning away, "a decent sample size", "settle window".

## Decisions for you

1. **Sign off these exact words**, or say what to change. "Worth watching" is the one heading Mark
   reads; the rest steers how both reads explain a dip.
2. **The colour slip:** the private report proposes rewording the brief note's first sentence so it
   no longer points at the structural signal. It is untested; change it now or after a test run?
3. **Merge timing:** merge after #387 and #388, or wait for the combined 18 Oct run (the allowance
   resets Sun 25 Oct 18:00 London).
