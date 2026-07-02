# Design: Breathwork integration (Batch 42)

**Status:** Specced, not started. Designed with Craig on 2026-07-02 from the
full-history census (Batch 40). Decision number assigned at `/batch-start` (next
free **#113**, after Batch 41's #112). Third of the 40–42 non-cycling trio.
Craig's decision (2026-07-02): a **consistency brief + a verdict lever** — track
the habit *and* let the morning verdict recommend a breathwork session — **not** a
per-session analysis.

Builds on / reuses:
- **Batch 19 strength watching-brief** (`services/strength_brief.py`) as the
  deterministic-rollup template (pure `compute_*_rollup`, read-only `*BriefService`,
  `GET /api/v1/*-brief`, daily-loop envelope) — breathwork is habit-shaped like
  strength, so the same frequency/trend rollup fits.
- **`services/morning_analysis.py`** — the verdict already emits advisory
  `plan_adjustments` strings (e.g. *"Substitute recovery, mobility, or rest."*) and
  already computes the **Red / low-readiness / unbalanced-HRV** signal. The lever
  is one more additive recommendation gated on that existing signal — it does
  **not** change the Green/Amber/Red classification.
- **The recovery-isolation invariant (#49/#80)** — breathwork is not a training
  load and never feeds the recovery/verdict math; it is only *recommended by* it.

## The grounding evidence (2026-07-02 census)

**224 breathwork activities** (`typeKey == "breathwork"`, parent 4), near-daily
since May 2025 — a well-established parasympathetic / stress-management habit. Each
is a short (≈3-min) breathing drill: **nothing to "analyse" per session**, which is
why the value is (a) the *habit* (is he keeping it up?) and (b) breathwork as a
*recovery tool the coach can prescribe*, not a workout to rate. No per-second
detail exists (excluded in #93) — summary only (duration, avg HR, respiration if
present).

## Two pieces

### 1. Breathwork consistency brief (deterministic, Batch 19 clone)

A pure `compute_breathwork_rollup(sessions, as_of)` → 4-week / 12-week frequency +
trend (session count, sessions/week, first-vs-second-half trend), mirroring
`compute_strength_rollup`. `BreathworkBriefService.brief` reads `activities` where
`typeKey == "breathwork"` (read-only), `GET /api/v1/breathwork-brief`, and a
`breathworkBrief` field on `/api/v1/daily-loop`. This tells the coach he's keeping
(or dropping) the habit.

### 2. Verdict recovery-lever (the actionable part)

On a **Red / low-readiness / unbalanced-HRV** morning, `morning_analysis` appends a
recommendation to the existing advisory `plan_adjustments` — e.g. *"Low readiness /
HRV — a breathwork session today can help down-regulate; you've done N this week."*
This turns breathwork from passively-logged data into an **active coaching lever**,
using the recovery signal the verdict **already computes**.

**Critically additive:** it adds a *suggestion string*; it does **not** change the
Green/Amber/Red classification, the metrics-vs-baselines read, or any recovery
math. This is the same class of change as the existing "substitute recovery /
mobility / rest" lines already in `morning_analysis.py` — one more option, gated on
a signal that's already there.

## The parallel — and where breathwork goes further than strength

| Concern | Strength brief (Batch 19) | Breathwork (this batch) |
|---|---|---|
| Rollup | frequency / volume / load, advisory | frequency / trend, advisory |
| Extra role | none (pure watch) | **verdict recommends it** on low-recovery mornings |
| Per-session LLM | no | no (a 3-min drill has nothing to analyse) |
| Verdict/recovery | isolated (#49/#80) | isolated — *recommended by* the verdict, never *feeds* it |

## Phases

- **42.1** Pure `compute_breathwork_rollup` + `BreathworkBriefService` +
  `GET /api/v1/breathwork-brief` + `breathworkBrief` daily-loop field + shared
  schema (Batch 19 clone).
- **42.2** Verdict lever: a pure `should_recommend_breathwork(signal)` +
  recommendation copy, appended to the morning `plan_adjustments` only on the
  Red/low-readiness/unbalanced-HRV signal; verdict classification untouched.
- **42.3** Frontend: a breathwork consistency line (reuse the brief panel pattern)
  and the recommendation rendered inline with the existing plan-adjustments.
- **42.4** Tests (below).
- **42.5** Green gates.

## Testing

- **Pure:** `compute_breathwork_rollup` frequency/trend; `should_recommend_breathwork`
  fires on Red / low-readiness / unbalanced-HRV and **not** on a Green/high-readiness
  morning; the recommendation is appended without mutating the verdict letter.
- **Isolation:** a fixture morning's Green/Amber/Red classification is identical
  with and without the lever (only `plan_adjustments` differs).
- **DB-backed:** the brief endpoint reflects synced breathwork sessions.
- Backend pytest/ruff/mypy pass; web lint/test/build pass; shared typecheck/tests.

## Non-goals / out of scope

- **No per-session LLM analysis** — a 3-min breathing drill has nothing to analyse
  (Craig, 2026-07-02).
- **No change to the Green/Amber/Red verdict classification** — the lever only adds
  a suggestion string.
- **No HRV/stress correlation engine** — "does breathwork improve next-morning HRV"
  is a natural later batch reusing the Batch 17 drivers / Batch 22 evaluator;
  explicitly deferred so this batch stays small.
- **No mobility / walking** — Batches 40 / 41.

## Open decisions to settle at `/batch-start`

1. **Lever trigger** — Red only, or Amber + low readiness, or any unbalanced-HRV
   morning? (Proposed: reuse the existing recovery-signal predicate.)
2. **Copy & placement** — exact recommendation wording and whether it sits with the
   plan-adjustments or as its own recovery-tip line.
3. **Ship shape** — brief + lever together (recommended), or brief first then lever.
4. **Count context** — include "N sessions this week" from the brief in the
   recommendation, or keep the lever independent of the rollup.

## Dependency & sequencing

- **Independent**; builds on the Batch 19 pattern and the existing morning-verdict
  recovery signal. The verdict-lever touch (analysis-engine output) is the
  reasoning-sensitive part, hence the 🔴 High tier.

## Safety / invariants preserved

- **Verdict classification untouched** — the lever is an additive suggestion only.
- **Recovery isolation (#49/#80)** — breathwork never feeds recovery/verdict math;
  it is only recommended by it.
- Deterministic, unit-testable rollup + a pure lever predicate.
