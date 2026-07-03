# Batch 52 — Design foundations (token + primitive tier)

Status: Specced, not started. Frontend-only, no migration.
Decision assigned at `/batch-start` (next free **#122**).
Tier: 🔴 High (a system-wide visual-foundation change — every screen inherits the
new surface/elevation ramp and control tier; needs design judgment to set the new
scale and hold WCAG AA across both palettes).

First of the four 2026-07-03 front-end premium batches. Overview + rationale:
`docs/designs/frontend-premium-review.md`. This one rebuilds the **foundation**
so B/C/D inherit a premium base; it changes tokens + primitives, not screen logic.

## Goal

Lift the shipped design system from "developer-dark" to **calm premium** at the
token + primitive layer: widen the dark surface value ramp so cards separate,
give real (restrained) elevation, redesign the input/control tier so forms are
legible, and pull the mono-uppercase treatment back to eyebrows only. No
per-screen layout change.

## Why (the problem)

From the live walk-through (`frontend-premium-review.md`, P0-1/P0-2/P1-6):

- **Surfaces are too close in value.** `--bg #0A1112 → --surface #111E1F →
  --surface-elevated #192A2B → --surface-overlay #213436 → --border #253A3C` all
  sit in one narrow near-black band. On Home the six collapsed sections read as a
  flat monotone wall and cards float on hairline borders with `shadow-sm` only —
  the single biggest reason the app doesn't feel premium. The **light** palette
  already separates well, so the dark ramp is the weak link.
- **Inputs are dark-on-dark.** `Input`/textarea use `bg-bg` (identical to the page
  background) with a `#253A3C` border and `#7B859B` placeholder; on Check-in the
  fields nearly vanish and placeholders are hard to read — a real accessibility
  problem for an older daily user.
- **Mono-uppercase is overused.** `font-mono uppercase tracking-[0.25em]` is used
  for date eyebrows, "NEXT", More headings **and** form-field labels ("OVERALL
  (0–10)"), which reads techy rather than calm and hurts label legibility.

## Product shape

- **Surface & border ramp.** Re-space the dark tiers so `bg → surface →
  elevated → overlay` have clear, deliberate steps (and borders that read against
  each), keeping the light palette's separation. Cards, hero, and sheets sit on
  visibly distinct surfaces. Depth is carried by **value first**, a refined shadow
  second (streaming/premium: subtle, not heavy black drop-shadows).
- **Elevation model.** A small, consistent elevation scale applied through `Card`
  and the hero/sheet primitives — restrained (calm), not glossy.
- **Input / control tier.** Inputs get their own elevated fill (not the page bg), a
  stronger idle border, a clear focus ring (reuse `shadow-glow`), and
  higher-contrast placeholder + label. Applied to `Input`, the shared
  `textareaClassName`, `Select`, and the `outline`/`ghost` button contrast.
- **Label / type system.** Reserve the mono-eyebrow treatment for kickers, the
  wordmark, and numerics; `Label` becomes sentence-case at a legible size/contrast.
  Establish a documented type scale (display / title / body / label / caption).

## Frontend

- `src/index.css` — both palettes: re-space `--surface-*` / `--border*`; refine the
  shadow tokens; add any new control-fill / label vars. Keep the pre-mount theme
  script + AA notes intact.
- `src/theme/tokens.ts` — mirror the new values (single source of truth for JS
  consumers: sonner, framer-motion, recharts hex).
- `tailwind.config.ts` — expose any new tokens (e.g. a control-fill colour) as
  utilities.
- `src/components/ui/input.tsx`, `src/components/ui/label.tsx`,
  `src/components/ui/select.tsx`, `src/components/ui/card.tsx`,
  `src/components/ui/button.tsx` — adopt the new fills/borders/elevation.
- The two inline `textareaClassName` copies (`pages/DashboardPage.tsx`,
  `pages/CheckInPage.tsx`) — factor to the shared input style so textareas match.

## Backend

None. Token + primitive only. No endpoint, payload, or migration change.

## Sequencing / dependencies

First of the four. B (branded verdict/hero/login), C (Home hierarchy), and D
(screen polish) all build on this. No dependency on prior unshipped work.

## Decisions to record at `/batch-start`

- The new dark **surface value steps** + the elevation/shadow model (how much
  depth is "calm premium" vs glossy).
- The **input fill** approach (elevated fill + focus ring) and the placeholder/
  label contrast floor (hold **WCAG AA** in both palettes, as the current
  on-primary/on-accent notes already do).
- Where **mono-uppercase** is allowed (eyebrow/kicker/numeric/wordmark) vs
  sentence-case (all form labels).

## Verification (planned)

- The existing web vitest suite still passes (token-level change); update only the
  handful of assertions that pin a removed utility class.
- A contrast spot-check on inputs, labels, and placeholders (AA) in dark + light.
- `tsc --noEmit` clean; web lint 0 new errors; web build clean under Node 20; the
  backend suite is untouched (only `apps/web/**` + tokens change).
- Visual confirm in a headless preview (mock `/api`, as used for the review):
  Home, Check-in, and Sleep at mobile width, dark + light.

## Deferred / non-goals

- No per-screen layout or copy change — that is Batches 54 (Home) and 55 (screens).
- No brand mark / verdict redesign — that is Batch 53.
- No new component library; this re-skins the existing primitives in place.
