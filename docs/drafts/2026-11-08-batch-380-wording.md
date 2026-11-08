# Batch 380 — the coach checks a claim before it states it: the words (for Craig's sign-off)

**Not yet signed off.** Chat moves from `coach-chat-v31-2026-11-02` to
`coach-chat-v32-2026-11-08`. None of this is copy the app shows Mark: it is what the
coach is told, so Mark only ever sees the coach's own answers.
`apps/api/tests/test_batch_380_claim_checks.py` holds the code's words to this file.

Every example, name and figure in this file is invented. The three real answers behind
it (Batch 379's #34, #37 and #39) stay in the review's git-ignored private evidence.

## Why (380.1, sanitised)

| Claim type | What the coach had | Why it went unchecked |
|---|---|---|
| A stretch of days | Today's reading, monthly means, the daily-readings lookup | No lookup; it summed six weeks up from means that sat inside his usual range |
| A phase of his plan | Nothing names a plan week anywhere | The record was silent, so it named the phase from his weekly rhythm |
| What a session was | The planned and completed sessions, one lookup away | It assumed the session from the day of the week |
| How Garmin scores a workout | Nothing (it is not in his records) | General knowledge, invented and stated as fact |

Two facts found while building:

- **One daily-readings lookup holds about 15 mornings** (its result is capped at 12,000
  characters), so checking six weeks takes three lookups, of the four an answer may
  make.
- **The coach's live context is already full.** At all nine real question moments of
  2–7 Nov, even on v31, it was trimmed to fit: recent sessions, review prose and sleep
  history were dropped every time, and what each morning did to his sessions on 2–3
  Nov. A dated six-week series of readings (about 1,500 characters) was built and
  measured, and it was trimmed at all nine, so it is not in this version: a stretch is
  checked by lookup.

## 1. The new rule (in the coach's instructions, after the record rule)

> Check a claim about a stretch of days, a phase of his plan or what a session was
> before you make it, and say in a few words what you checked, such as "across your
> mornings since 28 Sep". An average or a trend describes a stretch as a whole, never
> each day in it: before saying how his readings went across a stretch, look up its
> days with get_daily_metrics, and if any mornings fell outside his usual range, say
> how many and when. Name a week's phase only from planWeeks or a session's planWeek,
> never from his weekly rhythm or what a week usually holds. Say what a session was
> only from its own record for that date, the planned or the completed session, never
> from the day of the week it fell on. If you have not checked a claim, leave it out
> or say that you have not checked it. How Garmin, his watch or the app works a figure
> out is not in his records unless a basis is stated: say it is general knowledge, or
> that you do not know, and never present it as fact.

## 2. Its restatement in the closing reply rule (the last thing the coach reads)

Inserted after "take any range's first and last dates and values from the records."

> Check a claim about a stretch of days, a phase of his plan or what a session was
> against its dated records (a get_daily_metrics lookup, planWeeks, or the session's
> own record) before making it, and say in a few words what you checked; an average
> never shows that every day stayed in range. Give how Garmin or the app works a
> figure out only as general knowledge, or say you do not know.

## 3. The list of what the coach holds

One addition to the closed list ("You have where the app stands right now in front of
you - ..."): "the weeks of his plan by name and type from six weeks back through the
week ahead".

## 4. One new record in the coach's context

**His plan's weeks** (`planWeeks`, about 770 characters): each week's dates, name and
type, from six weeks back through the week ahead, as compact rows. On a block too full
for it, it is trimmed after sleep history and before what each morning did to his
sessions (on 2 Nov a never-trimmed version pushed that out of one answer). The block then
names it as trimmed, with the planned-sessions lookup to fetch it, whose rows now carry
their plan week.

> His plan's weeks from six weeks back through the week ahead, oldest first, as rows
> in `columns` order, named as his plan names them (PN3 W02 is week 2 of Plan No. 3).

## 5. Two lookup descriptions

**Daily readings** (`get_daily_metrics`). Adds "and before you say how a reading went
across a stretch of days" and the last sentence.

> Look up Mark's Garmin wake recovery readings between two dates. Call this when he
> asks about past readiness, recovery time, HRV, resting heart rate, training
> state/load, or Body Battery outside today's observation, and before you say how a
> reading went across a stretch of days. One lookup returns about two weeks of
> mornings at most, so ask for a longer stretch as several ranges in one go.

**Planned sessions** (`get_planned_workouts`). Each row now carries `planWeek`, the
week of his plan its date falls in. Adds "and the week of his plan it falls in" and
"before you say what a past session was or which phase of his plan a week was".

> Look up the active workouts prescribed between two dates, each with its full
> prescription (structuredWorkout: exercises or steps, sets, reps, targets and rest)
> and the week of his plan it falls in. Call this when Mark asks what was planned on
> past dates, before you say what a past session was or which phase of his plan a week
> was, when he asks how to do a session beyond the week ahead, or about adherence
> outside the current week; pair it with get_activities when the answer depends on
> planned versus completed.

## Unchanged

Answer-first and the word target, today's call and how it is made, every floor, the
answer guard, pass-on and propose/approve. The morning brief's prompt and packet are not
touched.
