# Batch 352 — wording for Craig's sign-off (26 Oct 2026)

Nothing here merges or deploys until you sign off the exact words. Mark's own words and
figures are not in this public file (the new examples' numbers are made up); the replayed briefs
are in the git-ignored scratchpad (`scratchpad/batch-352-replay/REPORT.md`).

## What Mark will see differently

- **His figures against his own history** read as "your usual" and "your usual range
  (52–64)", never "your median", "upper quartile" or "your personal quartiles".
- **How a floor is set** reads as what it means for him ("your own HRV floor of 41 ms, set
  from your recent nights"), never "median minus 1.5 standard deviations".
- **Counts in words** ("over 84 nights"), never "n=" or "samples".
- **Nothing else changes:** today's call, its headline and reading words, the sections, his
  numbers, the floors and the warnings.

## The new rule (graded morning prompt only, `MORNING_PLAIN_WORDS_RULE`)

> Give every figure to Mark in plain training words, speaking to
> him as you. Every median in the packet, whatever its field is called (baselineMedian,
> baselineMedianMs, medianMs and the like), is his usual, and "your usual" says all of it:
> "62 against your usual 58", or "usually" where a median describes a timing. The span from
> a lowerQuartile to its upperQuartile is his usual range, and any upper or lower quartile is
> an edge of it: "inside your usual range of 52-64", "below your usual range", "higher than
> usual for you". In Metrics vs baselines, give each line in that form, such as "Sleep score:
> 62, against your usual 58 and inside your usual range of 52-64". Quartile, percentile,
> median and standard deviation are words for your reasoning, never for Mark: never write
> them in the read, even where a rule above or a basis, reason or warning in the packet uses
> them, and never beside "your usual" to say which usual you mean. Say what a figure means
> for him instead, such as "your own HRV floor of 41 ms, set from your recent nights", rather
> than how it was calculated. Say in words how many mornings or nights a figure rests on
> ("over 84 nights"), never "n=" or "samples". Before you finish, reread every line for those
> words and say any line that has one again without it.

It sits after the rules that frame his baselines in medians and quartiles, so it governs
the words he reads while those rules still steer the reasoning.

## Sentences changed in the graded morning prompt

Removed:

- When verdict.readinessBaselineTrend triggers, state plainly that the recent readiness median has declined versus the prior half-window and never hide, soften, or argue down that deterministic warning.
- Where an entry carries baselineMedian, state the figure together with that median and deltaVsBaseline — "yesterday drained 66, dead on your 67 median" — and never also state the same figure bare: the compared form replaces it, it is not an addition to it.

Added (besides the rule above):

- When verdict.readinessBaselineTrend triggers, state plainly that his usual readiness over the last six weeks has fallen below the six weeks before and never hide, soften, or argue down that deterministic warning.
- Where an entry carries baselineMedian, state the figure together with that usual figure and deltaVsBaseline — "yesterday drained 66, dead on your usual 67" — and never also state the same figure bare: the compared form replaces it, it is not an addition to it.

## What stays, and why

- **The REM framing rule** still reads REM "against Mark's own stored median and quartiles":
  it is shared word for word with Trends, so changing it would change the trends read
  untested. The new rule keeps those words out of what Mark reads.
- **The weekly review's rule** (signed off 26 Oct) is unchanged.
- **The ladder prompt** (kept for the one-setting rollback) is unchanged at v50.
- **Versions:** graded morning v59 → `morning-analysis-v60-2026-10-26`. Nothing is withdrawn:
  the next morning written after the merge is v60.

## The logged check

After each brief is written, the app logs `morning_analysis_wording_leaks` with any
quartile or percentile, median, standard deviation, "n=" or "samples" it still contains.
It never blocks or withholds the brief. Colour words are not in it, because the call's own
headline is "Green light".

## Replay at no API cost (24 runs, Decision #424's route)

Three stored briefs that showed the words: 20 Oct (standard deviations), 25 and 26 Oct
(quartiles), all three with medians. For each, the v58 prompt production used was rebuilt
and matched the hash production stored with the brief. "v59" is the live prompt (its hash
checked against the running container) on the same stored packet plus the disruption
record v59 adds. Replays are samples, not production proof.

| Prompt | Runs | Still wrote |
|---|---|---|
| v58, as production sent it | 2 | a quartile in 1; a median in both |
| v59, live | 3 | a quartile in 1; a median in all 3 (8–15 each) |
| Draft 1 | 3 | a median in all 3; "his" for "you" in 2 |
| Draft 2 | 6 | a median in 3 (up to 12) |
| Draft 3 | 6 | a median in 2 (both 25 Oct) |
| **Draft 4, these words** | 4 | a median in 1 (twice, outside the metrics list) |

- **Quartiles, percentiles and standard deviations: gone.** None in any of the 19 runs on
  drafts 1–4. Production's own briefs showed quartiles on 25 and 26 Oct and standard
  deviations on 20 Oct.
- **Medians: nearly gone.** Draft 4 left two in one 25 Oct run, in the REM range and the
  overnight HRV line. The live prompt wrote 8–15 per brief, and production's briefs 11–13.
- **Voice:** replays often wrote about Mark ("his") rather than to him, even on production's
  own v58 prompt (1 of 2), while production's briefs never did (0 of 3). The replay route
  shows the model who is signed in, which pulls it that way. Draft 4 says "speaking to him as
  you", and all its runs did. Tomorrow's brief (27 Oct) is the first on the live v59 prompt,
  and will show whether v59 drifts in production too.
- **Nothing else changed:** every run opened Today's call with the stored headline and reading
  words and kept every required section. Draft 4's briefs averaged about 2% longer than the
  live prompt's replays.
- **Seen, not this batch's:** "settling window" once (Batch 347's rule asks for a date, never a
  window), and some ranges printed to two decimals, as the stored figures are.

## Decisions for you

1. **Sign off these exact words**, or say what to change. The metrics list will read like
   "Sleep score: 62, against your usual 58 and inside your usual range of 52-64".
2. **Medians:** you named quartiles and percentiles. This also turns "median" into "your
   usual", as the weekly review's rule does, because every brief had one. Keep it
   (recommended), or leave "median" in?
3. **Merge:** after your sign-off and green CI, outside 06:00–11:00 London, regenerating
   nothing ($0). The first v60 brief is the first morning after the merge.
4. **The two other places on the morning screen** that use these words: the oxygen notice's
   "usual upper quartile" and the "How these numbers were worked out" panel's "median minus
   1.5 standard deviations". A small follow-up (fixed wording, no replay needed), or leave them?
