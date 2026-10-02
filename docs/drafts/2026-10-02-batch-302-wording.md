# Batch 302: the words when the morning is graded and the brief is not written

**Status: signed off by Craig on Mark's behalf, 2 Oct 2026, as drafted, with the three
decisions at the end** (Mark is away until 6 Oct; no message to Mark). Covers every new
Mark-facing line in Batch 302.

Since this batch the morning's colour, its notices, the plan lines and the ride changes are
stored before the paid brief is written. So there are two new states on screen: the brief is
still being written, and the brief did not finish. In both, everything above the brief reads
exactly as on any other morning; only the lines below are new.

## What does not change

- The colour's headline and line, the medical and "counted in today's call" notices, the plan
  lines and Today's actions. They come from the stored morning and keep the words signed off
  for Batches 294, 296, 297 and 298.
- The existing card, "Couldn't finish your brief. Something went wrong while writing today's
  brief. Your check-in is saved.", stays for a morning that could not be graded at all (his
  watch has not synced, or the grading itself failed). Then there is no colour to show.
- "Today's brief is ready", the push when the brief is written.

## 1. While the brief is being written (Home and the brief page)

Shown under the colour, where the card that opens the finished brief will appear.

| | Was | Proposed |
|---|---|---|
| Heading | Writing your brief | *(unchanged)* |
| Line | You're checked in — I'm reading today's data now, this lands in a moment. | **Today's call and your plan are ready above. The written brief lands in a moment.** |

Before this batch that card stood alone, with no colour, for the minute or so the brief takes.

## 2. The written brief did not finish (Home and the brief page)

Shown under the colour, in the same place.

| | Was | Proposed |
|---|---|---|
| Heading | Couldn't finish your brief | **Couldn't finish your written brief** |
| Line | Something went wrong while writing today's brief. Your check-in is saved. | **Today's call and your plan above are complete without it. Your check-in is saved.** |
| Button | Try again | *(unchanged)* |

"Try again" now asks only for the written brief. It no longer re-saves his check-in, so it
cannot count as a new answer to the symptom question.

## 3. The check-in page, after the brief did not finish

| | Was | Proposed |
|---|---|---|
| Heading | Couldn't finish your brief | **Couldn't finish your written brief** |
| Line | Something went wrong while writing today's brief. Your check-in is saved — tap to try again. | **Today's call and your plan are ready on Home. Your check-in is saved — tap to try again.** |
| Buttons | Try again | Try again · **See today** |
| Toast | I couldn't finish your brief — tap to try again | **Today's call is ready — I couldn't finish the written brief** |

## 4. His note could not be read

In a full Anthropic outage the notes reader fails as well, so the colour is graded without
his note. The written brief is where the app has said so since Batch 297; with no written
brief, nothing said it. Shown with the card in §1 or §2 when his note was not read:

> **I couldn't read your note this morning, so today's call comes from your numbers and your
> answers alone.**

It is the sentence the brief's own rule already asks for ("you could not read his note today,
so the colour comes from his numbers and his answers alone"). When Try again reads the note,
the colour is graded again and the line goes.

## 5. A push when the brief did not finish

Today nothing is sent: the check-in says "I'll notify you when your brief is ready" and on an
outage morning no notification comes. Proposed, once a day, only when the brief failed and a
colour is stored:

- **Title: "Today's call is ready"**
- **Body:** the colour's first reason, exactly as "Today's brief is ready" uses it (on 1 Oct:
  "Two things are a little off: …"). It opens Home.

If the brief is written later that day, "Today's brief is ready" is still sent. This push is
an addition to the row; it can be left out without changing anything else.

## 6. Not Mark-facing: what the coach is told in chat

When a question is asked from a morning that has no written brief, the coach's context says
"The written brief for this morning did not finish. Mark has seen the colour, the notices and
the plan lines, and no written read." in place of "What you wrote in that read".

## Decided by Craig, 2 Oct

1. The lines in §1 to §4: approved as drafted.
2. The push in §5: sent.
3. The colour shows as soon as the morning is graded, on every morning, so §1 stands.
