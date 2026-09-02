# Batch 239 — Coaching-Integrity Refresh (4th)

**Date:** 2026-09-01 · **Lens:** experienced endurance cycling coach ·
**Base SHA:** `2178381` (`docs: close out batch 233`), the SHA production serves.
**Prior refreshes:** 2026-07-26 (155), 2026-08-06 (191), 2026-08-17 (211).
**Grade entering:** A− · **Grade leaving: B+ (down).**

Summary block lives in `COACHING_INTEGRITY_AUDIT.md`; this is the full report.
Cross-references: `BATCH_240_HEALTH_SCIENCE_REVIEW.md` (HS240-nn) and
`BATCH_238_AI_ENGINEERING_REVIEW.md` (AI238-nn). Findings owned by those passes
are cited, never restated.

---

## Bottom line

**The verdict engine is the best it has ever been. The session on the trainer is
not the session the verdict asked for.**

Three refreshes have graded this app on whether the Green/Amber/Red light is
honest. It is — F2, F3, F4 and F6 have all moved since 2026-07-10, and the
2026-08-28 Red narrative still leads with *"a genuinely poor night by your own
standard."* This pass asked the next question, which is the coach's question:
**what is actually prescribed, and what actually gets ridden?**

- **The default state on Zwift is the un-eased session.** `reconcile_deliveries`
  (Decision #99) pushes the as-planned baseline with no approval and no verdict
  check; the Amber/Red transform then *offers* a lighter alternative that only
  lands if Mark taps Approve. **Eleven of the eighteen eased offers ever made were
  never pushed.**
- **The one named delivery safety rule has a hole, and it has been through it.**
  On 2026-07-22 the morning verdict was written **Red at 08:41**. At **09:19** a
  proposal containing **6 × 12 s at 185 % FTP (518 W)** reached `pushed`. Mark
  rode 58 minutes with an **anaerobic training effect of 1.8**. Every path that
  carries `blocks_red_vo2` would have returned 409.
- **The first live Red since Batch 194's fix did not count.** 2026-08-28 was
  excluded from the chronic cluster as `expected_training_debt` — *because* it
  carried 2,590 minutes (43 hours) of Garmin recovery debt. That is the exact
  signature the deload rail exists to catch, and the exclusion is uncapped,
  undecaying and untested by anything Batch 194 bounded.

Nothing here is a manipulation vector Mark opened. He cannot argue the light
down — and he does not need to, because the full session is already loaded.

**Findings: 12.** 2 High · 3 Med-High · 4 Medium · 3 Low.

---

## Method

**Prong A** — the real functions driven with synthetic packets, no logic
re-implemented. Scripts: `scratchpad/probe_239.py` (verdict ladder),
`probe_239b.py` (verdict scaling + block shape), `probe_239c.py` /
`probe_239d.py` (delivery text, companion gate, execution grading). Run with
`PYTHONPATH=apps/api apps/api/.venv/bin/python`.

**Prong B** — read-only SQL over the `coach` schema, column-projected and
windowed (the Supabase egress cap is on until 2026-09-21). No writes of any kind.

**Evidence labels.** `observed` = seen in Mark's real production data ·
`proved` = produced by executing the real function · `implemented` = read in the
code and not yet exercised.

---

# Part 1 — F1–F7 re-tested

| # | 2026-07-10 finding | Status now | Decisive evidence |
|---|---|---|---|
| **F1** | "Normal" is self-recalibrating | **Partly closed** — 1 of 3 rails anchored | Readiness floor is `max(personal_center, 60)` and held at 60 against a drifted median of 50 (`proved`). The **RHR rail has no anchor**: identical night, RHR 52 → **Amber** against a healthy Q3 of 46, **Green** against a drifted Q3 of 53, with the readiness floor held at 68.0 in *both* runs so the RHR baseline is the only moving input (`proved`, `scratchpad/probe_239e.py`). HRV keys off Garmin's own rolling baseline. This is the 2026-07-10 Probe 4 reproduced on the rail that did not get an anchor. See HS240-15 for the health-side reading; this is the executed twin. |
| **F2** | Load cannot move the light | **Closed in code; near-inert in practice** | `_training_load_cap` caps Green → Amber at ACWR ≥ 1.50 or recovery > 1,440 min (`proved`). But it is **one-directional**: ACWR 3.0 **and** 4,320 min of recovery on an already-Amber day still returns **Amber** (`proved`). Across 32 August mornings the cap **triggered 3 times and applied 0** (`observed`); ACWR's August max is **1.31** against a 1.50 threshold, so that limb has never fired. The 2026-07-10 Probe-5 value of 1,400 min still returns **Green** (`proved`). |
| **F3** | One-directional sleep credit lifts a mediocre night to Green | **Closed** | Raw 62 → age-adjusted 74 without complete corroboration returns **Amber** with `sleepCreditCeiling.applied` (`proved`); with HRV + RHR + readiness + a positive check-in it returns Green. Raw 57 → 61 (the real 2026-08-30 night) returns Amber. HS240-17 quantifies what the ceiling holds back. |
| **F4** | No cumulative escalation to Red | **Partly closed** — escalation exists, gated on one categorical | Readiness **POOR** + soft sleep 62 + subjective 3 + hard yesterday + elevated RHR → **Red** (`proved`). The same five signals with readiness **LOW** → **Amber**; with readiness **MEDIUM** plus ACWR 2.0 and a 25-hour clock → **Amber**; with **no readiness level at all** → **Amber** (all `proved`). Nothing sums unless Garmin's own word is "Poor". |
| **F5** | Missing-data policy inconsistent and partly optimistic | **Partly closed** — absence is no longer *positive*, but it is still *cheaper than honesty* | Clean night + honest check-in of **3 → Amber**; clean night + check-in **omitted → Green** (`proved`). No HRV at all → Green; no RHR → Green; **no sleep row, no daily-metric row and no check-in → Green** (`proved`). There is no coverage gate before `_morning_verdict`. |
| **F6** | Chronic overreaching is advisory-only | **Materially closed, and closed in the wild** | Five `chronic_deload` proposals were built **and pushed** 2026-08-02 → 08-06 (`observed`). It still cannot *force*: `verdictImpact: "none"`, and a proposal ignored is a proposal. |
| **F7** | Corrections steer the narrative | **Partly closed** | Bounded at 5 items / 45 days (`RECENT_CORRECTIONS_LIMIT`, `RECENT_CORRECTIONS_MAX_AGE_DAYS`) — R155-C shipped. Corrections are still fed as ground truth with no truth-check. AI238's Lead #1 confirms one was acted on in the 09-01 brief. |
| **F8** | Narrative does not soften the light | **Still RESOLVED** | 2026-08-28 Red opens *"The age-adjusted sleep score lands at 58, which is 23.5 points below your personal median of 81.5 — a genuinely poor night by your own standard."* (`observed`). |

### Prior-refresh items still open

- **CI191-01 — now *observed*, and the observation goes against the app.** See
  **CI239-01**. The reservation Batch 211 called "the only thing between A− and
  A" has been answered by a live Red, and the Red was excluded through a
  *different* door.
- **CI211-01 — still open, and slightly worse.** Stale `proposed` proposals have
  gone **16 → 17**, every one for a workout date already past (2026-06-27 →
  2026-08-30). No expiry path exists. See **CI239-12**.

---

# Part 2 — new findings

## CI239-01 — HIGH · The first live Red since the fix was excused *because* of accumulated training load

**Where.** `chronic_patterns.py:1302-1324` (`_qualify_red_morning`, the
`expected_training_debt` branch), `RECOVERY_DEBT_EXPLAINED_MIN = 24 * 60`
(`:53`).

**What happened.** 2026-08-28 is the first Red morning since Batch 194 shipped on
08-15. Its stored qualification, carried unchanged in every packet from 08-28 to
09-01:

```
date: 2026-08-28
classification:      expected_training_debt
countsTowardCluster: false
explanationSources:  [recovery_debt, intact_hrv, intact_resting_hr]
checkInReasons:      []                      <- nothing was claimed
physiology:          recoveryTimeMin 2590    (43.2 hours)
                     hrvMs 49 / floor 44 / BALANCED
                     restingHeartRateBpm 44 / ceiling 45
```

`redMorningObservedCount: 1`, `redMorningCount: **0**`.

**Why this is a coaching failure, not a data quirk.** Batch 194 bounded the
*check-in* exclusion four ways — physiology can contradict it, `training_load`
and `deliberate_rest` never excuse at all, it expires after two days, and it is
capped at one. Every one of those bounds exists because CI191-01 established the
principle: **you may not remove a Red from the overreaching count by naming
accumulated load, because accumulated load is what the count is for.**

`expected_training_debt` does exactly that, from the physiology instead of the
text, and carries **none** of the four bounds: no cap, no expiry, no requirement
that anything corroborate. Read the branch as a coach would:

> HRV is fine, resting HR is fine, and you are 43 hours deep in recovery debt —
> therefore this Red is expected and does not count toward the deload signal.

Forty-three hours of recovery debt is not a reason to discount a bad morning. It
is the reason to have one.

**The inversion that ties this to F5.** Mark's 08-28 free-text check-in said the
cause plainly — chores, then a harder ride in 25 °C heat, then an evening out —
but the *structured* `checkInReasons` were empty. Had he tagged `training_load`,
`_qualify_red_morning` would have returned `endogenous_training_signal` and the
Red **would have counted** (`implemented`). Because he tagged nothing, the
physiological branch excused it. The same shape as F5's null move: the default
is the permissive branch.

**Scope note, honestly.** One Red cannot reach `CHRONIC_ACTION_RED_THRESHOLD = 2`
either way, so nothing was suppressed on 08-28 itself. What was suppressed is the
Red's *availability* — it is permanently marked as not counting, so it can never
pair with a future one inside the 7-day window.

**Evidence.** `observed` (stored packets 08-28 → 09-01) + `implemented` (the
branch and its absent bounds).

**Fix shape.** Give `expected_training_debt` the four bounds Batch 194 gave the
acute exclusion, or delete it. At minimum it must not fire when the recovery
clock is the *only* abnormal signal — which is the case it currently exists for.

---

## CI239-02 — HIGH · The un-eased session is the default on the trainer, and Red-never-VO2 does not cover the path that puts it there

**Where.** `executable_coaching.py:648` (`reconcile_deliveries`, "push-on-plan-set
… delivered **without a per-workout approval**", Decision #99) →
`workout_delivery.py:829/865` (`create_event` / `replace_event`);
`routers/workout_delivery.py:586` → `workout_delivery.py:743`
(`WorkoutDeliveryService.push`). **None of these four calls `blocks_red_vo2`.**
The gate is present on `auto_push_due` (`:509`), `send_today` (`:623`), the
interval editor (`:921`), `approve_adjustment` (`:1028`) and `plan_actions:838`.

`verdict_scaling.py:41` states that "`blocks_red_vo2` still gates the push
independently." That is true of the adjustment paths and false of the baseline
path.

**Observed in production — 2026-07-22.**

| time (UTC) | event |
|---|---|
| 08:41:17 | morning analysis written, **verdict Red** |
| 09:19:01 | proposal for 07-22 reaches `pushed`, `origin: as_planned` |
| — | its IR contains **6 × 12 s, `powerStartPct` = `powerEndPct` = 185**, labelled *"Neuromuscular sprints @185% work n/6"* — **518 W at FTP 280** |
| 10:00:10 | `red_substitution` proposal created — **never pushed** |
| (day) | ride completed: 58 min, NP 186 W, IF 0.663, load 87, **anaerobic TE 1.8** |

`ir_has_vo2` fires at ≥ 106 % FTP, so `blocks_red_vo2` returns True for this IR;
every gated path would have raised `409 Red verdict blocks VO2 delivery to
Zwift`. It did not, so it travelled an ungated one.

*(Batch 223's `SHORT_PRIMER_MAX_DURATION_SEC = 20` deliberately reclassifies
12-second primers as **not** VO2 for weekly-mix accounting. The safety predicate
has no such carve-out, which is the correct asymmetry — the gate would have
caught it.)*

**The same shape on Amber, where there is no gate at all.** 2026-08-13, verdict
Amber at 08:40: an `as_planned` proposal carrying the identical 185 % sprint
block reached `pushed` at 09:21, while **two** `amber_regeneration` proposals
(08:40 and 10:00) were never pushed. The ride carried anaerobic TE 1.4.

**The pattern, across the whole window.**

| origin | proposed, never pushed | pushed |
|---|---:|---:|
| `amber_regeneration` | **8** | 5 |
| `red_substitution` | **3** | 2 |
| `as_planned` | 0 (4 deleted) | **58** |

Eleven of eighteen eased offers never reached the trainer. On those days the
as-planned or hand-edited session did.

**What a coach would say.** The verdict is not the coaching; the workout is. An
architecture where the hard session is pre-loaded and the easy one needs a tap
has its defaults exactly backwards on the days that matter. On a Red morning the
correct default is that the hard session is *not available*.

**Evidence.** `observed` (two production days with timestamps and the IR steps) +
`implemented` (the ungated call paths).

**Fix shape.** Move `blocks_red_vo2` into `WorkoutDeliveryService.push`,
`create_event` and `replace_event` so the gate is at the rail rather than at four
of six callers — and extend the principle: on a non-Green morning the *baseline*
reconcile should deliver the adjusted IR, not the planned one, with the planned
one available on request.

---

## CI239-03 — MED-HIGH · A Red morning prescribes a *longer* ride than an Amber one

**Where.** `verdict_scaling.py:64` `AMBER_DURATION_SCALE = 0.75` against `:71`
`RED_ENDURANCE_DURATION_SCALE = 0.85`.

**Proved.** The same already-Zone-2 ride (120 min at 65 % FTP), one session on
the day, through the real `_verdict_adjustment_packet`:

```
Amber -> 90 min @ 65% FTP
Red   -> 102 min @ 65% FTP     <- 12 minutes MORE on the worse morning
```

On the generated 150-minute long ride the gap is wider: Amber 112.5 min, Red
127.5 min.

Batch 215 gave Red endurance-awareness — a good decision, and Decision #293's
reasoning (sustained easy work builds sleep pressure) is sound. But it set Red's
scale without checking it against Amber's, so the ladder is no longer monotonic.
Mark can be told, truthfully and by the same engine, that today is worse than
yesterday *and* that today's ride is longer.

**A second half to the same finding: the combined-load gate is Red-only.**
`companion_session_present` is passed on the Red path and not on the Amber one
(`companionSession: None` on every Amber packet, `proved`). On Mark's split
Saturday — bike plus strength — Red correctly withdraws the endurance allowance
(102 → 60 min at 60 %); **Amber does not look at the strength session at all**.
Amber is the verdict that leaves more work in, so it is the one where the day's
total matters more.

**Evidence.** `proved`.

**Fix shape.** Make Red's endurance duration scale strictly ≤ Amber's (a pinned
invariant, not a comment), and pass `companion_session` on both paths.

---

## CI239-04 — MED-HIGH · The verdict transform shortens the intervals themselves, which destroys the protocol rather than easing it

**Where.** `verdict_scaling.py:_adjust_step` applies `duration_scale` to **every
step**, including work reps and recovery floats.

**Proved**, against the app's own generated VO2 sessions built through the real
`build_structured_workout_ir`:

| planned | Amber | Red |
|---|---|---|
| 30/30 — 30 s @ 108 % / 30 s @ 50 % | **22 s @ 94 % / 22 s @ 50 %** | **15 s @ 60 % / 15 s @ 50 %** |
| Rønnestad 30/15 — 30 s @ 108 % / 15 s @ 50 % | **22 s @ 94 % / 11 s @ 50 %** | **15 s @ 60 % / 8 s @ 50 %** |
| Sweet Spot 3 × 8 min @ 91 % | 3 × 6 min @ 78 % (218 W) | 3 × 4 min @ 60 % |

No coach eases a session by shaving 25 % off every repetition and every float. You
remove reps, remove a set, or replace the session. What comes out here is a
30-minute workout containing **5.5 minutes of 22-second efforts at 263 W** — too
short and too easy to be a VO₂ stimulus, too fragmented to be tempo, and with a
work:rest ratio the protocol never specified. On Red it is 13 × 15 s at 168 W with
8-second floats, which is not a session at all.

The **intensity** half of the transform is well reasoned and I would keep it —
`ease_amber_power_pct` holding a Zone-2 ride at 67 % is exactly right, and Batch
173.2 fixed a real four-way disagreement. It is the **duration** half, applied at
step granularity, that is wrong.

**Related, and smaller: Amber is one recipe regardless of why it is Amber.** A
day that is Amber because the subjective score was 4 and a day that is Amber
because readiness is Poor with an elevated resting HR and a 25-hour recovery
clock receive the identical 75 % / 94 % prescription (`proved`). A coach titrates.

**Evidence.** `proved`.

**Fix shape.** Scale the *number* of work intervals, not their length: keep
`durationSec` on work and recovery steps, drop reps/sets to hit the duration
target, and let warm-up/cool-down absorb the remainder.

---

## CI239-05 — MED · The Amber instruction is bike-only and is emitted verbatim on strength, mobility and walk days

**Where.** `morning_analysis._plan_adjustments`, the `status == "Amber"` branch.

**Proved.** With a single `strength_maintenance` session as the day's only
workout:

```
Green  -> "Proceed with the planned workout if warm-up confirms readiness."
Amber  -> "Cut duration 25%; hold Zone 2, ease harder intervals by a zone, and
           convert former HIT/VO2 work to no more than 94% FTP (Sweet Spot)."
Red    -> "Substitute recovery, mobility, or rest."
```

The identical Amber text is returned for a mobility-only and a walk-only day.
This is not hypothetical: **Monday is a strength-only day in Mark's live plan**
(8 of 8 Mondays in the window carry `strength_maintenance` and nothing else), and
`planAdjustments` is fed to the model as the day's instruction.

Green and Red are both fine. Only Amber assumes a bike.

**Evidence.** `proved` + `observed` (Mark's Monday).

**Fix shape.** Branch the Amber text on whether the day holds a bike session, and
give strength/mobility/walk their own Amber wording.

---

## CI239-06 — MED · Perfect execution can never earn an FTP increase

**Where.** `block_progression.py:206-214` — the bump requires
`hit_rate >= 0.75` **and `over_rate >= 0.30`** and `adherence >= 0.75` and rising
FTP drift. `ride_intervals._adherence` grades `over` only above
`target_high + ADHERENCE_TOLERANCE_PCT` (5 pp), and a work interval of
`durationSec <= PEAK_GRADED_MAX_DURATION_SEC` (30 s) is **peak-graded, which by
construction has no "over"**.

**Proved.**

```
Sweet Spot target 88-94%, ERG holds 91%          -> on
Sweet Spot target 88-94%, rider at 99%           -> on
Sweet Spot target 88-94%, rider at 100%          -> over
VO2 30s target 105-110%, peak 130%, peak-graded  -> on      <- never "over"

on=20 over=0  under=0 -> hit 1.00, over_rate 0.00 -> NOT eligible
on=14 over=6  under=0 -> hit 1.00, over_rate 0.30 -> eligible
```

On Mark's plan the VO₂ work is 30-second reps — peak-graded, so structurally
ineligible to grade "over". The sweet-spot reps are the only over-eligible
intervals, and they are ridden in ERG, which holds them on target. **To earn a
3 % FTP bump he must ride ≥ 100 % FTP on 30 % of his sweet-spot repetitions** —
i.e. deliberately over-ride the prescription into threshold.

This sits directly against Batch 152's shipped instruction to *"treat ERG-held
power as delivered … never frame ERG-held power as under-performance."* The app
trusts ERG for the read and requires disobedience for the progression.

HS240-18 records that the ±3 % move itself is physiologically conservative and
correctly signed; the defect is the gate in front of it, not the size of the step.

**Evidence.** `proved` (the grading function and the gate arithmetic) +
`implemented` (never exercised — no generated block has ever been locked, see
CI239-09).

**Fix shape.** Replace `over_rate >= 0.30` with a signal that rewards clean
execution — e.g. `under_rate <= 0.10` with rising efficiency-factor drift, or a
scheduled FTP re-test — and treat over-riding as neutral rather than as the
qualifying evidence.

---

## CI239-07 — MED · Strength is invisible to every load rule, but counted as a spacer between two hard bike days

**Where.** `weekly_restructure.py:_CATEGORY_INTENSITY[CATEGORY_STRENGTH] =
INTENSITY_NONE`; `weekly_mix.mix_bucket` returns `None` for any non-`bike_` type;
`build_structured_workout_ir` raises 422 for a strength IR so no verdict transform
reaches it; the Amber delivery path passes no `companion_session`.

**Consequences, as a coach reads them.**

1. The no-stack rule (`MIN_GAP_DAYS = 2`, VO₂ and Sweet Spot never within two
   days) treats a strength day as a **clear day**. VO₂ Tue / strength Wed /
   Sweet Spot Thu is compliant. For a 57-year-old, a full-body lifting session
   between two quality bike days is not a rest day.
2. A Red or Amber morning changes the bike session and says nothing about the
   strength session on the same day (`proved` — the transform cannot build an IR
   for it, and `planAdjustments` never names it).
3. Weekly-mix accounting is bike-only, so a week in which the bike work collapsed
   and the strength work doubled reports the same mix status.

**What is genuinely good here, and should be protected.** The app *does* read the
whole athlete after the fact: 20 `post_strength`, 15 `post_flexibility` and 6
`post_walk` analyses since 2026-07-01 (`observed`). Mark's own plan carries
strength every week — Monday plus a weekend session. The gap is on the
*prescription* side, not the *review* side.

**Evidence.** `implemented` + `proved` (transform and adjustment text) +
`observed` (Mark's Monday strength day and the analysis counts).

**Fix shape.** Give strength a non-zero intensity weight in the restructurer
(`INTENSITY_MODERATE` at minimum, so it cannot serve as a spacer), count it in
`companion_session_present` on the Amber path, and add one line of Amber/Red
guidance for a strength day.

---

## CI239-08 — MED · Nothing validates an imported plan against the app's own periodisation principles

**Where.** `plan_import.build_plan_rows` validates exactly two things: the start
date is a Monday, and each bike workout is deliverable
(`validate_deliverable_bike_workout`). There is no periodisation check anywhere.

**Observed.** Mark's live plan (`source = plan_no2_import`, 70 active rows,
2026-07-20 → 2026-10-18) runs:

```
W01 build  W02 build  W03 RECOVERY
W04 build  W05 build  W06 build  W07 build  W08 build   <- five consecutive
W09 RECOVERY  W10 build  W11 build  W12 consolidation  W13 taper
```

Weekly planned bike minutes over the same stretch: 195 → 316 → 0 → 195 → 238 →
296 → **398 → 392** → 284 → **416 → 396** → 299 → 195.

The app's own `BLOCK_SEQUENCE` is 2:1 throughout. Mark's imported plan is 2:1 once
and then **5:1** — five build weeks between 2026-08-10 and 2026-09-13, over the
exact stretch where weekly volume climbs from 195 to 398 minutes. Nothing in the
app has noticed, because nothing in the app looks. The only place `plan_blocks`
is read for block type is `chronic_patterns._chronic_action_signal`, and it is
read to **suppress** the app's own deload proposal when a recovery block is
scheduled within seven days — the one use that makes a sparse recovery cadence
*less* visible, not more.

To be fair to the plan: it does carry genuine periodisation — a lighter third
week in the 09-14 and 10-05 slots, a real taper, and a VO₂ progression (30/30 →
40/20 → 7 × 3 min → 40/20 extended) that is **better than the app's own**. The
finding is that the app cannot tell the difference between this plan and a bad
one.

**Evidence.** `observed` (the live plan and its block table) + `implemented`
(the absent validation).

**Fix shape.** A read-only plan-audit at import: deload cadence, week-on-week
volume ramp, hard-session spacing, and weekly intensity distribution, surfaced as
warnings on the import result rather than as a block.

---

## CI239-09 — LOW-MED · The app's own 13-week generator has never produced a live plan, and its build weeks carry no progressive overload

**Observed.** `coach.planned_workouts.source` holds `plan_no2_import`,
`today_card_swap`, `batch_5_seed`, `plan_action_add`, `interval_editor` and
`holiday_pause`. There is **no `block_generator_lock` row**. The generator, the
refine-then-lock workflow and `block_progression`'s FTP proposal have never
touched Mark's plan.

**`implemented`, from driving the real `_block_templates`.** Every build week in
`BLOCK_SEQUENCE` is byte-identical apart from one field:

```
wk 1,2,4,5   build  3 bike / 285 min (vo2 60, sweet_spot 75, endurance 150) | vo2=30/30
wk 7,8,10,11 build  3 bike / 285 min (identical)                            | vo2=ronnestad_30_15
wk 3,6,9     recovery 3 bike / 195 min (recovery, tempo, endurance)
wk12 taper 155 min · wk13 consolidation 235 min
```

The Sweet Spot session is 3 × 8 min at 88–94 % in week 1 and in week 11. The long
ride is 150 minutes in week 1 and in week 11. **A block builds to nothing.** The
only progression is a single step at week 7, and it is a large one: 30/30 gives
3 × 5 × 30 s = **7.5 min** of work; Rønnestad 30/15 gives 3 × 13 × 30 s =
**19.5 min** — a 2.6× jump in one week with no intermediate. (HS240-16 owns the
separate question of whether 105–110 % FTP is the right intensity for either.)

It also emits **3 bike sessions** a week where `weekly_mix.py`'s own documented
canonical week is VO₂ × 1 + Sweet Spot × 1 + **Zone 2 × 3** — the mix Mark
actually rides. Locking a generated block would silently cut his week from five
rides to three.

**Why it still matters at Low-Med.** The generator is live, reachable, and is the
seed the whole `block_progression` engine feeds. If it is ever used it will
produce a thirteen-week block with no overload and the wrong weekly shape.

**Fix shape.** Either progress the build templates (interval duration or reps on
the Sweet Spot session, minutes on the long ride, across the 2121 cycle) and add
the two missing Zone-2 slots, or mark the generator explicitly as unused and stop
`block_progression` presenting it as the destination for an FTP recommendation.

---

## CI239-10 — LOW-MED · Two Zone-2 anchors coexist, and the endurance ceiling is the one that binds

**Where.** `verdict_scaling.ENDURANCE_CEILING_PCT = 75` (the "top of Zone 2"
below which an interval is held rather than eased) against the Zone-2 target the
plan and Batch 173 actually use, **67 %** (188 W at FTP 280), and the generated
long ride's 65 %.

`ease_amber_power_pct` therefore holds anything up to **75 % = 210 W**, which for
Mark is upper Zone 2 / low tempo rather than the Zone-2 anchor his rides are
written to. On an Amber day a 75 % ride keeps 210 W and only loses duration, and
`red_power_cap_pct` uses the same 75 % as Red's endurance ceiling.

This is a small number with a real effect: the difference between "hold your
Zone 2" at 188 W and at 210 W is about 12 % more power on a day the app has
judged compromised, and it is invisible because both are called Zone 2.

**Evidence.** `proved` (the full `ease_amber_power_pct` ladder across 55–120 %) +
`implemented`.

**Fix shape.** Name the two constants apart — a *classification* ceiling (is this
ride endurance?) and a *prescription* anchor (what does "hold Zone 2" mean in
watts?) — and make the second Mark's 67 %.

---

## CI239-11 — LOW · A total data blackout returns Green

**Proved.** `_morning_verdict(daily_metric=None, sleep=None,
age_adjusted_sleep_score=None, manual_entries=[])` returns **Green**, with the
reason *"Sleep clears the green rule; missing HRV/check-in data is neutral and
did not provide positive evidence."* — a sentence about sleep on a morning with no
sleep row. There is no coverage gate before the call in `assemble`.

In practice the watch is worn and this has not happened. But the failure direction
is wrong: a morning the app cannot see anything about should not be a morning it
grants permission to train, and `_plan_adjustments` already has the right instinct
for the analogous case (*"No active planned workout found for today; keep advice
conservative."*).

This is the coaching-side statement of the same gap HS240-01/02/03 report from
physiology: the ladder has no *absence* rail, as it has no illness rail.

**Evidence.** `proved`.

**Fix shape.** A minimum-evidence gate: no sleep row **or** no daily-metric row
caps the day at Amber with an explicit "not enough data" reason.

---

## CI239-12 — LOW · CI211-01 unresolved and growing

17 `workout_delivery_proposals` sit at `proposed`, every one for a workout date
already past (2026-06-27 → 2026-08-30), against 16 at the Batch 211 refresh. No
expiry path exists. Still hygiene rather than a live defect — the daily loop looks
proposals up by `planned_workout_id` — but it is now also the *measurement* of
CI239-02: eleven of those seventeen are eased Amber/Red offers that were made and
never taken.

**Evidence.** `observed`.

---

# Part 3 — what is sound, and must survive the fixes

- **The light is still not the model's to set.** `_morning_verdict` is
  deterministic Python; every probe in this pass moved the verdict by moving
  physiology, never by moving prose.
- **`sleep_credit_ceiling` is the single best guard in the codebase.** It closed
  F3 outright and HS240-17 quantifies what it holds back — 24 nights across the
  Amber→Green line, 10 across Red→Amber. It must never be relaxed.
- **`verdict_scaling` as a shared module is the right architecture.** One
  transform behind the delivery rail, the editor and the narrative is exactly
  how you stop four numbers for one ride. The findings above are about the
  *constants and the granularity*, not the design.
- **`ease_amber_power_pct` holding an endurance ride rather than dropping it into
  recovery is correct**, and Batch 215's reasoning for Red is correct too.
- **ERG-off on both micro-interval protocols is right** — the surges arrive
  faster than a smart trainer's ERG loop.
- **The chronic deload rail works end to end** — it built proposals and Mark rode
  them, 2026-08-02 → 08-06.
- **The whole athlete is reviewed**: post-strength, post-walk and
  post-flexibility reads all run in production.
- **Adherence is excellent and the app should say so**: across 2026-07-20 →
  2026-09-01, 34 planned sessions, **zero skipped**.
- **Verdict distribution, 2026-08-01 → 09-01** (one read per date, 32 mornings):
  **23 Green / 5 Amber / 4 Red** = 72 % Green, against 59 % at the Batch 211
  window and 75 % at Batch 191's. On this window's evidence that is physiology,
  not a loosening gate — every mechanism added since Batch 167 only hardens — but
  it remains the number to watch.
- **Mark's live weekly shape is exactly the canonical mix**: Mon strength ·
  Tue VO₂ · Wed Z2 · Thu Sweet Spot · Fri rest · Sat Z2 (+ strength) · Sun Z2,
  ~6.2 h of riding. VO₂ and Sweet Spot sit Tue/Thu, at the no-stack rule's exact
  `MIN_GAP_DAYS = 2` boundary.

---

# Part 4 — grade

## B+ (down from A−)

**The calibration is the one this document has used before.** Batch 191 held B+
with two open Highs. Batch 211 moved to A− on closing both. This pass opens two
new Highs — **CI239-01** and **CI239-02** — and one of them has a production
instance in which the app's own named safety rule (Decision #61, credited as
**S1** since the original audit) was not enforced on a Red morning. Consistency
requires the grade to move back.

**What is *not* the reason.** The verdict engine has improved, materially and
measurably: F2, F3, F4 and F6 have all moved since 2026-07-10 and none has
regressed. Judged on the light alone this would be an A.

**Why it moves anyway.** This audit exists to answer whether the training
guidance is coherent, honest, and something a good coach would stand behind. The
guidance is not the light; it is the session. And on the delivery side the
defaults are inverted: the hard session is pre-loaded without approval or a
verdict check, the eased one requires a tap, and eleven of eighteen eased offers
were never taken. On 2026-07-22 that produced 6 × 12 s at 518 W on a Red morning.
No coach stands behind that, however good the reasoning upstream of it was.

## What would move it back

**To A− — close both Highs:**

1. Put `blocks_red_vo2` at the rail (`push`, `create_event`, `replace_event`)
   rather than at four of six callers, and make the non-Green baseline reconcile
   deliver the *adjusted* IR. **CI239-02.**
2. Bound `expected_training_debt` the way Batch 194 bounded the acute check-in
   exclusion — cap, expiry, and a requirement that something other than the
   recovery clock agrees. **CI239-01.**

**To A — additionally:**

3. Fix the Amber/Red ordering (**CI239-03**) and stop the transform shortening
   individual intervals (**CI239-04**). These are the two places where the
   prescription stops being something a coach would write.
4. Anchor the resting-HR rail as readiness was anchored (**F1**, with HS240-15),
   and let a stack of negatives escalate without requiring Garmin's categorical
   "Poor" (**F4**).
5. Then watch it. The single most valuable observation available is a Red morning
   on which the *baseline* delivery is blocked and the substitution is what sits
   on the trainer. Nothing in this document has seen that happen.

---

# Limitations

- **The observation window is good but the Red count is small.** Four Reds since
  2026-08-01 (08-01, 08-07, 08-08, 08-28) and only **one** after Batch 194 shipped
  on 08-15. CI239-01 rests on that one — the mechanism is
  the finding, and the mechanism is unambiguous, but it has fired once.
- **The push-path deduction is a deduction.** The DB records `pushed_at_utc`, not
  the endpoint. The claim that 2026-07-22 travelled an ungated path follows from
  the gate returning 409 on every gated one, not from a request log.
- **Block-generator findings are latent.** `block_generator` and
  `block_progression` have never run against Mark's live plan; CI239-06 and
  CI239-09 are `implemented`, not `observed`.
- **Prong A used representative baselines, not Mark's live history**, except
  where a probe explicitly replays a stored value. The probes demonstrate the
  mechanism, and the mechanism is the finding.
- **No Anthropic spend.** This pass generated nothing; every narrative claim is
  read from a stored `analyses` row.
- **Diagnose-only.** No code changed, nothing written to production.
