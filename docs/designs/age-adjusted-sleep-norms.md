# Design: Age-adjusted sleep norms & a real age-adjusted score (Batch 61)

**Status:** Specced (this doc + ledger row), **not started**. Proposed
**Decision #135** (assigned at `/batch-start`), which revisits **#14**
(the flat "sleep +4" age adjustment) and extends **#131** (Batch 58 sleep-stage
age comparison). Origin: Mark's 2026-07-06 conversation with Craig about sleep
scores + the Copilot "age-adjusted norms" table (screenshots in
`~/Downloads/Dad Fitness`, 2026-07-06).

> Mark's framing: the "typical" values the app shows next to his sleep are the
> same as Garmin's — lab averages for a young athlete, not a 57-year-old — so
> his genuinely-normal-for-age sleep gets scored and flagged as poor.

## The complaint, and what's actually true

Mark is **half right, and the half he's right about is the important one.** There
are two different "age" surfaces in the app today and they behave very
differently:

### 1. The sleep *score* — Mark is essentially right
The "age-adjusted sleep score" is literally **Garmin's score + 4**, capped at 100:
- `apps/api/src/services/garmin_sync.py:428` — baked at sync time onto the `Sleep` row.
- `apps/api/src/services/morning_analysis.py:747` (`_age_adjusted_sleep_score`) — prefers the stored value, else `garmin_score + knowledge_base.age_adjustment.sleepScoreDelta` (default 4, `services/coaching_state.py:66`).

A flat +4 does **not** re-weight the components Garmin penalises against
young-adult targets. Garmin's own `dailySleepDTO.sleepScores` (which we already
store in `Sleep.factors_json`) exposes those targets, and they confirm the
complaint exactly. From a real sample night:

| Component | His value | Garmin "optimal" (young-adult) | Garmin qualifier |
|---|---|---|---|
| REM % | 16% | **21–31%** | FAIR |
| Deep % | 16% | 16–33% | GOOD |
| Light % | 68% | 30–64% | FAIR (dinged for *too much* light) |
| Duration | — | ideal ≈ 7.67 h | FAIR |

So Garmin marks his REM "FAIR" for missing a **21–31%** target — a young-adult
number. At 57, ~16% REM is normal. Our "+4" inherits that penalty and nudges it,
so for the **score**, the app really is using Garmin's young bar. This came from
Mark's *own* Handover rule (DECISIONS #14: "sleep +4; REM band 65–90 min") — we
didn't invent it; he's outgrown it.

### 2. The per-metric "Typical" column (Batch 58) — right data, wrong presentation
`services/age_norms.py` compares his value to a **single population average**
(≈50th percentile) for his decade band and warns whenever he's below the
midpoint (`_classify`, `age_norms.py:224`). These centres *are* literature-based
(e.g. REM 21% @ 50–59, Deep 17%), **not** copied from Garmin — but:
- A single average shown as "Typical" makes anything below the midpoint read as
  "Below average", even when it's squarely normal-for-age.
- The REM average (~21%) happens to sit near Garmin's young target because REM%
  genuinely declines only slightly with age — so it *looks* like Garmin's number
  and Mark concludes it is one.

Net: the column is honest but presents a **point** where a **healthy range** is
what a 57-year-old needs to see.

## On the Copilot table — use the direction, not the numbers

Copilot's thesis is correct (older adults: less Deep/REM %, more Light/Awake/
Restless, lower HRV — which we already encode directionally). Several specific
numbers are **not** adoptable:

- **REM 12–17% — too low.** The canonical meta-analysis (Ohayon et al. 2004,
  *Sleep* — which underlies the NSRR/SHHS/MESA-type datasets Copilot cited) has
  REM% declining ~0.6%/decade → high-teens/low-20s at 57. Our ~20% is closer to
  the evidence. Copilot likely conflated REM *minutes* (which fall partly because
  total sleep falls) with REM *%*.
- **Deep 20–30% — too high** for 57 (SWS declines the most with age; mid-to-high
  teens is typical). Adopting it would make his genuinely-excellent deep sleep
  look merely average.
- **Restless 40–70, Awake 35–55 min** — Garmin-proprietary metrics with no clean
  population norm; 40–70 restless reads like *his own* data, not a norm.
- **HR/HRV rows where the "57 norm" sits *below* Garmin's** (resting HR 45–55 vs
  55–65) — backwards for population aging; those are athlete-Mark's values, not a
  57-year-old norm.

Decision: keep our literature-anchored centres, express them as **healthy age
bands**, and cite Ohayon 2004 as the anchor.

## What we build

Four pieces, one batch. The unifying idea: **replace point-comparisons and the
flat +4 with age-band comparisons**, computed in one pure module so every
surface (morning verdict, Sleep page, chronic patterns, reviews) agrees.

### 61.1 — Healthy age bands replace single averages (`services/age_norms.py`)
Turn each `_Norm.averages` point into a `(low, high)` **healthy band** per sex ×
decade. Proposed male 50–59 bands (% of measured sleep), to finalise with source
citations at `/batch-start`:

| Metric | Proposed 50–59 healthy band | Centre | Garmin young target (for contrast) |
|---|---|---|---|
| REM % | 15–23% | ~19 | 21–31% |
| Deep % | 12–20% | ~16 | 16–33% |
| Light % | 48–62% | ~55 | 30–64% |
| Awake % | ≤12% | ~8 | (awakeCount-based) |
| Duration | 6.5–8.0 h | ~7.1 | ≈7.67 h |
| Restless | **keep descriptive only** | — | — |

Classification (`_classify`) becomes band-aware: **neutral/good anywhere inside
the band**, warn only when meaningfully outside it (with a small tolerance so an
edge value isn't a fail). **Restless** drops out of the *warn* logic — it's a
Garmin-proprietary count with no defensible population band (same caution as
#132's "Light is not suggestion-driving"); it stays shown against his personal
baseline, not an age norm.

The general-fitness rows (VO₂max, resting HR, HRV) keep their existing average +
direction-aware classification — those population averages are well-sourced and
already read correctly; they're out of scope for the band change unless a source
review at `/batch-start` says otherwise.

### 61.2 — A real age-adjusted score (`services/sleep_scoring.py`, new pure module)
Replace the flat +4 with a component re-qualification against age bands, using
Garmin's **own** exposed sub-score structure (`factors_json.sleepScores`):

1. For each age-sensitive component (REM%, Deep%, Light%, Awake), re-derive its
   qualifier against the **age band** instead of Garmin's young target.
2. Map qualifiers → points with a documented, transparent table and recombine
   into an overall, **calibrated so a night that is "optimal" on Garmin's own
   bands reproduces a Garmin-equivalent score** (calibration guard — we're not
   inventing a new scale, we're swapping the target bands).
3. **Downgrade guard:** the age-adjusted score can only ever be ≥ Garmin's raw
   score, never below it (consistent with #14's intent and the current +4
   direction). It eases where age-appropriateness was the penalty; it never
   hardens a night.

Computed at analysis time from stored inputs (stage seconds + `factors_json` +
profile age/sex) — **no migration, no re-sync.** `morning_analysis`,
`sleep_history`, `reviews`, and `chronic_patterns` all call the one function, so
the score is consistent everywhere. The `Sleep.age_adjusted_score` column keeps
being written for history but is no longer the source of truth (the pure function
is); `garmin_sync.py:428`'s inline `+4` is removed in favour of the module.

### 61.3 — UI: rename + a three-way contrast (`SleepStageAgeTable.tsx`, `MetricComparisonTable.tsx`)
- Rename the **"Typical"** column → **"Healthy range (50–59)"** and show the band
  (e.g. `15–23%`), not a single number.
- Add an optional, quiet **"Garmin target"** contrast (behind the existing
  evidence disclosure or as a footnote) so the divergence is explicit:
  *REM — You 16% · Healthy 50–59: 15–23% ✓ · Garmin's target 21–31% (young adult)*.
  That one row is the entire argument, shown honestly. Keep the calm-premium
  restraint from Batch 55 — contrast is opt-in, not a third always-on column on
  the compact Home table.
- Keep the "rough guide, not medical advice" footnote.

### 61.4 — Wiring & prompt
`age_adjusted_sleep_score` already threads into the morning packet and the
verdict ladder; no new payload field is required for the score. The Zod schema
picks up the widened age-comparison rows (band low/high). The morning-analysis
prompt gains one line so the LLM narrates against the age band, not Garmin's
qualifier ("REM 16% is within the healthy 50–59 range; Garmin flags it only
against a young-adult target").

## System interactions & safety (the real risk surface)

The verdict ladder gates on the age-adjusted score
(`morning_analysis.py:1076`–`1091`): **`<60` → Red, `<74` → Amber** (unless the
#133 soft-sleep override eases to Green), and `≥74` feeds `recovery_signals_good`.
A real recompute will **raise** the score on age-normal-but-Garmin-penalised
nights, so more soft Ambers legitimately ease toward Green — which is the point,
but it must not green-light genuinely bad nights. Guardrails:

- **Downgrade guard** (61.2) means the score can only rise, never fall — no night
  gets *harder* than today.
- The **Red floor**, **downgrade-only** soft-sleep override, categorical Garmin
  Low/Poor guard, and **Red-never-VO2** (DECISIONS #129, #133) are all unchanged.
- **Re-verify against Mark's real nights** the way #133 was validated: recompute
  across his stored history via `railway run` (real services, no faked rows),
  confirm the verdict distribution shifts sensibly, and confirm the **genuine
  POOR nights still gate** (the 17/85 ≤16-readiness nights flagged open in
  STATUS) — i.e. the recompute must not rescue a night that is bad on every
  signal, only one that is bad *only* on young-adult stage targets.
- Bump `PROMPT_VERSION` and force-regenerate the current morning verdict +
  baselines so the live surface reflects the new score (same closeout step #133
  used).

## Boundaries

- **No migration.** Score is recomputed from already-stored inputs; the existing
  `age_adjusted_score` column is retained (written for history, not authoritative).
- **No new endpoint.** Everything rides the existing `/api/v1/daily-loop` +
  morning packet.
- **Forward-only.** Like Batch 60, no historical backfill is required for
  behaviour — the verdict and Sleep page recompute live; reviews/trends pick up
  the new score as new days land (a one-off history regen is an optional closeout
  step, not a migration).
- General-fitness rows (VO₂max/RHR/HRV) unchanged unless a source review says
  otherwise. Restless is demoted to descriptive-only.

## Verification plan

- **Backend:** extend `test_age_norms.py` for band classification (in-band =
  neutral/good, outside = warn, edge tolerance); new `test_sleep_scoring.py` for
  the recompute (calibration guard: all-optimal ≈ Garmin; downgrade guard: never
  below raw; REM-penalised night rises; a genuinely-bad night does **not**);
  update `test_morning_analysis.py` verdict cases for the new score feeding the
  ladder; `test_chronic_patterns.py` / reviews inherit the central function.
- **Shared:** `schemas.test.ts` for the widened age-comparison rows (band).
- **Web:** `SleepStageAgeTable.test.tsx` / `MetricComparisonTable.test.tsx` for
  the band render, the rename, and the opt-in Garmin-target contrast.
- **Gates:** backend ruff/format/mypy, full pytest; shared vitest + typecheck;
  web vitest + tsc + lint + build under Node 20.
- **Live safety check:** the real-night recompute/regeneration described above
  before `/closeout`, plus a headless Sleep-page walk-through of the new table.

## Open calls to settle at `/batch-start`

1. **Final band numbers + citations** — lock the 50–59 (and other decade) bands
   against Ohayon 2004 + one or two corroborating sources; confirm the Garmin
   young-target contrast values come from `sleepScores` optimal ranges.
2. **Score method** — confirm the qualifier→points calibration approach vs a
   simpler "credit per age-band qualifier upgrade, capped" (both honour the two
   guards; the calibrated rebuild is more faithful, the credit model is simpler
   and easier to explain to Mark).
3. **Garmin-target contrast** — in for the Sleep-page deep table (recommended) or
   omit to keep the surface minimal.
4. **History regen** — run the one-off recompute over stored nights at closeout
   (recommended, mirrors #133) or let it roll forward only.
