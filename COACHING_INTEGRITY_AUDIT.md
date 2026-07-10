# Coaching-Integrity Audit — Garmin Coach

**Date:** 2026-07-10 · **Auditor lens:** exercise physiologist + cycling coach ·
**Scope:** how the app derives its scores and verdicts, and whether the run of
Mark-driven feedback batches has eroded the guardrails.
**Status:** internal / candid — this document names the exact input-manipulation
vectors. Not for Mark. (A Mark-safe scorecard exists separately.)

---

## Bottom line

The app is **well-defended against the two failure modes it was built to resist,
and weaker against a third it doesn't really model.**

- **Acute sycophancy ("talk the AI into it") — defended.** The Green/Amber/Red
  light is computed in deterministic Python, not by the language model. Claude
  only writes prose around a verdict that is already decided. Mark cannot argue
  his way to a different light. **Confirmed on 22 real mornings** (Prong B): an
  11 Green / 9 Amber / 2 Red spread, and every Amber/Red write-up leads with the
  honest "poor/fair night" call — no narrative hedging toward training.
- **Acute number-gaming ("type in a better number") — defended.** Every objective
  metric (HRV, readiness, sleep score, sleep stages) comes from Garmin and has
  **no write endpoint**. The only gate-relevant input Mark can edit — the
  subjective check-in — can only ever *harden* the light, never soften it.
- **Slow chronic drift ("let normal quietly recalibrate") — this is the gap.**
  The gates lean on Mark's own rolling 84-day baselines, and the fatigue/overload
  signals that a coach relies on (training-load ramp, recovery time, sustained
  HRV decline) are either advisory-only or absent from the decision entirely. A
  gradual slide into overreaching is the case the app is least equipped to catch.

Overall it is a genuinely thoughtful system — the design has real guards, real
citations, and conservative training logic — not a yes-man with a dashboard. The
findings below are mostly *second-order permissiveness*, not open holes. But
because the user we're protecting is a specialist in eroding exactly these
guards, second-order permissiveness is the whole ballgame.

**Grade: B / B+.** Strong bones; a handful of drift-shaped gaps to close.

---

## What is sound (credit where due)

- **S1 — The light is not the model's to set.** `_morning_verdict`
  ([morning_analysis.py:1123](apps/api/src/services/morning_analysis.py:1123))
  decides the status in Python; the Anthropic call
  ([:119-178](apps/api/src/services/morning_analysis.py:119)) only narrates it.
  The frontend renders that light **big and static** — the label and colour come
  from `verdictCopy`, not the model
  ([VerdictHero.tsx:22-53](apps/web/src/components/VerdictHero.tsx:22)), explicitly
  "replacing the small status Badge that was easy to miss."
- **S2 — Objective data is read-only to Mark.** `ManualEntry`
  ([coaching.py:300-330](apps/api/src/models/coaching.py:300)) exposes only
  subjective/RPE/feel/notes; `PUT /manual-entry`
  ([daily_loop.py:1150](apps/api/src/routers/daily_loop.py:1150)) is the only
  write path and it never touches a Garmin metric.
- **S3 — Corrections feed the prose, never the gate.** Free-text corrections are
  surfaced to the model as context
  ([feedback.py:162-198](apps/api/src/services/feedback.py:162)) and the prompt
  explicitly forbids them from overriding the Red floor, the soft-sleep rule, the
  Poor-readiness caution, or Red-never-VO2
  ([morning_analysis.py:80-84](apps/api/src/services/morning_analysis.py:80)).
- **S4 — The age-sleep credit is a real model, not a fudge.** Downgrade guard
  (never lowers a score), calibration guard (an already-optimal night earns zero),
  credit only where Garmin's own sub-score penalised an age-appropriate stage,
  capped +12, anchored to Ohayon et al. 2004
  ([sleep_scoring.py:11-47](apps/api/src/services/sleep_scoring.py:11)).
- **S5 — The soft-sleep→Green override is disciplined.** It requires readiness
  **at or above Mark's personal median**, clean HRV, and RHR in band, with the
  Garmin categorical Low/Poor as an absolute backstop
  ([morning_analysis.py:1301-1331](apps/api/src/services/morning_analysis.py:1301)).
  Proven: identical clean night, readiness 72 → Green, readiness 64 → Amber.
- **S6 — The training plan is well-built.** 13-week "2121" periodisation — a
  deload every third week, then taper + consolidation
  ([block_generator.py:1-4](apps/api/src/services/block_generator.py:1)); two
  quality sessions/week (VO2 + Sweet-Spot) over Z2 volume
  ([weekly_mix.py:56-76](apps/api/src/services/weekly_mix.py:56)); evidence-based
  VO2 protocols ([vo2_progression.py:27-34](apps/api/src/services/vo2_progression.py:27));
  and **execution-gated** FTP progression — you must actually ride the intervals
  (hit-rate ≥75%, over-rate ≥30%, adherence ≥75%, rising FTP drift) to earn a
  ~3% bump, and it *pulls back* on poor absorption
  ([block_progression.py:210-238](apps/api/src/services/block_progression.py:210)).
  Repeated Red mornings bias the next block toward conservative spacing.
- **S7 — Honesty is respected; some absences fail safe.** An honest low subjective
  (3) correctly hardens to Amber, and a missing RHR fails safe to Amber.

---

## Findings (ranked)

### F1 — HIGH · "Normal" is self-recalibrating (baseline drift)
**What the code does.** The daily gate's floors are Mark's *own* rolling 84-day
history: the soft-sleep override's readiness floor is his personal median
([morning_analysis.py:1315-1321](apps/api/src/services/morning_analysis.py:1315)),
and the "in band" checks key off his own quartiles
([personal_baselines.py:49-62](apps/api/src/services/personal_baselines.py:49);
window `DEFAULT_WINDOW_DAYS = 84`,
[metric_baselines.py:36](apps/api/src/services/metric_baselines.py:36)).
**Critique.** This is the classic overtraining blind spot. If Mark trains through
fatigue for weeks, his HRV, readiness and RHR baselines all drift the "wrong"
way, and the floors the gate tests against drift with them. What was Amber becomes
his new Green — with no input edited and no argument made. The numeric floors have
**no absolute physiological anchor**.
**Proven (Probe 4).** Identical night, readiness score 52 → **Amber** against a
healthy floor (median 68), **Green** against a drifted floor (median 50). Same
objective readiness, opposite verdict, purely because the baseline sank.
**Mitigations already present.** The Garmin *categorical* Low/Poor is an absolute
backstop the numeric floor can't erode; and the chronic detector compares a 28-day
window against the lagging 84-day baseline, so a *sharp* decline still trips.
**Recommendation.** Anchor the personal floors with an absolute floor they can't
sink below (e.g. never treat readiness < 50 as "at median", regardless of history);
and/or alarm on the baseline *trend itself* — flag when the 84-day median is
declining — so a slow slide is visible instead of being absorbed as the new normal.

### F2 — HIGH · Training load / ramp / recovery-time cannot move the light
**What the code does.** `_morning_verdict` takes no load parameter at all
(signature: `daily_metric, sleep, age_adjusted_sleep_score, manual_entries,
planned_workouts, baselines, yesterday_load, breathwork_brief`). ACWR, chronic
load and training-balance are handed to the model as *prose only*
([morning_analysis.py:69-72](apps/api/src/services/morning_analysis.py:69));
"yesterday hard" only appends a soft note
([:1163,1209-1212](apps/api/src/services/morning_analysis.py:1163)); Garmin
recovery-time is used merely to detect "load present", never as a gate
([:1342-1348](apps/api/src/services/morning_analysis.py:1342)).
**Critique.** Acute:chronic workload ratio is one of the best-validated predictors
of overreaching and injury, and for a masters cyclist it matters more, not less.
Here a fast ramp with clean overnight recovery signals sails to Green. The app can
green-light the exact behaviour — piling load on faster than it's absorbed — that
the whole product exists to moderate.
**Proven (Probe 5).** A day carrying `recovery_time_min = 1400` (≈23 h of
prescribed recovery) still resolved on other signals; recovery-time never entered
the decision.
**Recommendation.** Give the gate a load input and a hard cap: ACWR ≥ ~1.5, or
Garmin recovery-time above a threshold, caps the day at Amber independent of how
good last night looked. Load-driven caution is different from recovery-driven
caution and should be able to stand on its own.

### F3 — MED-HIGH · One-directional sleep credit can lift a mediocre night to Green
**What the code does.** `age_adjusted_sleep_score` only ever *raises* the raw
Garmin score (credit ≥ 0, capped +12;
[sleep_scoring.py:45-47,159](apps/api/src/services/sleep_scoring.py:45)), and it
feeds the only hard gates — Red < 60, Amber < 74, Green ≥ 74
([morning_analysis.py:1180-1206](apps/api/src/services/morning_analysis.py:1180)).
**Critique.** The rationale is legitimate — Garmin scores stage mix against
young-adult targets and over-penalises a healthy 57-year-old — but the +12 is
large enough to jump a full band, and there is no counter-mechanism for nights
where the low raw was driven by something the credit model can't fully see
(fragmentation, short duration co-occurring with age-normal stage %). Once a
credited night reaches ≥74 the "soft-sleep caution" path is skipped entirely.
**Proven (Probe 1).** A realistic age-normal-but-penalised night gets the full
+12: raw Garmin **62 → 74 = Green**, raw 58 → 70, raw 55 → 67. (The guard that
credit only fires on the four stage components Garmin penalised does hold — short
duration and stress are not credited.)
**Seen in real data (Prong B, 2026-07-08).** Mark's raw Garmin **53 (POOR)** was
lifted +12 to **65**, keeping a night that would otherwise be **Red** (age-adj < 60)
at **Amber**. The downstream Amber still protected him (it was a VO2 day and VO2 was
removed, LOW readiness), but the credit *alone* moved the night out of Red.
**Recommendation.** Consider not letting age-credit alone carry a night *across*
the Green threshold — let it lift *within* a band, but require a corroborating
objective signal (or a minimum raw score) to convert a credited night to Green.

### F4 — MED · No cumulative escalation to Red; Poor readiness caps at Amber
**What the code does.** The verdict is a first-match ladder
([morning_analysis.py:1180-1206](apps/api/src/services/morning_analysis.py:1180)):
Red requires age-adjusted sleep < 60 **or** (HRV below baseline **and**
low/unbalanced). Poor readiness alone lands **Amber**; nothing sums.
**Critique.** A coach treats a *pile-up* of moderate-bad signals as a rest day.
Here they never compound.
**Proven (Probe 5).** Age-adjusted 62 **+** Poor readiness **+** subjective 3
**+** yesterday hard **+** 1400-min recovery-time → **Amber**, not Red. "Cut
20–30%" when the honest call is "rest."
**Recommendation.** Add a stacking rule: Poor readiness co-occurring with any
second negative (soft sleep, low subjective, hard-yesterday, elevated RHR)
escalates Amber → Red.

### F5 — MED · Missing-data policy is inconsistent and partly optimistic
**What the code does.** `None` is treated as passing in several clauses —
subjective ([:1152](apps/api/src/services/morning_analysis.py:1152)), HRV status
and readiness score ([:1322-1331](apps/api/src/services/morning_analysis.py:1322))
— while a missing RHR fails safe.
**Critique.** The policy is arbitrary: one absent signal blocks a Green, two others
wave it through. And the single subjective safeguard is *opt-in* — it only bites
the honest user.
**Proven (follow-up probe, readiness held above floor).** **No HRV data at all →
Green** (absence read as "balanced"); **omitted subjective → Green**; but an
**honest subjective of 3 → Amber**, and **missing RHR → Amber**. So the most
manipulable move is the null move: feel awful, log nothing, keep the Green you'd
have lost by being honest.
**Recommendation.** Require *positive* HRV evidence to convert a soft night to
Green (absent HRV should neutralise the override, like absent RHR does), and treat
a stale/absent subjective as neutral rather than positive.

### F6 — MED · Chronic overreaching surveillance is advisory-only
**What the code does.** `chronic_patterns` watches HRV / readiness / RHR / sleep
against personal floors over 28 days, but it is explicitly read-only — "no verdict
or delivery-rule change" ([chronic_patterns.py:1-6](apps/api/src/services/chronic_patterns.py:1))
— and its action for a recovery-marker miss is a *suggestion*: "Pair the
suggestion with the existing Green/Amber/Red read; do not chase load"
([:713-716](apps/api/src/services/chronic_patterns.py:713)).
**Critique.** The app can *see* a sustained overreaching signature and still can't
*do* anything structural about it. A motivated Mark can dismiss a "watch" card
indefinitely.
**Recommendation.** Wire a sustained recovery-marker decline (or the ≥2-Red-morning
signal `block_progression` already computes) into an actual action — an automatic
deload proposal or a temporary daily-verdict cap — not just advice on a page.

### F7 — LOW-MED · Corrections can steer the narrative even though not the light
**What the code does.** Corrections are taken as "ground truth Mark gave" and fed
to the model (last 5), with no truth-check
([morning_analysis.py:80-84](apps/api/src/services/morning_analysis.py:80)).
**Critique.** The light holds, but the *story* can be nudged repeatedly ("my watch
always underreads my sleep"), and prose is what Mark actually reads. Over time the
narrative tone can drift toward validation while the verdict stays honest.
**Recommendation.** Age/decay corrections, and never let a correction restate an
objective metric as better than measured in the prose.

### F8 — RESOLVED · Narrative does not soften the light (Prong B, real data)
Now verified against Mark's real `coach.analyses`. Across all 11 non-Green mornings
in the window, every write-up **leads with the honest verdict** ("Poor night —
age-adjusted 57", "below the 74+ green threshold needed to unlock a full-intensity
day") and none hedges toward training. On the two VO2 days that landed Amber
(07-07, 07-08) the prose explicitly frames the day as not full-intensity. The
soft-sleep→Green override fired on only **1 of 22** mornings, so it is not a
routine backdoor. **No action — this is a clean result.** (Residual: only a
~3-week window and spot-checked post-workout narratives; worth a periodic re-check.)

---

## The unifying theme

Every high/medium finding is the **same shape**: the app is sharp on the *acute,
observable* move (edit a number, argue with the model) and soft on the *slow,
cumulative* one (let the baseline sink, ramp load faster than absorption, ignore a
month of drifting HRV). That is precisely the shape of real overtraining — and
precisely the shape a motivated athlete drifts into without ever doing anything
the acute guards would catch. Closing F1 and F2 would move the grade to an A-.

---

## Evidence appendix (Prong A)

All results produced by driving the **real** production functions with crafted
inputs (`scratchpad/probe_gates.py`, `probe_gates2.py`); no logic was
re-implemented.

```
SIGNATURE: _morning_verdict has no ACWR/load/ramp parameter.

PROBE 1 (age credit, one-directional):
  raw 55 -> 67 (+12) AMBER | raw 58 -> 70 (+12) AMBER
  raw 62 -> 74 (+12) GREEN | raw 64 -> 76 (+12) GREEN

PROBE 4 (baseline drift): readiness 52, identical night
  vs healthy floor (median 68) -> AMBER (override denied)
  vs drifted floor (median 50) -> GREEN (override granted)

PROBE 5 (no escalation):
  age-adj 62 + readiness POOR + subjective 3 + yesterday HARD + recovery 1400min -> AMBER

FOLLOW-UP (which absences pass, readiness held >= floor):
  full clean + subjective BLANK          -> GREEN
  NO HRV DATA AT ALL                     -> GREEN
  subjective HONESTLY LOW (=3)            -> AMBER
  RHR MISSING                            -> AMBER
  readiness 72 (>= median) vs 64 (< median), else identical -> GREEN vs AMBER
```

## Evidence appendix (Prong B — real stored data, `coach` schema)

Read-only queries against Mark's live `coach.analyses` (garmin-coach tables live
in the `coach` schema, not `public`).

```
MORNING VERDICT DISTRIBUTION (n=22, 2026-06-21 .. 07-10):
  Green 11 | Amber 9 | Red 2      -> half of mornings are non-Green

SOFT-SLEEP OVERRIDE ON GREEN DAYS:  1 true / others null|false  -> rare, not a backdoor

NARRATIVE vs LIGHT (all 11 non-Green mornings): no softening. Examples —
  06-21 Red : "Poor night ... Body Battery critically low 5"
  07-04 Red : "Poor night — 57 ... 86 min awake"
  07-08 Amber (VO2, LOW readiness): "below the 74+ green threshold needed to
              unlock a full-intensity day ... REM collapsed to 16 minutes"

AGE-CREDIT IN THE WILD:
  07-08 raw 53 (POOR) -> age-adj 65 (+12): kept a would-be RED night at AMBER (F3)
```

## Limitations
- **Prong B now run** (see appendix + F8): verdict distribution and narrative-vs-light
  verified on 22 real mornings. Residual: only a ~3-week window; post-workout
  narratives were spot-checked, not exhaustively reviewed.
- Probes use representative baseline/metric values, not Mark's live history; they
  demonstrate the *mechanism*, and the mechanism is the finding.
- This audit diagnoses only. No code was changed. Remediation is a separate,
  explicitly-approved step.
