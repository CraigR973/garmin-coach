# Batch 370 — Health rules completed: the words (for Craig's sign-off)

**Signed off by Craig on 5 Nov 2026** ("Yes, sign off").

Wave #6's health review found three gaps (HS361-04, -05, -06). The memory filter let 18 of
18 crafted health brush-offs through ("chest tightness is always his asthma"). A 9-second
heart-rate jump on 24 Sep's ride was read as the strap, and nothing asked him. And nothing
read his blood pressure or asked again about his medicines after Craig set the fact on 6 Oct.
Craig decided on 4 Nov: a held-back health statement goes nowhere; a jump eases the next hard
session until he answers, as a note does; and a new medicine is his to tell Craig.
`apps/api/tests/test_batch_370_health_rules.py` holds the app's words to this file.

## 1. The memory filter (370.1, no words)

A coaching memory, or the quote it rests on, that names a symptom, diagnosis, medicine or
medical reading is not saved and goes nowhere else. Mark sees nothing new. Plain heart-rate
facts still pass: a chest strap, drift in a warm room, breathless on VO₂ work. None of his
10 saved memories or 9 earlier proposals names a health matter, so there is nothing to remove.

## 2. A heart-rate jump on a ride (370.2)

**When:** the morning after a ride (or later the same day) whose trace shows a jump of 30 bpm
or more within 5 seconds, from his steady level, with no rise in power, or a heart rate more
than 10 above the highest he has recorded on a ride. On his 58 rides with a trace since March
it finds 24 Sep only. **Asked:** once, unless he has answered Home's question since the ride.
**Card:** Home's existing symptom card, *Any symptoms since your last check-in, including on
a ride?*, with the check-in's four answers ("Chest or heart" among them). Its line:

> On yesterday’s ride your heart rate jumped from 136 to 197 in 6 seconds, with no change in your power. Did you feel anything? Until you answer, today’s hard session is an easy ride.

With no hard session planned, the line ends instead:

> … Did you feel anything? If you did, tell me, so today’s plan fits.

For a heart rate past his recorded maximum, the line opens:

> On yesterday’s ride your heart rate reached 182, higher than on any ride you’ve recorded.

**A note that says it** ("HR shot to 190 on an easy spin") now asks, with the card's existing
words ("Your note mentions “HR shot to 190 on an easy spin”."). This is a rule in code beside
the notes reader, so the reader's prompt and its paid eval are unchanged.

**The brief is told:** "ride (the app saw his heart rate jump on a ride with no change in his
power, or pass the highest he has recorded, as notesReading.rideJump gives it, and asks whether
he felt anything): name it that way, never call a ride's jump a sensor glitch or the strap".

## 3. Blood pressure (370.3)

**180/110 or above** (either figure) on this morning's check-in, the notice:

> Your blood pressure this morning is 185/115, which is very high. Please speak to your GP or call 111 today, and keep to easy riding until you have.

A hard session becomes an easy spin, and the reason under today's call reads:

> Easing off for your very high blood pressure this morning: easy riding only until you've spoken to your GP or 111.

**160/100 or above**, a watch notice, with no change to the plan:

> Your blood pressure this morning is 165/95, higher than it should be. It's worth mentioning to your GP; today's plan doesn't change.

A reading outside 70–260 over 40–160 is taken as a typo and judged not at all. A low reading
with faintness already counts as chest or heart, through his note.

## 4. Any new medicines? (370.3)

From 5 Jan 2027, three months after the fact was last dated (Craig, 6 Oct), and every three
months after that, Home shows:

> **Any new medicines?**
>
> Have you started any new medicines or tablets in the last three months, from your GP or the chemist?
>
> [No, nothing new] [Yes, something new]

"Yes" opens a box, *Which one? (optional)*, and a Save button. Then:

> Thanks, noted. New medicines can change your heart rate and HRV, so mention it to Craig and he can check your zones.

After "No":

> Thanks. I’ll ask again in three months.

Nothing is sent to Craig. A yes is saved in his profile's medication fact, in his words, and
the coach and the brief read this:

> He told the app he has started a new medicine (newWords, on newSince) and was asked to mention it to Craig. Until his profile says it has been checked, a change in his heart rate, resting heart rate or HRV may be the medicine rather than his recovery: say so, and never read such a change at face value.
