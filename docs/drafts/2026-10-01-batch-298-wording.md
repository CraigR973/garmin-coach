# Batches 298–300: the words when the colour comes from the graded verdict

**Status: signed off by Craig on Mark's behalf, 1 Oct 2026, as drafted, with the five
decisions at the end** (Mark is away until 6 Oct; no message to Mark). Covers every new Mark-facing line in G7a's 298, 299 and 300, so
the group needs one sign-off. Examples use Mark's own numbers: 1 Oct (HRV 38 ms against a
usual 47) and 27 Sep (resting heart rate 47 against a usual 44).

Everything here applies only when the colour comes from the graded verdict. The rollback
(`VERDICT_ENGINE=ladder`) keeps today's words exactly.

## 1. The notice when one thing is a little off (Home and the brief)

For a low HRV night and for two mornings of raised resting heart rate. Replayed over the
102 stored mornings, 15 would carry this notice under the graded verdict, 5 of them beside
"Good to go — hold your targets" (23, 24 Jun, 22 Jul, 22 and 26 Sep). 1 Oct's real morning
showed it.

**Heading.** Was "Why today is capped". Proposed: **"Counted in today's call"**. A head cold
keeps "Why today is capped", because it does cap the day (easy riding at most).

**Low HRV night.** The first two sentences are unchanged; the last one changes.

> Your overnight HRV is 38 ms this morning against a usual 47 ms — lower than most nights
> for you. Dips like this usually come from a short night, a drink, a busy week or a hard
> day before. ~~On its own it caps today at Amber: an eased session, not a day off the
> bike.~~ **On its own it is one thing a little off, and today's call already counts it:
> not a day off the bike.**

**Resting heart rate up two mornings.**

> Your resting heart rate is 47 this morning against a usual 44 — a little above your
> usual range, as it was yesterday. Small rises like this usually come from travel, a short
> night, a busy week or a hard day before. ~~On its own it caps today at Amber: an eased
> session, not a day off the bike.~~ **On its own it is one thing a little off, and today's
> call already counts it: not a day off the bike.**

## 2. The off-the-bike notice: one clause

When the HRV dip comes with a second sign. The row said rest-level notices stay unchanged;
this clause is the only "cap" left in them.

> Your overnight HRV is 39 ms this morning against a usual 47 ms, and your resting heart
> rate is up as well. ~~Either on its own would only cap the day;~~ **Either on its own
> would only be a little off;** together they are worth respecting. Take today off the
> bike. If you feel unwell, rest until it settles, and see your GP if it doesn't.

## 3. Amber says the same thing on Home and the brief

| Where | Was | Proposed |
|---|---|---|
| Home, under "Take it easier" | Good morning, Mark. Take it a bit easier this morning. | Good morning, Mark. **Ease the hard work this morning; easy riding stays as planned.** |
| Brief page | Ease the hard work; easy riding stays as planned. | *(unchanged)* |

**On a rest or holiday day** the brief page now says what Home says: "Today's a rest day —
recovery is the plan, not training." On 1 Oct's holiday it said "Ease the hard work".

## 4. A light week that holds the session

W12 is CONSOLIDATION (5–11 Oct) and W13 TAPER (12–18 Oct). When a concern holds today's
session there (after Batch 300, only a mild one), every surface says the session stands.

| Where | Was | Proposed |
|---|---|---|
| Headline, Green held | Good to go — hold your targets | *(unchanged)* |
| Headline, Amber | Take it easier | **Ride as planned — hold your targets** |
| Line under it (brief) | One thing is a little off… / Ease the hard work… | **It's your consolidation week, so today's session stays as planned: hold your targets.** |
| Home line | …Take it a bit easier this morning. | **Good morning, Mark. It's your consolidation week, so today's session stays as planned: hold your targets.** |
| Plan line | This is a planned recovery week, so today's session stays as planned: hold the targets. | **This is your planned consolidation week, so today's session stays as planned: hold the targets.** |

"Consolidation" becomes "taper", "recovery" or "rest" to match the week his plan names.

## 5. "Yesterday was a hard day"

His commonest "a little off" reason (17 of 102 mornings). It reads as criticism of a
session his own plan set. It fires only when yesterday's training was hard by Garmin's
load or training effect.

> One thing is a little off: ~~yesterday was a hard day.~~ **you're still recovering from
> yesterday's hard session.**

## 6. The weekly mix when the hard work is eased (Batch 299)

Today any Amber adds "You'd be a Sweet Spot session short this week — moving it to …" or
"No Sweet Spot session this week", even when the session keeps its full length.

- **Hard intervals eased a zone, full length (new):** "Today's Sweet Spot session is eased,
  not lost: its hard intervals drop a zone and it keeps its full length."
- **Session held or moved:** no line.
- **Recovery spin or shortened ride (Red):** the "short this week" lines, unchanged.

## 7. Batch 300 adds no new words

A clearly-off morning in a light week shows the ordinary Amber lines: §3, and "Ease the hard
intervals a zone; the rest of the session stays as planned." Every other light-week concern
shows §4.

## 8. The knowledge base the brief reads (a production write; Craig's go of 1 Oct)

`training_plan.constraints`, written as a new version through the app's own writer (Mark's
real plan values kept, only these lines replaced). The code's seed text changes to match.

- **Amber.** Was "Amber days cut duration 20-30 percent and remove HIT." Proposed: **"Amber
  days ease the hard intervals a zone and keep the ride's full length; Zone 2 rides stay as
  planned. In a consolidation, taper or recovery week a mild concern holds the session,
  targets held."**
- **Red (optional, same write).** Was "Red days substitute recovery or rest and never keep
  VO2." Proposed: **"Red days turn hard sessions into an easy recovery spin and keep Zone 2
  rides, shorter; never VO2."** It matches what the graded Red does.

## 9. Model-facing, listed so nothing is hidden

- The brief's prompt (morning v53) stops calling an HRV or resting-HR signal a cap: on its
  own it is one thing a little off, already counted in the colour.
- The packet's reasons and the HRV floor's rule text say the same.
- The coach's view of recent mornings carries each morning's hold and each session's action.

## Decisions made on Mark's behalf (overrule any)

1. A single mild HRV or resting-HR notice is headed "Counted in today's call".
2. The off-the-bike notice loses "only cap the day" (§2).
3. The brief page follows Home on rest and holiday days (§3).
4. A light-week Amber is headed "Ride as planned — hold your targets" (§4).
5. The Red constraint is corrected in the same knowledge-base write (§8).
