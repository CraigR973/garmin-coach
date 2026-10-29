# Batch 343 — a day with no plan, and the small screen fixes (for Craig's sign-off)

**Draft, not signed off.** Batch 343 gives a day with no plan loaded its own words instead
of "Rest is the plan today", tells an Android phone how to turn notifications back on,
writes Home's read times the way the brief does, makes three small links easier to tap,
and puts the Zwift warning on Week. No colour, call or session changes.
`apps/api/tests/test_batch_343_no_plan_and_small_fixes.py` and the web tests named below
hold the app's lines to this file.

**Today:** Plan No. 3 has been loaded since 19 Oct, so Mark will not see section 1 until
it ends or he clears it.

## 1. A day with no plan loaded (343.1, UX333-06)

**Where:** Home's big card at the top (today's call), Home's Today section, and Week.
Only when no plan block covers the day and nothing is planned.

Today's call:

> **No plan loaded**
> There's no plan loaded for today. Make your next plan when you're ready.

Home's Today section (and its collapsed one-liner, "No plan loaded."):

> No plan loaded for today. [Make your next plan] — or add something light, or just record what happened.

Week, the week's badge and each empty day:

> No plan loaded (badge) · No plan (each day) · [Make your next plan]

**Replaces:** "No session planned · There's nothing in your plan for today yet." (the
call), "Rest is the plan today. Add something light, swap a workout in from the week, or
just record what happened." (Home), "Rest week" and "Rest day" (Week). A real rest day
inside a plan keeps its words.

## 2. Notifications blocked, by phone (343.2, UX333-08)

**Where:** Settings, when notifications are blocked.

On Android (Mark's phone since 16 Sep):

> Notifications are blocked for CheckMark. In Chrome, tap the three dots › Settings › Site settings › Notifications, allow CheckMark, then come back here.

On an iPhone (unchanged):

> Notifications are blocked for CheckMark. Turn them back on in iPhone Settings › Notifications › CheckMark, then come back here.

Anywhere else:

> Notifications are blocked for CheckMark. Allow them in your browser's site settings, then come back here.

## 3. Home's read times and small links (343.2, UX333-09)

**Where:** Home's strength, walk and mobility reads, and the post-ride read.

> Written at 13:02 this afternoon

**Replaces:** "Generated 08/10/2026, 13:02:36". The words are the brief's own, signed off
for Batch 254. "I disagree with today's call", "This looks wrong" and "Where these numbers
come from" keep their words and get a 44-pixel tap area.

## 4. Week carries the Zwift warning (343.2, UX333-10)

**Where:** the top of Week, when rides are not reaching Zwift. The words are Home's own,
signed off for Batch 326 (for example "Not reaching Zwift: intervals.icu has paused your
account…").

## Questions for Craig

1. Section 1's words, or "Plan finished" when a plan has just ended?
