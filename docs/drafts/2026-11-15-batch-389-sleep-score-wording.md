# Batch 389 — the name of the age-adjusted sleep score (DRAFT, for Craig's sign-off)

**Signed off 15 Nov (Craig, "C", relayed by the orchestrating session): option C, all three phrases
as written below; built into `verdict_grading._sleep_figure` (Decision #506).** Garmin's own
number keeps "(score 63)" on a night with no age credit and when the age-credit guard holds the
day. Options A and B are kept below as they were put to him.

Put to Craig with nothing preselected. Built on `feat/batch-389-sleep-score-name-whole-ranges`
(Decision #506). Every figure below is the row's fixture (a night Garmin scores 63 that the age
credit lifts to 71), not a stored morning; the counts are measured read-only and no text of
Mark's is quoted.

## Where these words appear

One sentence, `mark_facing_summary` in `services/verdict_grading.py`, words the graded sleep
reading. It is:

- the one-line reason under the call on **Home and the brief page** (Batch 317);
- the first of `verdict.reasons`, which the **coach** is given for each of the last seven mornings
  and told to quote, and which **every post-session read** is given for that morning;
- in the **brief's** packet, which the model reads (the brief copied it on 5 mornings since 1 Oct).

Since 1 Oct it named a sleep score on 14 mornings; on 11 the number was the age-adjusted one, which
neither Garmin Connect, the brief's metrics list nor Home's metrics table gives as "sleep score".

## Unchanged in every option

- **Garmin's own number keeps the signed-off words**, "a fair night's sleep (score 63)": on a night
  with no age credit (the two scores are equal, 7 of 46 nights since 1 Oct), and when the age-credit
  guard holds the day, where the line already explains it on Garmin's score.
- The rating, the colour, the floors and the age-credit guard (Batches 170 and 201). A test grades
  eight mornings with and without the name and finds every colour, hold, domain, guard and action
  identical.

## The options

Each option changes the same three phrases. The figures are the fixture's.

| | A fair night | A very poor night (fixture 50 → 57) | A fair night your readiness confirms |
|---|---|---|---|
| **A** | a fair night's sleep (age-adjusted score 71) | a very poor night's sleep (age-adjusted score 57) | last night's sleep (age-adjusted score 71), which your readiness says left you less recovered than the score suggests |
| **B** | a fair night's sleep (sleep score 63, 71 adjusted for your age) | a very poor night's sleep (sleep score 50, 57 adjusted for your age) | last night's sleep (sleep score 63, 71 adjusted for your age), which your readiness says left you less recovered than those scores suggest |
| **C** | a fair night's sleep (age-adjusted score 71; Garmin's score 63) | a very poor night's sleep (age-adjusted score 57; Garmin's score 50) | last night's sleep (age-adjusted score 71; Garmin's score 63), which your readiness says left you less recovered than the score suggests |

**As Home would show a whole line** (one thing a little off):

- **A:** One thing is a little off: a fair night's sleep (age-adjusted score 71).
- **B:** One thing is a little off: a fair night's sleep (sleep score 63, 71 adjusted for your age).
- **C:** One thing is a little off: a fair night's sleep (age-adjusted score 71; Garmin's score 63).

What tells them apart, without a preference:

- **A** is the shortest and uses the brief's own label ("Age-adjusted sleep score: 71" in its metrics
  list); it gives no number he can match to Garmin Connect.
- **B** leads with the number Garmin Connect shows, then the one the app judged; it is the longest,
  which matters on mornings with two or three things off.
- **C** leads with the number the app judged and names Garmin's beside it.

## Also for sign-off: the engine's reason line (never shown on screen)

The brief and the coach are also given the engine's own line. Built already, as the mechanism:

- today: "Sleep score 71 is fair."
- built: "Age-adjusted sleep score 71 is fair." ("very poor" and "good" likewise), and unchanged
  ("Sleep score 72 is fair.") when the number is Garmin's own.

## Decided on your behalf (overrule any)

- **His usual is rounded as well as the range.** The row named quartiles only; his "usual" (a median)
  sits on a half over an even count and reached 29 of 46 briefs since 1 Oct ("your usual 67.5"). It
  rounds half up (67.5 → 68), and the difference from his usual is taken from that whole figure.
- **The range rounds inwards** (68.75–82.25 → 69–82), not to the nearest: a whole reading is inside
  the printed range exactly when it was inside the true one. Over every stored morning, Home's
  metrics table changes its call on 0 of 1,281 rows; rounding to the nearest would change 11.
- **No prompt changes**, so no version moves and no paid eval runs. The brief's own wording is not
  told anything new; the 5 mornings it misnamed the score were each copying this sentence.
- **Nothing is regenerated.** Stored mornings keep their words; the coach's last seven mornings carry
  the old sentence for up to a week after the deploy.
