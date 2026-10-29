# Batch 340 — strength he can do and the app can see (for Craig's sign-off)

**Signed off by Craig on 29 Oct 2026** ("All as recommended"). Batch 340 lets Mark put this week's Dumbbells A and B on his
watch with one tap, keeps the legs session off the day before VO₂ or a test in the next
plan, adds a small bone-loading element, says how long each session really takes, and
lets the strength read see what he lifted. Every Mark-facing line is below.
`apps/api/tests/test_batch_340_strength.py` holds the app's lines to this file.

**Today:** Plan No. 3 is loaded, with Dumbbells A on Mondays, the day before VO₂. The
placement rule, the hops and the new "why this plan" lines apply to the next plan the
builder drafts (Plan No. 4); Plan No. 3's rows are not rewritten. The watch tap and the
strength read work on Plan No. 3's sessions from the merge.

## 1. "Put this week's dumbbells on your watch" (340.1, FC331-01)

**Where:** a button at the top of Week, shown when this week holds Dumbbells A or B:

> Put this week's dumbbells on your watch

After the tap, one of:

> On your watch after its next sync: Dumbbells A · Mon 02 Nov and Dumbbells B · Sat 07 Nov.

> Already on your watch.

> Couldn't send Dumbbells B · Sat 07 Nov to Garmin. Try again in a minute.

> Couldn't reach Garmin. Try again in a minute.

What it does: the next seven days' Dumbbells A and B go to Garmin Connect as strength
workouts, each scheduled on its own day, so they sync to his watch beside his own
routines. On his watch they are named, for example:

> Dumbbells A · Mon 02 Nov

> Dumbbells B · Sat 07 Nov

Each move is a repeat of its sets: reps (or a 30-second hold for the side plank), then a
minute's rest. A second tap uploads nothing. Nothing is sent on a schedule; only his tap
sends anything.

**Questions for Craig:**
1. Garmin's exercise names for four moves are on record from his own workouts; the rest
   carry Garmin's category only (for example "LUNGE" for the reverse lunge). The first real
   upload, on your go, confirms them.
2. One button on Week, or let Craig set A and B up once by hand instead?

## 2. The legs session, never the day before VO₂ or the test (340.2, FC331-03)

**Where:** the next plan's draft in the builder: Dumbbells A moves to the sweet-spot day,
after the ride (or swaps with B). "Why this plan" says so:

> The legs session is on Thursday, never the day before Tuesday's VO₂ session or the test, so you never ride hard on heavy legs.

## 3. How long a session really takes (340.2, FC331-04)

**Where:** each dumbbell session's description in the plan and the builder.

> … Rest about a minute between sets: about 40 minutes in all.

**Replaces:** "… Rest about a minute between sets." The session's planned minutes (20 or
25) are unchanged: sizing them to the sets would push some weeks past his longest week
and trim his Zone 2 and long rides. **Question for Craig:** keep the planned minutes, or
size them to the sets and let the rides give way (FC331-04's choice)?

## 4. A little impact (340.3, FC331-05)

**Where:** Dumbbells A's moves, and "why this plan".

> … side plank (30 s each side), low hops (2 × 10, soft landings)

> The legs session ends with two sets of low hops, small and with soft landings: riding doesn't load your bones, and a little impact does. The evidence is modest, so they stay small.

**Question for Craig:** whether Mark asks his GP about a bone-density (DXA) scan is yours
to raise; the app says nothing about it.

## 5. His own routines (FC331-07)

**Where:** "why this plan".

> Your daily bodyweight circuit and your mobility routine aren't in the plan because they're yours: keep them as they are.

## 6. The strength read (340.4, FC331-06)

**Where:** the read after a strength session (prompt v8; the model writes the words). It
now sees the exercises, sets and reps his watch recorded, and whether the session was
lifting or a short bodyweight circuit. It calls a circuit "movement maintenance", never
strength building; compares a dumbbell session with that day's prescription and says if a
planned move is missing; and, since his watch records no weights (every recorded weight
is 0), never judges whether he went up a weight.
