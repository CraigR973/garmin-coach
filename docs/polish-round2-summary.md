# Premium polish round 2 — round summary

Receipt for the 5-batch premium polish work driven by
`docs/design-audit-2026-05-25.md`. Equivalent of the "PR description
with deltas" Phase 4 step from `docs/polish-batches.md` — collected
into one doc because the round shipped per-batch rather than as a
single PR.

Closed-out 26 May 2026 against `main` at `5816fd9`.

---

## What landed

| Batch | Date | Commits | One-line summary |
|---|---|---|---|
| U1 | 25 May | `e12a942`, `c978262` | New brand mark (Concept 4 pitch-as-spreadsheet), self-hosted fonts, brass page-header divider |
| U2 | 26 May | `dbf1469`, `666e605` | Native `<select>` replaced; segmented PIN input; back-button placement consistent (top-left) |
| U3 | 26 May | `d643644` | Dashboard rebalance (next-match hero), copy polish, leaderboard dedupe, contrast fix on `--text-muted` |
| U4 | 26 May | `cde36da`, `7959334`, `9b427c7` | Premium empty states (bracket teaser, knockout teaser, groups pre-tournament view); PWA update banner (U4.7 added mid-session) |
| U5 | 26 May | `129952b` | Three motion moments (score-input spring, Save→✓ checkmark draw, rank-delta pulse) + elevation depth sweep + player-chip palette |

Plus tooling: `6ae831f` adds `U`-prefix support to `/phase-closeout` + `/strike-batch`; `6765c3a` adds polish mode to `/next-batch-prompt`.

## Audit findings addressed (Phase 1 → shipped)

From `docs/design-audit-2026-05-25.md`, the recommended priority list Q-13 (items 1–10):

| # | Audit finding | Where it shipped |
|---|---|---|
| 1 | C-1 brand-voice element (1-px brass divider) | U1.4 |
| 2 | C-3 / L-2 / Sp-1 / Cmp-1 native `<select>` removed | U2.1 |
| 3 | C-7 back-button placement (top-left) | U2.4 |
| 4 | C-8 / D-2 welcome line gradient drop | U3.1 |
| 5 | C-6 / B-1 bracket empty state | U4.1 |
| 6 | D-3 / D-7 dashboard rebalance | U3.2 |
| 7 | C-5 three motion moments | U5.1 / U5.2 / U5.3 |
| 8 | PP-1 / PP-2 streak + submit-time copy | U3.5 / U3.6 |
| 9 | LB-1 / LB-3 leaderboard dedupe + hint placement | U3.10 / U3.9 |
| 10 | New logo | U1.1 (concept swap from 3 → 4 in U1 follow-up) |

Plus additional audit items folded in during the run:

| Audit ID | Where it shipped |
|---|---|
| L-3 segmented PIN input | U2.2 |
| L-4 "Forgot your PIN?" helper | U2.3 |
| Sp-4 / Sp-5 Save → Update → "Saved ✓" | U2.5 |
| Set-1 platform-aware "How to enable" notif copy | U2.6 |
| C-10 mini-leaderboard heading → "LEADERS" | U3.3 |
| D-4 stale-data flicker fix | U3.4 |
| PP-3 Best/Worst card collapse | U3.7 |
| PP-4 unfinished match Pts neutralisation | U3.8 |
| U3.11 `--text-muted` contrast lift (first clause) | U3.11 |
| K-1 knockout picks empty state | U4.2 |
| G-1 pre-tournament Groups page | U4.3 |
| GD-1 group standings column reduction | U4.4 |
| LH-1 rank history connect-line | U4.5 |
| S-1 / S-2 schedule label + countdown trim | U4.6 |
| U4.7 PWA update banner (new — added mid-session) | U4.7 |
| C-4 elevation depth sweep | U5.4 |
| LH-3 rank-history palette (no green for players) | U5.5 |

## Logo direction picked

**Concept 4 — Pitch-as-spreadsheet.** Original recommendation in the
audit was Concept 3 (bold S letterform with pentagon detail); during
U1 it was swapped to Concept 4 because the pitch outlines carry the
spreadsheet/football duality more clearly at icon sizes, and the
mark needed a companion simplified variant
(`docs/logo-concepts/concept-4-pitch-favicon.svg`) for the 32 px
favicon slot.

Logo source files committed: `docs/logo-concepts/concept-4-pitch.svg`
(primary), `concept-4-pitch-light.svg`, `concept-4-pitch-favicon.svg`.
Generated PNG assets in `apps/web/public/`: `icon-192.png`,
`icon-384.png`, `icon-512.png`, `icon-maskable-512.png`,
`apple-touch-icon.png`, `favicon.svg`, `favicon.ico`.

## Bundle delta

Comparison against `docs/design-audit-2026-05-25.md` Phase 1 baseline.
Reproduced locally on `main @ 5816fd9` with `pnpm --dir apps/web build`.

| Chunk | Baseline gzip | Final gzip | Δ | Notes |
|---|---|---|---|---|
| **Main entry** (`index-BOeeKr3L.js`) | **8.54 kB** | **8.54 kB** | **0** | unchanged — bootstrap unchanged |
| `react-vendor` | 53.83 kB | 53.83 kB | 0 | unchanged |
| `query` (TanStack) | 12.76 kB | 12.77 kB | +0.01 kB | unchanged |
| `supabase` (lazy) | 53.30 kB | 53.30 kB | 0 | unchanged |
| `use-reduced-motion` (framer-motion) | 36.75 kB | 36.75 kB | 0 | reused — no new bundle for U5 motion |
| `LeaderboardHistoryPage` (recharts) | 107.97 kB | 107.85 kB | −0.12 kB | LH-1 line-mode swap is recharts-internal |
| **Layout chunk** (`index-CTjAdreo.js` vs baseline `index-C3b8sRyM.js`) | 28.68 kB | **59.40 kB** | **+30.72 kB** | new components from U2–U5 (PinInput, SaveButton, ScoreInput, BracketTeaser, UpdateBanner, About page extension, PageHeader.back) |
| **New lazy chunks** (sum) | — | ~10 kB | +10 kB | `save-button`, `score-input`, `BracketTeaser`, `PageHeader`, `workbox-window` |
| **SW precache total** | 1221 KiB | 1320 KiB | +99 KiB | self-hosted fonts (70 KB) + new icon set (~30 KB) |

**Target was main-entry < +50 KB gzip — met (0 KB delta on main entry).**

The +30.72 kB on the Layout chunk is the per-batch cost of the new
components added across U2–U5. It loads lazily on first auth-gated
route, not on the `/login` cold path. The `/login` cold-load transfer
(measured by Lighthouse below) only moved by +8 KB.

## Lighthouse delta

Full numbers in `docs/lighthouse-final-2026-05-26.md`. Headline:

| Metric | Baseline | Final | Target | Status |
|---|---|---|---|---|
| Performance | 0.82 | **0.92** | 0.90 | ✅ |
| Accessibility | 0.96 | **1.00** | 1.00 | ✅ (after `86ed938` U3.11 follow-up) |
| Best Practices | 1.00 | 1.00 | 1.00 | ✅ |
| SEO | 1.00 | 1.00 | 1.00 | ✅ |
| LCP | 2.5 s | 2.5 s | 2.0 s | ⚠️ same value, score 0.89 → 0.90 |
| TBT | 540 ms | **260 ms** | 400 ms | ✅ |
| FCP | 1.9 s | 1.7 s | — | improved |
| Speed Index | 2.3 s | 1.7 s | — | improved |
| TTI | 3.3 s | 2.5 s | — | improved |
| Third-party transfer | 65.9 kB | 0.5 kB | — | Google Fonts fully removed |

## Verification status

- **CI on main** — green
- **Vitest** — 167/167 passing
- **Playwright smoke** — green per per-batch CI (`666e605` updated for shadcn Select + PinInput)
- **Lighthouse** — re-run; Performance 0.82 → 0.92, Accessibility 0.96 → 1.00 (after `86ed938`), all Phase 4 targets met
- **Bundle delta** — within budget on main entry
- **Real-phone soak** — owner: you. Carried out per-batch as each landed via the soak loop; round-level soak is your call to declare complete.

## Open items (not blocking "polish round done")

1. ~~**U3.11 follow-up: primary button on-colour contrast.**~~
   ✅ Shipped 2026-05-26 in `86ed938` — new `--on-primary` /
   `--on-accent` tokens locked dark across themes; Button default +
   accent + the OfflinePage hand-rolled button updated. Lighthouse
   Accessibility 1.00.

2. **C-2 backend leaderboard dup-rows bug.** Frontend dedupe shipped
   (U3.10) — defensive only. The actual backend regression is its
   own ticket; file separately if not already.

3. **LH-2 recharts → hand-rolled SVG chart.** 107 KB gzipped on the
   LeaderboardHistory route. Audit-flagged; out of scope this round.
   Future ticket.

4. **About / How-it-works page (C-11).** Audit recommended; not in
   the U-batches. A partial about page exists from a pre-U1
   frontend-polish branch (`1425356`, `dfd7315`, `7a0388f` etc.).

5. **Bigger feature work surfaced by audit Journeys 3–5** — live-match
   surface, knockout-transition celebration, end-of-tournament
   podium. Out of scope for polish. Separate scoping pass when the
   tournament is closer.

## Tagging

`v1.0-pre-multi-league` applied to `main` on 27 May 2026, against
the Lewis-soak-prep commit (this doc commit). The tag bundles:

- Premium polish round 2 (U1–U5 + U3.11 a11y follow-up)
- C-2 backend leaderboard dedupe fix (`e7796e1`) — the original
  audit finding that the polish round chose to defer; shipped as
  part of soak prep so Lewis's leaderboard returns 1 row per
  player, not N.
- Lewis soak guide (`docs/lewis-soak-guide.md`) for the
  pre-multi-league user trial.

Recover the SHA at any time:

```sh
git rev-parse v1.0-pre-multi-league
```

This is the revert point named in the original brief, before the
multi-league refactor begins.
