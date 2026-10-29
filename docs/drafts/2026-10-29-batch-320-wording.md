# Batch 320 — tonight's advice, and whether it helped (for Craig's sign-off)

**Signed off by Craig on 29 Oct 2026** ("All as recommended"): the four pieces of advice as drafted, asked every advised morning. On a morning that was cautious, Home's Tonight card and the
brief's "Tonight:" sentence now give one thing to do tonight about the reason, with how
strong the evidence is. The next morning's check-in asks, in one tap, whether he managed
it, and the weekly review reports the next morning's change as weak evidence. Every
Mark-facing line is below. `apps/api/tests/test_batch_320_tonight_advice.py` holds the
app's lines to this file.

**Measured, read-only, on production (29 Oct):** of the 28 graded mornings since 30 Sep, 20
would have carried advice: 10 his heart readings, 6 his training load, 4 his sleep; 8 had
nothing off and carry none. No colour, floor or session action changes.

## 1. Tonight's advice (320.2)

**Where:** Home's Tonight card (its one-line summary, and the top of the card), and the
"Tonight:" sentence in the written brief's "Today's call" (the model words that sentence;
the card shows these words as they are). Chosen from the most-off part of the morning:
heart readings first, then sleep, then load, then how he feels.

**When his heart readings are down** (HRV this week or last night, or resting heart rate):

> Your heart readings are down. Tonight: no alcohol, finish eating about three hours before bed, and a quiet last hour without screens.
>
> Alcohol and late meals lower overnight HRV in studies of other people; the app hasn't measured them for you.

Example: the mornings after a holiday, when his HRV ran well under his usual.

**When last night's sleep let him down:**

> Last night's sleep let you down. Tonight: protect your sleep window. In bed at your usual time, the room cool and dark, and the alarm left where it is.
>
> A regular, protected sleep window is standard sleep advice; the app hasn't measured it for you yet.

Example: a morning after a short, broken night.

**When his training load is high:**

> Your training load is high. Tonight: a proper meal with carbohydrate and protein, and bed half an hour earlier than usual.
>
> Food and sleep are how hard training turns into fitness; this is general advice, not something the app has measured for you.

Example: the middle of a build week.

**When he's feeling flat:**

> You're feeling flat. Tonight: an easy evening and an earlier night.
>
> General advice; the app hasn't measured it for you.

**Replaces:** on Home, the sleep projection's headline ("Tonight looks like a standard
protocol night", "Give tonight extra margin for…") as the card's summary on a cautious
day; the projection itself stays in the card below. A morning with nothing off is
unchanged.

## 2. The next morning's question (320.3)

**Where:** the morning check-in, a card above "Last night's REM focus", only when
yesterday's morning gave advice. Optional; leaving it unanswered records nothing.

> **Last night's advice: did you manage it?**
> *(yesterday's advice line)*
> [Yes, I did] [Not this time]

**Replaces:** nothing; nothing recorded whether advice was followed.

## 3. The weekly review (320.3)

The review is told what the week's cautious mornings advised, how many nights he said he
did it, and, only with at least two nights each way, the next morning's average change in
sleep score and HRV on nights he did it against nights he did not. It reports it in one
or two sentences as what happened that week and says plainly it is weak evidence. It never
says the advice works or does not. The model writes those sentences.

## Not Mark-facing

- **HS332-02:** the REM experiment no longer calls a lever "better" or "worse" when the
  nights he applied it and the nights he did not sit in different weeks of the year. It
  says the season could explain the difference.

## Questions for Craig

1. Are the four pieces of advice the right ones, in his words? (They are general advice,
   and each says so.)
2. Is a one-tap question at the check-in welcome every cautious morning (about 20 of 28
   mornings so far), or should it ask only when the advice repeats?
