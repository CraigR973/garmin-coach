# Batch 366 — One honest bedroom push: the words (for Craig's sign-off)

**Signed off by Craig on 2 Nov 2026** ("yes to all", relayed by the orchestrator session, with decisions 1–5 of the PR; the seal reminder is dropped). Batch 366 judges the bedroom for the night Mark sleeps in
(from 21:30), never grades it `critical`, sends at most one bedroom push an evening, never
advises below 18 °C, sends one check-in push a day, gives Settings a switch for each kind of
push, and names a bedroom "lever" only when it survives an allowance for the ~56 links the app
scans and holds in his latest 60 nights. `apps/api/tests/test_batch_366_one_bedroom_push.py`
and `apps/web/src/pages/SettingsPage.test.tsx` hold the app's lines to this file.

## 1. The bedroom push (366.1, 366.2)

**When:** at most once an evening, from 21:30, and only when the room is too warm or too cold.
**Replaces** all four old pushes: "Bedroom temperature high … above the 20C disruption
threshold" (`critical`), "Bedroom nearing disruption range … Above 19.5C risks thermal sleep
disruption", "Seal the bedroom", and "Start room pre-cooling … toward 17C". None of those is
sent again.

Warm (24 °C or more), title and body:

> Bedroom is warm

> Bedroom is 24.6 °C. You sleep best below about 24 °C, so cool it a little before bed.

Cold (below 18 °C), title and body:

> Bedroom is cold

> Bedroom is 17.2 °C. Keep it at or above 18 °C tonight: colder is not better for sleep.

With the fan on Auto, a warm room sends nothing unless the fan cannot cope; that push's words
are unchanged ("Check the bedroom fan"), now graded a warning, not critical, and only from 24 °C.

**Replayed on 7 Oct–1 Nov (read-only):** on the 21 evenings with readings the room ran
18.2–20.9 °C between 21:15 and 23:00, so the new rule would have sent **0** bedroom pushes,
against the 42 sent (13 graded critical).

## 2. The evening sleep read's default tip (366.2)

**Where:** the 20:00 evening push and Home's sleep read, on an ordinary night.
**Replaces** "Pre-cool the bedroom toward 17C." (17 is his own protocol's number; it stays
stored, and anything shown is floored at 18 °C).

> Keep the bedroom between 18 and 24 °C.

The REM tip "pre-cool to 17°C" now reads "pre-cool to 18°C". The evening read counts the room
as warm from 24 °C, not 19.5 °C.

## 3. Check-in pushes (366.3)

One "How did it feel?" push a day. A walk or a session under 20 minutes sends none (on 1 Nov a
12-minute circuit and a 17-minute walk each sent one before the ride). The words are unchanged.

## 4. Settings → Notifications: a switch for each kind (366.3)

Shown under "Push notifications enabled", each on by default:

> Morning brief and workout reads
> When your brief is ready, and one check-in a day after a session.

> Bedroom and tonight’s sleep
> Tonight’s sleep read at 20:00, and a bedroom alert only when the room is too warm or too cold.

> Weekly review
> When Sunday’s review is ready.

> Alerts that your watch or bedroom data has stopped arriving always come through.

## 5. The bedroom "lever" (366.4)

No new words. The evening read and the morning brief name a measured link (for example warm
nights and a lower sleep score) only when it clears a Bonferroni allowance for every link the
app scans **and** holds the same way over his latest 60 nights. On his data to 2 Nov (121
nights, read-only) the old gate named bedroom temperature and warm-room minutes; the new gate
names nothing.
