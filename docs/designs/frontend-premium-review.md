# Front-end premium review — CheckMark

> A world-class UI/UX pass over the shipped app (2026-07-03). North-star agreed
> with Craig: **calm, premium health companion** — quiet confidence, one clear
> action per screen, data on demand. Brand latitude: **keep CheckMark; make the
> identity felt and lift execution to premium.** Review-first: this doc is the
> findings + proposed direction + batch plan. Nothing is built yet.

## Method

Read the full front-end (chrome, primitives, tokens, and every core screen) and
**walked the live app** in a headless preview against mock `/api` envelopes
(prod-free), mobile 375×812, dark + light. Screens captured: Home (verdict /
today / collapsed-section wall), Sleep (Last night + Tonight), Check-in, Login
splash, light-mode Home.

## What's already strong (keep)

- **Real token system.** `theme/tokens.ts` ↔ `index.css` ↔ Tailwind, with a
  light + dark palette, radius/shadow/motion/z scales, safe-area helpers, 44px
  tap floor, reduced-motion. This is a genuine design system, not ad-hoc classes.
- **Sound IA.** 3-tab + More (Home / Week / Sleep) is right for a phone-first
  daily user (Batches 49–51). Verdict-first Home and collapse-not-remove are the
  right instincts.
- **Good bones per component.** CVA button/badge variants, Lucide iconography,
  a spring tab-underline, `press-down` feedback, lazy section bodies.
- **Light theme separates well** — cards read cleanly on off-white.

The gap is not architecture. It's **execution polish + brand presence**: the app
currently reads as competent "developer-dark," not premium calm companion.

---

## Findings — prioritised

### P0 — Premium blockers & usability (do first; everything inherits these)

**P0-1 · Dark surfaces are too close in value → nothing separates.**
`bg #0A1112 → surface #111E1F → elevated #192A2B → border #253A3C` all sit in a
narrow near-black band. On Home the six collapsed sections become a flat monotone
wall; the verdict and cards float on hairline borders with `shadow-sm` only. This
is the single biggest reason it doesn't feel premium. *Fix:* widen the surface
value steps, introduce real (soft, slightly colour-tinted) elevation, and reserve
a subtle gradient for hero surfaces. The light theme already proves the layout
works when surfaces separate — the dark theme is the weak link.

**P0-2 · Form inputs are dark-on-dark and barely legible.**
Inputs use `bg-bg` (#0A1112) — identical to the page background — with a #253A3C
border and #7B859B placeholder. On Check-in the fields nearly vanish and
placeholders are hard to read. This is both a premium miss and a real
**accessibility problem for an older daily user**. *Fix:* give inputs their own
elevated fill, a stronger idle border, a clear focus ring, and higher-contrast
placeholder/label. Rework the whole input/control tier together.

**P0-3 · The verdict — the product's heartbeat — isn't crafted.**
`VerdictHero` is a faint tinted bordered box that on dark barely separates from
the page. The single most important glance in the app should be its most
considered moment. *Fix:* real depth, a branded ring/gradient, larger confident
type, and a genuine sense of "this is today's answer."

### P1 — Identity & hierarchy (high impact)

**P1-1 · There is no logomark anywhere in the running app.**
Brand = text wordmark only ("CHECKMARK" mono in the top bar; "CHECK/MARK" split
on login). A mark asset exists (`public/brand/checkmark-icon-primary.svg`,
favicons, apple-touch-icon) but never appears in-product. The **login splash —
the prime brand moment — is a floating text wordmark in a void.** *Fix:*
introduce the mark into login (hero), the top bar, and the PWA/first-run feel.

**P1-2 · The signature gradient & secondary colours are defined but unused.**
`--wordmark-gradient` (teal→green) exists yet the login renders flat white/green;
the brass **accent (#C8943C)**, **Steele** silver, and medal colours almost never
appear in the daily screens. The identity collapses to "emerald-green on black."
*Fix:* give the accent a real, consistent role (secondary actions, "next"
emphasis, data highlights) and let the checkmark gradient appear at signature
moments so the brand is *felt*, not just labelled.

**P1-3 · Home lacks hierarchy — it's a wall of equal accordions.**
Six near-identical cards (green icon + bold title + muted one-liner + chevron),
distinguished only by a small dot when action is pending. Nothing separates
retrospective (Last night) from prospective (Tonight), or important from ambient.
*Fix (calm-companion):* a clear reading order — **verdict → the one next action →
today** — with the remaining context receding (lighter weight, grouped under a
quiet "More detail" divider), so the eye lands where it should.

**P1-4 · The "Next" strip is under-weighted and wastes space.**
A full-width bordered box holding a small mono "NEXT" label + a small
left-aligned button, with a large empty right area. It's the second-most
important element but looks like an afterthought. *Fix:* a proper primary
action band (full-width CTA, clear label, arrow), visually tied to the verdict.

**P1-5 · Primary-card button clusters are too dense.**
The pending-change state shows **5 buttons** (Approve & upload, Ignore, Manual
edit, Swap day, Skip) wrapping on one card. *Fix:* one primary (Approve) + one
secondary, with the rest behind a "More options" overflow.

**P1-6 · Mono-uppercase micro-labels are overused.**
`font-mono uppercase tracking-[0.25em]` is applied to date eyebrows, "NEXT", More
headings *and* form field labels ("OVERALL (0–10)", "IN A FEW WORDS"). As form
labels it hurts readability and feels techy for a calm health app. *Fix:* reserve
mono-eyebrow for kickers + numerics/wordmark; use clean sentence-case labels.

### P2 — Polish & delight

- **P2-1 · Motion on signature moments.** Section expand is instant (card pops);
  the verdict has no reveal. Add restrained height/opacity animation on expand
  and a gentle verdict entrance.
- **P2-2 · Empty/error states are generic.** "couldn't load / please try again"
  cards — give them character + a clear recovery action.
- **P2-3 · Truncation breaks mid-word** ("REM in your 65–90 …", "keep it
  conv…"). Truncate on word boundaries or tighten the source copy.
- **P2-4 · First-screen density.** "Good evening, Mark" at text-3xl consumes the
  top of the glance screen above the verdict; fold the greeting + date into a
  smaller lockup so the verdict sits higher.

---

## Proposed direction — "calm premium"

Principles: **one thing to look at, one thing to do, everything else on demand.**

1. **Depth & surface.** Widen the dark value ramp; soft, low-opacity elevation
   (optionally faintly teal-tinted) so cards read as layered paper, not outlines.
   Hero surfaces (verdict) get a subtle gradient + ring.
2. **The verdict as the hero.** Green/Amber/Red rendered large and confident with
   real depth and a branded ring; the plain-English line beneath. This is the
   most crafted object in the app.
3. **One next action.** A single full-width CTA band directly under the verdict —
   the app's "do this now" — using accent/tone colour, not a faint outline box.
4. **Calm hierarchy below.** Today's card leads; the remaining sections recede
   (quieter titles, lighter cards, grouped detail) so Home reads as a curated
   brief, not a stack of accordions.
5. **Brand felt, not just present.** Logomark on login (hero) + top bar; the
   checkmark gradient at signature moments; a real secondary-colour role.
6. **Legible, human controls.** High-contrast inputs, sentence-case labels,
   1 primary action per card, restrained motion on reveals.

---

## Implementation plan (frontend-only, no migration; repo batch cadence)

Sequence **52 → 53 → 54 → 55**. Batch 52 is the foundation everything else
inherits. Full specs are separate design docs; the ledger row is in
`docs/phase-batches.md` → "Post-roadmap — Front-end premium UX batch plan".

- **Batch 52 — Design foundations (token + primitive tier)** 🔴 High.
  Surface/elevation ramp, shadow system, input/control redesign, mono-label
  pullback, type scale. Touches `index.css`, `theme/tokens.ts`,
  `tailwind.config.ts`, `components/ui/*`. Highest leverage; low behavioural risk.
  Spec: `docs/designs/design-foundations.md`.
- **Batch 53 — Branded verdict, hero & login** 🔴 High.
  The existing (currently icon-only) mark brought in-app, `VerdictHero` redesign,
  login splash, top-bar mark, the next-action CTA band. Where the identity becomes
  felt. Spec: `docs/designs/branded-verdict-hero-login.md`.
- **Batch 54 — Home hierarchy & calm density** 🟢 Mid.
  Section recede/reading-order, button overflow, greeting/first-screen,
  word-boundary truncation, section-expand motion. Spec:
  `docs/designs/home-hierarchy-calm-density.md`.
- **Batch 55 — Screen polish & states** 🟢 Mid.
  Apply the system across Sleep / Check-in / Week; empty/error states with
  character; check-in flow density. Spec: `docs/designs/screen-polish-states.md`.

Each is a normal `/batch-start` unit with a design doc, tests, and prod verify.
No backend, payload, or migration changes anywhere in this plan. Decision numbers
**#122–#125** assigned at `/batch-start`.
