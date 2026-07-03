# Design: Block-to-block progression (Batch 47)

**Status:** Specced, not started. Backend + frontend, no LLM, no migration.
Decision assigned at `/batch-start`.
Builds the **second feedback coupling** Mark named — "use the stats from each
completed [multi-week] block to propose the next block" — the per-block mirror of
the daily sleep→training coupling.

## Problem

The block generator programs the next block from a **static** starting point.
`block_generator.generate_block_plan` builds a 13-week 2121 block deterministically
from `profile` + a fixed FTP (`DEFAULT_FTP_WATTS = 280` / the profile FTP) and the
shared `coaching_state` templates. It **never reads how the last block actually
went** — no adherence, no achieved-vs-planned load, no interval-execution grade,
no FTP-drift verdict. Its own consolidation week is even described in
`_BLOCK_FOCUS` as "Stabilize gains and **set up the next cycle**" — but nothing
reads the completed cycle to do so.

The signals to close this are all already shipped as **isolated read-only
surfaces**:

- **Batch 17** `insights` FTP-drift (rising / falling / stable + evidence window).
- **Batch 20** `reviews.compute_review_rollup` (load, adherence, verdict trend,
  by-type volume over a window).
- **Batch 44** `ride_intervals` per-work-interval execution grades (`on` / `over`
  / `under` vs %FTP target).
- **Adherence** from `manual_entries` (did he do it; what changed).

They just aren't wired into programming the next block.

## Builds on / reuses

- **`block_generator`** — `generate_block_plan` and the refine-then-lock workflow
  (`generate` / `refine` / `lock`; `knowledge_base` `section='generated_block'`;
  `generate` refuses to clobber an unlocked draft, #69). Unchanged as the
  **human-gated authoring surface** — this batch changes only what *seeds* the
  draft.
- **Batches 17 / 20 / 44 + `manual_entries` adherence** — the outcome signals,
  reused as-is. No new statistics engine.

## What the change adds

**Backend**

- **`services/block_progression.py`** — a pure, DB-free core:
  - Aggregate the **completed** block's stats into a `BlockOutcome` —
    achieved-vs-planned load, adherence rate, an execution-grade summary (were the
    work intervals actually hit, from Batch 44?), the FTP-drift verdict (Batch
    17), and the recovery / morning-verdict trend (Batch 20).
  - Map `BlockOutcome` → a **next-block proposal**: a recommended **FTP** (bump on
    sustained over-target execution + rising drift; hold or cut on under-target +
    falling drift), a **focus carry-forward** (e.g. repeat a build emphasis if VO2
    execution lagged), and a **structural nudge** (e.g. an extra recovery week if
    the trend degraded). **Recommendation only**, with its evidence attached.
- **Seed the generator from the proposal** — when generating the next block,
  `generate_block_plan` takes the proposed FTP + focus as its starting point
  instead of the static default, surfaced in the `/builder` draft as, e.g.,
  "proposed from your last block: FTP 280 → 290 — you held +4% over target on 5/6
  VO2 blocks and drift is rising." The athlete still **refines-then-locks**;
  nothing auto-applies (#16 / #69).
- **Block-boundary trigger** — at consolidation week / block end, surface a
  "ready to plan your next block" prompt on Home (optionally pushed via Batch 45).

**Shared / Frontend**

- `/builder` shows the proposed FTP + focus with its evidence, editable before
  lock. Optional Zod field for the proposal on the block-generator payload.

## Boundaries (kept)

- **Recommendation only** — the refine-then-lock workflow stays the single path
  that mutates `plan_blocks` / `planned_workouts`; the proposal is a *seed*, never
  an auto-applied change (#16 / #69). No silent FTP change.
- **Deterministic, no LLM** — like Batches 14 / 16 / 17, the progression maths are
  inspectable, unit-tested invariants (no `ANTHROPIC_API_KEY` needed).
- **Reuses existing engines** — no new stats engine, no new ingestion.
- **No migration** — the proposal lives in the existing `generated_block` KB draft
  and/or an `analyses` audit row (`block_progression`).
- **Graceful degradation** — before a full block of history exists, falls back to
  the static default FTP / template.

## Tests

- Pure `BlockOutcome` aggregation over fixtures: over-target + rising drift → FTP
  bump; under-target + falling drift → hold / cut; degraded trend → extra
  recovery.
- The generator seeds FTP + focus from the proposal (not the static default).
- The **never-auto-apply** guard: generating from a proposal still produces a
  *draft* that must be locked, and still refuses to clobber an unlocked draft
  (#69).
- Insufficient block history → falls back to the static default.
