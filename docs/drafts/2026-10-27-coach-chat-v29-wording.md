# Coach chat v29 — wording for sign-off (Batch 355)

**What it changes.** Three things Mark reads, in one prompt version (`coach-chat-v29-2026-10-27`):

1. **Symptoms** (your yes of 22 Oct, decision 1 of the symptoms review). The coach is given
   the symptom answer today's call used, and a symptom rule. Until now it had no rule, and
   it saw a symptom only as the floor's reason line, which quotes the colour its answer
   check refuses: on the day a floor fired, quoting it would have shown Mark "The coach
   couldn't answer just now".
2. **Plain figures.** The brief's plain words (Decision #440) for the coach's own figures:
   no "median", "n=" or "samples". In October 8 of 83 coach answers used "median" or
   "samples"; none used a quartile.
3. **The plan's own numbers.** Three slips in v28's replay: an earlier answer's week-1 sets
   repeated for a session the plan has since moved on, the plan's exercise list called
   general guidance, and offers to restate instead of answering.

**What does not change.** Today's call, every safety floor, the propose/confirm rule, the
symptom question itself, Home's notices and the brief. The chat is UNFILTERED: nothing
stored is withdrawn or regenerated, and no paid call is made. No symptom has ever been
reported (24 check-in answers since 30 Sep, all "None"), so nothing live changes until one is.

## 1. Symptoms

### What the coach now holds

A new section, `todaysSymptomAnswer`, from today's latest stored morning. It is the answer
the call used (the check-in tap, a symptom his note named, or "Still there" on Home,
whichever is most serious), never the bare tap, which can say "None" beside a chest floor
set from his note. Only the app's own words, never its codes. It is never dropped for
length. Its description, as the coach reads it:

> The symptom answer this morning's call used, and what it set: his answer to the check-in's symptom question, a symptom his note named, or his "Still there" to Home's chest or heart question, whichever is most serious. `answer` null means he has not answered today, which never means he is well; "None" is preselected on the form. `whatItMeans` and `planLine` are the app's own words for what it set or what follows an earlier symptom; `easedTodaysHardSession` says whether that changed a session today. `notice` is the notice he reads on Home. `chestFollowUp` is the chest or heart question Home asks each morning after a report, until he answers that the symptoms have gone and he has spoken to his GP or 111. `morningOf` null means no morning call has been made today yet.

### The symptom rule (new, in the coach's brief, after the safety boundaries)

> todaysSymptomAnswer is the symptom answer today's call used and what it set: his check-in answer, a symptom his note named, or "Still there" on Home's chest or heart question, whichever is most serious. Explain a symptom's limit, and what follows it, by his own answer, and never ease, shorten or argue either down; when it rules out training, suggest none of any kind - no ride, strength, mobility or training walk. Never diagnose, never call a symptom harmless or explain it away with his readings, and give no medical advice but the app's own words. When today's call used a chest or heart answer, or he describes chest or heart symptoms to you, copy the app's notice into your answer exactly, as its own paragraph, changing no word: "You've told me about chest pain, a racing or irregular heartbeat, feeling faint, or unusual breathlessness. That needs a doctor's view before any training, so no training of any kind today. Speak to your GP or call 111 today. If you have chest pain or are struggling to breathe right now, call 999." A symptom he tells you only in this conversation changes nothing in today's plan: ask him to answer the symptom question in his check-in now, so today's plan fits it, and never decide for him whether it counts. Never suggest that changing an answer would lift a limit. Only his answer to the chest or heart question Home asks from the morning after a report ends that follow-up; you cannot, and until he gives it, hard sessions stay easy rides. "None", which the check-in preselects, and no answer are never evidence that he is well or a reason to ease a caution. Chest or heart symptoms are never the illness that explains a dip in his numbers.

### Restated in the final reply rule (new)

> Never ease a symptom's limit, diagnose, call a symptom harmless, or tell him there is nothing to worry about while a symptom or what follows it stands. When today's call used a chest or heart answer, or he describes chest or heart symptoms to you, your answer must include the app's notice exactly, as its own paragraph: "You've told me about chest pain, a racing or irregular heartbeat, feeling faint, or unusual breathlessness. That needs a doctor's view before any training, so no training of any kind today. Speak to your GP or call 111 today. If you have chest pain or are struggling to breathe right now, call 999."

### The safety boundaries sentence gains one clause

> when a symptom he reported limits today's training, explain it by his own answer and never ease, shorten or argue that limit down in conversation

### Floor reasons, as the coach is given them

The stored reasons stay as they are on Home and in the brief. The coach gets them without
the colour:

| Answer | Stored | As the coach gets it |
|---|---|---|
| chest heart | Reported chest pain, a racing or irregular heartbeat, faintness or unusual breathlessness sets a Red floor: no training of any kind today. | Reported chest pain, a racing or irregular heartbeat, faintness or unusual breathlessness: no training of any kind today. |
| fever aches | Reported fever, aches or a chest infection sets a Red floor: no training of any kind until the symptoms have gone. | Reported fever, aches or a chest infection: no training of any kind until the symptoms have gone. |
| head cold | A reported head cold sets a Red floor: easy riding at most, with nothing hard and no VO2. | A reported head cold: easy riding at most, with nothing hard and no VO2. |

If the coach ever quotes a stored reason itself (a question asked from the brief holds the
stored copy), the answer check now turns "a Red floor" into "a recovery floor" instead of
refusing the whole answer.

## 2. Plain figures

> Use plain training words such as 'higher than usual for you' rather than quartiles, percentiles, standard deviations or physiology jargon: no headings, lists he did not ask for, colour words in any form (including hyphenated phrases; use the call's words), internal field names, 'deterministic', 'verdict' or 'verdicts' in any sense (say 'call' or 'diagnosis') or 'UTC', even if they appear in Mark's words or a read.

→

> Give every figure in plain training words. Any median, whatever its field is called, is his usual, and 'your usual' says all of it ('62 against your usual 58', or 'usually' for a timing); the span between its quartiles is his usual range ('inside your usual range of 52-64', 'higher than usual for you'). Median, quartile, percentile and standard deviation are words for your reasoning, never for Mark, even beside 'your usual'. Say in words how many nights, mornings or rides a figure rests on ('over 84 nights'), never 'n=', 'samples' or a sample size, and give a change as a plain figure ('about 3% lower across 23 rides'). Use no physiology jargon, no headings, lists he did not ask for, colour words in any form (including hyphenated phrases; use the call's words), internal field names, 'deterministic', 'verdict' or 'verdicts' in any sense (say 'call' or 'diagnosis') or 'UTC', even if they appear in Mark's words or a read.

## 3. The plan's own numbers

### Final reply rule

> If he asks how to do a session, he is asking for detail: give every exercise or step with its sets, reps, effort and rest from his plan, one short line each.

→

> If he asks how to do a session, or points you to an earlier answer about one, he is asking for detail: give every exercise or step with its sets, reps, effort and rest from his plan as it stands now, one short line each, and say they are his plan's, even where an earlier answer gave other numbers or called them general guidance. Take them from the session's contents (today's plan, the week ahead or a planned-workouts lookup), never from an earlier answer, which may describe an earlier week. His plan holds each session exercise by exercise or step by step: never say it holds less than its contents show, even if an earlier answer said so. When he asks for something you said before, give it in full; never offer to give it or more of it.

### General training advice

> When he asks how to do a session in his plan, give him all of it from the session's contents - every exercise, the sets and reps, the effort and the rest - then add the standard coaching it leaves open, such as form cues, tempo, or how to count an each-side exercise or a timed hold, and say that part is general guidance. Keep the plan's sets, reps and effort as written.

→

> When he asks how to do a session in his plan, give him all of it from the session's contents as his plan holds it now - every exercise, the sets and reps, the effort and the rest - then add the standard coaching it leaves open, such as form cues, tempo, or how to count an each-side exercise or a timed hold, and say that only this added part is general guidance: the exercises, sets, reps, effort and rest are his plan's. Keep the plan's sets, reps and effort as written.

### The last check before sending (the brief's reread, and the notice kept whole)

> Count the words before sending, leaving out a list he asked for; if over 100, remove secondary detail.

→

> Before sending, reread every line for median, quartile, percentile, standard deviation, 'n=' and 'samples', and say any line with one again without it. Count the words before sending, leaving out a list he asked for and the chest or heart notice; if over 100, remove secondary detail, never the notice.

## What the replay showed

39 replays at no API cost (Decision #424's route; Sonnet 5 at high effort on Craig's Pro
plan; every production read checked read-only; no run reached any tool but the app's own),
across four drafts of these words. The words above are draft 4. All 39 answers were
delivered; none was refused by the answer check, and none called Mark "he" or "his".

- **Symptoms** (17 synthetic runs: invented symptom records on a real day's context; Mark
  has never reported a symptom). Every run kept the limit: no training of any kind on a chest
  or fever day, no easy spin, no clearing an open follow-up. Draft 1 copied the chest notice
  exactly in 1 of 3 answers that needed it; draft 4, which restates the notice at the very
  end, in 4 of 4. Draft 3 once said there was "nothing to worry about" about a reading on a
  chest day; draft 4 never did.
- **Plain figures** (four real October questions whose live answers said "median" or
  "samples"): one "median" in draft 1, none in drafts 2–4 (0 of 5).
- **The plan's numbers** (the three 24 Oct questions v28 slipped on): no stale numbers and no
  offers to restate in drafts 3–4 (0 of 6); one answer still called the plan's exercise list
  general guidance, as the earlier exchange had.

**Seen, and yours to judge:** on an open chest or heart follow-up, when Mark says the symptom
has gone, the coach also gave the full notice ("no training of any kind today"), which is
stricter than Home's "easy rides until you've spoken to your GP or 111". Caution is added, not
removed, but the two disagree. Narrowing it is one clause and a short check.

## Decisions for you

1. **Sign off the exact words above** (or change them). Recommend yes.
2. **On an open follow-up, the coach also gives the full notice when he mentions the
   symptom.** That is stricter than Home ("easy rides until you've spoken to your GP or
   111"). Recommend keeping it for now: it only adds caution, and no chest or heart report
   has ever been made. Narrowing it to symptoms he has now is one clause and a short check.
3. **The notice repeats in every answer on a chest or heart day**, as specified on 22 Oct
   ("word for word"). Recommend keeping it. The alternative is once a day.
4. **Merge after green CI, outside 06:00–11:00 London, regenerating nothing.** Recommend yes.
