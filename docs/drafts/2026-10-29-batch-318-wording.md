# Batch 318 — the brief's new shape (for Craig's sign-off)

**Signed off by Craig on 29 Oct 2026** ("All as recommended"): the 120-word cap and the "Tonight:" line kept; one paid evaluation pass approved. Example figures are made up, so the repo carries none of Mark's readings. Batch 318 moves "Today's call" to the top of the written morning
brief and keeps it under a minute's read. The words of the call itself are not new: its
first line is the headline and reading Home already shows (signed off 4–5 Oct). What is
new is the shape the model is asked for, so this draft gives the instruction and an
example, not fixed words. `apps/api/tests/test_batch_318_brief_leads.py` holds the
instruction to this file.

**Measured, read-only, on production (29 Oct):** in all 24 written briefs since 5 Oct the
call came last of six sections, after about 1,000–1,400 words; 23 of 24 call sections ran
over 120 words (119–359; 28 Oct's was 271); 7 used a word Mark is never shown ("verdict"
six times, "Amber" once, "Red" once). None quoted an HRV, resting-heart-rate or sleep-score
figure the morning did not hold, and every call opened with Home's headline and reading.

**Replay, read-only (129 stored mornings, this branch against `main`):** no colour, floor,
session action or notice changes. Only the written brief's shape moves.

## 1. Today's call comes first (318.2)

**Where:** the top of the written brief, on the brief page and in the read-aloud.

**The instruction the brief is written to** (in the app's prompt, not shown to Mark):

> Write this section first. Its first line is the headline and the reading exactly as
> stored. Then, in about 100 words and never more than 120: two or three of his own numbers against his usual;
> one sentence that begins "Because"; one that begins "This would change it:"; and one
> that begins "Tonight:" with one thing for tonight the morning supports, or none. Never
> write Green, Amber, Red or verdict. A "Your question" answer comes straight after it;
> everything else goes below.

**Example, with made-up numbers (the model writes the sentences; this shows the shape):**

> ## Today's call
> Green light · Recovered
>
> Your HRV was 52 ms last night against a usual 48 ms, your resting heart rate 46, and
> you slept 7 h 40 with a score of 80. Because every reading sits in your usual range,
> today's session is on as written. This would change it: a short night or a resting
> heart rate up two mornings running. Tonight: the same wind-down as last night.

**Replaces:** the call as the last section, usually 120–270 words, after sleep stages,
the metrics table, the room, four experiments and the chronic actions.

**Questions for Craig:**
1. Is 120 words the right cap? (Recommended: yes; Home already shows the headline.)
2. "Tonight:" overlaps Batch 320, which fills it from today's reason once it merges.
   Until then it is one thing the morning already supports. Keep the line, or drop it
   until 320?

## 2. What reaches Craig (318.3)

Not Mark-facing. Each written brief is checked; a miss sends Craig one Sentry alert
(`admin_alert` kind `brief_check`) naming what missed: the call not first, its opening
not the stored headline and reading, over 120 words, a colour word or "verdict", or an
HRV, resting-heart-rate or sleep-score figure the morning did not hold. The brief is never
held back for it.

## 3. The eval (318.4)

Not Mark-facing, and not run: it is paid and needs Craig's go. Ten stored mornings
covering eight different calls, written again under the new prompt and scored by the
check. **Cost, counted free with Anthropic's token count:** 409,391 input tokens a pass,
output about 4,800 tokens a brief, so about **$1.30 a pass, $2.60 for two**. Only scores go
into the repo; the briefs and mornings stay in the git-ignored scratchpad.
