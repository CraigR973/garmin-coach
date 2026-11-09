# Batch 384 — the words for tomorrow's session in the morning brief (draft, not signed off)

Built 9 Nov 2026 on `feat/batch-384-tomorrow-in-brief`. Nothing here is live. The morning
instructions and `PROMPT_VERSION` (v69) are untouched until Craig signs off the exact words.
Starts from §4 of `2026-11-09-batch-382-wording.md`. Every figure and example is invented.

## What the brief is given (built, no words yet)

The brief's input gains `tomorrowsPlannedWorkouts`: the active sessions the plan has for the
day after the morning's date, in the same form as `plannedWorkouts` (title, type, duration,
intensity, structured steps, and the plain-words basis for where it came from). Empty when the
plan has none. It is context for a question only: today's colour, floors, plan and rest-day
reading are computed without it (a test proves it).

## The words to add (one paragraph in the morning instructions, after the "Your question" rule)

Draft A, from §4 with one change (the first sentence is new, §4 had no meaning sentence):

> tomorrowsPlannedWorkouts holds the sessions the plan has for tomorrow, in the same form as
> plannedWorkouts. It is there to answer a question about tomorrow and never changes today's
> call, colour or plan: do not bring tomorrow up unless he asks. When Mark's check-in asks
> about tomorrow's session (swapping it, moving it, how hard it is), answer from
> tomorrowsPlannedWorkouts, under the same "**Your question**" heading. If it is empty, say you
> have no session planned for tomorrow. Never say that what you were given holds only today's
> sessions.

Why each change from §4:

- **The first two sentences are new.** Without a meaning sentence the brief has no reason not to
  mention tomorrow every day, which adds words to every brief for a question asked once.
- **"under the same Your question heading"** puts the answer where the existing rule already
  sends every check-in question, rather than leaving its place to chance.
- **Kept word for word:** the empty-list sentence and the last sentence.

Not covered, on purpose: a question about two or more days ahead. The brief has only tomorrow's
sessions, and the rule does not claim more. (The week so far is in the brief; the coach chat can
look up any range.)

## What it must not do (checked privately on the replayed 7 Nov case, not in the repo)

- Answer from the sessions given, not from memory or a guess.
- Use no packet word or field name (the 382 check already flags `tomorrowsPlannedWorkouts`).
- Not change today's colour or the app's own session lines.
