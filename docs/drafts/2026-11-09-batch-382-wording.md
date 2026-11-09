# Batch 382 — internal words out of the brief and the post-ride read: the words (for Craig's sign-off)

**Signed off by Craig on 9 Nov 2026** ("Yes to all 4", Decision #491). Sections 1 to 3 are built
on the batch branch. Section 4 is **not built** and stays out of Batch 382 (it is its own
planned batch). Section 1 is what Mark reads; sections 2 and 3 are instructions to the model.
`apps/api/tests/test_batch_382_internal_words.py` holds the code's notice sentences to section 1.

Every example, name and figure in this file is invented. The real reads behind it stay in
Batch 379's git-ignored private evidence.

## 1. The experiment notice (built; this is what Mark reads)

The notice is a fixed template, not model prose. Its sentence in the middle used to be the
evaluation's own first line, which quotes a correlation figure, a range and a measured driver's
internal name. It now says the same thing in words. The frame is unchanged:

> **Something changed:** *{experiment name}* now has enough evidence to read as *{supported or
> refuted}*. *{one sentence from the list below}* I have not concluded it for you; the
> experiment still needs your explicit decision.

The sentences, one per kind of experiment (figures here are invented):

**Overnight disruption, refuted**

> Nothing I can measure lines up closely enough with the disturbed nights to be a trigger.

**Overnight disruption, supported** (the driver is named by its existing plain label)

> Fan speed moves closely with the disturbed nights, so it looks like a trigger.

**Sleep-score target, supported**

> Your age-adjusted sleep score has stayed at or above 75 for 7 nights in a row, which meets the 7-night target.

**Intervention against nights without it, supported or refuted**

> On the nights you tried it, REM was 2.4 percentage points higher and you were awake 12 minutes less than on the nights you didn't.

**Recovery weeks against build weeks, supported or refuted**

> Your HRV averaged 44.1 ms in recovery weeks against 51.2 ms in build weeks.

If a figure a sentence needs is missing, the notice carries no sentence at all (never the
technical line). The Experiments page still shows the technical reasons: see option 5 in the
stop message.

**What the 4 Nov notice said** (the real one, kept private): it quoted the correlation as
`r=` with a signed figure, a range in brackets, and "rules out anything as large as 0.3".

## 2. The repair call (built; Mark never sees this)

Applies when a stored brief or post-session read uses the app's own words. One call, the same
model and settings as the existing plain-words repair. The result is kept only if the words are
gone and every figure is unchanged; otherwise the original stands and Craig is told.

> You edit a short coaching note written to Mark, a 57-year-old cyclist, so that it never
> uses the app's own words for the information it was given. Rewrite only the sentences that
> use the words named, saying the same thing as the fact itself, in plain words: "your planned
> sessions", "your check-in", "the numbers from the ride", never "the packet", a field name or
> where a figure was kept. If a sentence only describes where the information came from, say
> what is or is not known instead ("I don't have tomorrow's session in front of me"). Keep
> every heading, every figure and every other sentence exactly as written. Return only the
> markdown.

The brief's existing repair instruction gains one clause: *for a word the app uses about its
own information, such as "packet" or a field name, say the fact itself: "I only have today's
planned sessions", not "the packet only has today's sessions".*

## 3. Option B, built: the post-ride prompt v20 (signed off 9 Nov)

Why: the post-ride prompt never carried the field-names rule the morning, strength, review and
trends prompts carry, and it told the model to "use only the supplied context packet". Moving
post-ride read v19 to v20 makes the hourly poll write again every ride read from the last 7
days (about 4 rides, about $0.20, accepted by Craig).

In the post-ride instructions, three replacements:

1. "Use only the supplied context packet." becomes

> Use only the information supplied.

2. "answer it directly in the read using only the supplied packet" becomes

> answer it directly in the read using only the information supplied

(the clause where Mark's check-in questions are answered, so the likeliest source of the leak;
added on the orchestrator's call for Craig and told to him so it can be overruled)

3. "Say plainly when the packet cannot support an answer" becomes

> Say plainly when the information supplied cannot support an answer

and the rule the other prompts already carry is added, word for word:

> Packet field names are instructions to you, never words for Mark: never print a field, key
> or path in the output and never cite the packet as a source; state the fact itself.

Left as it is, on purpose: "explicitly given elsewhere in this same packet", in the VO2max
paragraph. No other wording is approved.

## 4. Option C, not built and out of Batch 382: tomorrow's session in the brief (needs a version bump and a paid eval)

Why it is an option: the brief is given only today's planned sessions, so on 7 Nov a
check-in question about swapping today's and tomorrow's rides could not be answered from it.
Adding tomorrow's sessions changes what the brief is given, so morning v69 moves to v70.

The brief's input gains the next day's planned sessions, in the same shape as today's. In the
morning instructions, add:

> When Mark's check-in asks about tomorrow's session (swapping it, moving it, how hard it is),
> answer from tomorrowsPlannedWorkouts. If it is empty, say you have no session planned for
> tomorrow. Never say that what you were given holds only today's sessions.

## 5. What is not changed

The morning prompt (v69), chat (v32), the strength, walk and flexibility prompts, every screen, the weekly review and the monthly trends
(no stored read of either has used these words since their current versions went live), and
the driver-analysis text (only the coach's lookups read it; no screen shows it).
