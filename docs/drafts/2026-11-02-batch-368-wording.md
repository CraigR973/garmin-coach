# Batch 368 — strength he does, recorded as he does it: the words (for Craig's sign-off)

**Draft, not signed off.** Batch 368 records a dumbbell session as done only when his watch
shows its exercises, progresses his strength within the 5 and 10 kg dumbbells he has
(Decision #462 (7)), counts circuits apart from loaded sessions, swaps loaded strength for
mobility on an off-the-bike morning, and keeps a record of what it puts on his watch.
`apps/api/tests/test_batch_368_strength_as_done.py` holds the app's lines to this file.

## 1. The plan's strength doses, within his kit (368.2)

**Where:** each Dumbbells A and B session's description in the plan (Week, the session card,
the watch), from the next plan the app writes. **Replaces** every "one weight up" (he has one
step, 5 kg to 10 kg) and "an easier weight than last week" (he is already on his lightest).

Recovery and later recovery weeks (2 × 10, 2 × 8):

> light: stop each set with 3–4 reps in reserve

Week 4 (3 × 10), **replaces** "one weight up from week 2; 2 reps in reserve":

> the 10 kg dumbbells if 5 kg felt easy in week 2; 2 reps in reserve

Week 5 (3 × 10), **replaces** "the same weight, or one up if week 4 felt easy":

> the same weight; lower each rep over 3 seconds

Week 7 (3 × 8), **replaces** "one weight up; 2 reps in reserve":

> the harder version of each move you can (rear foot raised on the lunge, one leg on the deadlift); 2 reps in reserve

Week 10 (3 × 6–8), **replaces** "one weight up; 1–2 reps in reserve":

> the harder versions, lowering over 3 seconds; 1–2 reps in reserve

**Plan No. 3's own rows are not rewritten by this batch.** Its remaining rows still say "one
weight up" in weeks 7 and 10 and "an easier weight than last week" in its recovery weeks; a
one-off edit of those rows to the words above is a production write, put to Craig separately.

## 2. An off-the-bike morning (368.4)

**Where:** the plan lines under today's call, on a morning an acute signal rules out riding
(an illness-grade HRV drop, or resting heart rate up 7) and a dumbbell session is planned.
Today it read only "Take today off the bike…", and the session card still asked for his sets.

> Swap today's strength session for gentle mobility: the signal that rules out riding today rules out loaded legs too.

## 3. While a fever follow-up is open (fixes Batch 364)

**Where:** the same plan lines, on a dumbbell day while Home is asking whether his fever has
gone. Batch 364 swapped strength for mobility there but reused the chest follow-up's line,
which says "until you've spoken to your GP or 111". No fever has been reported, so Mark has
never seen it.

> Swap today's strength session for gentle mobility until the fever has gone.

## 4. The watch button on Home (368.5)

**Where:** Home, on a day with Dumbbells A or B still to do. The same button and messages as
Week's (signed off 29 Oct), no new words:

> Put this week's dumbbells on your watch

## Not Mark-facing

- The matcher (368.1) changes what is recorded, not what is said: "Dumbbells A" is completed
  only by a session whose watch recorded a hinge or a lunge (a Romanian deadlift or a lunge),
  never by his upper-body routine or a circuit. The strength read's existing words already say
  when a planned move does not appear.
- The strength read (v9) and the weekly review (v15) are told to give strength frequency from
  loaded sessions and to call circuits movement maintenance (368.3).
