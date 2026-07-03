# Batch 55 — Screen polish & states

Status: Specced, not started. Frontend-only, no migration.
Decision assigned at `/batch-start` (next free **#125**).
Tier: 🟢 Mid (applies the Batch 52 system across the remaining screens and adds
loading/empty/error states — well-specified, screen-by-screen, low reasoning).

Last of the four 2026-07-03 front-end premium batches. Overview + rationale:
`docs/designs/frontend-premium-review.md`.

## Goal

Bring Sleep, Check-in, and Week up to the premium system, and give
loading/empty/error/offline states character and a clear recovery action —
finishing the calm-premium pass so the whole app is consistent.

## Why (the problem)

From the live walk-through (`frontend-premium-review.md`, P0-2 applied fully,
P2-2, and cross-screen consistency):

- **Check-in is the worst-hit by the dark-on-dark inputs** (Batch 52 fixes the
  primitive; this applies it to the flow) — and the form is long, low-contrast,
  with mono-uppercase labels and a fragmented per-card save model.
- **Sleep** has an "vs your age" column that is mostly empty (— for most rows), a
  heavy full-width "Evidence" disclosure pill, and dense footnotes.
- **Week / other screens** nest cards several levels deep on the flat surfaces.
- **Empty/error/offline states are generic** — "couldn't load / please try again"
  cards with no character and no clear recovery action.

## Product shape

- **Check-in.** Apply the new inputs + sentence-case labels; reduce density; make
  the save model per section clear and legible. Keep the manual-entry +
  per-workout adherence data flow unchanged.
- **Sleep.** Apply the surfaces/type from Batch 52; redesign or fold the mostly-empty
  "vs your age" column in `MetricComparisonTable`; lighten the evidence disclosure
  in `SleepPrepBody`; tidy the footnotes. No data change.
- **Week.** Apply surfaces; reduce card nesting; keep the schedule + move/swap flow.
- **States.** A shared, on-brand empty/error/offline pattern (a small
  `EmptyState`/`ErrorState`) — say what happened + a clear recovery CTA (per CDS
  content voice), replacing the generic cards on Home/Sleep/Week/Check-in.

## Frontend

- `src/pages/CheckInPage.tsx` — inputs/labels/density; the shared textarea style
  from Batch 52.
- `src/pages/SleepPage.tsx`, `src/components/MetricComparisonTable.tsx`,
  `src/components/SleepPrepBody.tsx` — surfaces, the age column, evidence, footnotes.
- `src/pages/WeekAheadPage.tsx` — surfaces + nesting.
- A shared `EmptyState`/`ErrorState` component + adoption in the pages' error/empty
  branches (currently inline `Card` fallbacks).

## Backend

None. No data/endpoint/analysis-engine change; the "vs your age" and evidence
content is unchanged, only its presentation. No migration.

## Sequencing / dependencies

After **Batch 52** (primitives) and ideally after **53/54** so the whole app is
consistent. Last of the four; independently shippable per screen.

## Decisions to record at `/batch-start`

- The **"vs your age" column** treatment (fold into a per-row descriptor vs keep as
  a column) — presentation only, no metric change.
- The shared **empty/error/offline** pattern + recovery-CTA copy (CDS content
  voice: say what happened, then what to do; no "please try again").
- The **Check-in save model** (per-section save vs a clearer single flow), keeping
  the existing endpoints.

## Verification (planned)

- Page tests updated: `CheckInPage.test`, `SleepPage.test`, `WeekAheadPage.test`
  still pass with the new markup; the empty/error branches render the new component.
- `tsc --noEmit` clean; web lint 0 new errors; web build clean under Node 20;
  backend suite untouched. Headless-preview visual confirm of each screen + a
  forced error/empty state, mobile + desktop, dark + light.

## Deferred / non-goals

- No data, endpoint, or analysis-engine change; no new metrics or copy from the
  coach — presentation only.
- No nav/IA change (that was Batches 49–51).
