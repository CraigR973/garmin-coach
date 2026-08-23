# What's New in CheckMark

**Released 15–16 August 2026**

A run of thirteen fixes, all coming out of the full app review we did at the
start of the month. This is the plain-English version — the technical record
lives in the repo.

## The headline

**The coach button was invisible, and that was hiding everything.**

The floating coach button had a positioning bug that pushed it off the edge of
the screen on every page. Because you couldn't reach it, none of the proactive
coaching we built in July could actually get to you — the Sunday weekly review,
the week-ahead guidance, and the "something's changed" messages were all being
written and then landing somewhere you couldn't see. That's fixed, and with it
the whole proactive side of the app is live for the first time.

Alongside that: **a Red day can no longer be talked away by your own check-in
notes**, a genuinely poor night can no longer be credited up to Green, and 75
bits of hard-to-read text across the app have been darkened.

---

## Things you'll notice straight away

| What changed | What it means for you |
|---|---|
| **The coach button is back** | It now sits fixed in the corner of every screen, where it was always meant to. |
| **The thread opens at the newest message** | Previously it opened 14 days back and you'd have had to scroll a very long way to find anything recent. |
| **A failed conversation says so** | If the thread can't load, you now get an honest error and a Retry button. Before, it said "Nothing here yet" — which made it look like your whole history had been deleted. |
| **Your message appears the moment you send it** | Plus a "thinking" indicator while the coach composes a reply, so a multi-second wait doesn't look like a dead app. |
| **The unread dot works for all coach messages** | It only lit up for weekly reviews before. A "something's changed" message lit nothing at all. |
| **Text is easier to read** | 75 pieces of text across 13 of the 15 screens failed the accessibility contrast standard in light mode — including the label of the tab you're currently on, and the sleep table's own health warning. All darkened. |
| **Bigger things to tap** | Seven controls were under the 44-pixel minimum, including the feel-score slider — your one daily interaction — and the back links. All raised. |

---

## Changes to how the coaching judges you

These are real changes to the traffic light and the guidance. Every one of them
only ever makes the app **more** cautious, never less — that rule was tested
explicitly in each case.

**A Red day caused by training is now the signal, not noise.**
In late July we added the ability for your check-in notes to explain away a Red
morning. It went too far: writing "hard training block" or "rest day" in your
check-in could remove a Red from the fatigue cluster entirely, permanently, with
no check against your actual physiology. We watched it switch off a real
seven-day deload escalation on 5 August — one whose first four sessions you had
already approved and pushed. Now:

- Training load and deliberate rest **always count**. They're the training
  signal we're looking for, not a one-off event.
- Only genuinely one-off causes — alcohol, illness, travel — can excuse a Red,
  and only the most recent one, only for two days, and only while your HRV and
  resting heart rate agree that you're actually fine.
- Re-run against your real 31 July / 1 August data, both Reds now count, where
  before they counted as zero.

**A poor night can't be credited up to Green.**
The age-adjusted sleep credit had a guard on the Green line but not the Red one,
so a raw sleep score of 53 could still collect the full bonus and come out
Green. A raw score under 60 can now rise no higher than Amber.

**"It's just the training load" now has to be true.**
Low readiness could be waved through as load-driven whenever load was merely
*present*. It now requires load to be genuinely benign (an acute:chronic ratio
of 1.30 or below) and no recovery clock over 24 hours.

**Amber days ease properly, and the wording matches.**
An Amber day now caps hard work at 94% of FTP (Sweet Spot) rather than 98%, keeps
the 75% duration cut and the Zone 2 hold — and the guidance text now describes
what the session actually becomes, instead of saying "remove all VO2 work" when
what you'd get is a still-useful Sweet Spot ride.

**Red-day VO2 sessions are now spotted by what's in them.**
The morning read matched "is this a VO2 session?" on the workout's *name*, while
the safety layer matched on the actual intervals. A session you'd manually edited
could therefore be silently blocked from being pushed while the morning read
never mentioned it. Both now look at the intervals.

---

## The chat knows more, and makes fewer things up

- **Your weight and VO2max come from Garmin, dated.** Ask about either and you
  get the app's own most recent reading with the date it was taken, rather than
  a figure from earlier in the conversation.
- **A post-workout chat no longer reports the ride it's about as news.** It was
  listing the session you'd just done under "things that have changed since this
  read".
- **"Want me to adjust it?" only appears when it's real.** The offer used to
  attach on keywords alone — including the word "harder". Now it needs a live,
  adjustable session to exist *and* the coach to have actually offered it.
- **Unprompted messages agree with your brief.** When the coach messages you
  out of the blue, it now reads the morning brief you actually saw rather than
  recomputing your state with different settings — so it can't contradict the
  read you'd had an hour earlier. It also won't announce "something's changed"
  when you come back from holiday and nothing has, and won't message you during
  a holiday at all. And an important message (a deload) can now take priority
  over a trivial one, instead of a minor heads-up using up the week's one
  message.

---

## Things you won't see, but that matter

- **One bad row can no longer cost you a whole day's verdict.** A single failed
  step in the morning run used to poison everything after it — including the
  verdict itself.
- **Failed background jobs now say so.** They used to fail silently with nothing
  to alert on. Every scheduled job now records what it did and whether it worked.
- **A deploy that doesn't reach the server now raises an alarm.** In July a
  platform outage meant a release silently never went live, with no failure
  anywhere to show it.
- **The backup is now one we've actually restored.** Your data is backed up
  nightly and that had never once been restored to check it worked. There's now
  a weekly automatic drill that restores the newest backup into a disposable
  database and verifies the contents, plus alerts when a backup fails.
- **The guard on the coach's hard rules now actually works.** The automated check
  that stops safety rules like "never VO2 on a Red day" being quietly deleted was
  itself broken — it would have accepted a prompt saying the exact opposite. It's
  now been tested against ten deliberately inverted rules, and the five
  protections added since July are locked into it too.
- **No duplicate messages or notifications** if a background job fires twice.
- **Data-transfer monitoring** after we blew a hosting cap on 4 August, plus a
  few small privacy hardening fixes.

---

## Coming next — not live yet

**One day, one set of numbers.**
Your Garmin readiness and recovery figures were stored as a single row per day
that got overwritten with that day's final reading. Your verdict is computed at
wake — so every backward-looking view (your baselines, the trends, the weekly
reviews) has been reading a *different* number from the one the morning verdict
was actually based on. On 18 mornings checked, the readiness the app used was
higher than the surviving record on 11 of them.

The fix preserves the wake-time reading separately and points everything
retrospective at it, and pins each day's counted verdict to the one you were
actually shown that morning. It's built and tested but not yet released.

---

*Any of this look wrong from where you're sitting — or something you expected to
change that hasn't — say so and we'll look.*
