# Design: Explicit daily/block loop model (Batch 48)

**Status:** Specced, not started. **Optional / consolidating refactor** — Batches
45–47 ship without it; sequenced last. Behaviour-preserving, no migration.
Decision assigned at `/batch-start`.
The highest-altitude tweak from the 2026-07-03 reassessment: make "the loop" a
first-class object so the passive-first work stops being hand-wired.

## Problem

The loop is **implicit**. The app is ~44 excellent batch-features, but "the daily
loop" and "the block loop" aren't modelled anywhere — they're spread across
scheduler jobs, `homeSections`, and services. Two concrete symptoms:

- **`useDailyPhase` is cycling-and-morning shaped** — `pre_ride | post_ride |
  rest_day`, and `post_ride` is keyed off **ride** analyses only
  (`postWorkoutAnalyses`). A strength-only, walk-only, flexibility-only, or
  breathwork-only day never advances the day's phase — those reads render as
  collapsed cards but Home's *phase* stays `pre_ride`/`rest_day`. And there is
  **no evening / wind-down phase**: evening is only a clock nudge (`EVENING_HOUR
  = 20` in `homeSections.ts`) that reorders sections, not a first-class state.
- **No orchestrator** knows "where is Mark in his day/block, and what's the next
  thing to push/surface" — which is *why* Batch 45's pushes are each hand-wired at
  a scheduler completion point, and why Batch 46's projection and Batch 47's
  block trigger each have to re-derive state.

## Builds on / reuses

- **`useDailyPhase` + `homeSections`** — the existing phase / ordering surface,
  **generalised**, not replaced.
- **The scheduler jobs + the Batch 45 push points + Batch 47's block boundary** —
  re-expressed as transitions of one explicit loop state.

## What the change adds

**Backend + shared**

- **A single loop-state model** (`services/daily_loop_state.py`, mirrored in a
  generalised `useDailyPhase`):
  - The **day** advances morning → (any) training → post-training → evening
    wind-down → night. Generalise `post_ride` → **`post_training`** off *any* of
    the `post_*` analyses (ride / strength / flexibility / walk), and add a
    first-class **`wind_down`** evening phase (not just a clock reorder).
  - The **block** advances build / recovery / … / consolidation → next block
    (the Batch 47 boundary becomes an explicit block-phase transition).
- **An orchestration seam** — one function that answers "where is Mark in his
  day/block, and what is the next thing to push / surface", which Batches 45 / 46
  / 47 **consume** instead of each re-deriving state.

**Frontend**

- `homeSections` primary-selection reads the **generalised** phase: a
  strength-only day leads with its post-session read; the evening floats to a real
  `wind_down` phase rather than a 20:00 hack. The existing per-state Home renders
  are preserved.

## Boundaries (kept)

- **Behaviour-preserving refactor + generalisation** — **no new coaching logic**;
  the verdict, fan, and analysis engines are untouched.
- **Deferrable** — 45–47 ship without it. This pays down the wiring cost *once
  piecemeal orchestration starts to hurt*; sequenced last. If 45–47 land cleanly
  and the wiring stays cheap, this can stay on the shelf.
- **No migration.**

## Tests

- Phase derivation across **all** modalities: ride / strength / walk / flexibility
  / breathwork-only days each advance to `post_training` (not stuck `pre_ride`),
  plus rest and the evening `wind_down` phase.
- Block-phase transitions (build → recovery → consolidation → next block).
- Home primary-section selection reads the generalised phase, with the existing
  per-state renders preserved (no visual regression).
- The orchestration seam returns the right "next thing" per state, exercised by
  the Batch 45 push tests.
