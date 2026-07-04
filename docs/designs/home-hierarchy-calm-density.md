# Batch 54 — Home hierarchy & calm density

Status: Shipped in PR #75 / squash `8fb90a2` (2026-07-04). Frontend-only, no migration.
Decision recorded in **#124**.
Tier: 🟢 Mid (a well-specified recomposition of the shipped Home render — reuses
the Batch 37 collapse model, the Batch 50 action override, and the Batch 51
two-lane desktop; the judgment is in how the secondary sections recede).

Third of the four 2026-07-03 front-end premium batches. Overview + rationale:
`docs/designs/frontend-premium-review.md`.

## Goal

Turn Home from a wall of equal accordions into a **curated brief** with a clear
reading order — verdict → next action → today — while the rest of the context
recedes, the primary card's button cluster collapses to one primary + overflow,
the first screen tightens, summaries truncate on word boundaries, and section
expand gets a subtle animation.

## Why (the problem)

From the live walk-through (`frontend-premium-review.md`, P1-3/P1-5/P2-1/P2-3/P2-4):

- **Home is a wall of equal accordions.** The six collapsed sections are
  near-identical cards (green icon + bold title + muted one-liner + chevron),
  distinguished only by a small dot when action is pending. Nothing separates
  retrospective (Last night) from prospective (Tonight), or important from ambient.
- **The primary card's buttons are too dense.** The pending-change state shows
  **five** buttons (Approve & upload, Ignore, Manual edit, Swap day, Skip) wrapping
  on one card.
- **The greeting eats the first screen** — "Good evening, Mark" at `text-3xl` sits
  above the verdict, pushing the day's answer down.
- **Summaries truncate mid-word** ("REM in your 65–90 …", "keep it conv…").
- **Section expand is instant** — the card pops open with no animation.

## Product shape

- **Reading order & recede.** Keep collapse-not-remove (Batch 37) + the action
  override (Batch 50) + the desktop two-lane (Batch 51). Visually **de-emphasise the
  secondary/context sections** — lighter titles, quieter cards — and group them
  under a subtle "More detail" divider so the eye lands on verdict → action band →
  Today. The primary/expanded section stays prominent.
- **Button overflow.** On the primary session card, keep **one primary** (Approve &
  upload, or Edit when no pending change) + **one secondary**, and move the rest
  (Manual edit, Swap day, Skip, Ignore) into a "More options" overflow (reuse the
  existing `dropdown-menu` or a disclosure). Restraint = one primary per card.
- **Compact first screen.** Fold the greeting + date into a smaller lockup (or into
  the top bar / verdict eyebrow) so the verdict sits higher on cold load.
- **Word-boundary truncation.** Truncate section summaries on word boundaries (a
  small helper) instead of mid-word ellipsis.
- **Expand motion.** Animate `CollapsibleSection` open/close (height + opacity) with
  the existing motion tokens, honouring `prefers-reduced-motion`.

## Frontend

- `src/pages/DashboardPage.tsx` — the greeting/header lockup; `WorkoutRow` action
  cluster → one primary + secondary + a "More options" overflow.
- `src/components/CollapsibleSection.tsx` — a quieter "secondary" visual variant for
  context sections; the expand/collapse animation.
- `src/lib/homeSections.ts` — any grouping/order needed for the "More detail"
  divider (keep the one-expanded model + evening float + lanes intact).
- A small truncation helper in `src/lib/` for word-boundary summaries.

## Backend

None. Presentation/interaction only; every signal already rides
`/api/v1/daily-loop`. No new endpoint, payload, or migration.

## Sequencing / dependencies

After **Batch 52** (inherits surfaces/type) and best after **Batch 53** (the
verdict hero + action band anchor the new top-of-Home). Independent of 55.

## Decisions to record at `/batch-start`

- **How the secondary sections recede** — a "More detail" grouping/divider vs
  weight-only de-emphasis (keep them present, per collapse-not-remove).
- **Which actions stay visible vs overflow** on the session card (proposed: Approve
  + one secondary visible; Manual edit / Swap / Skip / Ignore in overflow).
- **Where the greeting goes** — a compact lockup above the verdict vs merged into
  the verdict eyebrow / top bar.
- Preserve the **one-expanded** model (need first, time second) and the Batch 51
  desktop lanes unchanged.

## Verification (planned)

- `DashboardPage.test` — the overflow exposes Manual edit / Swap / Skip / Ignore;
  the primary action stays visible; all sections still render with the correct
  expanded/collapsed state; the verdict renders once; offline still renders.
- `homeSections.test` — ordering, evening float, lanes, and the action override are
  preserved after any grouping change.
- Reduced-motion honoured (no forced animation).
- `tsc --noEmit` clean; web lint 0 new errors; web build clean under Node 20;
  backend suite untouched. Headless-preview visual confirm at mobile + desktop.

## Deferred / non-goals

- No change to the `nextAction` resolver or the one-expanded selection logic
  (Batch 50) beyond visual weighting.
- No payload/endpoint change; no persistence of manual expand/collapse state.
- Sleep / Check-in / Week polish is Batch 55.
