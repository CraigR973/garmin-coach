# Batch 381 — a moved session says who moved it and why: the words (for Craig's sign-off)

**Signed off by Craig on 9 Nov (Decision #489)**: "Yes to all 5", with one change to
the reason (section 2), relayed by the run's session. Mark's label words stay as they
are; the optional rewording was declined. None of this is copy the app shows
Mark on a screen: it is what the coach reads, so Mark only ever sees the coach's own
answers. `apps/api/tests/test_batch_381_move_provenance.py` holds the code's words to
this file. Every example below is invented; the real case behind it (Batch 379's #33)
stays in the review's git-ignored private evidence.

## Why (381.1, sanitised)

On 2 Nov the ten Dumbbells A rows moved to Thursdays under Decision #462 went through
the app's own move (`swap_day`), run in the api container. That move stamped every row
it wrote `today_card_swap`, whose plain words are "moved to this day from the app's
Today card". So when Mark asked why a session had moved, the coach told him his record
showed his own Today-card move, with no reason logged.

- **Writers of `today_card_swap`:** only `swap_day`. It is reached by the Today card,
  the Week page and the morning's swap suggestion (all one endpoint), by an unused
  plan-actions endpoint, and by any script run in the container.
- **Readers:** the coach's week ahead and planned-sessions lookup and the morning read
  (as plain words), the post-ride, post-strength, post-walk and post-flexibility reads
  (as the raw label), and the API's session payloads, whose web screens only check for
  a session Mark added himself. Nothing schedules by it: the plan importer, a
  locked plan, reconcile, reset weeks, holidays and the restructure treat a
  `today_card_swap` row like any other, so a new label keeps exactly the protection it
  had.
- **Recount, all history:** 47 rows carry `today_card_swap`. 10 were Craig's (2 Nov
  13:00); 9 of those are still active (Thu 19 Nov to Thu 14 Jan), and Mark moved the
  tenth back himself at 16:05. The other 37 are Mark's own. The general audit table
  records no moves; each move's own audit row (in `analyses`) does.

## 1. Who moved it (the session's plain-words basis)

Mark's own move keeps its label and its words, unchanged:

> moved to this day from the app's Today card

A move Craig makes, or one made on his decision, gets a new label, `operator_move`:

> moved to this day by Craig, not by you

## 2. Why (recorded on the move, quoted beside the session)

A move Craig makes must record one short plain sentence, at most 280 characters. The
coach sees it as `moveReason` beside the session, in the week ahead and in the
planned-sessions lookup. Mark's own moves record none, because the app never asks him
why.

The reason written on the 9 corrected rows:

> Craig moved Dumbbells A from Mondays to Thursdays for this plan, so it no longer
> falls the day before Tuesday's VO₂ session; on Thursday it comes after the
> sweet-spot ride and 48 hours before Saturday's ride.

Craig's change (9 Nov) adds the move's main reason: on a Monday, Dumbbells A sat the day
before a VO₂ session. Re-checked read-only on 9 Nov: for all 9 rows, the Tuesday two
days before the Thursday holds a VO₂ session (full, Light or Primer), and every
Thursday holds a sweet-spot ride (full, Light or Primer). It says "Saturday's ride", not
"sprints", because 4 of the 9 Saturdays after these Thursdays (28 Nov, 19 Dec, 9 Jan
and 16 Jan) are easy rides without them. 208 characters, inside the 280 limit.

## 3. What the coach is told about the two fields

Added to the end of the meaning of today's sessions, which already speaks for the week
ahead:

> In weekAhead, a session's basis says how it reached that day; moveReason, when
> present, is why Craig moved it.

Added to the end of the planned-sessions lookup's result meaning:

> basis says how a session reached that date; moveReason, when present, is why Craig
> moved it.

## How a #33-style answer reads now (invented, not a replay)

Asked "why is my legs session on Thursday this week?", the coach has, for that session,
"moved to this day by Craig, not by you" and the reason above, so it can say that Craig
moved it, and why, instead of "you moved it from the Today card, no reason logged".

## Not changed

- The chat's instructions and lookup descriptions: `coach-chat-v32-2026-11-08` stands
  (Craig, 9 Nov: no bump).
- The morning prompt, its packet's shape, and the post-session prompts (post-ride v19
  among them). Once the 9 rows are corrected, a morning or post-session packet that
  holds one of them carries the new label (and, in the morning's, its words) in the
  slot the old one filled; no key is added to them. Craig, 9 Nov: a data correction,
  not a prompt change, so no paid eval.
- Anything Mark sees on a screen: the Week page's session sheet still says
  "Coach-planned" for a moved session (Craig, 9 Nov: no change, no new row).
