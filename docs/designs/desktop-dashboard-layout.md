# Batch 51 — Desktop two-column dashboard (optional)

Status: Specced, not started. **Optional / low-priority, deferrable** — the real
user is on a phone PWA, so this is last. Frontend-only, no migration.
Decision assigned at `/batch-start`.
Tier: 🟢 Mid.

The polish tail of the 2026-07-03 Home/nav read — a layout-only win once Batches
49 + 50 have set the content.

## Goal

Use the horizontal space on `md+` viewports: lay Home out as a two-column
dashboard instead of a single narrow column, without changing the mobile-first
phone layout or the section model.

## Why

Home renders one column inside `max-w-6xl` (`Layout.tsx` / `DashboardPage.tsx`),
so on desktop most of the width is empty. The primary user is on a phone PWA —
mobile-first is correct — so this is explicitly **optional and last**: a polish
item, not a loop gap.

## Product shape

On `md+`, split the ordered section list into two lanes — an **act** lane
(verdict, the Batch 50 Next strip, Today / After-your-ride) leading, and a
**context** lane (Last night, Tonight, Bedroom) beside it. Mobile stays the single
stacked column. The expanded/collapsed model, ordering, and the Batch 50 action
logic are all unchanged — only the container layout differs by breakpoint.

## Frontend

- `DashboardPage.tsx` (or a small layout helper): a responsive grid
  (`grid-cols-1 md:grid-cols-2`) that partitions `orderedSections` into the act vs
  context lanes using the **same** section components; the primary/expanded section
  always leads its lane.
- No change to `homeSections`, `useDailyPhase`, `homeActions`, or the section
  bodies.

## Backend

None.

## Sequencing / dependencies

Last. After **Batch 50** (so the Next strip + action logic are built once, then
laid out). Genuinely optional — skip if desktop isn't a priority.

## Decisions to record at `/batch-start`

- Whether desktop is worth the layout complexity at all (this batch may be
  dropped).
- The act/context column split — which sections go in which lane.

## Verification (planned)

- `DashboardPage.test`: at a desktop width the two-column layout renders; at
  mobile width the single stacked column is preserved; same sections + expanded
  state as Batch 50.
- Web lint + build clean; backend suite untouched.

## Deferred / non-goals

- No new content — pure layout.
- No mobile change; no backend/payload change; no migration.
