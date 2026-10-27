# Batch 353 — wording for Craig's sign-off (26 Oct 2026)

**Signed off by Craig, 27 Oct:** "1) I sign off the exact words in the #400 draft. 2) Do the notice dates as "10 Jun to 1 Sep" in a separate small change. 3) Merge after CI is green, outside 06:00-11:00."

Batch 352's follow-up, which you asked for on 26 Oct: the oxygen notice and the "How these numbers
were worked out" panel, in the brief's plain words. Nothing here merges or deploys until you
sign off the exact words. The figures below are the tests' examples, not Mark's.

## The oxygen notice (low oxygen on several nights)

Before:

> Your watch recorded an **oxygen nadir** of 86% last night, below 88% on 2 of the last 3 nights.
> Its usual overnight average is 96% from 2026-06-10 to 2026-09-01, and your breathing rate has
> stayed **above its usual upper quartile of 12** from 2026-06-10 to 2026-09-01 for two nights.

After:

> Your watch recorded **a lowest oxygen reading** of 86% last night, below 88% on 2 of the last 3
> nights. Its usual overnight average is 96% from 2026-06-10 to 2026-09-01, and your breathing rate
> has stayed **above its usual range (up to 12 from 2026-06-10 to 2026-09-01)** for two nights.

Unchanged, word for word: the closing sentences ("Sustained low overnight oxygen has causes worth
checking properly — a chest infection, or disrupted breathing during sleep. This one isn't
something training or rest changes. Mention this to your GP if it happens again.") and the other
oxygen notice (a low average), which was already plain.

## The panel's HRV floor row ("How these numbers were worked out")

Rule — before:

> your own **median** (46.0 ms) **minus 1.5 standard deviations of it**. This is your own floor,
> not a population band and not Garmin's.

Rule — after:

> **your usual** (46.0 ms), **less 1.5 times how much your nights usually vary from it**. This is
> your own floor, not a population band and not Garmin's.

Off the bike — before:

> only at 34.6 ms or lower (**2.5 standard deviations or 30% under your median**), or below the
> floor together with a raised resting heart rate or a symptom you've reported.

Off the bike — after:

> only at 34.6 ms or lower (**2.5 times that variation, or 30%, under your usual**), or below the
> floor together with a raised resting heart rate or a symptom you've reported.

No other panel row uses these words.

## When Mark sees it

- **The panel** builds its words on screen from the stored figures, so every morning he opens,
  old or new, shows the new row as soon as the web deploys.
- **The oxygen notice** is stored with each morning, so it changes from the next morning written.
  It shows only on a morning with low oxygen readings.
- No prompt version changes, nothing is regenerated, and there is no paid call.

## Not changed here

- **Dates:** the notices print their baseline windows as "2026-06-10 to 2026-09-01". That is true
  of the HRV notices as well as the oxygen one, so it is a change of its own ("10 Jun to 1 Sep").
- **The packet's own HRV floor basis**, which the brief and the coach read but Mark never sees,
  still says "median minus 1.5 standard deviations". Batch 352's rule keeps it out of the brief.

## Decisions for you

1. **Sign off these exact words**, or say what to change.
2. **Dates in the notices:** print them as "10 Jun to 1 Sep" in a separate small change, or leave them?
3. **Merge:** after your sign-off and green CI, outside 06:00–11:00 London.
