# Coach memory: showing his standing habits — wording for sign-off (Decision #439)

**Signed off by Craig, 27 Oct 2026, in his words:** "Habits card: use wording A ("Habits you already keep" / "Your coach leaves these out of your REM focus, because you already do them.") and include it in the editor. Build it." Built as wording A, placed after "Sleep protocol", with the editor card (Decision #439).

**Status before the sign-off:** draft, not built. The fix that ships with this file (Decision #439) only makes
Setup → Coach memory load again. The `standing_habits` section stays off the page until
Craig signs off the wording below.

**What the section is.** Batch 231 (Decision #308) added a human-written knowledge-base
section for habits Mark already keeps. The coach leaves any REM action a habit covers out of
the weekly REM focus, because a habit he always keeps can never have a night without it, so
the experiment could never conclude. Production has one habit, recorded 28 Aug at Batch
231's close-out and stored as a first-person quote from his own chat.

**Why show it.** The page says it shows "what your coach knows about you". This section
changes what he is asked every week, and today he cannot see it anywhere.

## Proposed card (read view)

- **Title:** Habits you already keep
- **Description:** Your coach leaves these out of your REM focus, because you already do them.
- **Body:** each recorded habit's `statement`, one per line, shown as written (in quote
  marks, since each is his own words). The action ids, dates and sources stay hidden.
- **When nothing is recorded:** no card.
- **Placement:** straight after "Sleep protocol", since every action it removes is a sleep one.

**Alternative wording (B):** title "Standing habits"; description "Things you always do, so
your coach treats them as part of your routine and won't ask you to try them."

## Two knock-on changes

1. **The section count.** The "N active memory sections" pill counts only the sections the
   page knows. Showing this one takes production from 9 to 10.
2. **The editor.** Adding it to the page's section list also gives it a JSON editor card,
   titled "Standing Habits" from its key like the others. A habit could then be added or
   removed in the app rather than by script. Mark is the app's only admin, so he would see
   that card too.

## For Craig

1. Show the card? A (above), B, or your own words.
2. Include it in the editor as well, or keep the editor as it is?

Building it after sign-off: one web change (`CoachStatePage.tsx`, no API or schema change),
with a page test for the card and its empty state.
