# Batch 191 — Coaching-integrity audit refresh

**Date:** 2026-08-06
**Branch:** `chore/batch-191-coaching-integrity-refresh`
**Tier:** 🔴 High
**Mode:** diagnose-only — no verdict logic, threshold, prompt, plan, migration or
production row was changed
**Auditor lens:** exercise physiologist + cycling coach
**Code baseline:** `7e77169..20d75ae` (Batches 157–190)
**Data baseline:** Mark's live `coach` schema, read-only, observed 2026-08-06
**Prior grade:** **B+** (Batch 155, 2026-07-26) — framework and history in
`COACHING_INTEGRITY_AUDIT.md`

This is the fourth lane of the 2026-08-05 wave-2 audit. It answers the question
the code review cannot: after 31 batches of added coaching machinery, is the
coaching *better* on Mark's real data, or merely more complex — and can the new
spoken layer undermine the deterministic one? Remediation stubs deliberately
carry no batch numbers until the whole wave is triaged.

A Mark-safe version is at `docs/reviews/BATCH_191_MARK_SCORECARD.md`.

---

## Executive summary

**Grade: B+ (held) — but for completely different reasons than in July.**

The three chronic gaps the last two audits named are genuinely closed, and closed
*in the wild*, not just in code. **F2** (load could not move the light) closed:
the Batch 167 cap fired for real on 2026-07-29 and turned a Green into an Amber
on ACWR 1.61 / a 25-hour recovery clock. **F4** (no cumulative escalation) closed:
the Batch 170 stacking rule fired for real on 2026-07-31 and made a Red out of a
day whose sleep score was 76. **F3** (age credit alone carrying a night to Green)
closed by the credit ceiling — probes confirm a raw-62 night credited to 74 is now
held at Amber unless HRV, resting HR, readiness *and* the check-in all corroborate.
**F1** (self-recalibrating baselines) is anchored and the anchor is load-bearing on
every single morning: Mark's own 84-day readiness median is **50** (Q1 28, Q3 61),
so `effective_readiness_floor` is the absolute 60 anchor, not his personal centre,
on 12 of 12 mornings in the window. Without Batch 168 the soft-sleep override would
today be testing against a floor of 50. **F8 stays RESOLVED** — the 31 July and
1 August Red narratives lead with the honest call and name the cause. **F9 and
R155-C/D shipped**: learned context is capped at 12 items / 365 days, corrections
at 5 items / 45 days, and the chat now carries an explicit anti-sycophancy rule.

**And one new gap opened, in exactly the shape the original audit warned about —
this time it inverts a property the audit had credited.** The original audit's
second pillar was that the only gate-relevant input Mark can edit "can only ever
*harden* the light, never soften it." That is still true of the daily light. It is
no longer true of the structural rail. Batch 182's Red qualification lets a
matching phrase in Mark's own check-in text remove a Red morning from the chronic
cluster — unconditionally, with no cap, no decay, and no requirement that the
physiology agree. It is not hypothetical: between 1 and 4 August a genuine two-Red
cluster had triggered a seven-day chronic deload, four sessions of which Mark
approved and pushed; on 5 August — the first morning after Batch 182 deployed —
both Reds were reclassified `explained_by_check_in`, `redMorningCount` fell 2 → 0
and the escalation switched off. One of the two exclusions rests entirely on the
word "alcohol" over a morning whose resting HR (48) was *above* its own ceiling
(45); the other rests on Mark writing that he had a hard three-day training
block — which is the overreaching signature the deload path exists to catch.

Underneath both sits the same structural fact: **the app's record of a day is
mutable, and the last write wins.** `daily_metrics` holds one row per day,
overwritten by the evening sync (`recorded_at_utc` between 19:00 and 21:30 on 12
of the 14 days examined), while the verdict was computed hours earlier from the
morning snapshot. On 2026-07-30 the morning packet held readiness `MODERATE`/64
with a 943-minute recovery clock; the row now holds `POOR`/**19** with **3,233**
minutes. Every retrospective consumer — the Red-morning qualification, the
84-day baselines the personal floors key off, the trend alarm, the chronic
recovery-marker misses — reads the *evening* value, and the divergence is
directional, not random: after training, recovery debt is higher (which *excuses*
Reds) and readiness is lower (which *depresses* the personal baseline). A stored
verdict is mutable too, and the latest one wins for every retrospective consumer:
2026-07-05 reads `Amber@07:23 → Green@22:03`.

**The spoken layer has not undermined the deterministic one — mostly because it
has barely spoken.** The state-change coach (Batch 187) has produced **zero** turns
since it shipped; the scheduled Sunday review (Batch 185) has not yet had a
Sunday — the newest `weekly_review` row is 2026-06-29. Of the 41 recorded chat
exchanges, none is a "just tell me I'm fine" attempt, and the one turn that
touches a deterministic ceiling stays inside the app's own numbers. But the
shared floors registry has five entries and **none** of them covers the five
deterministic protections shipped since Batch 155, so the morning read's
"never soften the cap" sentences are hand-written, unprotected by the drift test,
and not inherited by the chat that answers questions about the same morning.

**8 findings: 2 High / 5 Medium / 1 Low**, `CI191-01…08`. Closing CI191-01 and
CI191-02 is what now moves this to A−.

---

## 191.1 — The framework, re-run

The audit's two lenses are unchanged: **acute** (edit a number, argue with the
model) and **chronic** (let normal quietly recalibrate; ramp load faster than
absorption).

### Acute — still defended, and now harder

`_morning_verdict` (`apps/api/src/services/morning_analysis.py:1943-2193`) is
still deterministic Python and still takes the model nowhere near it. Since
Batch 155 it gained four hard mechanisms, all of which only ever *harden*:

| Mechanism | Where | Direction |
|---|---|---|
| `trainingLoadCap` (167) | `morning_analysis.py:1820-1854`, applied `:2122-2128` | Green → Amber only |
| `sleepCreditCeiling` (170) | `:1905-1940`, applied `:2115-2120` | Green → Amber only |
| `cumulativeEscalation` (170) | `:2088-2113` | Amber → Red only |
| `readinessEffectiveFloor` (168) | `personal_baselines.py:33-37` | raises a floor, never lowers it |

Probe results (Prong A — the real functions driven with crafted inputs; script
kept in the session scratchpad, not committed):

```
PROBE 1 (F3, age credit crossing the Green line)
  raw 62 -> age-adj 74, full corroboration          -> Green
  raw 62 -> age-adj 74, check-in absent             -> Amber [credit-ceiling]
  raw 62 -> age-adj 74, readiness 58 (< median 68)  -> Amber [credit-ceiling]
  raw 62 -> age-adj 74, no HRV measurement at all   -> Amber [credit-ceiling]

PROBE 5 (F4, the pile-up that used to stop at Amber)
  age-adj 62 + Poor + check-in 3 + hard yesterday   -> Red [stack-red]
  Poor readiness + hard yesterday only              -> Red [stack-red]
  Poor readiness alone, nothing else negative       -> Amber

F5 (which absences still pass)
  clean night 80, check-in BLANK                    -> Green
  clean night 80, NO HRV DATA AT ALL                -> Green
  clean night 80, honest low check-in (3)           -> Amber
  soft night 66, no HRV -> override denied (positive evidence required)

F2 (the load cap)
  perfect Green day, ACWR 1.49                      -> Green
  perfect Green day, ACWR 1.50                      -> Amber [cap applied]
  perfect Green day, recovery 1440 min              -> Green
  perfect Green day, recovery 1441 min              -> Amber [cap applied]
  RED day with ACWR 1.8                             -> Red  [cap triggered, no-op]
```

The original Probe 5 value (`recovery_time_min = 1400`, ≈23.3 h) still does not
cap — the threshold is 24 hours **exclusive**. That is a deliberate boundary, not
a defect, but it is worth recording that the audit's own motivating number sits
40 minutes under the line.

### Chronic — F1 verified on real data, and the anchor is doing the work

`effective_readiness_floor(personal_center)` returns `max(personal_center, 60.0)`.
Whether that matters depends entirely on where Mark's personal centre actually
sits, which is the thing Batch 155 could only assume. It sits **below the anchor**:

```
coach.metric_baselines (readiness_score, db_history, window 2026-05-11..08-02, n=84)
  lower quartile 28 | median 50 | mean 44.6 | upper quartile 61.5
recomputed live from coach.daily_metrics over the same window
  Q1 28 | median 50 | Q3 61          -> the persisted row is current, not stale
packet verdict.readinessBaselineCenter across 2026-07-29..08-06
  53.5, 53.5, 53.5, 53.5, 53.5, 50.0, 50.0, 50.0, 50.0
packet verdict.readinessEffectiveFloor across the same days
  60.0 on every single day
```

So on 12 of 12 mornings the soft-sleep override was gated by the absolute anchor
rather than by Mark's own history, and the anchor was 6.5–10 points above it. **F1's
remediation is materially load-bearing in production.** It is also evidence that
the drift F1 described is real: his 84-day readiness centre fell 53.5 → 50.0 inside
this window.

The residual is the *other* half of Batch 168 — the trend alarm. Probes show it
catches a step but not a slide:

```
84 days, 72 -> 62 step decline           -> status=declining triggered=True  delta=-10.0
same decline, only every 3rd day observed -> status=insufficient_data triggered=False
slow slide 72 -> 67 across 84 days        -> status=stable triggered=False    delta=-3.0
```

The alarm needs a ≥5-point gap between two 42-day medians and ≥21 observations in
each half, and it is `verdictImpact: "warning_only"`. In Mark's live data it reads
`stable` with a **+22.5** delta — i.e. his recent half-window median is 22.5 points
*above* the prior half, so readiness is improving even as the persisted 84-day
centre falls, because the earlier half was so much worse. Two statistics, both
correct, telling opposite-sounding stories from the same packet.

The anchor also covers exactly **one** gate. `grep` finds
`SOFT_SLEEP_READINESS_ABSOLUTE_FLOOR` used in one place. Resting-HR "in band"
(`personal_baselines.py:127-140`) is still a pure personal quartile — currently
median 44, upper quartile 45, so a 1-bpm band — HRV floors come from Garmin's own
baseline or the personal lower quartile, and `chronic_patterns`' recovery-marker
misses are personal-band relative throughout. Those are all still
self-recalibrating; they are simply not currently drifting.

---

## 191.2 — Each coaching change since Batch 155, assessed

| Batch | Change | Integrity effect | Evidenced on real data? |
|---|---|---|---|
| 167 | Training-load Amber cap | **Credit.** Load can now only harden. Closes F2. | **Yes** — fired 2026-07-29 (ACWR 1.61, recovery 1502 min): `trainingLoadCap.applied=true`, Green → Amber |
| 168 | Absolute readiness anchor + 84-day trend alarm | **Credit**, partial. Anchor binds daily; trend alarm is step-only, warning-only | **Yes** — floor 60.0 vs centre 50.0/53.5 on 12/12 mornings |
| 169 | Bounded, decaying memory | **Credit.** Closes F9 and F7's decay half: `learned_context.py:9-10` caps at 12 items / 365 days; `feedback.py:47-48` caps corrections at 5 / 45 days | **No** — 0 learning proposals have ever existed; assessment stays code-level |
| 170 | Credit ceiling, Poor-readiness stacking, missing-HRV neutrality | **Credit.** Closes F3, F4, and F5's optimistic half | **Yes** — stacking fired 2026-07-31 (`cumulativeEscalation.applied=true`) |
| 171 | Chronic action (deload proposal) | **Credit** — makes F6's surveillance actionable | **Yes** — a seven-day deload was proposed 08-01, four sessions approved and pushed |
| 173 | `verdict_scaling.py` | **Credit** — one canonical ease rule; provably downstream of the computed status | **Yes** — the 67%-vs-60% discrepancy Mark reported on 07-29 is exactly what it fixed |
| 176 | Live weight → W/kg | Neutral; ride-only scope | **Partial** — `weight_kg` present on 59/67 days, but not in the morning packet (CI191-07) |
| 177 | Live VO2max in the packet | **Credit** — replaces a static seed with dated live data | **Yes** — `vo2max` on 30 days, range 53.0–55.5, latest 08-04 |
| 182 | Red-cluster qualification | **The new gap.** First mechanism where Mark's own text can weaken a protection | **Yes** — CI191-01 |

### Is it over-conditioned?

The ladder is now 11 branches plus four post-hoc adjusters, and the morning prompt
went from `morning-analysis-v13` to `v27` inside the 17 days this window covers —
seven distinct versions across 12 mornings. Against that, the *outputs* have not
become erratic: the verdict distribution has drifted toward Green
(48% → 71% → 75% across the three audit windows), but the two most recent Reds and
the one Amber are all explicable from the physiology in front of them, and both
Reds fired on days Mark himself reported as bad. The machinery is more complex; it
is not yet incoherent. The risk it carries is not wrong colours — it is that the
packet now contains five separate deterministic sub-verdicts (`trainingLoadCap`,
`sleepCreditCeiling`, `cumulativeEscalation`, `readinessBaselineTrend`,
`chronicAction`), each with its own hand-written "do not soften this" sentence in
one prompt, and none of them in the shared floors registry (CI191-04).

---

## 191.3 — The spoken surfaces

The lane's question is whether an unprompted state-change turn (187), a weekly
review conclusion (185/186), or an ask-time chat answer (178) can soften,
contradict or pre-empt the verdict.

**Two of the three have never spoken.**

```
coach.analyses where analysis_type='state_change_coach'   -> 0 rows, ever
coach.analyses where analysis_type='weekly_review'        -> 4 rows, newest 2026-06-29
coach.brief_messages                                       -> 41 user / 41 assistant
   of which the Batch 179 rolling thread (origin_kind set) -> 9 user / 9 assistant
conversation_learning_proposals                            -> 0 rows, ever
```

Batch 185's cron fires Sunday 18:00 local and shipped on 5 August, so its first
scheduled run is **Sunday 9 August** — after this review. Batch 187's job fires at
11:45 local and has found no qualifying transition since it shipped, which is
consistent with `chronicAction.triggered` having gone false on 5 August. Both
rails are therefore **unexercised in production** and are assessed from code only.

**Pre-emption is structurally prevented by timing, not by design.** The
state-change job runs at 11:45 local (`scheduler.py:1462-1471`), after the wake
trigger and after the 11:00 morning backstop, so it cannot reach Mark before the
verdict. That ordering is not asserted anywhere in the job or in a test; it is a
property of two independently chosen cron times.

**Contradiction is possible and unguarded** (`state_change_coach.py:355-364`):
`_current_weekly_mix` recomputes the weekly mix with `verdict_status="Green"`
hard-coded, and `_current_chronic` recomputes the chronic signal without
`current_verdict`. So the state that an unprompted turn describes is *not* the
state the morning brief described that day, and there is no holiday guard and no
check on today's colour. A "Sweet Spot has gone at risk this week" heads-up
computed under an assumed Green can land at 11:45 on a Red morning. Batch 188
found the same mechanism from the engineering side (`CC188-02`); the coaching
consequence is that the app's two voices can disagree about the same day.

**The chat did not soften — narrowly.** The only exchange in the record that
touches a deterministic ceiling is 2026-07-29, the day the load cap fired for the
first time. Mark asked which of two intensities was better; the answer named the
trade-off honestly in the first turn ("If you want to be more conservative given
the load cap and 25-hour recovery clock, 60% is the safer call"), then recommended
67% — which is exactly what `ease_amber_power_pct` returns for an already-endurance
step, so it quoted the app's own canonical figure rather than inventing one. What
it added was framing: *"The Amber cap is load-driven, not a sign your body is
struggling … probably more conservative than the situation actually requires."*
That is defensible physiology and it changed no colour, but it is the app talking
its own first-ever load cap down within hours of setting it, and nothing in the
chat's floors forbids it (CI191-04).

**Narrative-vs-light: no softening (F8 stays RESOLVED).** Every non-Green morning
in the window leads with the honest call:

- **07-29 Amber** — opens on the disrupted-sleep question, names the thermal
  evidence, then the load cap.
- **07-31 Red** — *"That read is correct."* then names the VO2 session, the Z2, the
  81-minute Sweet Spot and the acute:chronic ratio they pushed him to.
- **08-01 Red** — *"You've flagged the alcohol and the rough night directly, so
  let's deal with it honestly … Every objective signal this morning confirms
  exactly that effect."*

**Zero sycophancy attempts.** Across all 41 user turns there is no "just tell me
I'm fine" move. The nearest thing to pressure is Mark supplying his own figures
("I average 11st 12 lbs", "my VO2 max currently sits between 55 & 56") — which
Batch 181's observed-data floor expressly permits — and the answer warming
noticeably in response ("that actually makes the picture even stronger", "elite").
Tone only; no number and no colour moved (CI191-08).

---

## 191.4 — Prong B: the real-data pass

Read-only queries against Mark's live `coach` schema. No row was written and no
payload was copied into the repository beyond the short excerpts quoted here.

### Verdict distribution

```
A: 2026-06-21..07-09 (original audit)   21 mornings   Green 10 | Amber 9 | Red 2   48% Green
B: 2026-07-10..07-25 (Batch 155)        17 mornings   Green 12 | Amber 1 | Red 4   71% Green
C: 2026-07-26..08-06 (this refresh)     12 mornings   Green  9 | Amber 1 | Red 2   75% Green
```

The Green share has risen across all three windows. On this window's evidence that
is Mark's physiology improving, not the gate loosening: the 84-day readiness trend
is +22.5 points between half-windows, the two Reds fired on genuine signals, and
the machinery added since Batch 155 only hardens. It is nevertheless the number to
watch, because a rising Green share is the observable signature of both "he is
getting fitter" and "normal has recalibrated."

### The mechanisms, in the wild

```
softSleepRecoveryOverride applied   0 / 12   (his personal centre 50 is below the 60 anchor,
                                              so the override is now near-unreachable)
sleepCreditCeiling applied          0 / 12
cumulativeEscalation applied        1 / 12   07-31: Poor readiness + a second negative -> Red
trainingLoadCap triggered           2 / 12   07-29 (applied: Green -> Amber), 07-31 (no-op, already Red)
chronicAction triggered             4 / 12   08-01..08-04, source red_morning_cluster
acuteChronicLoadRatio present      12 / 12   0.84 .. 1.61  (the cap's input is genuinely populated)
```

The last line matters: the cap's ACWR input is derived from a nested Garmin
`raw_payload` node (`morning_analysis.py:1070-1093`) and would silently be `None`
if training status were absent. It is present on every morning, with values that
straddle the 1.5 threshold — so the cap is a live control, not a dormant one.

### The age credit at the Red line

```
07-21  raw 50 -> age-adj 54   Red    (credit +4, still below 60)
07-23  raw 59 -> age-adj 63   Amber  (credit +4 lifted the night OUT of Red)
08-01  raw 51 -> age-adj 55   Red
07-24  raw 71 -> age-adj 79   Green  (crossed 74 on credit; predates the ceiling)
```

07-23 is a real instance of CI191-06: the credit ceiling guards the 74 line, and
nothing guards the 60 line.

### The morning snapshot versus the settled record

`coach.daily_metrics` holds one mutable row per day. Comparing the packet the
verdict was computed from against the row that now stands (18 mornings,
2026-07-20 → 08-06):

| Date | Packet score / level / recovery | Row now | Verdict given |
|---|---|---|---|
| 07-30 | 64 / MODERATE / 943 | **19 / POOR / 3233** | Green |
| 07-28 | 76 / HIGH / 1 | **41 / LOW / 2244** | Green |
| 07-25 | 68 / MODERATE / 1 | 44 / LOW / 1423 | Green |
| 08-02 | 66 / MODERATE / 1 | 50 / MODERATE / 1303 | Green |
| 07-23 | 46 / LOW / 55 | 25 / LOW / 1522 | Amber |
| 07-31 | 20 / POOR / 2584 | 25 / LOW / 2286 | Red |

The packet's readiness score exceeds the settled score on **11 of 18** mornings and
its recovery clock is lower on **12 of 18**. `recorded_at_utc` on the surviving row
is between 19:00 and 21:30 on 12 of the 14 days checked. This is not corruption —
Garmin's training readiness is a live intra-day metric and the evening value
legitimately reflects that day's training (07-30 carried 197 training load from an
indoor session). The finding is what everything downstream then reads (CI191-02).

### The chronic escalation, before and after Batch 182

```
morning packet verdict.chronicAction, by subject date
  07-30  triggered=false  redMorningCount=0
  07-31  triggered=false  redMorningCount=1
  08-01  triggered=TRUE   redMorningCount=2   sources=[red_morning_cluster]
  08-02  triggered=TRUE   redMorningCount=2
  08-03  triggered=TRUE   redMorningCount=2
  08-04  triggered=TRUE   redMorningCount=2      <- brief generated 07:25Z; Batch 182 merged 12:27Z
  08-05  triggered=false  redMorningCount=0   redMorningObservedCount=2
  08-06  triggered=false  redMorningCount=0   redMorningObservedCount=2
```

The 08-05 and 08-06 packets carry the qualification detail:

```
07-31  checkInReasons=[training_load]  classification=explained_by_check_in  counts=false
       physiology: hrv 52 (floor 44, BALANCED), RHR 43 (ceiling 45), recovery 2286 min
08-01  checkInReasons=[alcohol]        classification=explained_by_check_in  counts=false
       physiology: hrv 50 (floor 44, BALANCED), RHR 48 (ceiling 45), recovery 1370 min
```

Both Reds remain inside the seven-day window on 08-06, so without the check-in
exclusions the cluster would still stand at 2 and the escalation would still be
triggered. `redMorningObservedCount=2` alongside `redMorningCount=0` is the app
stating that plainly, which is a real design credit — the mechanism is transparent
even where it is permissive.

The check-in text that produced those tags is scrupulously honest. 31 July:
*"…presumably due to a harder day's training yesterday and cumulative 3 day
training load."* 1 August: *"…I virtually never drink alcohol now and had 13 uk
units last night and had poor sleep and feel the effects this morning."*

### What the escalation had already done

```
coach.workout_delivery_proposals, origin=chronic_deload
  proposed 2026-08-01 08:45Z for 08-02, 08-04, 08-05, 08-06   -> all four approved and pushed
  proposed 2026-08-02 07:37Z for 08-08                        -> status STILL 'proposed'
  proposed 2026-08-03 09:00Z for 08-09                        -> status STILL 'proposed'
```

### A stored verdict is mutable too

```
coach.analyses, morning, dates with more than one row
  2026-07-05   Amber@07:23  ->  Green@22:03
  2026-07-06   Amber@07:54  ->  Amber@16:43
  2026-07-12   Green@08:30  ->  Green@08:40  ->  Green@08:41
```

`ChronicPatternSuggestionService._recent_verdicts` (`chronic_patterns.py:710-737`)
orders ascending and keeps the last row per date, so the **latest** regeneration is
the one that counts toward the Red cluster.

---

## Findings

Ranked severe-first. Every finding is diagnose-only; the remediation stubs are
placeholders until the wave is triaged.

### CI191-01 — High — A check-in phrase can switch off a live structural escalation

**Where:** `apps/api/src/services/chronic_patterns.py:1101-1120` (the exclusion),
`:54-91` (`_CHECK_IN_CAUSE_PATTERNS`), `:781-798` (`classify_check_in_causes`),
`:1048-1055` (qualification applied to the cluster)

```python
if evidence.check_in_reasons:
    return RedMorningQualification(
        calendar_date=calendar_date,
        counts_toward_cluster=False,
        classification="explained_by_check_in",
        ...
    )
```

The check is unconditional: any single matching tag removes the Red, whatever the
physiology says, however many Reds are excluded, and forever — there is no cap, no
decay, and no corroboration requirement. The vocabulary is a deterministic regex
set (a genuinely good choice — the same text always produces the same result, and
`_non_negated_match` handles "no alcohol"), but two of its five categories are not
acute events at all: `training_load` matches "training load", "hard training",
"back-to-back", "3-day block", and `deliberate_rest` matches "deload",
"recovery week".

**This inverts a property the original audit credited.** Its second pillar was
that the one gate-relevant input Mark can edit "can only ever *harden* the light,
never soften it." On the daily light that still holds. On the structural rail it
no longer does.

**Failure scenario — observed, not hypothetical.** 1 August: Mark's Red morning
carries a resting HR of 48 against his own ceiling of 45, which
`_qualify_red_morning` would classify `systemic_markers_strained` and count. He
also writes, honestly, that he drank 13 units. The word "alcohol" removes the
morning from the cluster. 31 July: he writes that he had a hard training day and a
cumulative three-day load — the overreaching signature itself — and the
`training_load` tag removes that morning too. `redMorningCount` falls 2 → 0 and a
live seven-day deload escalation is withdrawn. An athlete who annotates every bad
morning with a plausible cause never accumulates a cluster, and the more honestly
he attributes his Reds to training, the less the app escalates.

**Remediation stub.** Separate genuinely acute exogenous causes (alcohol, illness,
travel) from endogenous training causes, and stop `training_load` /
`deliberate_rest` from excusing a Red at all — a Red caused by training load is the
signal, not the noise. Then bound the exclusion: require the physiology not to
contradict it (an out-of-band resting HR or a crashed HRV should override the
note), cap how many of the last N Reds may be excluded, and decay the tag's power
so a habitual annotation cannot permanently silence the rail. Whatever the shape,
the invariant to restore is the one the audit was built on: a user-editable input
may harden a protection, never weaken one.

### CI191-02 — High — The day's record is mutable and the last write wins

**Where:** `apps/api/src/models/coaching.py:28-33` (one `daily_metrics` row per
`(user_id, calendar_date)`), `chronic_patterns.py:766-779` + `:853-870`
(`RecoveryDay`/`RedDayEvidence` built from that row),
`metric_baselines.py:36` (84-day baselines from the same rows),
`chronic_patterns.py:710-737` (`_recent_verdicts` keeps the latest analysis per
date), `morning_analysis.py:385-388` (the trend alarm's observations)

The verdict is computed at wake from that morning's Garmin snapshot. The row is
then overwritten by later syncs — `recorded_at_utc` is between 19:00 and 21:30 on
12 of the 14 days checked — so the record that survives is the *end-of-day* one.
Every retrospective consumer reads the survivor. The divergence is directional:
after a training day, recovery debt is higher and readiness is lower.

Three consequences compound:

1. **Batch 182's `expected_training_debt` exclusion** (`chronic_patterns.py:1132-1143`)
   tests `recovery_time_min > 1440` against the evening value, which that day's
   training inflated. The harder Mark trains, the more likely that day's Red is
   classified as expected debt and excluded. On 07-31 the settled clock was 2,286
   minutes on a day with **zero** recorded activities — carry-over from 07-30's
   session — so the exclusion is fair there; the mechanism is what is unsound, not
   this instance.
2. **The personal baselines** the floors key off are built from evening readings
   (median 50, Q1 28) while the daily comparison uses a morning reading. That is
   an apples-to-oranges comparison biased toward a *lower* floor — F1's mechanism,
   with a systematic cause rather than a drifting one. Batch 168's anchor is the
   only thing holding it up, which is precisely why it binds on 12/12 mornings.
3. **A stored verdict is mutable.** 2026-07-05 reads `Amber@07:23 → Green@22:03`,
   and `_recent_verdicts` counts the later row. An evening regeneration on
   post-training data can rewrite the colour that the Red-cluster count, the
   reviews and the trends all see.

**Failure scenario.** 30 July: Mark reads a Green built on `MODERATE`/64 with a
943-minute clock, trains, and the day settles at `POOR`/19 with 3,233 minutes. The
morning read was right for the morning. But every later question — did that Red
cluster? what is my readiness baseline? was the week hard? — is answered from a
record that no longer resembles the one the coaching was based on, and nothing
anywhere states which snapshot a stored figure came from.

**Remediation stub.** Decide explicitly, per consumer, whether it wants the
*morning* observation or the *day* observation, and make the storage able to
express both — either an as-of column on `daily_metrics` with the morning
observation preserved, or having retrospective consumers read the figures out of
the stored morning packet (which already holds them) rather than re-reading the
live row. At minimum, the Red qualification and the readiness baseline should
agree with each other about which time of day they mean.

### CI191-03 — Medium — A withdrawn escalation leaves its proposals standing

**Where:** `coach.workout_delivery_proposals` (live rows),
`chronic_patterns.py:1086-1098` (the signal), `verdict_scaling.py:200-233`
(`adjust_ir_for_chronic_deload`)

The 1 August escalation created a seven-day deload spanning 08-02 → 08-09. Four
sessions were approved and pushed. When Batch 182 retroactively disqualified both
Reds on 5 August, the two undecided proposals for **08-08 and 08-09 stayed in
`proposed` state** with `adjustment.reason = "sustained_recovery_strain"`. Nothing
retracts a proposal when its evidence stops holding.

**Failure scenario.** On Saturday 8 August Mark's morning brief says no chronic
action is warranted (`chronicAction.triggered=false`, and the prompt is instructed
to explain the qualification), while the Week view offers him a "Seven-day chronic
deload" for that same session, justified by sustained recovery strain. Two app
surfaces state incompatible things about the same day, and the one he is more
likely to act on is the button.

**Remediation stub.** Give a chronic-origin proposal a lifetime tied to its
signal: when `chronicAction.triggered` goes false — or when the qualification that
produced it changes — expire the undecided proposals it created, with an audit row
saying why. The already-pushed ones stay; only undecided offers should evaporate.

### CI191-04 — Medium — The newest deterministic protections have no floor coverage

**Where:** `apps/api/src/services/coach_policy.py:80-134` (`FLOORS`,
`READ_PROMPT_FLOORS`), `morning_analysis.py:178-207` (the hand-written
non-softening sentences), `brief_chat.py` (composes from `FLOORS` + the rules)

`FLOORS` has five entries: `never_vo2_on_red`, `no_power_balance`,
`local_clock_times`, `no_skipped_as_live`, `recorded_data_honesty`. None covers
`trainingLoadCap`, `sleepCreditCeiling`, `cumulativeEscalation`,
`readinessBaselineTrend` or `chronicAction`. Those five protections are the entire
substance of the F1–F4 remediation, and their "never soften this" instructions
exist only as prose inside `morning_analysis.SYSTEM_PROMPT`. Two consequences:
`missing_floors()` cannot detect their removal, so deleting them would not fail
CI; and the chat that answers questions about the same morning inherits none of
them.

`ANTI_SYCOPHANCY_RULE` (`coach_policy.py:197-202`, the shipped R155-D stub) is a
real partial mitigation — it forbids caving on "a hard recovery signal" — but a
load cap is explicitly *not* a recovery signal, which is exactly the distinction
the 07-29 answer drew.

**Failure scenario.** On the first day the load cap ever fired, the chat described
it as "not a sign your body is struggling … probably more conservative than the
situation actually requires." No colour moved and the recommended figure was the
app's own, so nothing broke. But the sentence the morning read is forbidden to
write is one the chat is free to write, about the same cap, an hour later.

**Remediation stub.** Promote the five deterministic sub-verdicts to `FLOORS`
entries with patterns, add them to `READ_PROMPT_FLOORS["morning"]` so the drift
test protects them, and let brief-chat inherit them through `floors_sentence()`.
The rule to state is narrow: explain a deterministic ceiling, never argue it down.

### CI191-05 — Medium — An Amber ease can turn VO2 into threshold work

**Where:** `apps/api/src/services/verdict_scaling.py:81-96` (`ease_amber_power_pct`),
`:39` (`AMBER_POWER_CAP_PCT = 98`), `morning_analysis.py:2256` (the generic plan
wording), `:1548-1561` (`_eased_ride_detail`, which does quote the real figure)

A 115% VO2 interval eases to `min(max(115-13, 75), 98) = 98`% FTP. So on an Amber
day a VO2 session becomes threshold intervals at 98% FTP for 75% of the planned
duration. HIT is removed as defined (nothing ≥106% survives) and the 25% duration
cut is real, but 4×4 at 98% FTP is still a quality session on a day the engine
judged compromised.

The wording is honest on one surface and not the other. `_eased_ride_detail`
quotes the transform's own output when the adjustment summary is present
("Ease to ~98% FTP and cut to 45 min — no HIT/VO2"), which is exactly right. The
generic `_plan_adjustments` fallback still says *"Cut duration 20-30%, drop
intensity by a zone, and remove HIT/VO2 work"* — and "remove HIT/VO2 work" reads
as "the hard session is off", not "the hard session is now at threshold".

**Failure scenario.** An Amber caused by a 1.6 ACWR — i.e. specifically by
accumulated load — eases a VO2 session into a threshold session, which is one of
the highest-load sessions available short of VO2. The cap fires and the athlete
still does hard work.

**Remediation stub.** Consider whether an Amber that was set *by the load cap*
should ease differently from an Amber set by recovery: capping at the top of
sweet-spot rather than at threshold, or converting the session type rather than
scaling its numbers. Either way, align the plan-adjustment wording with what the
transform actually produces.

### CI191-06 — Medium — The credit ceiling guards the Green line, not the Red line

**Where:** `morning_analysis.py:1905-1940` (`_sleep_credit_ceiling` tests only the
74 crossing), `:2041-2043` (the Red line), `:2295-2308` (the override band),
`sleep_scoring.py:45-47` (`_MAX_CREDIT = 12`)

Batch 170 stopped the age credit from carrying a night *across the Green line*
without corroboration. Nothing tests the credit carrying a night across the *Red*
line. Because the credit is computed from stage percentages against age norms and
is independent of the raw score, a raw score deep in Garmin's POOR band can be
lifted into the 60–74 override window — and the soft-sleep override can then carry
it to Green. Probe:

```
raw 48 -> age-adj 60 : Green (override granted)   | without the credit: Red
raw 53 -> age-adj 65 : Green (override granted)   | without the credit: Red
raw 58 -> age-adj 70 : Green (override granted)   | without the credit: Red
raw 62 -> age-adj 74 : Amber unless fully corroborated (the ceiling)
```

Real data: 07-23 raw 59 → 63 lifted a night out of Red into Amber. No day in the
window reached Green this way, because Mark's readiness centre (50) sits below the
anchor and the override is currently near-unreachable — the exposure is latent,
not active.

**Failure scenario.** A night Garmin scores 53/POOR earns the full +12, lands at
65, and with clean HRV, in-band resting HR, readiness ≥60 and a "Good" check-in
resolves **Green** — a full-intensity day off a night the device called poor. The
ceiling that was built to stop precisely this shape only watches the higher
threshold.

**Remediation stub.** Apply the `crossedGreenThreshold` treatment to the Red line
too: if the raw score is below 60 and only the age credit lifts it above, either
hold the day at Amber or require the same complete corroboration the Green
crossing already demands.

### CI191-07 — Medium — Load still relaxes below the cap, and the unprompted rail is untested

**Where:** `morning_analysis.py:2030-2039` + `:2049` (the `load_driven` escape),
`:1829-1841` (the cap thresholds), `state_change_coach.py:355-364`,
`scheduler.py:1462-1471`

Two residuals in the same family — load and the surfaces that talk about it.

*Load relaxes below the cap.* A Low Garmin readiness plus clean recovery signals
plus *any* load present is read as "load-driven" and escapes the auto-Amber. The
cap only bites at ACWR ≥1.5 or recovery >24 h. Between "load present" and "load
high" there is a band where load can only relax:

```
readiness LOW + clean recovery + ACWR 1.20, recovery 600 -> Green [load_driven]
readiness LOW + clean recovery + ACWR 1.55, recovery 600 -> Amber [cap applied]
readiness LOW + clean recovery + ACWR n/a,  recovery 1400 -> Green [load_driven]
```

Real data: 07-24 (`load_driven`, Green, pre-cap) and 07-29 (`load_driven`, cap
applied, Amber). F2's original real instance is closed only above the threshold.

*The unprompted rail cannot be observed.* `state_change_coach` has produced zero
turns. Its `_current_weekly_mix` computes with `verdict_status="Green"` hard-coded
and `_current_chronic` computes without `current_verdict`, and neither the 11:45
ordering behind the morning verdict nor a holiday guard is asserted anywhere.

**Failure scenario.** A fast ramp at ACWR 1.4 with a good night reads Green while
the readiness Garmin computed says Low — and at 11:45 an unprompted turn tells him
a bucket has gone at risk this week, computed as though the day were Green,
possibly on a day that is Red.

**Remediation stub.** Make the escape symmetric with the cap: if load is allowed to
*relax* a Low-readiness Amber, the same load figure should be required to be
genuinely benign (e.g. ACWR ≤ 1.3) rather than merely present. Separately, pass
the real current verdict into the state-change coach's recomputation and add the
ordering and holiday guards as tests rather than as cron arithmetic.

### CI191-08 — Low — Tone warms to user-supplied numbers, and W/kg is absent where he asks

**Where:** `coach_policy.py:101-114` (`recorded_data_honesty`), `:197-202`
(`ANTI_SYCOPHANCY_RULE`), `body_metrics.resolve_effective_weight_kg` (ride-only
scope, Decision #256), live `coach.daily_metrics.weight_kg`

On 29 July Mark asked what the app thought of his metrics for his age. The answer
had no weight in front of it — Batch 176 put `powerToWeight` in the post-workout
packet only — so Mark supplied "11st 12 lbs" and the answer computed 3.73 W/kg
from it, then, when he added "my VO2 max currently sits between 55 & 56", replied
*"Noted, and that actually makes the picture even stronger"* and reached for
"elite". Meanwhile the app holds a live weight on 59 of the last 67 days and a
live VO2max on 30 (range 53.0–55.5, latest 04 August).

No number and no colour moved, and Batch 181's floor expressly permits deferring
to his own device on observed data — so this is the F7 residual, not a new gap,
and it is now bounded by the 45-day correction decay. But it is the one place in
the record where the coach's tone follows the user's framing rather than the
data's, and it happened on the surface where the data was missing.

**Remediation stub.** Extend the effective-weight/VO2max resolution to the morning
packet so the metric question is answered from the app's own dated figures, and
consider a light guard on superlatives when the underlying figure came from Mark
rather than from a measurement on file.

---

## Verification

| Area | Method | Result |
|---|---|---|
| Verdict ladder (Prong A) | Drove the real `_morning_verdict` and helpers with crafted inputs; scratchpad script, not committed | F1 bounded/anchored, F2/F3/F4/F5 closed; CI191-05/06/07 reproduced by execution |
| Baselines | Persisted `coach.metric_baselines` vs live percentiles recomputed over the same window | Persisted rows are current, not stale; readiness median 50 confirmed |
| Verdict distribution | `coach.analyses` grouped by the three audit windows | 48% → 71% → 75% Green |
| Mechanism firing rates | Packet `verdict.*` sub-objects across 12 mornings | cap 2, stack 1, ceiling 0, override 0, chronic 4 |
| Snapshot vs settled record | Packet `dailyMetrics` vs current `coach.daily_metrics`, 18 mornings | packet readiness higher on 11/18, recovery lower on 12/18 |
| Chronic escalation | `verdict.chronicAction` before/after the Batch 182 deploy, plus `workout_delivery_proposals` | 2 → 0 qualified Reds; 4 pushed, 2 orphaned proposals |
| Narrative vs light | `output_markdown` for every non-Green morning in the window | no softening; F8 stays RESOLVED |
| Spoken surfaces | Row counts and content over `coach.brief_messages` / `coach.analyses` | 0 state-change turns, 0 scheduled reviews, 0 sycophancy attempts in 41 user turns |
| Floors | `coach_policy.FLOORS` / `READ_PROMPT_FLOORS` against the morning prompt | 5 floors; none covers the five new deterministic protections |

## Explicit non-actions

- No verdict logic, threshold, ladder branch, prompt, prompt version, plan,
  proposal, migration or configuration was changed.
- No production row was written, updated or deleted; every database access was a
  read.
- The two orphaned `chronic_deload` proposals for 08-08 and 08-09 were **left in
  place** — retracting them is a product decision for Craig, not a review action.
- No remediation batch numbers are allocated; the stubs stay review-local until
  the wave-2 findings are triaged together.
- The Batch 191 ledger row remains Planned and unstruck until explicit
  `/phase-closeout 191`.

## Limitations

- The refresh window is 12 mornings (2026-07-26 → 08-06). Batch 182 has been live
  for two of them, and Batches 185/187 for none — the two newest spoken surfaces
  are assessed from code alone.
- Prong A probes use representative baselines and metrics, not Mark's live history;
  they demonstrate the mechanism, and the mechanism is the finding. Where a
  mechanism also fired on real data, that is stated.
- Post-workout narratives were spot-checked, not exhaustively reviewed, as in the
  prior two passes.
- The verdict-distribution drift toward Green is reported, not explained. Twelve
  mornings cannot distinguish "fitter" from "looser"; the next refresh should read
  it against a longer window.
