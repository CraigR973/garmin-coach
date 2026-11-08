# Batch 380 — the coach checks a claim before it states it: the words (for Craig's sign-off)

**Not yet signed off.** Chat moves from `coach-chat-v31-2026-11-02` to
`coach-chat-v32-2026-11-08`. None of this is Mark-facing copy the app shows: it is what
the coach is told, so Mark only ever sees the coach's own answers.
`apps/api/tests/test_batch_380_claim_checks.py` holds the code's words to this file.

Every example, name and figure in this file is invented. The three real answers behind
it (Batch 379's #34, #37 and #39) stay in the review's git-ignored private evidence.

## Why (380.1, sanitised)

| Claim type | What the coach had | Why it went unchecked |
|---|---|---|
| A stretch of days | Today's reading, 14 nights, monthly means | No lookup; it summed six weeks up from means that sat inside his usual range |
| A phase of his plan | Nothing names a plan week anywhere | The record was silent, so it named the phase from his weekly rhythm |
| What a session was | The planned and completed sessions, one lookup away | It assumed the session from the day of the week |
| How Garmin scores a workout | Nothing (it is not in his records) | General knowledge, invented and stated as fact |

One fact found while building: a daily-readings lookup returns at most about 15 mornings
(its result is capped at 12,000 characters), so checking six weeks by lookup takes three.

## 1. The new rule (in the coach's instructions, after the record rule)

> Check a claim about a stretch of days, a phase of his plan or what a session was
> before you make it, and say in a few words what you checked, such as "across your
> mornings since 28 Sep". An average or a trend describes a stretch as a whole, never
> each day in it: before saying how his readings went across a stretch, read its days
> in recoveryDays or look them up, and if any mornings fell outside his usual range,
> say how many and when. Name a week's phase only from planWeeks or a session's
> planWeek, never from his weekly rhythm or what a week usually holds. Say what a
> session was only from its own record for that date, the planned or the completed
> session, never from the day of the week it fell on. If you have not checked a claim,
> leave it out or say that you have not checked it. How Garmin, his watch or the app
> works a figure out is not in his records unless a basis is stated: say it is general
> knowledge, or that you do not know, and never present it as fact.

## 2. Its restatement in the closing reply rule (the last thing the coach reads)

Inserted after "take any range's first and last dates and values from the records."

> Check a claim about a stretch of days, a phase of his plan or what a session was
> against its dated records (recoveryDays, planWeeks, the session's own record or a
> lookup) before making it, and say in a few words what you checked; an average never
> shows that every day stayed in range. Give how Garmin or the app works a figure out
> only as general knowledge, or say you do not know.

## 3. The list of what the coach holds

Two additions to the closed list ("You have where the app stands right now in front of
you - ..."): "the weeks of his plan by name and type from six weeks back through the
week ahead" and "his Garmin wake readings for each morning of the last six weeks".

## 4. Two new records in the coach's context, with what each means

**Six weeks of wake readings** (`recoveryDays`, about 2,500 characters): one row per
morning of readiness, overnight HRV, seven-day HRV average, Garmin's HRV status and
resting heart rate.

> His Garmin wake readings for each morning of the last six weeks, oldest first, one
> row per date in the order of `columns`: readiness, overnight HRV, seven-day HRV
> average, Garmin's HRV status, resting heart rate. A date with no row has no reading
> stored. An average describes a stretch as a whole, not each day in it: before saying
> how a reading went across a stretch, check its days here against his own band in
> personalBaselines. For mornings before these, use get_daily_metrics.

**His plan's weeks** (`planWeeks`, 1,000 to 1,400 characters): each week's dates, name and
type, from six weeks back through the week ahead.

> The weeks of his plan from six weeks ago through the week ahead, oldest first, each
> with its dates and the name and type his plan gives it (PN3 W02 is week 2 of Plan
> No. 3). This is the record of which phase a date fell in: name a week's phase from
> here, or from planWeek on a get_planned_workouts row for older dates, never from his
> weekly rhythm or what a week usually holds. An empty list means no week of his plan
> is recorded for those dates.

## 5. Two lookup descriptions

**Daily readings** (`get_daily_metrics`). Adds "and the six weeks of readings in front
of you" and the last sentence.

> Look up Mark's Garmin wake recovery readings between two dates. Call this when he
> asks about past readiness, recovery time, HRV, resting heart rate, training
> state/load, or Body Battery outside today's observation and the six weeks of
> readings in front of you. One lookup returns about two weeks of mornings at most, so
> ask for a longer stretch as several ranges in one go.

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
