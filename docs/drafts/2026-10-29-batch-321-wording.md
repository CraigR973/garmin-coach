# Batch 321 — three small fixes: the words (for Craig's sign-off)

**Draft, not signed off.** Batch 321 makes three morning lines say only what the engine
knows, and names a reading that is missing rather than letting it pass for normal.
`apps/api/tests/test_batch_321_three_small_fixes.py` holds the app's lines to this file.

**Replay, read-only, on production (29 Oct, 129 stored mornings, this branch against
`main`):** no colour, floor, session action or notice changes. Three replayed mornings (22–24 Jun, before the
readings were reliable) gain the two missing-reading reasons below. No head-cold morning,
no missing-data morning and no Red strength-only morning has happened yet, so no stored
morning shows the new calls.

## 1. A head cold (321.3)

**Where:** the big card at the top of Home and the brief page, on a morning he answers
"Head cold", whatever his numbers.

> **Easy riding at most**
> You've told me you have a head cold. Easy riding at most today, and only if you feel up to it: nothing hard.

**Replaces:** "Recovery day · Your body's still recovering. The hard session will do more
for you on a fresher day — today, rest or an easy spin." His body may be fine; the cold
is the reason. The head-cold notice signed off on 28 Sep is unchanged beside it.

## 2. A morning the app could not fully judge (321.3)

**Where:** the same card, on a morning held at "careful" because Garmin's or the sleep
record did not arrive. The chip under it reads **Not enough data** (instead of "Some
fatigue").

With a hard session planned:

> **Not enough data**
> Last night's data didn't fully come through, so today errs on the careful side: ride the full session with the hard efforts eased a zone.

With only easy riding or strength:

> **Not enough data**
> Last night's data didn't fully come through, so today errs on the careful side. Today's plan already suits that; keep it comfortable.

**Replaces:** "Take the edge off · There's some fatigue about…" and "As planned · There's
some fatigue about…", which claimed a fatigue the app had not measured.

## 3. A Red morning with only strength planned (321.3, FC331-02)

**Where:** the plan line under today's call.

> Keep today's strength easy: the weight you used last time, no step up, fewer sets, and stop well short of failure.

**Replaces:** "Substitute recovery, mobility, or rest.", which disagreed with the call ("As
planned") and with the session itself ("one weight up").

## 4. A reading missing from a night that arrived (321.2)

**Where:** the morning's reasons, which the written brief and the coach read (not a line
on Home by itself).

> No overnight HRV reading last night: it counts neither way today.

> No sleep score last night: it counts neither way today.

**Replaces:** nothing; a missing reading quietly rated as normal. **Provisional choice
(the row left it open):** say so, rather than carry the last rating one more morning,
which would change the call on those mornings.

## Questions for Craig

1. "Not enough data" as the chip on a missing-data morning, or keep "Some fatigue"?
2. Section 4: say it (built), or carry the last rating one morning (adds caution, moves
   the call)?
