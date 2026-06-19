# Logo concepts — pick one direction

> **Chosen — Concept 6 · "Calcio C" (`concept-6-calcio-c.svg`).** After the rebrand
> from *The Steele Spreadsheet System* to **Calcio**, the identity moved from an **S**
> letterform to a **C**: a geometric monoline C (open centre-circle ring) cradling a
> football, in the brass-gold wordmark gradient on graphite. It is the single source of
> truth in `apps/web/generate-icons.mjs`, which rasterises every PWA icon + favicon and
> re-emits the archival SVGs here. The notes below are the original Steele-era exploration.

Five concept marks for **The Steele Spreadsheet System**, drafted at 512 × 512 SVG with a brass + graphite palette (`#D4A24A` on `#0B0E13`). Each concept ships in both a dark variant and a light variant. Once you pick a direction I'll refine that one through Phase 3 — convert text to outlined paths, export to PNG at 192/384/512 for the PWA manifest, and create a 32×32 favicon.

## How to view

The SVGs are pure vector — open any of them directly in a browser or in VS Code with the SVG preview extension. Dark variant filenames have no suffix (`concept-1-monogram.svg`); light variants have `-light` (`concept-1-monogram-light.svg`).

A side-by-side preview HTML page can be re-built quickly from the SVGs if you'd rather see them all on one screen.

## The five concepts

### 1. `concept-1-monogram` — "S³"

Heavy monogram set in JetBrains Mono (matches the existing wordmark). The three S's of "Steele Spreadsheet System" are compressed into one mark with a small superscript 3 — half exponent, half tournament round count. Quietly maths-coded for the spreadsheet half of the brand; quietly premium for the rest. The "3" doubles as a rhythm break against the heavy S.

**Pros:** Direct line back to the existing wordmark. Scales cleanly. Animatable (the 3 can pop in 200 ms after the S settles).
**Cons:** Doesn't reference football at all. Reads "fintech" to a cold viewer.
**Favicon scaling:** ✅ at 32 px+ · ⚠️ at 16 px the "3" disappears — would need a simpler 16 px alt (just the S).

### 2. `concept-2-cell` — Cell + ball

A 3 × 3 spreadsheet grid with the centre cell outlined in brass, and a small football inside it. The football is rendered as a brass disc with one black pentagon panel — minimal but unambiguous. The whole mark reads as "the predictive cell" — where the spreadsheet and the football converge.

**Pros:** Most explicit duality. Tells the brand story without a sentence.
**Cons:** Literal. Could look corporate-startup at a glance. Doesn't survive favicon scaling.
**Favicon scaling:** ❌ — too much detail. Below 64 px the grid becomes a smudge. Would need a simplified favicon variant (centre cell + ball only).

### 3. `concept-3-letterform` — Bold S with pentagon

A single heavy S, stroke-based for clean scaling, with a small football pentagon set into the optical centre as a "found detail". The S is the loud move; the pentagon is the reward for looking closer. The pentagon also visually splits the S's counters in a way that hints at the geometry of a football panel without spelling it out.

**Pros:** Confident, single letterform. Lots of brand weight in one shape. Pentagon detail rewards re-looks. Animatable as a pentagon-grows-into-place reveal.
**Cons:** Pentagon detail disappears at favicon size — you lose the second-layer meaning.
**Favicon scaling:** ✅ at any size · the S alone is enough at 16 px even when the pentagon vanishes.

### 4. `concept-4-pitch` — Pitch as spreadsheet

A football pitch (full outline + centre line + centre circle + small penalty boxes) overlaid with three dashed brass rows that read as spreadsheet rows. Single small ball at centre. The pitch is the headline; the spreadsheet rows are a quiet second voice.

**Pros:** Best illustration of the duality at PWA-icon size. Premium "drawn for us" feel. Looks great as the loading splash.
**Cons:** Too detailed for favicons. The dashed rows can read as decorative noise if you don't know the brand.
**Favicon scaling:** ❌ — only works at 96 px and up. Would need a totally different mark (e.g. just the ball + centre circle) for small sizes.

### 5. `concept-5-tick` — Ticked football

A football (circle + one pentagon panel) with a bold tick mark drawn across it. The most playful of the five, and the most action-coded: the user is "ticking off" their prediction. Lands the spreadsheet half through the tick (checkbox), the football half through the ball.

**Pros:** Action-led — the only mark that has motion baked in. Reads instantly. Survives at favicon size.
**Cons:** Less serious than the other four — closer to a sports-betting app than a premium brand. Could feel disposable.
**Favicon scaling:** ✅ at any size · circle + tick reads down to 16 px.

## Scaling summary

| Concept | 16 px | 32 px | 64 px | 192 px | 512 px |
|---|---|---|---|---|---|
| 1 · S³ | ⚠️ | ✅ | ✅ | ✅ | ✅ |
| 2 · Cell | ❌ | ⚠️ | ⚠️ | ✅ | ✅ |
| 3 · Bold S | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4 · Pitch | ❌ | ❌ | ⚠️ | ✅ | ✅ |
| 5 · Tick | ✅ | ✅ | ✅ | ✅ | ✅ |

(⚠️ = legible but loses a layer of meaning · ❌ = becomes a smudge)

## What I'd pick if I had to pick

If the priority is **premium and timeless**: **Concept 3 (Bold S with pentagon)**. It's the move that survives every size, says "Steele" with one shape, and rewards the close-looker with the football reference without being literal. It also looks the most like something you'd see on a small-studio app.

If the priority is **explicit brand story**: **Concept 4 (Pitch grid)**. It tells the duality in one glance and looks like nothing else in this category. But it needs a simplified favicon partner.

I would not pick Concept 2 (too literal) or Concept 5 (too playful for the wordmark voice) — they're included as range checks so you can see what we're moving away from.

## Constraints honoured

- All SVGs use **at most two colours** (brass mark on graphite background, or brass mark on off-white background).
- All SVGs are **viewBox-based and editable** — no embedded raster, no encoded fonts (where fonts are used they're system-font fallbacks; on direction-pick I'll outline them to paths so the mark is fully portable).
- All SVGs render the **same shape at 16 px and 512 px** — no separate "favicon variant" hidden in a different file.
- The **iOS app-icon corner radius** (rx=96 on a 512 box, ~18.75 %) is baked in so the dark variant is install-ready without further treatment.

## Once a direction is picked

Phase 3 work for the chosen concept:
1. Convert any web-font typography to outlined paths
2. Export PNG at 192, 384, and 512 (already-correct sizes for `manifest.webmanifest`)
3. Generate a 32 × 32 ICO favicon (Apple touch icon stays at 192 px PNG)
4. Update `apps/web/public/icon-{192,512}.png` and `apps/web/public/favicon.ico`
5. Update `vite.config.ts` PWA manifest icons list if a maskable variant is needed (added padding for the safe zone)
6. Replace the `Brand` component's render so the chosen mark sits alongside (or replaces) the typographic wordmark on the splash
7. Sanity-check the install prompt + iOS-Add-to-Home-Screen flow with the new mark
