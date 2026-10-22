# Batch 347 — wording for Craig's sign-off (22 Oct 2026)

Draft PR stacked on #387. Nothing here merges, deploys or spends until you sign off the exact
words and choose what is regenerated. Mark's own words are not in this public file; the
replayed reads are in the git-ignored scratchpad (`scratchpad/batch-347-replay/`).

## What Mark will see differently

- **Weekly review:** the section "Concerns" is renamed **"Worth watching"**, and holds only what
  is still a concern once a recorded holiday, night away, illness or drink is taken into account.
  A dip such a disruption explains moves to Trends, with its cause and the date it should settle by.
  The review stops using quartiles, "n=" counts, "samples" and internal field names.
- **Weekly review and morning brief:** when a dip in HRV, resting heart rate, sleep or readiness
  falls in a recorded disruption's days or the week after it, the read gives that disruption first
  as the most likely cause, says the date by which his numbers should be back in his usual range,
  and calls it a concern only if they are not. Today's call, its floors and warnings do not change.

## The rule shared by both reads (`coach_policy.KNOWN_DISRUPTION_RULE`)

> recordedDisruptions is what the app has on record as disturbing his recovery
> numbers: a holiday or another night away, illness (a cold, fever or aches, never
> chest or heart symptoms), or alcohol, with the mornings each one covers
> (firstMorning to lastMorning) and settleBy, a week after the last. When a dip in
> his HRV, resting heart rate, sleep or readiness falls between a disruption's
> firstMorning and its settleBy, give that disruption first, as the most likely
> cause, not one possibility among several, and never argue that the timing fails to
> prove it. Say what would confirm it, giving the date: his numbers back in his
> usual range by settleBy. If only part of a dip falls in those days, say so and do
> not stretch it to the rest. Raise a dip as a concern only when it is still there
> after settleBy, or when nothing on record covers it, and never name a disruption
> the record does not hold unless his own words in front of you report it, such as a
> late meal. A disruption explains a number; it never changes the computed call, a
> floor or a warning.

## The morning brief's extra line (graded prompt only)

> recordedDisruptions is separate from verdict.chronicAction's
> bookkeeping: apply the rule above whenever a disruption covers a dip, whatever
> chronicAction says, and name the disruption itself (his holiday, a night away), never the
> record it came from.

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

Added (besides the three rules above):

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

## Replay at no API cost (Decision #424's route)

- The old prompts were rebuilt from `main` and checked against the hash production stored with
  each read; the new runs used the same stored packet plus the new record.
- 1 of 10 planned runs completed before Claude Code's plan limit stopped the rest ("monthly spend
  limit"; session reset 19:10 London): the 11 Oct weekly review on the new prompt.
  - It led with the trip home as the cause of the week's low HRV and slightly raised resting
    heart rate, gave the 13 Oct settle-by date, had no Concerns section and no quartile, "n=" or
    sample count.
  - Two slips, fixed since: it called the settle-by date "the app's settle window", and it listed
    the settling dip under Worth watching while saying it was not a concern.
- Still to run: the 18 Oct review, the 12 and 18 Oct morning briefs, and old-prompt baselines.

## Decisions for you

1. **Sign off these exact words**, or say what to change. The heading "Worth watching" is the
   one literal Mark reads; the rest steers how both reads explain a dip.
2. **Regeneration:** recommended **none** ($0). The first new review is Sun 25 Oct's, and the first
   new brief is the first morning after a merge landing after 11:00 London. Alternatives: rewrite the
   12–18 Oct review (about $0.09) or the latest brief (about $0.12).
3. **The remaining replay runs** need Claude Code's plan limit: wait for the 19:10 reset, or raise it.
