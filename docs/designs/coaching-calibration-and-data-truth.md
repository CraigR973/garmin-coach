# Design: Coaching calibration & data truth — Mark's feedback (2026-07-05)

**Status:** Step 0 diagnosis run; Batch 56 shipped via PR #78 / squash
`20437e8`; Batch 57 shipped via PR #79 / squash `4e0497a`. Overview + fix spec for the
nine points Mark raised on 2026-07-05. The diagnosis showed Garmin daily
metrics/sleep/activities are loaded for 2025-06-24 → 2026-07-05, strength is
classified, and the active plan exists; the first two shipped builds therefore
focused on calibration/schedule truth and data-truth safeguards, not a broad
backfill. Safety decisions:
**DECISIONS #129** and **#130**.

> Mark's framing: "No rush… probably better if we run through it together on
> screen." This doc is the shared punch-list for that session, not a green-lit
> build order.

## The through-line

Two root themes explain eight of the nine points:

1. **The engine applies generic thresholds and has no model of Mark's routine.**
   It doesn't know that a readiness of 76 is *good for him*, that good HRV/RHR
   should hold a mediocre sleep night, or that Mon & Fri are already his rest
   days. This is why it diverges from Claude/Copilot — he *tells them* that
   context in the prompt; the app never learned it.
2. **Missing or shallow data is narrated as fact.** When a packet field is `0`
   or absent (no plan loaded, no prior-year history, strength not classified),
   the LLM narrative reports it as truth — "strength training has stopped",
   "zero planned sessions", "last year was…". The deterministic aggregation is
   correct; the packet doesn't distinguish *"genuinely zero"* from *"no data"*,
   and the prompt doesn't suppress low-sample claims.

The remaining point (sleep-stage age comparison) is a clean additive feature.

---

## The nine points, grouped

### Theme A — Calibration & personalisation (doesn't know Mark's baselines/routine)

#### A1. Too cautious — sleep is a hard gate; good HRV/RHR can't override it
**What Mark saw:** two below-average sleep nights, HRV & RHR still good, yet the
app said *don't exercise* one day and *cut today 30%*. Claude/Copilot greenlit
the same planned workouts on the same stats.

**Root cause — `apps/api/src/services/morning_analysis.py:825` (`_morning_verdict`).**
The verdict ladder gates on age-adjusted **sleep** first and hard:
- `age_adjusted_sleep_score < 60` → **Red**
- `age_adjusted_sleep_score < 74` → **Amber** ("below the 74+ green target")

The `recovery_signals_good` flag (good HRV, RHR, subjective) *only* rescues the
separate "Garmin readiness is Low" branch — it **cannot** hold a low-sleep
night. So two soft-sleep nights force Amber regardless of strong recovery
signals. The eased ride then follows deterministically:
`apps/api/src/services/executable_coaching.py:63` — `AMBER_DURATION_SCALE = 0.75`
(a 25–30% cut, drop a zone, remove HIT); Red substitutes an easy spin.

**Fix (safety-gated — needs sign-off):** let strong recovery signals hold a
*soft-sleep Amber* at Green (or "Green with a note"), without touching the Red
floor. Concretely, add a recovery-override branch: when sleep is in the soft band
(≈60–73) **and** HRV is not below baseline and its status is balanced/optimal
**and** RHR is at/below Mark's personal baseline **and** readiness is not Low
**and** subjective ≥ 5 → do not down-rank on sleep alone. Keep Red hard
(sleep < 60, or HRV low+unbalanced) unchanged. Optionally move from a hard gate
to a **composite recovery read** where sleep is one weighted input, not a veto.
Guard rails: Red-never-VO2 (`executable_coaching.blocks_red_vo2`) stays; the
change can only ever *keep or raise* a verdict that recovery justifies, never
harden it beyond today's behaviour.

**Risk:** medium (changes the core safety verdict). **Effort:** backend, focused.

#### A2. "Recovery is eroding" citing readiness "slipping at 76" — no baseline context
**Root cause — `apps/api/src/services/reviews.py`.** `RecoveryRollup.trend` is
`_half_trend(days, "readiness_score")` (`reviews.py:251`), which flags
"decreasing" on any second-half drop > **5%** — an 80→76 dip qualifies. The
packet then carries only the raw mean + a direction word
(`reviews.py:951` `rollup_packet`), with **no personal baseline band**, so the
LLM judges 76 against a generic scale and any noise-level dip as "eroding".

**Fix (low risk):**
1. Feed the review/trend packet Mark's **personal baseline bands** for
   readiness/HRV/RHR from the `MetricBaseline` rows already computed
   (`services/metric_baselines.py`), so the narrative can say "76 — within your
   normal range" instead of "eroding".
2. Tighten `_half_trend`: require *both* a % change **and** a minimum absolute
   delta (e.g. readiness ≥ ~3–4 points) before calling a trend, so noise isn't a
   trend.
3. Prompt both narrative boundaries (reviews `SYSTEM_PROMPT` and trends
   `TREND_SYSTEM_PROMPT`) to interpret movement **against the baseline band**,
   not the absolute number, and to avoid alarming verbs for within-band moves.

#### A3. Recommends a midweek recovery day — doesn't know Mon & Fri are rest days
**Root cause:** there is no structured weekly-training-pattern the engine reads.
The only trace is a stray string in `services/coaching_state.py:129` ("Monday
recovery or mobility strength"); nothing first-class carries "rest days = Mon,
Fri". If `planned_workouts` is empty (see B2) the coach has *no* schedule at all,
so a generic "add a recovery day" recommendation has nothing to check against.

**Fix (low risk, needs Mark to confirm his pattern):** add Mark's fixed weekly
shape (rest days Mon & Fri, long-ride day, etc.) as a structured KB section
(e.g. `training_schedule`), thread it into the review packet, the block generator
(`services/block_generator.py`) and any recovery-day recommendation path, and
prompt the narrative to respect existing rest days. Ties to B2 — his real plan
must also be loaded.

### Theme B — Data truth (missing/zero narrated as fact)

#### B1. Monthly report wrong; last-year comparison missing / "not calculating"
**Two distinct causes:**
- **Year-on-year is genuinely empty, and that's expected — but presented
  confusingly.** `services/trends.py:71` `RELIABILITY_START_DATE = 2026-06-11`
  and history only starts ~24 Mar 2026; YoY needs `MIN_YOY_SAMPLES = 5`
  (`trends.py:75`) in *both* windows, so last-year is `insufficient_history`
  until ~Mar 2027. This is correct behaviour, not a calculation bug — but the
  narrative/UI should say so plainly rather than looking "wrong".
- **The monthly review averages over whatever days are present.** If the Garmin
  history in `daily_metrics`/`sleep` has gaps or isn't backfilled deep enough,
  the month reads wrong. `garmin_history_backfill.py` exists but we need to
  confirm the actual loaded date range.

**Fix (diagnosis-first):**
1. **Diagnose real DB coverage** — a per-metric, per-month coverage report over
   `daily_metrics`/`sleep`/`activities` to see exactly what's loaded.
2. Run/extend the Garmin history backfill for any missing range (especially
   prior year, if Garmin holds it).
3. Make the packet + UI carry an explicit **coverage / sample count** and have
   the narrative say "insufficient data for this window" instead of computing a
   misleading average. (The reviews packet already has `sleep.nights` /
   `recovery.days`; the prompt and Trends UI need to *use* them to suppress
   low-n claims.)

#### B2. "Strength training has stopped" / "Zero planned sessions captured"
**Root cause:** both are truthful reads of empty inputs, narrated as events.
- Strength: `strengthBrief.trend == "stopped"` when no recent strength activity
  is classified/synced (`services/strength_brief.py`, surfaced via
  `reviews._strength_packet`). If his strength work isn't coming through Garmin
  as gradable strength, the brief says stopped.
- Planned sessions: `adherence.plannedCount == 0` when there are no active
  `PlannedWorkout` rows in the period (`reviews.py:795` `_planned_count`) — i.e.
  no plan loaded.

**Fix:**
1. Verify strength-activity classification/sync
   (`services/workout_categories.py`, `post_strength_analysis.py`).
2. Ensure his plan is imported into `planned_workouts` (shared with A3).
3. Packet + prompt: carry a flag distinguishing **"0 because none
   planned/tracked"** from **"0 because he stopped"**, and instruct the
   narrative never to assert "stopped/zero sessions" when the source is absent —
   say "no plan loaded" / "not tracked" instead.

### Theme C — Missing feedback loop

#### C1. No visible post-workout feedback; not fed into the next day
**Root cause:** per-session analyses *are* generated
(`services/post_workout_analysis.py`, pushed in Batch 45, carried on
`postWorkoutAnalyses`) — but:
- **Visibility:** they may be collapsed / not obvious on Home. Verify on screen
  that Mark is actually seeing them (this may be surfacing, not engine, work).
- **Feed-forward:** `_morning_verdict` does **not** take yesterday's *completed*
  session, its Training Effect / interval grade / load, or its post-workout
  analysis as an explicit input to today's ease decision. Garmin readiness bakes
  in load implicitly and the packet carries `acuteChronicLoadRatio`
  (`morning_analysis.py:500` `_training_and_activity_fields`), but there's no
  explicit "yesterday's hard session → ease today" rationale.

**Fix:** add an explicit **yesterday's-load** input to the morning packet and
verdict reasoning — read yesterday's completed activity + its execution grade +
its post-workout analysis, and surface a "yesterday's session took a toll →
today eased" line in the verdict/eased-ride rationale. Coordinate with A1 (same
verdict inputs).

**Risk:** medium (touches verdict inputs). **Effort:** backend, moderate.

### Theme D — Surfacing & features

#### D1. Sleep components vs age-average table (Duration, Deep, Light, REM, Awake, restless)
**Root cause:** `services/age_norms.py` covers VO₂max, RHR and HRV only
(`age_norms.py:77` `_NORMS`) — **no sleep-stage norms.** The data exists: the
`Sleep` model already stores `deep_sleep_sec`, `light_sleep_sec`, `rem_sleep_sec`,
`awake_sleep_sec`, `unmeasurable_sleep_sec`, `duration_sec`, `score`
(`models/coaching.py`). The age-comparison surface is already wired
(`morning_analysis.py:751` → `build_age_comparison` → daily-loop →
`components/MetricComparisonTable.tsx`).

**Fix (clean, additive, low risk):** add sleep-stage age-norm tables to
`age_norms.py` (deep %, light %, REM %, awake %, total duration by age band —
well-documented population norms), extend `build_age_comparison` (or a sibling
`build_sleep_stage_comparison`) to emit sleep rows, thread through the sleep
packet, and render a sleep-stage comparison table on the Sleep page. "Restless
moments" from `raw_payload` if present. This is exactly the table Mark asked for.

#### D2. General actionable suggestions (e.g. chronically low REM → do X)
**Root cause:** the coach surfaces a verdict + tonight's projection but no
**pattern-based suggestions** for chronic issues. `services/insights.py` already
computes *his* strongest sleep/recovery drivers (Pearson movers) but nothing
turns "REM chronically low" into concrete actions.

**Fix:** a deterministic pattern-detector (metric chronically below age-norm /
personal baseline over N weeks — REM, deep, duration) that emits a small set of
grounded, KB-backed **actions**, prioritised by `insights.drivers` so the advice
targets what actually moves *his* sleep. Surface on Sleep/Home. Could be its own
batch.

#### D3. Trend words without the from→to number
**Root cause:** overlaps A2 — the **narrative** prose ("Recovery is eroding")
lacks numbers. Note the deterministic Trends *page* already shows
`priorMean → currentMean` + delta (`apps/web/src/pages/TrendsPage.tsx:211`) and
per-window means, so the gap is the LLM prose and the Reviews rendering.

**Fix:** prompt both narrative boundaries to **always cite from→to numbers** for
any trend claim (folds into A2). Optionally render a deterministic "from X to Y"
line beside any narrative trend word.

---

## Proposed sequencing

Each batch carries the build model from the tier map (DECISIONS #19): 🔴 High →
**Opus** (Claude) / **GPT-5.5** (Codex) for verdict logic / analysis-engine
prompts / debugging; 🟢 Mid → **Sonnet** / **GPT-5.4** for well-specified
CRUD/component/test work. Batch numbers 56–59 are proposed; the real number +
decision are assigned at `/batch-start` (like #122–#125 were). Step 0 is
diagnosis, not a shipping batch.

| Batch | Scope | Covers | Tier · Model (Claude / Codex) |
|---|---|---|---|
| **Step 0 — Diagnosis** (on-screen with Craig; check vs Mark) | No code. Run `scripts/diagnose_coaching_data.sql` against prod: history depth per source + per month, is a plan in `planned_workouts`?, activity-type mix (is strength classified?), rest-day day-of-week pattern, do personal baselines exist?, verdict distribution + the "Amber-on-sleep-despite-good-HRV" rows, and the analysis inventory. Capture Mark's real weekly schedule + confirm the wrong outputs against live data. | de-risks A3, B1, B2, C1 | 🔴 High · **Opus / GPT-5.5** — investigation/debugging, not a shipping batch |
| **Batch 56 — Verdict calibration & personal baselines** | Recovery-override for soft-sleep Amber (A1); personal-baseline bands into the packet + tighter trend threshold (A2); yesterday's-load feed-forward (C1); respect fixed rest days (A3). | A1, A2, A3, C1 | 🔴 High · **Opus / GPT-5.5** — verdict logic + analysis-engine prompts; **safety-gated, decision #129** |
| **Batch 57 — Data truth in reviews/trends** | Coverage/sample-count honesty + history backfill (B1); absent-vs-zero flag + prompt so "stopped/zero" isn't asserted from missing data (B2); from→to numbers in narrative (D3). | B1, B2, D3 | 🔴 High · **Opus / GPT-5.5** — shipped via PR #79 / squash `4e0497a`; no speculative prod backfill was needed |
| **Batch 58 — Sleep-stage age-comparison table** | Add sleep-stage age norms to `age_norms.py`, extend `build_age_comparison`, thread through the sleep packet, render the table (Duration/Deep/Light/REM/Awake/restless). | D1 | 🟢 Mid · **Sonnet / GPT-5.4** — well-specified CRUD/component/tests, additive |
| **Batch 59 — Chronic-pattern suggestions** | Deterministic pattern-detector (metric chronically below age-norm/baseline over N weeks) → grounded actions, prioritised by `insights.drivers`; surface on Sleep/Home. | D2 | 🔴 High · **Opus / GPT-5.5** — analysis-engine reasoning + surface |

## Decisions that need sign-off before build

1. **Loosening the sleep gate (A1).** This changes the core Green/Amber/Red
   safety verdict. The Red floor stays; the change only lets strong recovery
   signals hold a *soft-sleep Amber*. Must be agreed with Craig and sanity-checked
   against how Mark actually trains (the Claude/Copilot greenlight is the
   reference point). → Decision #129.
2. **Yesterday's-load feed-forward (C1)** shares the verdict-input surface with
   A1 — decide together.
3. **Mark's canonical weekly schedule & baselines (A3, A2)** — capture the real
   values from Mark before encoding them.

## Boundaries / non-goals

- Keep the Red-never-VO2 delivery guarantee and recovery-isolation rules intact.
- Don't fabricate prior-year trends — where history is genuinely absent, say so.
- The age-norm tables are coarse population guides, framed as such in the UI
  (same standard as the existing VO₂max/RHR/HRV comparison).
- **Build model ≠ runtime model.** The table above is the *build* model (which
  agent writes the batch, per #19). Batches 56/57/59 change the coaching
  *narrative*, whose output quality also depends on the **runtime** model the app
  calls — currently `anthropic_model = "claude-sonnet-4-6"`
  (`apps/api/src/config.py:53`), now behind Opus 4.8 / Sonnet 5. Worth a separate
  decision on whether to lift the runtime model when we touch these prompts (the
  Anthropic-API cost revisit was already pencilled for ~Sept 2026).
