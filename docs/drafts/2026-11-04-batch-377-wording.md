# Batch 377 — 369's follow-up: the words (for Craig's sign-off)

Batch 369 shipped as provisional at 4 of 5 replayed mornings. In its fourth replay the brief
put the readiness line inside Today's call on 28 Oct and said it again on 1 Nov, when it was
not due; "autonomic" and "domain" survived v67's two rules against them; asked to trim a
long call to 110 words, the fix-up call left 2 of 6 over 120; and 3 of the 4 fix-ups kept
dropped the call's "Because" or "This would change it:" opening (no brief the fix-up left
alone lost one). Nothing below is a new sentence Mark reads word for word: the readiness
line keeps 369's signed-off words, and the rest are instructions to the model.
`apps/api/tests/test_batch_377_readiness_line.py` holds the app's words to this file.

## 1. The readiness line: placed by the app (377.1)

**What changes:** the app now writes the line into the brief itself, on the mornings it is
due (the first morning it shows, a 3-point move, and Mondays, as 369), as the first line
under the heading after Today's call: normally "Sleep and recovery", or the heading after
his question's answer when he asked one. Any copy the brief wrote itself is taken out
first, so it never sits inside the call and never appears on a morning it is not due.

How 31 Oct would read:

> **Sleep and recovery**
>
> Your readiness has run lower for six weeks: usually 63 lately, against 74 the six weeks before. It still shows with your days away left out (64 against 74).
>
> (the brief's own sleep paragraph follows, as now)

**The brief is now told (replaces "give its sentence word for word as the first line under
the heading that follows Today's call"):**

> The app adds the six-week readiness trend in verdict.readinessBaselineTrend to the brief itself, so never hide, soften or argue down its warning and never write it yourself: on the mornings its say flag is true, the app places its sentence as the first line under the heading that follows Today's call. Never give the trend, its two figures or its sentence anywhere, Today's call included, and never refer to it. It does not set the colour itself or grant permission to train.

**The check:** a call that still says the trend in its own words (readiness with "six
weeks", or with both of the trend's figures) is a miss, and the fix-up call takes it out.

## 2. "domain" and "autonomic" (377.2)

The check now looks for both, anywhere in the brief, and the fix-up call rewords them. It is
told:

> for "domain" or "autonomic", say what it measures: your HRV and resting heart rate, your sleep, your training load, how you feel

**The packet's HRV floor**, which the model reads and the brief copied "median",
"standard deviations" and "the graded verdict" from, now says it as the Sleep page's panel
already does (Batch 353):

> the middle of his nights over the window, less 1.5 times how much his nights usually vary from it — his own floor, not a population band, and not Garmin's. Below it last night is one thing a little off that today's call already counts; it rests the bike only at 2.5 times that spread or 30% under the middle of his nights, or below the floor alongside a raised resting heart rate or a reported symptom

**Replaces:** "his own median over the window, minus 1.5 standard deviations of it — a
personal floor, not a population band, and not Garmin's. Below it last night counts as one
thing a little off in the graded verdict; it rests the bike only at 2.5 standard deviations
or 30% under the median, …"

## 3. The trim: a margin, and the call keeps its shape (377.3)

- A call over 120 words is now trimmed **to at most 95** (was 110). Kept trims landed at
  114 and 116 when asked for 110, so 95 leaves room for the overshoot.
- Whatever the fix-up call changes, the call's sentences that begin **"Because"**, **"This
  would change it:"** and **"Tonight:"** keep those openings. A fix-up that drops "Because"
  or "This would change it:" is not kept, and the original stands.
- The check now also misses a call with no "Because" or no "This would change it:"
  sentence, and the fix-up call is asked to begin the right sentence with it.

## 4. What Craig sees (no words for Mark)

A miss of any of the three new kinds (readiness in the call, "domain"/"autonomic", a
missing opening) is stored with the brief and reaches Sentry with the brief check's other
misses, naming the words or openings it found.
