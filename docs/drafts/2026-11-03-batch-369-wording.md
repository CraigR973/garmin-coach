# Batch 369 — The brief and the review in plain words: the words (for Craig's sign-off)

**Signed off by Craig on 4 Nov 2026** ("Yes, sign off"; the 80-word call and the "Because"
rule on 3 Nov), and accepted as provisional ("Merge now, fix in 369b", Batch 377).
Wave #6 found the brief's call running long because the readiness paragraph sat inside it
(AI358-03), "median" in 4 of 6 briefs and twice in the 1 Nov review after Mark had asked
about the word twice (ST363-08b, UX362-04), and three REM yardsticks that disagreed: a
"65–90 min" range on Home that was not his, an age band on the REM card that "missed" 80%
of nights by construction, and the age band in 10 of 25 briefs (HS361-03, ST363-07,
UX362-06). `apps/api/tests/test_batch_369_plain_words.py` and
`apps/web/src/lib/sleepSummary.test.ts` hold the app's lines to this file.

## 1. The readiness line (369.1)

**When:** his usual readiness over the last six weeks is 5 points or more under the six weeks
before. **Said:** the first morning it shows, when the recent figure has moved 3 points or
more since it was last said, and on Mondays (Craig, 3 Nov); otherwise not repeated.
**Where:** the first line under the heading after Today's call, never inside the call, so it
no longer counts toward the call's 120 words.

**Replaces** a paragraph inside the call, every morning it triggered, in the model's words
(for example "the recent 42-day median (63.0) is 11 points below the prior median").

The app writes it in one of three forms:

> Your readiness has run lower for six weeks: usually 63 lately, against 74 the six weeks before.

> Your readiness has run lower for six weeks: usually 63 lately, against 74 the six weeks before. It still shows with your days away left out (64 against 74).

> Your readiness has run lower for six weeks: usually 63 lately, against 74 the six weeks before. Most of that is your days away: with them left out it is 72 against 74.

His mornings of 31 Oct and 1 Nov had the second form, with these figures.

## 2. Statistics words (369.2, no new words)

The brief's check now also looks for median, quartile, percentile, standard deviation and
sample counts. A brief that has one gets one fix-up call (2 to 5 cents) that rewrites only
those sentences in his words ("your usual", "your usual range"). It is kept only if the
words are gone and every figure is unchanged; otherwise the original stands and Craig is
told. The weekly review gets the same call for the same words.

The same fix-up call also:

- shortens a call over 120 words to at most 110, keeping its first line and adding no
  figure;
- rewords "verdict" or a colour name (Green, Amber, Red) written outside the headline.

## 3. One REM yardstick, his own (369.3)

**Home's sleep line** gives his REM minutes and their share of the night, and no range:

> REM 46m (10%)

**Replaces** "REM 34m, below 65–90": 65–90 minutes was not his range (his REM runs about
10% of the night, near 45 minutes). The share is of the measured night (deep + light +
REM + awake), the same basis as his usual range on Sleep and in the brief (Batch 227), so
Home and Sleep give the same night the same figure. His own usual range stays on Sleep.

**The REM card** ("Protect REM consistency") now judges his own usual range, not the
50–59 age band. It opens:

> REM sleep has repeatedly missed its personal baseline

and its count line reads, for example:

> 12 of 20 measured nights missed your usual 7–13%.

**Replaces** "REM sleep has repeatedly missed its age norm" and "… missed healthy 50–59
range 15–23%", which a wrist device met on 19 of 93 nights.

**The brief** reads REM and the other stages against his own usual range only: never the
age band, "healthy for your age" or Garmin's target in the daily brief. The age bands stay
in the monthly read. It says at most once that REM is the stage a wrist device measures
least well, as a limit on the figure, never as "no concern".

## 4. The call (Craig, 3 Nov)

- It aims at **about 80 words** (was about 100), never more than 120. At about 100 the
  replayed calls ran 114–133 words on 4 of 5 mornings.
- Its "Because" sentence says why **in his words, never "domain" or "autonomic"**. For
  29 Oct the third replay wrote "Because none of your autonomic, sleep, load or feel
  domains are showing anything off today, the Sweet Spot ride stands as planned."; the
  fourth wrote "Because your HRV, sleep, training load, and how you said you felt this
  morning are all sitting within your own usual ranges, today's Sweet Spot session stands
  as planned." One of the fourth replay's five briefs still wrote "autonomic"; Batch 377
  adds the word to the check so the fix-up call rewords it.
- A low HRV or a resting heart rate up two mornings is described to the model in his own
  signed-off words ("one thing a little off that today's call already counts", Batch 298),
  not "one domain signal the graded verdict has already counted", which the second replay
  copied into his 31 Oct brief.

## 5. Behind the scenes (no new words)

- The brief's eval records how much the model thought on each case (369.4).
- **Prompt version:** the morning brief moves v66 → v67. **Nothing is regenerated:** the
  merge comes after the day's brief and outside 06:00–11:00, a day's morning is written
  once, and the next morning is the first at v67. The weekly review's prompt text is
  unchanged (v16): its fix-up call is code, not prompt.
