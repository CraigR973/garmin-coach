# Morning verdict redesign — review before the spec

28 Sep 2026 · Lenses: cycling coach, doctor, AI engineer, software engineer · Read-only: no code changed, nothing written to production, no paid model calls.

**What was reviewed.** The proposal from the 28 Sep chat: keep the colour computed by rules, but (1) grade the evidence instead of letting the first matching rule decide the day, (2) have Claude read Mark's check-in notes into flags, (3) keep the hard floors fixed, and (4) replay every stored morning before shipping.

**Terms used below.**

- **Floor:** a rule no other signal can override.
- **Domain:** a group of signals that measure the same underlying thing.
- **Packet:** the bundle of data a morning's read is built from.
- **Evidence labels** follow `COACHING_INTEGRITY_AUDIT.md`:
  - *observed:* seen in production data.
  - *computed:* a rule's arithmetic re-run in SQL over production rows, not by running the app's own function.
  - *implemented:* read in the code.

## Bottom line

**Go, with six changes.** The direction is right: a deterministic colour, graded evidence, and Claude as a reader rather than a decider. But three parts of the proposal were wrong, and one thing I said in chat was wrong:

- **"Keep the hard floors fixed" was wrong.** The overnight-HRV alarm that takes Mark off the bike is itself miscalibrated. It would have fired on 6 of 75 mornings, 3 of them by less than 1 ms.
- **"Two signals agreeing" must mean two independent domains.** Garmin readiness mostly restates his sleep score and recovery time. Counting it as a separate vote repeats the double-count behind September's Reds.
- **"Flags weigh in either direction" was wrong.** Flags Claude reads from notes may only add caution. Only Mark's own taps can relax the day.
- **I said his feel score adds little because it hardly moves.** It moves in a narrow band, but it tracks his sleep, readiness and HRV. Judge it against his own average, not a fixed line at 5.

The six changes:

1. Count agreement across independent domains, not signals (AI engineer).
2. Make floors medical and rare, and grade everything else (doctor).
3. Ask about symptoms with one tap, with fever and heart floors (doctor).
4. Let Claude's reading of the notes only add caution (AI engineer).
5. Make the action depend on today's session: move a hard session before cutting it, and leave easy days alone (coach).
6. Add shadow mode and outcome checks, not just a replay (software engineer).

## What the data says

Observed over 98 mornings, 21 Jun to 27 Sep.

- **Colours:** 59 Green, 18 Amber, 21 Red (21%).
- **Reds came from three rules:**
  - the HRV rule: 12
  - one bad night's sleep (age-adjusted score under 60): 8
  - Poor readiness plus a second signal: 1
- **After the 27 Sep HRV change** (Batch 269), 8 of those Reds become 5 Green and 3 Amber. 13 Reds remain (13%):
  - 8 from one bad night's sleep
  - 4 from HRV
  - 1 from readiness

  No live morning has run under the change yet.
- **Ambers came from:**
  - readiness Low or Poor: 9
  - sleep 60–73: 6
  - the age-credit ceiling, the rule that stops age credit alone making a day Green: 2
  - heavy load: 1
- **His feel:** 79 scored mornings, average 6.7, spread ±1.0. It moves with:
  - sleep score: r = 0.58
  - readiness: r = 0.54
  - overnight HRV: r = 0.42
  - resting HR: r = −0.41

  That fits the evidence that athletes' self-reports track training strain at least as well as objective measures (Saw 2016).
- **Garmin readiness:** moves with his sleep score (0.69), recovery time (−0.72) and resting HR (−0.55), but hardly with overnight HRV (0.15).
- **Notes:** 54 of 75 morning check-ins have notes, median about 165 characters. A keyword search for illness words matched 7. All 7 were about bedroom temperature, draughts or breathing exercises. None reported a symptom.
- **Mark's own words, in chat, 18–24 Sep:** the app over-weights one marginal metric. It should grade rather than jump to Red ("at worst Amber"). It risks under-training him.

## Coach

### CO-1 · High · A mild concern on an easy day should change nothing

Today's cautious days cut the session whatever it is (implemented, observed):

- Amber shortens even a Zone 2 ride to 75% of its time.
- On 24 Sep a single HRV signal turned a long sweet-spot ride into a short, easy spin.

HRV-guided training trials all use one simple rule. They were run in cyclists (Javaloyes 2019) and runners (Vesterinen 2016; Kiviniemi 2007):

- HRV inside the athlete's normal range: do the planned session.
- HRV below it: make it a low-intensity day.

Those groups improved as much or more, usually with fewer hard sessions. The gain came from putting hard sessions on good days, not from deleting them.

**Fix.** Make the action depend on both the concern and the session:

- **No concern:** ride as planned.
- **Mild concern:**
  - An easy day is unchanged.
  - A hard day moves within the week if a better day exists.
  - Otherwise ride it with targets held: the full session, without pushing past the top of each zone.
- **Marked concern:** today's Amber, with hard work eased a zone. Zone 2 is kept at full length.
- **Two domains marked, or he says he feels rough:** recovery or rest.

### CO-2 · High · Nothing measures under-training

The app counts Reds but not what they cost him. That is exactly Mark's worry.

**Fix.** Report two numbers each week and in the replay:

- key sessions completed against planned (VO2, threshold, long ride)
- cautious days, broken down by what caused them

Coaching judgement, not a published figure: for a healthy, well-trained 57-year-old, true "recover today" days should be a few a month at most. If the replay still shows Red on more than about 1 morning in 10, a rule is too sensitive. Find which rule; don't tune the thresholds to hit the number.

### CO-3 · Medium · One bad night's sleep shouldn't be Red on its own

This is now the biggest cause of Red: 8 of the 13 that remain. A poor night lowers the quality of hard work and makes efforts feel harder. But easy riding is fine and helps rebuild sleep pressure. That is the app's own reasoning from when it stopped Red deleting Zone 2 rides (Batch 215).

**Fix.** A very poor night on its own means skip the intensity but keep the easy riding (Amber). Red needs a second domain to agree.

### CO-4 · Medium · Recovery weeks need their own reading

In a planned recovery week the sessions are already light, so cutting them further gains nothing. HRV also often shifts during a deload. Mark's belief that his HRV dips in recovery weeks has already been tested, and it holds (Batch 275, 27 Sep): his overnight HRV averages 45.3 ms in recovery weeks against 48.1 ms in build weeks (95% interval −5.0 to −0.6 ms).

**Fix.**

- In a recovery or taper block, mild and marked concerns keep the session as planned; only a floor changes it.
- Judge recovery-week HRV against his recovery-week normal, so the expected dip isn't read as strain.

## Doctor

### MD-1 · High · Floors are for harm, not performance

A floor is justified only when training could hurt him: a possible infection, or a heart symptom. Sleep, readiness, load and a moderate HRV dip affect how well he trains, not whether it's safe. Those should be graded, never made floors.

### MD-2 · High · The "off the bike" HRV alarm fires on noise

The alarm fires when last night's HRV is more than 1.5 standard deviations below his 84-day median (implemented). His nightly HRV varies by about ±5 ms around about 47 ms, so the line sits about 8 ms (17%) below his median.

- **Computed:** it would have fired on 6 of 75 mornings (8%): 16 Jul, 19 Jul, 1 Aug, 7 Aug, 21 Sep and 22 Sep.
- **Three of those were under the line by less than 1 ms:** 19 Jul, 7 Aug and 22 Sep.
- **Observed:** it fired live on 21 and 22 Sep and told him to take the day off the bike.
- **Origin:** the alarm came from the health-science review (Batch 240), whose finding was about a 60–70% overnight collapse, not a 17% dip.

**Fix.** Keep "off the bike" for an illness-grade drop, for example either:

- 2.5 standard deviations, or 30%, below his median. Computed: 1 of 75 mornings, 16 Jul at 33 ms.
- a smaller drop together with a raised resting HR or a symptom.

Anything less becomes a graded concern. Set the exact line from the replay.

### MD-3 · Medium · The two-mornings resting-HR rule also fires on noise

His resting HR is unusually steady: median 44, varying by about ±1.7 bpm. His "usual range" ends about 1.5 bpm above his median, which is within wrist-sensor noise.

- **Computed:** "above usual two mornings running" happened on 6 of 99 mornings, and 32 of 440 over the year. Today each one caps the day at Amber on its own.
- **The +7 bpm jump:** about 4 standard deviations for him, it happened once in 440 days. That one is well calibrated. Keep it as a floor.

**Fix.** Two mornings above usual becomes a mild concern, not a cap on its own.

### MD-4 · High · Symptoms are the biggest safety gap

The colour never asks about symptoms and never reads what he writes. For a 57-year-old endurance athlete, the warnings that matter most are symptoms, not numbers:

- chest pain, pressure or tightness, especially during effort
- breathlessness out of proportion to the effort
- palpitations or an irregular pulse. Atrial fibrillation is more common in long-term male endurance athletes (Abdulla 2009).
- dizziness or fainting, especially during or just after exercise
- fever, or illness "below the neck": chest infection, body aches, stomach upset

Observed: in 75 morning notes he has never reported a symptom. The app can't tell whether he's been well or just wouldn't think to write it.

**Fix.**

- **Ask one question at check-in:** "Any symptoms today?"
  - None (the default, so it costs him one tap)
  - Cold-type (above the neck)
  - Fever, aches or chest infection
  - Chest, heart or dizziness
- **Chest, heart or dizziness:** no training today. He should call his GP or 111 the same day, and 999 if the pain is happening now.
- **Fever or illness below the neck:** no training until he's free of symptoms, then build back gradually.
- **Above the neck:** easy riding only. This is the "neck check" sports medicine uses.
- **The notes are the second net.** Claude reading them backs up this question; it doesn't replace it.
- **Clinician check:** before it ships, have a clinician (his GP or a sports-medicine doctor) check the wording and the floors. This review is not medical advice.

This needs no AI and can ship first, on its own.

### MD-5 · Low · A sudden HRV rise isn't always good news

Irregular heartbeats inflate wrist HRV. A reading far above his usual range should never count as good evidence. Next to a palpitations note, it should prompt "mention it to your GP".

### MD-6 · Low · Sleep stages are the least reliable thing the watch measures

The age-adjusted sleep score is built from sleep-stage percentages. The Batch 240 review found his "REM deficit" is probably a device artefact. The sleep domain should lean on total sleep and Garmin's overall score. Keep the age credit, but never let it be the only thing between Amber and Green; the age-credit ceiling (Batch 170) already partly guarantees this.

## AI engineer

### AI-1 · High · Count agreement across independent domains

"Two signals agree" repeats September's bug unless the signals are independent. Garmin describes readiness as a composite of sleep score, recovery time, HRV status, acute load, sleep history and stress history. On Mark's data it is mostly his sleep and recovery time.

**Fix.** Group the signals into domains. Take the worst signal inside each domain, and count agreement across domains:

- **Autonomic:** overnight HRV, 7-day HRV, resting HR.
- **Sleep:** total sleep, sleep score.
- **Load:** this week's load against his usual, recovery time, yesterday's load.
- **Subjective:** feel against his own average, and optionally a "legs" tap.
- **Symptoms:** the check-in question and the notes. These are floors (see MD-4).

Readiness confirms the sleep or load domain but never gets a vote of its own.

### AI-2 · High · Judge HRV against his own baseline, not Garmin's band

Every HRV problem this month came from Garmin's band and status:

- **Counted twice:** Garmin's status was counted twice alongside the app's own recalculation of the same average (Batch 269).
- **Moving floor:** the floor moved underneath readings that hadn't changed (Batch 271, the moved-floor detector: 12 moves, all upwards).

Garmin's status is built the right way in principle: a 7-day average against a personal band. But the band is hidden and it moves, so the app keeps working around a signal it can't see inside.

**Fix.** Judge HRV the way the trials do (Plews 2013):

- Compare his 7-day average with his own longer-term normal range: his mean, plus or minus a small band called the "smallest worthwhile change".
- Compute that range from the nightly values the app already stores.
- Use last night's value only for the illness alarm (see MD-2).
- Garmin's status becomes context for the brief.

This reverses how Batches 269 and 271 work, not what they achieve: a marginal weekly dip on its own still won't cut the session.

### AI-3 · High · Claude's reading of the notes is one-way

If flags Claude reads can relax the day, an extraction mistake relaxes it too. A persuasive paragraph also becomes a lever on the colour.

**Fix.**

- **Flags Claude reads can only add caution** (a symptom, heavy legs, feeling unwell) or add context for the brief.
- **Causes explain the day; they don't excuse it.** "The dog woke me" or "two glasses of wine" don't soften today, because his body is in the same state whatever caused it.
- **Causes still matter for trends.** The rule that proposes rearranging the week after two Reds in seven days already uses them.
- **Only his explicit taps can relax the day:** his feel, and legs if that tap is added.

### AI-4 · High · The notes reader needs a design and an eval before it ships

**Design.**

- Use structured output against a strict schema. Each flag records:
  - present, absent or unclear
  - the exact words
  - who it's about (him or someone else)
  - when (now, last night, or earlier)
- Negation, other people and time are where extraction fails: "no chest pain", "Jane has a cold", "was ill last month", "room too cold". The keyword search above got 7 out of 7 wrong.
- An "unclear" symptom makes the app ask him. It is never silently ignored.
- Read each check-in once, and store the result with the model and prompt version. Regenerating the brief reuses the stored flags.
- Sonnet 5 doesn't accept a temperature setting, so reproducibility has to come from storing the result, not from settings.
- If the call fails (it has, in two billing outages), the colour still computes from the numbers and his taps. The brief says it couldn't read his notes. The colour never waits on Claude.

**Model and cost.** On the app's production model (`claude-sonnet-5`, $2 in and $10 out per million tokens), about 1,500 tokens in and 200 out costs about half a US cent a morning, before thinking tokens. That is well under £1 a month. Whether Haiku 4.5 ($1 / $5) catches symptoms as reliably is a question for the eval, and your call.

**Eval.**

- Label his 75 real morning notes, plus about 40 hand-written hard cases: negations, other people, bedroom temperature, "heart rate" as data talk, and genuine symptoms.
- The gate: every red-flag case caught, with few enough false alarms that he isn't questioned every week.
- Keep the eval as a regression test, and rerun it on any prompt or model change.
- Running it costs a few dollars.

### AI-5 · Medium · A replay shows what changes, not whether it's better

There's no ground truth, but the data has proxies:

- whether he hit his intervals on mornings the new rules would have eased
- whether HRV and resting HR recovered the next morning after hard days on flagged mornings
- his dissents
- any illness

Report these with the replay, labelled as directional: about 100 mornings from one person.

## Software engineer

### SE-1 · High · Pure, table-driven and property-tested

- The verdict is already a pure function with no database access; Batch 245 moved it into its own module. Keep it that way.
- Put every threshold in one table: value, unit, source and reason. The provenance panel, the replay and the tests all read from that table.
- Test the invariants with generated inputs, not only examples:
  - a worse input never gives a better colour
  - floors always hold
  - missing data never gives Red
  - flags Claude reads never relax the day
  - no VO2 on Red

### SE-2 · High · The replay harness is a tool, not a script

- Replay from the inputs each morning actually saw. Use its stored packet where that holds the input, and otherwise rows dated before that morning. Never use today's re-synced rows or today's baselines.
- Output one row per morning: the old colour, the new colour, what drove each, and what would have happened to the session.
- Batch 269's one-off replay was the right idea. Keep the harness in the repo and run it on every future verdict change.

### SE-3 · High · Shadow first, then switch

- Compute the graded verdict beside the live one for at least 14 mornings, and store both.
- Show Mark only the live one.
- Review every disagreement.
- One flag switches over; the same flag rolls back.

### SE-4 · High · The colour has many consumers

- the VO2 delivery gate
- the two-Reds-in-a-week rearrangement and the deload
- week swaps and the weekly mix
- the Amber and Red ride changes
- the calendar colours
- recent mornings in chat, and the weekly review
- the reasons and provenance display
- the morning prompt, which quotes the current rule ladder's own fields

**What this means for the change.**

- Keep Green, Amber and Red meaning the same thing to every consumer.
- Version the packet.
- Rewrite the prompt with a version bump.
- Decide in writing what gets regenerated, because a bump withdraws every stored read at the old version.

### SE-5 · Medium · Storing flags and symptom answers is a schema change

They need a home: a column on the check-in or a new table. That means a migration, which counts as consequential under Craig's rules. Decide it in the spec.

## The revised design

```
 Check-in taps  +  notes
      |              |
      |       Claude reads notes
      |       (adds caution only)
      v              v
 Floors (medical, rare)
  chest/heart -> no training, GP
  fever/aches -> no training
  HRV crash or RHR +7 -> no bike
      |
 Rate each domain vs his normal:
 autonomic, sleep, load, feel
   -> none / mild / marked
      |
 Red:   2+ domains marked,
        or he feels rough
 Amber: 1 marked, or 2+ mild
 Green: 1 mild (targets held),
        or nothing
      |
 Action = colour x the session
 (move before cut; easy kept)
      |
 Claude writes the why
```

Missing data: keep today's rule, so missing sleep or Garmin data means no Green. It didn't decide any of the 98 mornings.

## Suggested batches

1. **Medical floors.** A small batch with no AI:
   - the symptom question and its floors
   - "off the bike" only for an illness-grade HRV drop or the +7 bpm jump
   - needs Craig's sign-off on the wording, and ideally a clinician's check
2. **Graded verdict in shadow.** Domains, HRV against his own baseline, the threshold table, the replay tool and property tests. Nothing changes for Mark.
3. **Switch-over.** Actions that depend on the session, a prompt rewrite and new copy. Mark sees the replay first.
4. **Claude reads the notes.** The extractor, the eval set, one-way flags and storage, including a migration. Adds well under £1 a month.

## Acceptance criteria for the spec

- The replay covers every stored morning, with a per-day table of old and new colours, and counts by colour and by what drove each day.
- No replayed morning becomes less cautious where a floor applies.
- If Red stays above about 1 morning in 10, the report names the rule responsible.
- The invariant tests (SE-1) pass.
- Shadow runs for at least 14 mornings, with every disagreement reviewed.
- The extractor catches every red-flag case in the eval.
- The outcome proxies (AI-5) are reported.
- The prompt version is bumped, and the regeneration decision is written down.

## Not recommended

- **Claude choosing the colour, even within limits.** The colour couldn't be reproduced or audited, and it could be argued with.
- **Tuning thresholds to hit a target Red rate.** Set them from physiology, and read the rate as a warning sign.
- **More rungs on the ladder.** Each new special case is what made it rigid.

## Limitations

- **Small sample.** One person and about 100 mornings. Correlations are uncertain: r = 0.5 on about 80 mornings means roughly 0.3 to 0.65.
- **Recomputed, not run.** The alarm rates were recomputed in SQL from each rule's arithmetic, not by running the app's own functions. The results for 21 and 22 Sep match what the live packets recorded.
- **Garmin readiness.** The list of what goes into it comes from Garmin's documentation. Its weights aren't public.
- **Not medical advice.** This review takes a clinical perspective, but the symptom floors need a clinician's check before they reach Mark.

## References

- Saw AE, Main LC, Gastin PB. Monitoring the athlete training response: subjective self-reported measures trump commonly used objective measures: a systematic review. *Br J Sports Med* 2016;50:281–291.
- Javaloyes A, Sarabia JM, Lamberts RP, Moya-Ramon M. Training prescription guided by heart-rate variability in cycling. *Int J Sports Physiol Perform* 2019;14:23–32.
- Vesterinen V, Nummela A, Heikura I, et al. Individual endurance training prescription with heart rate variability. *Med Sci Sports Exerc* 2016;48:1347–1354.
- Kiviniemi AM, Hautala AJ, Kinnunen H, Tulppo MP. Endurance training guided individually by daily heart rate variability measurements. *Eur J Appl Physiol* 2007;101:743–751.
- Plews DJ, Laursen PB, Stanley J, Kilding AE, Buchheit M. Training adaptation and heart rate variability in elite endurance athletes: opening the door to effective monitoring. *Sports Med* 2013;43:773–781.
- Abdulla J, Nielsen JR. Is the risk of atrial fibrillation higher in athletes than in the general population? A systematic review and meta-analysis. *Europace* 2009;11:1156–1159.
