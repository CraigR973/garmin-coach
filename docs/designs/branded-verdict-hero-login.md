# Batch 53 — Branded verdict, hero & login

Status: Specced, not started. Frontend-only, no migration.
Decision assigned at `/batch-start` (next free **#123**).
Tier: 🔴 High (brand-craft judgment — the verdict is the product's heartbeat and
the login is the prime brand moment; needs taste to land "premium calm" without
overdoing it, and to place the existing mark consistently).

Second of the four 2026-07-03 front-end premium batches. Overview + rationale:
`docs/designs/frontend-premium-review.md`. Where the CheckMark identity becomes
**felt** rather than just labelled.

## Goal

Weave the identity through the app: bring the existing logomark in-product,
redesign `VerdictHero` into a crafted, branded heartbeat, elevate the login
splash, add the mark to the top bar, and turn the "Next" strip into a proper
primary action band.

## Why (the problem)

From the live walk-through (`frontend-premium-review.md`, P0-3/P1-1/P1-2/P1-4):

- **No logomark appears anywhere in the running app.** The brand is a text
  wordmark only ("CHECKMARK" mono in the top bar; "CHECK/MARK" split on login).
  A well-designed mark **already exists** — `public/brand/checkmark-icon-primary.svg`
  / `checkmark-mark.svg`: a checkmark that doubles as an ECG/heartbeat trace on a
  teal→green tile with a Green/Amber/Red verdict-gauge arc (see
  `public/brand/README.md`) — but it is used only as the PWA/favicon icon. The
  **login splash — the prime brand moment — is a wordmark floating in a void.**
- **The verdict isn't crafted.** `VerdictHero` is a faint tinted bordered box that
  on dark barely separates from the page; the single most important glance should
  be the app's most considered object.
- **The signature gradient & accent are unused.** `--wordmark-gradient` (teal→green)
  is defined but the login renders flat; the brass **accent (#C8943C)** and Steele
  silver almost never appear — the identity collapses to "green on black".
- **The "Next" strip is under-weighted** — a small left-aligned button in a big
  empty bordered box, despite being the "do this now".

## Product shape

- **Logomark in-product.** A `Logomark` (extend `components/Brand.tsx`) rendering
  the existing mark. Placed: login splash (mark-led hero), the top bar (mobile
  centre lockup + desktop left), and as the verdict's brand cue. Assets are
  generated from `generate-icons.mjs` — **do not hand-edit the SVGs**; regenerate
  if the art changes (per `public/brand/README.md`).
- **Verdict as the hero.** Redesign `VerdictHero` on the Batch 52 surfaces: real
  elevation, a branded ring (echoing the verdict-gauge arc), confident type, the
  plain-English line beneath. Keep the Green/Amber/Red semantics + the PENDING
  state and `verdictCopy`. The checkmark gradient appears here (or on the green
  state) so the brand is felt at the daily glance.
- **Login splash.** Mark-led, tighter vertical composition (less floating void),
  the wordmark gradient actually applied; keep the invite-only / PIN-fallback copy
  and flow.
- **Next-action band.** Turn `NextActionStrip` (in `DashboardPage.tsx`) into a
  full-width primary action band — a real CTA tied under the verdict, tone-aware
  (accent vs warning vs the quiet all-clear), not a faint outline box.
- **A role for the accent.** Give brass/Steele a defined secondary-emphasis role
  (e.g. the next-action band, data highlights) — held to CDS-style restraint (one
  accent per view).

## Frontend

- `src/components/Brand.tsx` (+ a `Logomark`/mark export) and the asset under
  `public/brand/`.
- `src/components/VerdictHero.tsx` — the redesign (states unchanged).
- `src/pages/LoginPage.tsx` — mark-led splash.
- `src/components/TopBar.tsx` — mark in the mobile + desktop lockups.
- `src/pages/DashboardPage.tsx` — the `NextActionStrip` → action band.
- `src/lib/copy.ts` — only if verdict/hero copy needs a touch (semantics
  unchanged).

## Backend

None. No change to the verdict **logic**, `/api/v1/daily-loop`, or any endpoint;
this is presentation only. No migration.

## Sequencing / dependencies

After **Batch 52** (inherits the surface/elevation/type tokens). Independent of
54/55; ships before them so the brand foundation is in place.

## Decisions to record at `/batch-start`

- **Mark placement** — where the logomark appears (login hero + top bar + verdict
  cue) and at what sizes.
- **How bold the verdict hero** — calm-premium restraint vs a louder statement
  (keep it the most crafted object without becoming glossy).
- **Gradient / accent scope** — where the checkmark gradient and the brass accent
  are allowed, holding one-accent-per-view restraint.

## Verification (planned)

- `VerdictHero.test` — each verdict (green/amber/red) + the pending state render
  the right label/line and the mark/ring; a11y label preserved.
- `LoginPage.test` — the splash renders the mark + wordmark and keeps the
  invite/PIN toggle.
- `DashboardPage.test` — the next-action band renders the right CTA per state
  (reuse the Batch 50 cases); top-bar mark renders; offline still renders.
- `tsc --noEmit` clean; web lint 0 new errors; web build clean under Node 20;
  backend suite untouched. Headless-preview visual confirm (login, Home) mobile +
  desktop, dark + light.

## Deferred / non-goals

- No change to verdict/recovery **logic** or the analysis engine (backend).
- No rename or palette rebrand — CheckMark, emerald/teal/brass stay (Craig's brand
  latitude: keep CheckMark, integrate it better).
- No Home section-hierarchy rework — that is Batch 54.
