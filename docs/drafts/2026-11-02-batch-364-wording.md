# Batch 364 — a morning with no data still gets a cautious call: the words (for Craig's sign-off)

**Signed off by Craig on 2 Nov 2026** ("yes lets make the no brief as cautious"). Batch 364 gives a morning whose overnight data never arrived a
call of its own, says on Home why the brief is waiting, tells the coach, and follows a
fever up the way a chest or heart report already is.
`apps/api/tests/test_batch_364_no_data_morning.py` holds the app's lines to this file.

Every change here adds caution or says why; none removes any.

## 1. Today's call on a morning with no overnight data (364.1)

**Where:** the big card at the top of Home and the brief page, on a morning the app made
without last night's data (Garmin down, or the watch not synced). The chip under it reads
**Not enough data** on every kind of day now, never "Some fatigue".

A ride kept as planned (Zone 2 or a long ride). **Replaces** 321's "Today's plan already
suits that; keep it comfortable." for a ride; strength-only days keep 321's line:

> **Not enough data**
> Last night's data didn't fully come through, so today errs on the careful side. Ride as planned with an easy first 15 minutes; if your heart rate sits higher than usual or it feels harder than it should, make it shorter and easier.

A test day. **Replaces** "A test needs you fresh, and you're not quite there today…", which
blamed his freshness:

> **Test day — fresh or move it**
> Last night's data didn't come through, so I can't tell whether you're fresh enough for a test. Move it to a morning with data; don't ride it eased.

A rest day. **Replaces** "Good timing — there's some fatigue about, and today lets it clear.":

> **Rest day**
> Last night's data didn't come through, but nothing about today changes. Enjoy the rest.

Unchanged and reused: a hard session reads 321's "Last night's data didn't fully come
through, so today errs on the careful side: ride the full session with the hard efforts
eased a zone."; a recovery week reads "As planned — hold the targets" with its own line.

## 2. Home when the brief waits for the data (364.3)

**Where:** the card under today's call, when the brief is held for missing watch data.
**Replaces** "Couldn't finish your written brief · Today's call and your plan above are
complete without it. Your check-in is saved." The button stays **Try again**.

> **Your watch data hasn't come through**
> Today's call above is a careful one, made without last night's data: follow it if you ride before your watch syncs, and stop if anything feels wrong. Once it has synced, tap Try again for your written brief.

On the check-in page after saving:

> **Your watch data hasn't come through**
> Today's call is ready on Home: a careful one, made without last night's data. Your check-in is saved. Once your watch has synced, tap to try again.

The pop-up after saving:

> Today's call is ready — your watch data hasn't come through yet

On the rare morning the app could not make a call at all (Home's top card):

> **Your watch data hasn't come through**
> I can't read your day without last night's data. If you ride before it comes through, keep it easy and stop if anything feels wrong. Your check-in is saved.

The push he already gets ("Today's call is ready", with the call's headline) is unchanged.

## 3. The coach on such a morning (364.4)

**Not shown to Mark; it shapes what the coach says.** New rule in the coach's instructions
(chat v31):

> When todaysBrief.state is waiting_for_watch_data, last night's watch data has not reached the app. Say so plainly. Today's call was made without it and is already the careful one: give it in its own words, and never tell him that checking in again will bring the read. If he asks whether to ride, the call's session actions decide: hard efforts a zone easier, a test moved to a morning with data, and easy riding with an easy first 15 minutes. Once his watch has synced, Try again on Home writes his brief.

## 4. After a fever: "has it gone?" (364.5)

**Where:** a card on Home each morning after he reports a fever, aches or a chest
infection, until he answers that it has gone. It works like the chest or heart card
(signed off 6 Oct). Until he answers, riding stays easy and loaded strength becomes gentle
mobility; his "Gone" starts the two easy days back (signed off 2 Oct), so those now count
from the morning he says it has gone, not from the morning after the report. "Still there"
shows the fever notice signed off on 28 Sep and sets that day's no-training floor.

The card:

> **Fever, aches or a chest infection on Thursday**
> Has it gone for a full day, without paracetamol or ibuprofen? Until it has, riding stays easy.
>
> [Gone for a full day, without paracetamol or ibuprofen]
> [Still there]

The reason under today's call while it is open:

> Easing off after the fever you reported on Thursday: easy riding only until you tell me it has gone.

The notice above it:

> You told me about a fever, aches or a chest infection on Thursday. Until it has gone for a full day without paracetamol or ibuprofen, easy riding at most and gentle mobility instead of strength. Then two easy days back before anything hard.

Today's call on such a day with no hard ride to ease:

> **Easy riding only**
> Until you've told me the fever has gone, keep any riding easy and swap strength for gentle mobility.

**Why "a full day, without paracetamol or ibuprofen":** both bring a temperature down, so
a day on them can hide a fever that has not gone; the return-to-sport guidance asks for
symptoms to have resolved before training resumes (ESC 2020 sports cardiology, IOC 2022
acute illness consensus), then graded.

The written brief is told the same (brief v66, a rule the reader never sees):

> Since Batch 364 a fever is followed up as chest or heart symptoms are. Kind fever_follow_up means he reported a fever, aches or a chest infection on easing.reportedOn and has not yet said it has gone for a full day; Home asks him each morning, riding stays easy and loaded strength is gentle mobility: say so in one sentence, in the app's own words (easing.reason), and never decide for him whether it has gone. symptoms.feverFollowUp is the fever follow-up the morning is in. Kind fever_return's two easy days back now count from the morning he said it had gone.
