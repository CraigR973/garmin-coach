# Batch 317 — the words Mark sees (for Craig's sign-off)

**Not yet signed off.** Batch 317 shows Home's one-line reason under today's call, gives
his HRV one "usual" everywhere, and rewords the one place where a fair night was called
"clearly off". These are every Mark-facing line that is new or changes, word for word.
`apps/api/tests/test_batch_317_home_shows_why.py`, `apps/web/src/components/TodaysCallHero.test.tsx`
and `apps/web/src/lib/provenance.test.ts` hold the app's lines to this file.

Figures below are his own, from the stored mornings replayed read-only on 28 Oct 2026.
"His usual HRV" below is the average of his nightly HRV over the 84 nights before the
morning (46.3 ms on 5 Oct, 46.5 ms on 28 Oct); the middle of the same nights was 47 ms
(Decision #450).

## 1. Home shows why, under today's call (317.2)

**Where:** Home's big card at the top (and the same card on the brief page), under the
call's own line, every morning the graded verdict wrote (since 30 Sep). Not shown when
the morning could not be judged ("Not enough overnight data…"), or on a morning stored
before 30 Sep.

**The words are not new:** they are the reason line Craig signed off on 29 Sep (Batch 296),
which every graded morning has stored since and no screen showed. Examples:

> One thing is clearly off: your HRV has been well below your usual this week (39 ms against 46).

(6 Oct, under "Take the edge off".)

> Your numbers are all within your usual range.

(28 Oct, under "Green light".)

> Two things are a little off: a fair night's sleep (score 71), and your training load is climbing (ratio 1.31).

(26 Oct.)

**Replaces:** nothing; Home had no reason line.

## 2. One usual HRV (317.3)

His usual HRV is now one number everywhere he sees one. The numbers below change; the
sentences around them do not.

### 2a. Home's notice after a low night

**Where:** the notice on Home and the brief page after a night under his own HRV floor.

> Your overnight HRV is 38 ms this morning against a usual 46 ms — lower than most nights for you. …

(5 Oct.) **Replaces:** "… against a usual 47 ms …". The same "usual" change applies to the
off-the-bike notice and the illness-grade one, whose words are otherwise unchanged. Of his
129 stored mornings, 3 notices change their number: 1 Aug (47 → 48), 5 Oct and 6 Oct
(47 → 46).

### 2b. The reason line, when last night was low

**Where:** the reason line (section 1).

> your HRV was low last night (38 ms against a usual 46)

(The form, with 5 Oct's night; that morning the reason line led with his week.)

**Replaces:** "… against a usual 47" on a morning when the two differed. On 5 and 6 Oct the
reason line said "against 46" for his week while the notice said "a usual 47" for his night;
now both say 46. Across his 129 stored mornings, 0 now quote two different usuals (2 did:
5 and 6 Oct).

### 2c. A recovery or taper week (new words)

**Where:** the reason line, only in a recovery or taper week when his 7-day HRV is judged
against his usual for those weeks, which is not his ordinary usual. It has never happened
(his HRV was clear on every taper morning so far).

> your HRV has been below your usual this week (41 ms against 44, your usual for a recovery week)

**Replaces:** "(41 ms against 44)", which called a different number his usual.

### 2d. The "how was this worked out" panel for the HRV floor (new words)

**Where:** the working panel under the HRV floor on Home and the brief page. The floor is
still set from the middle of his nights, not his usual (so no morning changes colour), so
the panel stops calling that number his usual.

> **Rule:** the middle of your nights (47.0 ms), less 1.5 times how much your nights usually vary from it. This is your own floor, not a population band and not Garmin's.

> **Off the bike:** only at 34.6 ms or lower (2.5 times that variation, or 30%, under the middle of your nights), or below the floor together with a raised resting heart rate or a symptom you've reported.

(28 Oct.) **Replaces:** "your usual (47.0 ms), less 1.5 times …" and "… or 30%, under your usual)".

### 2e. The written brief

**Where:** the morning brief Claude writes. No fixed words; the brief is told that his usual
HRV is one number (46 on 28 Oct) and that the other HRV figures in its data are working,
never his usual. The metrics line it writes for HRV becomes, for example:

> 7-day average HRV: 52, against your usual 46 and above your usual range of 45-48

**Replaces:** "… against your usual 47 …" (5 Oct used both 47 and 46.3).

## 3. A fair night your readiness confirms (317.3)

**Where:** the reason line (section 1), when last night's sleep score was only fair and
Garmin's readiness is low too, which together count it as clearly off.

> One thing is clearly off: last night's sleep (score 67), which your readiness says left you less recovered than the score suggests.

(12 Aug.) With another reading:

> Two things are clearly off: your HRV has been well below your usual this week (41 ms against 47), and last night's sleep (score 70), which your readiness says left you less recovered than the score suggests.

(4 Oct.) **Replaces:** "… clearly off: a fair night's sleep (score 70) (your readiness
agrees)", which called the night fair and clearly off at once. 9 of his 129 stored mornings
read that way (8 Jul, 23 Jul, 24 Jul, 12 Aug, 30 Aug, 3 Oct, 4 Oct, 8 Oct, 18 Oct).

A short night or the load that readiness confirms keeps its signed-off words ("… (your
readiness agrees)"): neither calls itself fair.

**Questions for Craig:**
1. Section 3: the recommended words name what readiness adds. The 6 Oct review's own
   suggestion was "a fair night that your readiness says cost you more than usual", which
   keeps "fair" beside "clearly off". A shorter option: "last night's sleep (score 67), with
   your readiness low too". Pick one, or give your own.
2. Section 2d: "the middle of your nights" is the plainest honest name I found for the
   number the floor is set from. Say if you would rather the panel showed no number there.
