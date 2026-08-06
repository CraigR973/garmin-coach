# Coaching-Integrity Audit — Garmin Coach

**Original audit:** 2026-07-10 · **Refreshes:** 2026-07-26 (Batch 155),
2026-08-06 (Batch 191) ·
**Auditor lens:** exercise physiologist + cycling coach ·
**Status:** internal / candid — this document names the exact input-manipulation
vectors. Not for Mark. (Mark-safe scorecards:
`docs/reviews/BATCH_155_MARK_SCORECARD.md`,
`docs/reviews/BATCH_191_MARK_SCORECARD.md`.)

**This file is the running framework and the 2026-07-10 baseline.** Each refresh
adds a summary block here; the full report for a refresh lives in `docs/reviews/`.

---

## 2026-08-06 Refresh (Batch 191)

**Full report:** `docs/reviews/BATCH_191_COACHING_INTEGRITY_REFRESH.md`
(8 findings, `CI191-01…08`, 2 High / 5 Medium / 1 Low).

**Grade: B+ (held) — for entirely different reasons.** Three of the four chronic
gaps are closed, and closed *in the wild*: **F2** closed (the Batch 167 load cap
fired for real on 07-29 at ACWR 1.61 / 1502 min recovery, Green → Amber), **F4**
closed (the Batch 170 stacking rule fired on 07-31, Amber → Red on a night whose
sleep score was 76), **F3** closed (the credit ceiling holds a credited 74 at
Amber unless HRV, RHR, readiness and the check-in all corroborate). **F1** is
anchored and the anchor is load-bearing on **12 of 12** mornings — Mark's own
84-day readiness median is **50** (Q1 28, Q3 61), so `readinessEffectiveFloor` was
the absolute 60 on every morning rather than his personal centre (50.0–53.5).
**F5** closed for the exception paths (absence is neutral, never positive
evidence). **F8 stays RESOLVED** — no narrative softening on any non-Green
morning. **F9 / R155-C / R155-D shipped** — learned context capped at 12 items /
365 days, corrections at 5 / 45 days, and `ANTI_SYCOPHANCY_RULE` is now in the
chat's floors.

**The new gap (CI191-01, High) inverts a property the original audit credited.**
The audit's second pillar was that the one gate-relevant input Mark can edit "can
only ever *harden* the light, never soften it." Still true of the daily light;
**no longer true of the structural rail.** Batch 182's Red qualification lets a
matching phrase in Mark's own check-in text remove a Red from the chronic cluster
— unconditionally, uncapped, undecaying, with no requirement that the physiology
agree. Observed live: 08-01 → 08-04 the packet carried
`chronicAction.triggered=true, redMorningCount=2` and a seven-day deload whose
first four sessions Mark approved and pushed; on 08-05, the first morning after
Batch 182 deployed, both Reds became `explained_by_check_in`
(07-31 `training_load`, 08-01 `alcohol`), `redMorningCount` fell 2 → 0 and the
escalation switched off. 08-01's resting HR was 48 against its own ceiling of 45 —
only the word removed it. The `training_load` tag is the sharpest edge: it excuses
a Red *because* Mark named cumulative load, which is the signature the deload path
exists to catch.

**The second High (CI191-02) is structural.** `daily_metrics` holds one mutable
row per day, overwritten by the evening sync (`recorded_at_utc` 19:00–21:30 on 12
of 14 days), while the verdict was computed at wake. The packet's readiness
exceeds the surviving row on 11 of 18 mornings and its recovery clock is lower on
12 of 18 — directionally, not randomly. 07-30: packet `MODERATE`/64 with 943 min;
the row now reads `POOR`/**19** with **3233** min. Everything retrospective — the
Red qualification's `recovery_time_min`, the 84-day baselines the floors key off,
the trend alarm, the chronic misses — reads the evening value. Stored verdicts are
mutable too (07-05: `Amber@07:23 → Green@22:03`) and `_recent_verdicts` counts the
latest.

**The spoken layer has not undermined the deterministic one — largely because it
has barely spoken.** `state_change_coach`: **0** turns ever. Scheduled
`weekly_review`: newest row 2026-06-29 (Batch 185's first Sunday is 08-09). 41
user chat turns, **0** sycophancy attempts. The one exchange touching a
deterministic ceiling (07-29) quoted the app's own canonical figure but framed the
cap as "not a sign your body is struggling" — and nothing in the chat's floors
forbids that, because **none of the five deterministic protections shipped since
Batch 155 is in `coach_policy.FLOORS`** (CI191-04).

**Verdict distribution:** 48% → 71% → **75%** Green across the three audit
windows. On this window's evidence that is physiology improving, not the gate
loosening — but it is the number to watch.

**Closing CI191-01 and CI191-02 is what now moves this to A−.**

---

## 2026-07-26 Refresh (Batch 155)

**Scope:** re-ran the 2026-07-10 lenses against the code as it then stood, audited
the four coaching-brain surfaces shipped since (Batches 148 / 150 / 151 / 152), and
re-graded against real `coach`-schema reads for 2026-07-10 → 2026-07-26.

### Refresh bottom line

**Nothing regressed.** The four new brain-surface changes did not open a single new
path to the verdict, and two of them (the ERG honest-note and the factual
training-week grounding) actively *raise* honesty. The two structural gaps the
original audit named — **F1** (self-recalibrating baselines) and **F2** (training
load cannot move the light) — are **both still open, unchanged in code**; F2 now has
its first *real-morning* instance (07-24) rather than only a synthetic probe. One
new low-severity item (**F9**: confirmed memory has no volume cap or decay). The
acute defences got fresh real-world confirmation: a genuine four-Red cluster fired
on real signals, the soft-sleep override stayed rare (1 / 16), and 19 real chat
turns show substantive dialogue with **zero** "just tell me I'm fine" gaming.

**Grade: B+ (held).** Acute honesty reconfirmed in the wild; the chronic F1/F2 gaps
are unchanged, and closing them is still what would move this to A−.

### F1 / F2 — still the open gaps (re-verified in current code)

- **F1 — HIGH · baselines still self-recalibrate. OPEN, unchanged.** The
  soft-sleep→Green override still floors readiness at Mark's *own* rolling median
  (`_soft_sleep_recovery_override` → `readiness_floor = readiness_center`,
  [morning_analysis.py:1696](apps/api/src/services/morning_analysis.py:1696)),
  resting-HR "in band" still keys off his personal quartiles
  ([personal_baselines.py:49-62](apps/api/src/services/personal_baselines.py:49)),
  and the window is still `DEFAULT_WINDOW_DAYS = 84`
  ([metric_baselines.py:36](apps/api/src/services/metric_baselines.py:36)). No
  absolute-anchor constant exists anywhere in the verdict/baseline code. The
  categorical Garmin Low/Poor backstop (`readiness_level not in {"low","poor"}`)
  and the absolute Red floor (age-adjusted sleep < 60) still hold, so the finding
  is unchanged — neither closed nor worsened.
- **F2 — HIGH · load still cannot move the light. OPEN, unchanged — now seen in
  real data.** `_morning_verdict` still takes no ACWR/ramp parameter (only the
  advisory `yesterday_load`,
  [morning_analysis.py:1450-1461](apps/api/src/services/morning_analysis.py:1450));
  a hard prior day only appends a plan-note when the day is already non-Green
  ([:1547-1550](apps/api/src/services/morning_analysis.py:1547)); and the one place
  load enters the ladder *relaxes* rather than caps — a Low Garmin readiness with
  clean recovery signals + any load present is read as "load-driven" and escapes the
  auto-Amber ([:1503-1508,1522](apps/api/src/services/morning_analysis.py:1503)).
  **Real instance (07-24):** Garmin readiness **LOW** + yesterday **HARD** →
  **Green**, `readinessInterpretation="load_driven"`, reason *"Garmin readiness is
  Low but recovery signals justify a load-driven read."* The original audit could
  prove F2 only with synthetic Probe 5; it now fires on a live morning. (The
  `load_driven` path predates the 07-10 audit — commit `743770f`, 2026-07-02 — so
  this is F2 unchanged, not a new regression.)
- **F3–F7 unchanged.** The verdict ladder is structurally identical
  ([:1514-1540](apps/api/src/services/morning_analysis.py:1514)): one-directional
  age-sleep credit (F3), first-match with no stacking (F4), `None`-subjective and
  `None`-HRV still read as passing (F5), chronic surveillance still advisory-only
  (F6), corrections still fed as ground truth with no decay (F7). F7 is **active in
  real data** — Mark repeatedly corrected the watch's sleep-start (07-19), and the
  07-23 read acknowledges it (*"you've flagged again that the watch mis-detected
  sleep start"*) — but it steered only narrative; 07-19 stayed **Red**.
- **F8 — still RESOLVED.** See the refreshed Prong B below.

### New coaching surfaces (155.2) — integrity assessment

**(a) ERG-always trust (Batch 152) — sound; a small honesty *credit*.** The
instruction to "treat ERG-held power as delivered … never frame ERG-held power as
under-performance" is *physically accurate* (an ERG-locked trainer holds the target
watt), and it is grounded in **real recorded execution data**, not the prescription:
`intervals`/`execution` come from `segment_ride_intervals(timeseries, …,
actual_laps=…)` + `activity.avg_power_watts`
([post_workout_analysis.py:335-343](apps/api/src/services/post_workout_analysis.py:335)),
so genuine under-performance still surfaces via each work interval's `fade` /
`hrDriftPct` / `workoutAdherence`. The trust only removes the false-negative of
reading a structurally-low *whole-ride average* as pacing failure. The weekly surge
honest-note (`prescribedErgMode == "off"` ridden in ERG) is calibrated as *one plain
line, no change-suggestion*
([:97-101](apps/api/src/services/post_workout_analysis.py:97)) — it tells Mark a
mildly unwelcome truth (ERG softened the neuromuscular hit) without nagging. **No
masking of under-performance or over-reach** (over-reach is an FTP / block-progression
concern, not a read concern). Real data: the 07-25 indoor VO₂ read correctly labels
whole-ride avg *"207 W (context only — structured session)"*; the surge honest-note
path is not yet exercised (07-25 was a 2-min VO₂ protocol, not a 30/15 surge).
*Dependency to preserve:* the trust stays honest only because `execution` is real
recorded data (Batch 145) — never grade an ERG session off the prescription.

**(b) Conversational learning (Batch 151) — well-defended; cannot reach the light.**
Five independent layers hold: (1) sources are **user-authored only**
(`BriefMessage.role == "user"`, own notes, own corrections,
[conversation_learning.py:328-329](apps/api/src/services/conversation_learning.py:328)),
so the coach can never learn its own reassurance; (2) a deterministic filter rejects
verdict / threshold / Red-VO2 / data-quality / L-R-balance / reliability content
*and* the explicit sycophancy patterns ("just tell/mark me fine/green/ready", "tell
me I'm fine"), applied to both the statement and every evidence quote
([:177-197,262-295](apps/api/src/services/conversation_learning.py:177)); (3)
evidence must be a **verbatim** quote from a real user source; (4) the accept gate is
confirmed-only and re-validates edited text (`statement_is_durable` → HTTP 422,
[:609-617](apps/api/src/services/conversation_learning.py:609)), user-scoped,
idempotent; (5) accepted items land in `learned_context`, packet-marked
`classificationImpact:"none"` with an explicit "cannot alter verdicts/thresholds"
rule ([learned_context.py:13-20](apps/api/src/services/learned_context.py:13)), and
**`_morning_verdict` never reads it**. The sycophancy trap ("I feel great / just
tell me I'm fine") yields *no* durable item. **Residual (F9, LOW):**
`learned_context_packet` returns *all* confirmed items with no volume cap and no
decay/aging — over long accumulation this could grow the prompt and subtly warm
prose tone (human-curated, cannot touch the light); parallels F7. Real data: **0
proposals have ever been distilled** (only the empty seed row), so there is no
accumulation to drift yet — the assessment is code-level plus "unused in the wild."

**(c) Post-workout follow-up chat (Batch 150) — structurally advisory-only;
non-gaming on the verdict.** The plan-change proposal affordance is gated to
`analysis_type == "morning"`
([brief_chat.py:170-174,272](apps/api/src/services/brief_chat.py:170)), so a
completed-session chat can *never* emit a proposal — confirmed in real data
(`proposals_on_nonmorning_chat = 0`). The chat inherits the shared floors (no
VO2-on-Red, no L/R balance, local times, no skipped/holiday-as-live,
[:65-68](apps/api/src/services/brief_chat.py:65)) and cannot touch the verdict — it
is immutable data in the packet. The 19 real user turns are substantive coaching
dialogue and factual corrections; **none** is a "just tell me I'm fine" attempt.
**Low-severity hardening note:** unlike the post-workout *read* prompt ("this is the
one place you must not be sycophantic"), the chat prompt carries no explicit
anti-sycophancy directive — a tone-only residual, since the verdict is immutable.

**(d) Training-week grounding (Batch 148) — a strength; cannot confabulate.** The
deterministic assembler populates a day's `executed` **only** from real Garmin
activities
([training_week.py:248-256](apps/api/src/services/training_week.py:248)), and
`_day_status` returns `"executed"` only when a real activity is present
([:346-362](apps/api/src/services/training_week.py:346)); a moved-away, skipped,
removed, or merely-planned session resolves to its own honest status and can never
read as executed. The packet's `grounding` block tells the model "executed = the
only completion truth" and refuses to infer that a change followed an app suggestion
without a durable audit link. This is exactly the factual grounding that *prevents*
narrative confabulation. Real reads confirm honest deviation verdicts in the wild
(07-10 skip flagged `diverged: true`; 07-21 Red-day flagged; 07-23 "approved
adjustment, not a deviation").

### Prong B refresh — real `coach`-schema reads, 2026-07-10 → 2026-07-26

Read-only queries against Mark's live data (garmin-coach tables live in the `coach`
schema, not `public`).

```
MORNING VERDICT DISTRIBUTION (n=16 mornings; 07-13 has no analysis):
  Green 11 | Amber 1 | Red 4
  Genuine 4-Red cluster 07-19..07-22 on real HRV-unbalanced / age-adj<60 signals
  -> the acute Red gate fires honestly; bad days are not suppressed.

SOFT-SLEEP -> GREEN OVERRIDE: 1 / 16 (07-16, age-adj 61 -> Green) -> rare (F1 surface)

NARRATIVE vs LIGHT (every non-Green + override morning): no softening. Examples --
  07-16 Green(override): "Garmin scores this Poor (raw 57; age-adjusted 61) ...
                          this is a recovery override situation"
  07-21 Red : answers his snack question honestly; "Age-adjusted sleep is below 60"
  07-22 Red : great sleep (age-adj 83) but Red on unbalanced HRV -- NOT gameable
              by a good sleep score
  07-23 Amber: "Garmin readiness is Low without enough recovery evidence"

F2 IN THE WILD (new evidence):
  07-24 Green despite readiness LOW + yesterday HARD; readinessInterpretation=
        "load_driven" -> load relaxed the Low-readiness Amber (F2's exact shape)

ERG (152) IN THE WILD:
  07-25 indoor VO2: whole-ride avg "207 W (context only -- structured session)";
        has_erg_profile=true -> guard fires. Surge honest-note not yet exercised.

LEARNING (151) IN THE WILD:
  conversation_learning_proposals: 0 total (feature live, never run)
  proposals_on_nonmorning_chat: 0 -> advisory-only gate holds

CHAT (150) IN THE WILD:
  19 user turns: substantive Q&A + factual corrections; 0 sycophancy attempts
```

### Remediation stubs (diagnose-only — no code changed in Batch 155)

- **R155-A (= close F2):** give the verdict a load input with a hard cap (ACWR ≥
  ~1.5, or Garmin recovery-time over a threshold, caps the day at Amber) so load can
  *cap*, not only relax. 07-24 is the motivating real case. **HIGH.**
- **R155-B (= close F1):** anchor the personal floors with an absolute floor (e.g.
  never treat readiness < 50 as "at median") and/or alarm on the 84-day median
  *trend* so a slow slide is visible. **HIGH.**
- **R155-C (F9):** cap and/or age `learned_context` items in the packet, and decay
  old corrections (F7), so confirmed memory cannot grow or warm tone unboundedly.
  **LOW.**
- **R155-D:** add an explicit "do not cave to reassurance pressure" line to the
  brief-chat system prompt, matching the post-workout read. **LOW.**

(F3–F6 remediation stubs remain as recorded in the 2026-07-10 audit below.)

---

> **The sections below are the original 2026-07-10 audit — the baseline this refresh
> updates.** F1 / F2 / F8 statuses above supersede their entries in the ranked
> findings; F3–F7 are unchanged.

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
