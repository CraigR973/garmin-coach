# Batch 339 — the words Mark sees (for Craig's sign-off)

**Draft, not signed off.** Batch 339 makes a chest or heart symptom reach the next
morning wherever Mark mentions it (a note on a ride, or the coach chat), stops a quiet day
reading "You're recovered" while a chest or heart follow-up is open, and makes four health
lines say no more than the evidence. Every Mark-facing line that is new or changes is
below, word for word. `apps/api/tests/test_batch_339_symptom_anywhere.py` and
`apps/web/src/components/NotesAskCard.test.tsx` hold the app's lines to this file.

**Replay, read-only, on production (29 Oct, 129 stored mornings, this branch against
`main`):** no colour, floor or session action changes on any morning. Two mornings gain a
notice (section 5: 1 and 2 Oct). Nothing in his history reaches the other new lines: no
chest or heart follow-up has ever been open, his highest HRV night is 60 ms against a line
of about 63 ms, no single night has averaged under 92% oxygen, and no coach answer has
ever carried the chest or heart notice. Every change is toward caution.

## 1. Home's question when he told the coach (339.2)

**Where:** Home's symptom question card, the morning after the coach gave him the chest or
heart notice (the coach gives it word for word when he describes chest or heart symptoms
to it). With a hard session planned:

> You told the coach about chest or heart symptoms. Until you answer, today's hard session is an easy ride.

With no hard session:

> You told the coach about chest or heart symptoms. If they're still there, tell me, so today's plan fits.

**Example:** none in his history (0 coach answers carry the notice).
**Replaces:** nothing; a symptom told only to the coach reached no morning.
**The same first sentence** is the reason line under today's call on such a morning.
**Question for Craig:** this asks and eases rather than setting the full chest or heart
floor, because the coach also gives the notice when chest symptoms come up in other ways
(a question about what to do if they happened). His tap of "Chest or heart" sets the
floor. Is that the right strength?

## 2. A chest or heart symptom in a note on a ride (339.2)

**No new words on Home:** the next morning reads the note he left on yesterday's or
today's session. A clear report sets the existing chest or heart floor, with its notice
signed off on 28 Sep ("You've told me about chest pain, a racing or irregular heartbeat,
feeling faint, or unusual breathlessness…"). A possible one asks with the existing card
("Your note mentions "…". Until you answer, today's hard session is an easy ride.").

**The post-ride read (new rule, prompt v19):** when his post-ride notes mention chest
pain or tightness, a racing or irregular heartbeat, feeling faint or dizzy, or unusual
breathlessness, the read copies the chest or heart notice word for word, then says in one
sentence that the app will ask him about it on Home tomorrow morning and that tomorrow's
plan will fit his answer. The model writes that sentence in its own words; the rule tells
it what to say.

**The coach (new sentence, prompt v30):** when he describes chest or heart symptoms, the
coach also tells him the app will ask him about them on Home the next morning, and that a
hard session is an easy ride until he answers.

**Example:** none in his history; he has left 112 notes on sessions since 5 Jul and none
mentions a chest or heart symptom.

## 3. Today's call while a chest or heart follow-up is open, with no hard ride (339.3)

**Where:** the big card at the top of Home and the brief page, on a morning after he
reported chest or heart symptoms and before he has answered "Gone, and I've spoken to my
GP or 111", when no hard ride is planned (a Zone 2 ride, strength, or a rest day).

> **Easy riding only**
> Until you've spoken to your GP or 111 about the chest or heart symptoms you reported, keep any riding easy and swap strength for gentle mobility.

**Replaces:** "Green light. You're recovered. Today's session is on as written. Keep the
easy riding easy." (or the rest-day words). With a hard ride the call stays "Easy day", as
signed off for Batch 315.
**Question for Craig:** the small chip under the call still shows the numbers' reading
("Recovered" on a good-numbers morning). Keep it, or hide it on this call?

## 4. The day's plan lines on the same mornings (339.3)

**Where:** the plan lines under today's call.

> Easy riding only until you've spoken to your GP or 111: nothing hard.

and, when a strength session is planned (not recovery strength):

> Swap today's strength session for gentle mobility until you've spoken to your GP or 111.

**Replaces:** "Proceed with the planned workout if warm-up confirms readiness." and the
strength session going ahead as planned.

## 5. His breathing rate, up two nights beside his heart readings (339.4, HS332-07)

**Where:** a notice on Home and the brief page, headed as a "watch" notice. It changes no
training. Shown when his breathing rate was at least 2 breaths a minute above his usual
for two nights running and a heart reading is off too (his HRV or resting heart rate rail,
or last night's HRV under his usual by more than half his usual spread).

> Your breathing rate has been up for two nights (13 then 13 breaths a minute, against a usual 11), and your heart readings are off too. That can be the start of a cold. If you feel one coming, tell me in your check-in.

**Example:** 1 Oct and 2 Oct, his numbers (the first days back from his holiday, HRV
38 ms against a usual 47). **Replaces:** nothing; breathing never spoke on its own.

## 6. A night far above his usual HRV (339.4, HS332-06)

**Where:** a "watch" notice on Home and the brief page. It changes no training, and the
night is left out of his 7-day HRV so it cannot hide a dip. Shown when last night was
above his usual by more than three times his usual spread (about 63 ms for him now).

> Your overnight HRV was 85 ms last night, far above your usual 47 ms. A jump that size is more often the watch than you, so it doesn't count as extra recovery today. A racing or irregular heartbeat in the night can cause it too: if you noticed one, answer "Chest or heart" in your check-in.

**Example:** none in his history (highest night 60 ms on 22 Aug; the 85 ms above is the
review's probe). **Replaces:** nothing; such a night read "Green light. You're recovered.
Make it count."

## 7. One low oxygen night (339.4, HS332-08)

**Where:** the oxygen notice on Home and the brief page, when one night averaged under 92%.

> … A low reading like this is often the watch; if it repeats, it has causes worth checking properly — a chest infection, or disrupted breathing during sleep. This one isn't something training or rest changes. Mention this to your GP if it happens again.

**Replaces:** "… Sustained low overnight oxygen has causes worth checking properly — …".
The opening sentence with his figures, and the notice for several low nights, are
unchanged. **Example:** none in his history.

## Not changed

- The chest or heart notice itself, the floors, and the follow-up's card and buttons.
- 339.5 (a chest report also alerting Craig) is not built: it waits for Mark's consent.
