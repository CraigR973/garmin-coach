# Premium polish round 2 — batches (U1–U5)

Implementation plan for the items locked in by the 2026-05-25 design audit
(`docs/design-audit-2026-05-25.md`) and the chosen logo direction
(Concept 3 — bold S letterform with football pentagon panel, see
`docs/logo-concepts/`).

Same idea as `review-batches.md`: group same-model adjacent work, one
conceptual area per batch, ship-able in a single focused session.

Mark batches complete by striking through the row.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U1~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U1.1–U1.5~~ | ~~Shipped e12a942~~ |
| ~~U2~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U2.1–U2.6~~ | ~~Shipped dbf1469~~ |
| ~~U3~~ | ~~🟢 Sonnet~~ | ~~~4.5 h~~ | ~~U3.1–U3.11~~ | ~~Shipped d643644~~ |
| ~~U4~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U4.1–U4.7~~ | ✅ Shipped 2026-05-26 |
| ~~U5~~ | ~~🔴 Opus (extended thinking)~~ | ~~~3 h~~ | ~~U5.1–U5.5~~ | ✅ Shipped 2026-05-26 |

**Total ≈ 17 h** across 5 focused sessions.

Each batch ships as one PR off `feat/premium-polish`. Do not merge to
`main` until all five are done and the user has finished a real-phone
soak — see "Close-out" notes at the bottom.

---

## Scope guardrails

**In scope for this round:**
- The five batches below — roughly one third of the audit findings, picked from the audit's recommended priority list (Q-13).

**Explicitly out of scope, tracked separately:**
- Backend leaderboard duplicate-rows bug (C-2) — backend ticket, not this PR.
- Recharts → hand-rolled SVG chart (LH-2) — 107 KB gzipped win, but disrupts the polish flow; future ticket.
- Live-match surface (Journey 3), knockout-transition celebration (Journey 4), end-of-tournament podium (Journey 5) — bigger features, separate scope decision.
- First-run coachmark (Q-10 recommended "no" — better served by an About page).
- Dedicated About / How-it-works page (C-11) — future ticket; not yet locked.
- "Still Email?" tagline copy (C-9) — keep as-is, see Q-2.

**Implementation pre-conditions (set by audit):**
- Logo direction = Concept 3 (`docs/logo-concepts/concept-3-letterform.svg`).
- Brand-voice recurring element = 1-px brass divider under page headers (Q-3 option a).
- Light + dark mode both supported (Q-1 — keep both, pixel-check both in Phase 4).
- Bundle baseline locked in audit doc Phase 1 section — compare in Phase 4.

---

## U1 — Logo identity + brand-voice element 🟢 Sonnet · ~3 h

The single highest-leverage visual change in the round: a real mark + a
recurring brand element that lifts every page.

- **U1.1** Refine `docs/logo-concepts/concept-3-letterform.svg`:
  - Convert any remaining `<text>` to outlined `<path>` so the mark is fully portable (currently the concept uses path-based S — no text — but double-check)
  - Tighten the pentagon panel's optical centring; verify at 16, 32, 64, 96, 192, 512 px
  - Produce **maskable variant** (mark inset to 80 % to fit Android's safe zone) in `apps/web/public/icon-maskable-512.png`
  - Export `apps/web/public/icon-192.png` (replace existing), `apps/web/public/icon-512.png` (replace existing), `apps/web/public/icon-384.png` (new)
  - Generate `apps/web/public/favicon.svg` (vector, scales perfectly) and `apps/web/public/favicon.ico` (32×32 fallback for old browsers)
  - Optional: `apps/web/public/apple-touch-icon.png` (180×180 PNG, padded — Apple ignores manifest maskable hints)
  (~75 min)

- **U1.2** `apps/web/index.html` — wire the new favicon set:
  ```html
  <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
  <link rel="icon" href="/favicon.ico" sizes="32x32" />
  <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
  ```
  Update `apps/web/vite.config.ts` `VitePWA.includeAssets` to list the new files; add the maskable icon entry to `manifest.icons`.
  (~20 min)

- **U1.3** `apps/web/src/components/Brand.tsx`:
  - Add a new `variant="lockup"` rendering the mark to the **left** of the wordmark (icon + type on one line) — for use on the splash
  - Add a `variant="mark"` rendering just the mark (16/24/32 px sizes) — for use in places we previously used the `🏆` Lucide icon
  - Keep the existing `compact` and `splash` variants unchanged so other consumers don't break
  - Update `LoginPage.tsx` to render `<Brand variant="lockup" />` on the splash (mark + wordmark)
  (~45 min)

- **U1.4** Brand-voice recurring element (C-1): in `apps/web/src/components/PageHeader.tsx`, add a 1-px brass-coloured horizontal rule between the eyebrow row and the title:
  - Use `border-t border-accent/30` (brass with low opacity so it whispers, not shouts)
  - Subtle on dark, slightly more visible on light — already handled by the token's per-mode value
  - Verify it doesn't visually compete with the existing `border-b border-border` patterns on cards
  Apply manually only if `PageHeader` doesn't already wrap every page top — grep to verify (~5 min check, ~25 min apply incl. visual sweep)
  (~30 min)

- **U1.5** Self-host the splash fonts (surfaced by Lighthouse baseline — see `docs/lighthouse-baseline-2026-05-25.md`):
  - Download the woff2 files for the two weights actually used on `/login` (JetBrains Mono 600 + 700; Outfit 400 + 600 if needed) into `apps/web/public/fonts/`
  - Update `apps/web/src/index.css` `@font-face` rules to point at `/fonts/…` rather than `https://fonts.gstatic.com`
  - Add `<link rel="preload" as="font" type="font/woff2" crossorigin href="/fonts/jetbrains-mono-600.woff2">` to `apps/web/index.html` for the splash-critical weight
  - Remove the Google Fonts CSS `<link>` from `index.html`
  - Update the service worker's `googleFontsCache` route in `apps/web/src/sw.ts` to drop the (now-unused) `fonts.gstatic.com` cache tier
  - Verify the wordmark gradient still renders correctly (it depends on JetBrains Mono being loaded before paint)
  (~30 min)

**Acceptance:**
- `apps/web/public/icon-{192,512}.png` and friends present and reference the new mark
- `manifest.webmanifest` includes the new icons including maskable entry
- Favicon shows new mark in the browser tab (tested in Chrome + Safari)
- Install prompt + iOS "Add to Home Screen" both produce the new icon
- Splash on `/login` renders mark + wordmark as a lockup
- Every page with `PageHeader` shows the 1-px brass divider
- Existing `Brand variant="compact"` / `variant="splash"` callers are unbroken
- All existing Vitest + Playwright tests still pass
- New bundle delta < +20 KB gzipped (PNG icons are precached but not loaded eagerly)
- Self-hosted fonts: no requests to `fonts.gstatic.com` on cold load of `/login`; LCP element (the wordmark) paints at or before the existing 2.5 s baseline

---

## U2 — Form unification + navigation consistency 🟢 Sonnet · ~3 h

Kills the native `<select>` regression and tidies up nav inconsistencies
that fight the design system.

- **U2.1** Replace native `<select>` with the existing shadcn `Select` (Radix-based) on:
  - `apps/web/src/pages/LoginPage.tsx` (lines 77–91) — name picker
  - `apps/web/src/pages/SpecialsPage.tsx` — tournament winner picker and top scoring team picker (the Golden Boot input stays a text input)
  - `apps/web/src/pages/ComparePage.tsx` — Player A + Player B pickers
  Keep `<input type="time">` and `<input type="date">` as native (the platform picker is genuinely better there).
  (~75 min)

- **U2.2** `LoginPage.tsx` — replace the plain PIN `<Input type="password">` with a **4-cell segmented PIN input** component. Build it as `apps/web/src/components/PinInput.tsx`:
  - Four focusable cells, each `inputMode="numeric"`, single character
  - Auto-advance on input, backspace returns focus to previous cell
  - Paste of 4 digits fills all cells
  - Renders as a controlled component with one `value: string` / `onChange: (v: string) => void` API for easy form integration
  - Length is fixed at 4 (admin can extend in a future PR if/when 8-digit PINs are wanted)
  (~50 min)

- **U2.3** `LoginPage.tsx` — add a "Trouble signing in?" helper line under the submit button:
  > "Forgot your PIN? Ask your league admin for a reset."
  Small text, muted colour, non-link (PIN reset is admin-side).
  (~10 min)

- **U2.4** Back-button consistency (C-7) — in `apps/web/src/components/PageHeader.tsx`:
  - Add an optional `backTo?: string` (route) or `back?: { to?: string; label?: string }` prop
  - When set, render a top-**left** back chip (ChevronLeft + label) above the eyebrow row
  - The right-slot action slot stays for forward actions only
  - Update every page that currently uses an `← Back` chip in the right slot:
    - `GroupDetailPage` (`← Groups`)
    - `LeaderboardHistoryPage` (`← Leaderboard`)
    - `RoundLeaderboardPage` (`← Overall`)
    - `ComparePage` (`← Leaderboard`)
    - `PlayerProfilePage` (`← Leaderboard`)
    - Admin sub-pages (`← Admin`)
  - On `MatchDetailPage` keep its existing top-left back affordance unchanged (or unify with the new prop)
  (~60 min)

- **U2.5** `SpecialsPage.tsx` button label fix (Sp-4): the per-card button reads:
  - "Save" if the player has no value committed yet for that special
  - "Update" if a value already exists
  - "Saved ✓" briefly (1.2 s) immediately after a successful save (Sp-5 — animated state in U5; for this batch just change the label)
  (~30 min)

- **U2.6** Settings `Subscribe` button (Set-1): when `permission === 'denied'`, replace the button with a "How to enable" link that explains how to unblock the notification permission in browser settings. Use platform-aware copy if cheap.
  (~15 min)

**Acceptance:**
- No `<select>` element in the rendered DOM of `/login`, `/predictions/specials`, `/compare`
- New `PinInput` component renders 4 cells with auto-advance, backspace nav, and paste support — covered by a Vitest unit test
- Back chip is top-left on all pages that have one; the right slot is action-only (or empty)
- Specials button label state machine works correctly (no committed → "Save", committed → "Update")
- "How to enable" copy renders only when permission is denied
- All existing tests pass; new test for `PinInput` is green
- Accessibility test still passes (Radix selects come with role + label correctness out of the box)

---

## U3 — Dashboard rebalance + copy polish 🟢 Sonnet · ~4 h

The biggest single batch. Dashboard is the most-visited surface; this
batch flips its information hierarchy and tidies the long tail of copy
nits that surfaced in the audit.

- **U3.1** `DashboardPage.tsx` — welcome line (C-8 + D-2): drop `text-wordmark-h` on the player name. Use weight + colour contrast instead (`font-semibold text-text-primary`). The wordmark gradient is reserved for the wordmark itself.
  (~5 min)

- **U3.2** `DashboardPage.tsx` — make next-match the hero (D-3 + D-5 + D-7):
  - Move `NextMatchCard` to the top of the page (right under the welcome line), full-width, larger countdown (`text-4xl`), larger team labels
  - Move the two stat cards (`YOUR RANK`, `TOTAL POINTS`) to **below** the next match card
  - Move the quick-link nav cards (Predictions / Knockout / Specials) **above** the mini-leaderboard (D-7 — players come to predict, not gloat)
  - Add a `Predict now` button inside the `NextMatchCard` when the user hasn't yet predicted that match (1 small query: fetch the user's prediction for `nextMatch.id` and check)
  (~90 min)

- **U3.3** `DashboardPage.tsx` — rename mini-leaderboard section heading (C-10): `STANDINGS` → `LEADERS` (or `TOP OF THE TABLE` — pick whichever reads better against the tabbar item next to it).
  (~5 min)

- **U3.4** `DashboardPage.tsx` — kill the "—" placeholder flash on refetch (D-4):
  - In the React Query options for `leaderboard`, `upcoming`, `recent`, add `placeholderData: keepPreviousData` (React Query v5 helper)
  - Verify the dashboard now shows last-known values during refetch instead of "—"
  - Cover with a Vitest test that mocks an in-flight refetch and asserts the previous value is rendered
  (~30 min)

- **U3.5** `PlayerProfilePage.tsx` — streak emoji (PP-1): hide 🔥 when streak < 2 (show `0` plainly or `—`).
  (~5 min)

- **U3.6** `PlayerProfilePage.tsx` — AVG SUBMIT TIME format (PP-2): convert hours to a humanised relative format (`> 24 h ago` → `Xd Yh before`; `< 1 h` → `Xm before`). Helper in `apps/web/src/lib/format.ts` (new file) so other places can reuse.
  (~25 min)

- **U3.7** `PlayerProfilePage.tsx` — Best / Worst round (PP-3): when both Best and Worst show 0 pts AND the player has zero settled rounds, collapse the two cards into a single "No round results yet" placeholder.
  (~20 min)

- **U3.8** `PlayerProfilePage.tsx` — Recent Predictions table 0 pts (PP-4): when actual result is `?–?` (unfinished), render `—` in the Pts column with neutral colour; when actual is settled and pts is 0, keep current red treatment.
  (~15 min)

- **U3.9** `LeaderboardPage.tsx` — hint placement (LB-3): move "Tap a row for breakdown · long-press to compare" from the bottom of the page to just under the `PageHeader` (above the sub-nav). Make it dismissible — once dismissed, persist in `localStorage` (key `sss_leaderboard_hint_dismissed`).
  (~25 min)

- **U3.10** `LeaderboardPage.tsx` + `DashboardPage.tsx MiniLeaderboard` — client-side leaderboard dedupe (LB-1): introduce a `dedupedLeaderboard(entries)` helper in `apps/web/src/lib/leaderboard.ts`:
  - Dedupe by `player_id` (keep first occurrence)
  - **Recompute** rank locally using standard competition ranking (`1, 1, 1` when all tied; `1, 1, 3` when two tied for first)
  - Always run the dedupe defensively, even after backend bug is fixed (cheap, makes the frontend resilient)
  - Cover with a Vitest test: input with 9 dup rows for 3 players all `total_points: 0`, all `rank: 4` → output is 3 rows, all `rank: 1`
  (~50 min)

- **U3.11** Colour-contrast token fixes (surfaced by Lighthouse baseline — see `docs/lighthouse-baseline-2026-05-25.md`):
  - `apps/web/src/theme/tokens.ts` + `apps/web/src/index.css` — lift the dark-mode `--color-text-muted` from `#5A6478` to a value that clears WCAG AA 4.5:1 against `bg-surface` `#131720` (target ~`#7B859B` — verify with a contrast checker). Same lift for the light-mode value if it doesn't already pass.
  - Affects every page eyebrow (`FIXTURES`, `STANDINGS`, `ACCOUNT & DEVICE`, etc.) across the app — single token edit, dozens of consumers improve at once.
  - **Primary button text fix:** in `apps/web/src/components/ui/button.tsx`, the `default` variant currently lets `text-text-inverse` resolve to white on emerald — Lighthouse measured 2.53 contrast (white on `#10B981`). Force the on-primary text colour to `text-text-inverse` (`#0B0E13`) explicitly so it clears 12:1. Verify the same fix for the `accent` variant on brass.
  - Cover with a Vitest snapshot or accessibility test: re-run the existing `accessibility.test.tsx` and confirm no new violations.
  (~30 min)

**Acceptance:**
- Welcome name no longer renders with the brass gradient
- Dashboard scroll order: welcome → next match (hero) → stat cards → quick links → mini leaders
- "Predict now" button appears on the hero card when the user has no prediction for the next match
- `LEADERS` (or chosen alternative) heading on mini section
- No "—" flicker during refetch on the dashboard
- Player profile streak emoji hidden at 0
- AVG SUBMIT TIME no longer shows raw hours
- Best/Worst card collapses to single placeholder when no variance
- Recent Predictions `?–?` rows show `—` not red `0`
- Leaderboard hint visible at top, dismissible, dismissal persists across reloads
- Leaderboard + Dashboard mini-table show 3 rows (not 9) even against the buggy backend, with ranks 1/1/1 not 4/4/4
- New `format.ts` and `leaderboard.ts` lib modules covered by Vitest tests
- `--color-text-muted` and primary-button on-colour text all clear WCAG AA 4.5:1 (verify via a Lighthouse re-run during U3 close-out)
- All existing tests pass; no regressions in Playwright smoke

---

## U4 — Premium empty states + bracket teaser 🟢 Sonnet · ~3 h

Lifts the long-tail empty states from "dashed-card with text" to "feels
like the team thought about this".

- **U4.1** `BracketPage.tsx` empty state (C-6 + B-1):
  - Replace the current `EmptyState` with a custom component `BracketTeaser` rendered as:
    - A greyscale SVG silhouette of the R32 column (16 placeholder boxes in `text-text-muted/30` with the brass divider hint between halves)
    - A title "The bracket arrives after group stage"
    - A countdown to the first knockout match's scheduled kickoff (fetch via `/api/v1/matches?stage=r32&limit=1` — show "—" if not available)
    - A CTA "Make your group-stage picks →" linking to `/predictions`
  - Keep the actual bracket SVG component unchanged for the populated case
  (~75 min)

- **U4.2** `KnockoutPredictionsPage.tsx` empty state (K-1):
  - Same `BracketTeaser` component but with copy adapted: "Knockout picks open after group stage"
  - Add a CTA linking to `/predictions/specials` so the player can use their time pre-tournament
  (~15 min — reuses U4.1)

- **U4.3** `GroupsPage.tsx` pre-tournament view (G-1):
  - When every match in the group has `status === 'scheduled'`, replace the mini standings table with a "First match" preview row showing kickoff time + the two teams (since the standings are all zeros anyway)
  - The full standings table appears the moment a single match in that group is `completed`
  - Header keeps the "Details →" link so admins/curious players can still drill in
  (~45 min)

- **U4.4** `GroupDetailPage.tsx` column reduction (GD-1):
  - Default visible columns on `< 480 px` viewports: `#`, `Team`, `P`, `W`, `D`, `L`, `Pts` (drop GF, GA, GD)
  - Add a small "Show full stats" toggle below the table that expands to all 10 columns
  - In landscape (`@media (orientation: landscape)`) show full table by default
  - Drop the `(CZE)` text suffix after team name when flag + name are present (GD-3)
  (~30 min)

- **U4.5** `LeaderboardHistoryPage.tsx` — connect-line chart (LH-1):
  - Switch Recharts `<Scatter>` to `<Line>` (or layer `<Line>` underneath the scatter dots) so each player's trajectory is visible across rounds
  - Keep the dot markers on top (helpful for sparse data points)
  - Replacing recharts with a hand-rolled SVG line chart (LH-2 — 107 KB win) is **out of scope here**, tracked as a future ticket
  (~30 min)

- **U4.6** `SchedulePage.tsx` countdown trim (S-2): drop the per-match `<Countdown>` rendered under the kickoff time. The countdown already appears on the dashboard and match-detail page; the schedule list doesn't need it. Match cards become ~20 % shorter.
  Also: rename the `3rd` stage-filter pill to `3rd place` (S-1).
  (~15 min)

- **U4.7** PWA "Update available" banner — currently the app uses `registerType: 'autoUpdate'` with `self.skipWaiting()` + `clientsClaim()` in `sw.ts`, which silently swaps the SW with no user-visible signal. Users on the installed PWA have no idea a new version landed.
  - Switch `vite.config.ts` `VitePWA` `registerType` from `'autoUpdate'` to `'prompt'`
  - Add a new `apps/web/src/components/UpdateBanner.tsx` component that uses `useRegisterSW` from `virtual:pwa-register/react`:
    - Shows a slim dismissible banner at the top of the viewport when `needRefresh` is true: `"New version available"` + `"Update"` button + `"×"` dismiss
    - Calls `updateServiceWorker(true)` on button click, then `window.location.reload()`
    - Dismiss (× only) hides the banner for the current session without reloading
    - Uses existing design tokens: `bg-surface-elevated`, `border-accent/40`, `text-text-primary`, `Button` variant `accent` size `sm`
  - Mount `<UpdateBanner />` in `apps/web/src/App.tsx` (or the root layout) above the router outlet so it overlays every page
  - Remove `self.skipWaiting()` from `sw.ts` — with `registerType: 'prompt'` the SW stays in the waiting state until the user taps "Update", so we no longer want auto-activation. `clientsClaim()` can stay (it only matters at first install, not on updates)
  - Cover with a Vitest test: mock `useRegisterSW` returning `{ needRefresh: [true, vi.fn()], updateServiceWorker: mockUpdate }` and assert the banner renders with the correct text and that clicking "Update" calls `mockUpdate(true)`
  (~30 min)

**Acceptance:**
- Bracket page empty state shows the greyscale R32 silhouette, countdown, and predict-CTA
- Knockout picks page empty state mirrors the bracket teaser visually
- Groups page pre-tournament shows a "First match" preview row per group, not a wall of zeros
- Group detail standings show 7 columns by default on mobile; toggle expands to all 10
- "(CZE)" suffix removed
- Rank history chart shows connected lines per player + dot markers on top
- Schedule match cards no longer carry the per-card countdown; the page is visibly more compact
- Stage filter label is `3rd place`, not `3rd`
- When a new SW is waiting, the `UpdateBanner` appears with "New version available" + "Update" button; tapping it reloads to the new version
- Dismissing the banner (×) hides it without reloading
- `registerType` is `'prompt'`; `self.skipWaiting()` is removed from `sw.ts`
- `UpdateBanner` Vitest test passes
- All existing tests pass; new `BracketTeaser` component has a basic render test

---

## U5 — Motion moments + elevation depth 🔴 Opus (extended thinking ON) · ~3 h

The judgment-heavy batch. Three motion moments that move the app from
"competent" to "felt", plus a small elevation-tier sweep on the highest-
traffic surfaces. Run on Opus with extended thinking ON.

- **U5.1** Score-input spring (C-5, motion moment 1):
  - On `PredictionsPage.tsx` and `MatchDetailPage.tsx`, when the prediction number changes (up/down chevron or keyboard), animate the digit with a brief 1.1× scale spring (`framer-motion`, `transition={{ type: 'spring', stiffness: 380, damping: 22 }}`)
  - Respect `prefers-reduced-motion: reduce` — fall back to no animation
  - Verify the score input pattern is the same on both pages first (MD-1 — unify if not; reuse the same component)
  (~45 min)

- **U5.2** Save-confirmation animation (C-5, motion moment 2 + Sp-5):
  - On `MatchDetailPage.tsx` Save button and `SpecialsPage.tsx` Update buttons (and any other "Save" CTA), when the save resolves successfully:
    - Button briefly transitions to a `"Saved ✓"` state for 1.2 s
    - The check icon path draws in (`pathLength: 0 → 1` over 280 ms)
    - Then morphs back to the resting state
  - Single shared `SaveButton` component if reasonable (`apps/web/src/components/ui/save-button.tsx`)
  - Respect reduced-motion
  (~60 min)

- **U5.3** Rank-delta pulse (C-5, motion moment 3):
  - On `LeaderboardPage.tsx`, when a rank changes between fetches (compare `prevRank` vs `entry.rank`), animate the `<ArrowGlyph>` with a brief 1.25× scale pulse + colour intensity flash over 240 ms
  - Trigger only on the first render after a real change — not on initial mount
  - Respect reduced-motion
  (~35 min)

- **U5.4** Elevation depth sweep (C-4):
  - On `SchedulePage.tsx`, the sticky date header (`bg-bg/95 backdrop-blur-sm`) → use `bg-surface-elevated/95` so it lifts visibly above the cards underneath
  - On `MatchDetailPage.tsx`, the "Your Prediction" card → `bg-surface-elevated` so it sits above the match-header card
  - On `DashboardPage.tsx` after U3.2, the hero "Next match" card → `bg-surface-elevated` so it visually leads the page
  - One careful pass: verify each change in both light and dark, on both mobile + desktop viewports
  (~30 min)

- **U5.5** Rank-history player chip palette (LH-3):
  - In `apps/web/src/pages/LeaderboardHistoryPage.tsx` and any other consumer of the per-player colour palette, drop `#22c55e` (green primary collision) and `#10b981` from the palette; swap in two neutral but distinguishable colours (e.g. `#94a3b8` slate-400 and `#cbd5e1` slate-300, or a tasteful warm pair like `#e879f9` and `#facc15`)
  - Apply consistently across LeaderboardHistory + Bracket (the bracket also uses this palette per its `PALETTE` constant)
  (~20 min)

**Acceptance:**
- Score input number visibly springs on change (and is static under reduced motion)
- Saving a prediction or special shows the `Saved ✓` draw-in animation, then returns to resting state
- Leaderboard rank-delta arrow pulses when the player's rank changes between refetches
- Schedule date header, MatchDetail prediction card, Dashboard next-match card all use `surface-elevated` and the depth difference is visible in both light + dark
- Rank history chart no longer uses green for any player (primary green is brand-only)
- Reduced-motion test: with `prefers-reduced-motion: reduce`, none of the new animations fire
- Bundle delta: framer-motion is already shipped; expect < +3 KB gzipped total for the new motion code
- All existing tests pass; new tests cover the reduced-motion fallback and the rank-delta-pulse trigger logic

---

## Verification (run at the end of U5, before merge)

Once U1–U5 are all green and pushed:

1. **Real-phone walk-through** — every page on iOS Safari (and ideally one Android Chrome). Both light and dark mode. The full 5 user journeys.
2. **Vitest + accessibility** — `pnpm test` green.
3. **Playwright smoke** — `pnpm e2e:smoke` green against staging.
4. **Lighthouse mobile** — run against the staging URL; capture vs the Phase 1 baseline (in the audit doc). Aim: no regression on Performance / Accessibility / Best Practices.
5. **Bundle delta** — compare `pnpm build` output to the Phase 1 baseline. Target: main entry < +50 KB gzipped (excluding the new logo PNGs which are precached but not loaded eagerly).
6. **PR description** — document: what changed per batch, audit findings addressed, logo concept picked, bundle delta numbers, Lighthouse delta numbers, any deferred items.
7. **Do not merge.** Push, confirm CI green, hand to user for real-phone soak. After user sign-off + merge, tag `main` as `v1.0-pre-multi-league`.

---

## Close-out per batch

Each batch closes the same way `R1–R7` did:

1. After all items in the batch are green locally, push the branch
2. `/phase-closeout U<n>` (the slash command handles CI poll + ff-merge — fallback to manual if it doesn't recognise the `U` prefix)
3. Append a short entry to `session-log.md` (use the project's lean format)
4. Strike the row in this file's table

The branch (`feat/premium-polish`) is shared across all five batches —
each batch is a commit, not its own branch — so the close-out doesn't
ff-merge to main until U5 is done and verified per the section above.

The `/next-batch-prompt` skill won't auto-recognise `U` batches (it's
hardcoded for `phase-batches.md` and `wc2026-architecture.md`). At
batch start, paste the relevant `## U<n> — ...` section into the new
session as the prompt scope.

---

# Round 3 (soak prep) — batches (U6–U8) — added 2026-05-30

From the 2026-05-30 pre-soak UX re-audit (`docs/soak-review/ux-audit-2026-05-30.md`),
triggered by multi-league reaching more people (the Lewis soak). Round 2 (U1–U5) is
shipped; this round picks up the two **user-flagged** items plus finish issues found in
the live visual pass. **Independent of round 2** — own branch (`feat/premium-polish-3`),
ff-merge per batch once green (don't wait on anything). The current `/next-batch-prompt
polish` reads this file's `## U<n>` acceptance inline, so no manual pasting needed.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U6~~ | ~~🟢 Sonnet~~ | ~~~2 h~~ | ~~U6.1–U6.3~~ | ✅ Shipped 2026-06-01 |
| ~~U7~~ | ~~🟢 Sonnet~~ | ~~~2 h~~ | ~~U7.1–U7.3~~ | ✅ Shipped 2026-06-01 |
| ~~U8~~ | ~~🟢 Sonnet~~ | ~~U8.1–U8.2~~ | ✅ Shipped 2026-06-01 |

---

## U6 — Variable-length PIN, unified everywhere 🟢 Sonnet · ~2 h

> Follow-up to **U2.2**, which built `PinInput` fixed at 4 cells with the note "admin can
> extend in a future PR if/when 8-digit PINs are wanted." Decision 2026-05-30: PIN range is
> **4–8 digits**. Today `SignupPage` pairs a 4-cell `PinInput` with a *plain* confirm box
> (visually inconsistent, confirmed in the live pass), the cell cap silently truncates to 4
> (contradicting the "4–8 digits" label), and `JoinPage` uses plain inputs for both.

- **U6.1** Make `apps/web/src/components/PinInput.tsx` variable-length: accept a `length`/`maxLength` prop (render N cells up to max, paste up to max, backspace nav across N). Keep the controlled `value`/`onChange` API. Update its Vitest test for N-length + paste. (~50 min)
- **U6.2** Use `PinInput` for **both** entry and confirm on `SignupPage` and `JoinPage` (and Login already uses it). Remove the plain `<Input type="password">` PIN/confirm fields. Set `autoComplete="new-password"` on signup/join, `current-password` on login (fixes the reused-component bug at `PinInput.tsx:68`). (~45 min)
- **U6.3** Reconcile copy + validation to 4–8 everywhere; ensure the confirm-match check works across the full range. (~20 min)

**Acceptance:** one `PinInput` used for every PIN entry/confirm on Login, Signup, Join; accepts 4–8 digits (no silent 4-cap); entry and confirm are visually identical; `autoComplete` correct per context; Vitest for variable length + paste green; a11y test green.

---

## U7 — Invite-flow cleanup + finish issues 🟢 Sonnet · ~2 h

- **U7.1** (UX U-FIX-2, user-flagged) Remove the "Invitee email (optional)" capture from `apps/web/src/pages/LeagueAdminInvitesPage.tsx` (state line 17, body field 31/37, field 83–93) — the auto-copied join link makes it dead weight. Post an empty invite body; remove the "For: {invitee_email}" line (122–126). Decide whether to retire the backend `invitee_email` column/param or leave it nullable for back-compat. (~45 min)
- **U7.2** (UX U3) Route destructive confirms through the design-system `ui/dialog.tsx` instead of native `window.confirm()`: `LeagueMembersPage` (remove member / leave, 56/70), `admin/PlayersPage` (62), `admin/InvitesPage` (98). Reuse the "type-to-confirm" pattern from `LeagueSettingsPage`. (~50 min)
- **U7.3** (UX U2) Remove/correct the stale `display: '"Instrument Serif", …'` token in `apps/web/src/theme/tokens.ts:75` — no Instrument Serif font is loaded and `font-display` aliases to Outfit; make the "single source of truth" token match reality. (~15 min)

**Acceptance:** no email field in the invite-create flow; no native `window.confirm()` for destructive actions (all styled dialog); the display-font token matches what renders; tests green.

---

## U8 — Partnership lockup polish 🟢 Sonnet · ~1.5 h

> Decision 2026-05-30: the "In partnership with Robinsons" splash joke **stays** — fix the
> quality. The Robinsons bitmap is low-res and reads as pasted clipart against the crisp
> vector wordmark, and the lockup differs between Login (full partnership line + "Still
> Email?" tagline) and Signup (wordmark only).

- **U8.1** Replace the low-res Robinsons raster with a crisp asset (vector if obtainable, else a 2–3× PNG with transparent background); align its sizing/spacing to the splash grid so it reads as an intentional element, not clipart. (~50 min)
- **U8.2** Unify the splash lockup across `LoginPage` and `SignupPage` (same partnership line + tagline placement). (~30 min)

**Acceptance:** the partnership logo renders crisp at all splash sizes (no visible pixelation); Login and Signup show the same brand lockup; no layout regression; tests green.

> Non-blocking note: embedding a real third-party brand mark carries a small trademark/professionalism consideration if the app ever goes more public — informational only for the private soak.

---

## Close-out (round 3)

Per batch: push `feat/premium-polish-3` → `/phase-closeout U<n>` (CI poll + ff-merge; manual fallback if the `U` prefix isn't recognised) → lean `session-log.md` entry → strike the row in the round-3 table above. Round 3 is independent of round 2's "do not merge until U5" rule.

---

# Round 4 (post-soak app review) — batches (U9–U13) — added 2026-06-01

From the 2026-06-01 user app-review (on-device iOS pass). Same batching rationale as
earlier rounds: user-flagged items + a code-grounded analysis of the current build,
with `file:line` refs inline. **Independent of rounds 2–3** — own branch
(`feat/premium-polish-4`), ff-merge per batch once green (don't wait on anything). The
current `/next-batch-prompt polish` reads this file's `## U<n>` acceptance inline, so no
manual pasting needed.

**Decisions locked in the review (carry these — a few reverse earlier decisions):**
- **PIN = exactly 4 digits.** *Reverses the U6 "4–8 digits" decision.* Safe to hard-force
  everywhere — **no accounts exist yet** (pre-release), so there is no existing-PIN
  lockout risk and the backend regex can tighten too.
- **Robinsons = original raster, not the U8.1 SVG.** Keep U8.2's unified lockup; only the
  asset reverts (user prefers the original look over the rendered SVG).
- **Knockout picks = per-round placeholder list** (mirrors the schedule), *not* a
  converging visual bracket (unusable on a phone). Optional read-only mini bracket on the
  existing Bracket tab for the "whole tree" view.
- **Invites = multi-use league join code** (Kahoot-style). Code-only — the league name is
  shown for *confirmation*, never typed; **do not call it a "PIN"** (collides with the
  login PIN). The shareable link carries the same code as a second door.
- **PWA deep-linking = not pursued.** iOS PWAs can't intercept `https` links or share
  storage with the Safari tab, so join is **browser-first + in-app join-by-code**; a
  generic "get the app" landing replaces all deep-link/universal-link engineering.
- **Player typeahead = deferred** to its own batch once official 26-man squads drop
  (~early June 2026). Golden Boot stays free-text until then (see *Deferred* below).
- **Quick tour = yes** — note this reverses round 2's Q-10 ("first-run coachmark: no,
  better served by an About page"). User explicitly wants a press-through intro.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U9~~  | ~~🟢 Sonnet~~ | ~~~2.5 h~~ | ~~U9.1–U9.7~~   | ✅ Shipped 2026-06-01 |
| ~~U10~~ | ~~🟢 Sonnet~~ | ~~~3 h~~    | ~~U10.1–U10.3~~ | ✅ Shipped 2026-06-01 |
| ~~U11~~ | ~~🟢 Sonnet~~ | ~~~2.5 h~~ | ~~U11.1–U11.3~~ | ✅ Shipped 2026-06-01 |
| ~~U12~~ | ~~🟢 Sonnet~~ | ~~~4 h~~    | ~~U12.1–U12.5~~ | ✅ Shipped 2026-06-01 |
| ~~U13~~ | ~~🔴 Opus (extended thinking ON)~~ | ~~~5 h~~ | ~~U13.1–U13.5~~ | ✅ Shipped 2026-06-02 |
| ~~U14~~ | ~~🟢 Sonnet~~ | ~~~6 h~~ | ~~U14.1–U14.6~~ | ✅ Shipped 2026-06-02 |

**U9–U13 shipped 2026-06-02** (~17 h across 5 sessions). **U14** was promoted from the
Deferred list once official squads published — it's the one remaining round-4 batch (~6 h,
gated on sourcing the squad dataset; see U14.1).

---

## U9 — Login + leagues quick wins 🟢 Sonnet · ~2.5 h

The low-risk, high-visibility surface fixes. All small, no new infra.

- **U9.1** PIN → exactly 4 digits everywhere (*reverses U6*). Frontend: `LoginPage.tsx:69`,
  `SignupPage.tsx:154` & `:159` — `maxLength={8}` → `maxLength={4}`; `SignupPage.tsx:53-56`
  client check → require length `=== 4`; reword "4–8 digits" copy to "4-digit PIN". Backend
  `routers/auth.py` — change `pin` pattern `^\d{4,8}$` → `^\d{4}$` at `:62`, `:68`, `:100`,
  `:105-106`, `:119`. `PinInput` stays variable-length (U6) but is driven with `maxLength={4}`.
  Tests: backend rejects 3- and 5-digit PINs (422); 8-cell overflow gone. (~40 min)
- **U9.2** Robinsons revert (*reverses U8.1, keeps U8.2*). Restore the original raster
  (`apps/web/public/robinsons-logo.png`, recoverable from commit `dfd7315`) and point
  `apps/web/src/components/PartnershipLockup.tsx:10-15` back at it; remove the now-unused
  `robinsons-logo.svg`. Keep the unified Login/Signup lockup from U8.2. (~20 min)
- **U9.3** Create-account prominence. `LoginPage.tsx:78-85` — promote "Create account" from a
  muted footer text-link to a **full-width secondary/outline `Button`** directly under the
  primary "Sign in" submit. Keep "Forgot PIN?" as the small text link. (Chosen over equal-size
  buttons: returning users sign in far more often than they sign up.) (~25 min)
- **U9.4** League card fully clickable. `MyLeaguesPage.tsx` `LeagueCard` (`:13-79`) — make the
  whole card the `Link` to `/leagues/{slug}`; remove the now-redundant "View" button (`:73-75`).
  Verify no nested-interactive a11y issue (the list card has no other interactive children). (~20 min)
- **U9.5** League-detail back button. `LeagueHomePage.tsx:46` — pass the `back` prop to
  `PageHeader` (the prop exists since U2.4) → top-left "← Leagues" chip to `/leagues`. (~10 min)
- **U9.6** Specials tab first. `PredictionsSubNav.tsx:4-8` — reorder so **Specials is leftmost**
  (Specials → Group → Knockout). Leave the `/predictions` route still rendering Group as the
  default landing (only the tab order changes; flag if the user later wants Specials as the
  default screen too — group predictions are the recurring daily action). (~10 min)
- **U9.7** Specials dropdown won't scroll (real bug). `components/ui/select.tsx:35-63` — the
  Radix `SelectContent` is `overflow-hidden` with **no max-height**, so the 48-team
  "top scoring team" list renders taller than the viewport with nothing to scroll. Add a capped
  height + scrollable viewport (`max-h-[min(20rem,var(--radix-select-content-available-height))]`
  + `overflow-y-auto`) and ensure `SelectScrollUpButton`/`DownButton` are present. One fix, every
  Radix select benefits. Reproduce on the SpecialsPage team picker on a phone-width viewport. (~30 min)

**Acceptance:** PIN inputs render 4 cells and don't overflow `max-w-sm`; backend rejects non-4-digit
PINs (test); original Robinsons raster renders on Login + Signup, no SVG reference left; "Create account"
is a visible secondary button on Login, "Forgot PIN?" still a small link; tapping anywhere on a league
card opens it (no separate View button); league detail shows a "← Leagues" back chip; Specials is the
leftmost predict sub-tab; the team-picker dropdown scrolls on a narrow viewport; all existing tests green.

---

## U10 — Forgot-PIN + first-run onboarding 🟢 Sonnet · ~3 h

Wires up the dead "Forgot PIN?" link, then adds the two first-run prompts the user asked for.

- **U10.1** Forgot-PIN frontend (backend already exists). The `/forgot-pin` link
  (`LoginPage.tsx:82-84`) currently dead-ends (no route → catch-all redirect). Build:
  (a) `/forgot-pin` request page → POST `/api/v1/auth/pin/reset-request` (`routers/auth.py:286-327`
  — confirm the exact request field: name vs email) → "check your email" confirmation; and
  (b) a reset-confirm page `/pin/reset/:token` → enter a new 4-digit `PinInput` → POST
  `/api/v1/auth/pin/reset` (`:330-355`, clears lockout) → success → redirect to `/login`. Add both
  routes to `App.tsx`. Handle invalid/expired-token + email-not-verified states. This **supersedes
  U2.3's "ask your league admin" copy** — remove/replace it. Tests for both pages. (~75 min)
- **U10.2** First-run notifications prompt. After the first successful login/signup, show a prominent
  modal: "🔔 Match alerts — strongly recommended" with **Enable** (calls the existing
  `hooks/usePushSubscription.ts` → triggers the OS permission prompt) + a smaller "Maybe later", and
  default the in-app notification *preferences* to all-on. Gate to once via a localStorage flag
  (e.g. `sss_notif_prompt_seen`, same pattern as `WelcomeCard`'s `sss_welcome_dismissed`).
  **iOS caveat (must handle):** push only works in the *installed* PWA — if `display-mode` is not
  `standalone`, show "Add to Home Screen first" guidance instead of the Enable button, and never claim
  push is "on" before the OS grants permission. (~50 min)
- **U10.3** Quick intro tour (*reverses round 2 Q-10*). A lightweight **custom** 3–4 slide
  press-through intro shown once on first run (localStorage `sss_tour_seen`), skippable: how scoring
  stacks (reuse `WelcomeCard` copy), predict before kickoff, knockout opens round-by-round, where the
  leaderboard/leagues live. **No tour library** (react-joyride/driver.js are fragile on mobile) — a
  simple modal carousel. (~45 min)

**Acceptance:** "Forgot PIN?" leads to a working request → email → reset-confirm flow against the
existing endpoints (no more dead link; admin-reset copy gone); a first-login notifications modal appears
once, enables push via the existing hook, defaults prefs on, and degrades to an install nudge when not
standalone; a once-only press-through intro tour shows on first run and is skippable; localStorage gates
prevent re-showing; tests green.

---

## U11 — Home screen rebalance 🟢 Sonnet · ~2.5 h

Trims the dashboard to the four things the user wants and surfaces the previous-match breakdown
(which already exists, just buried). Builds on U3.2's dashboard hierarchy work.

- **U11.1** Remove the 3 quick-link nav cards (Predictions/Knockout/Specials) from
  `DashboardPage.tsx` (`NAV_CARDS` `:366-369`, render `:474-478`) — pure duplication of the bottom
  bar. Replace with a **single contextual CTA**: pre-tournament, "Make your specials picks →"
  (`/predictions/specials`) — this keeps specials reachable from home per the user's ask. (~30 min)
- **U11.2** Replace the per-league full `LeagueCard`s (`:487-493`) with a **compact rank strip** — one
  tappable row per league showing the user's rank + points, linking to that league. Keep
  `CrossLeagueSummaryWidget` (`:457`, total points + avg rank). (~50 min)
- **U11.3** Promote + enrich the previous-match breakdown. Move `LatestResultCard` (`:501`) up to
  directly under `NextMatchCard` (`:463`), and enrich it from total-only to the **full breakdown**
  (Result ✓ +3 · Goal total ✓ +2 · Exact ✗ — → total) using the `points_breakdown`
  (`goals`/`result`/`exact`/`total`) already returned by `/players/{id}/predictions/recent`
  (`lib/types.ts:49-55`). **No backend change.** (~40 min)

Resulting home order: greeting → dismissible WelcomeCard → total points → Next Match (with "Predict now")
→ previous-match breakdown → compact league strip → pre-tournament specials CTA.

**Acceptance:** no Predictions/Knockout/Specials nav cards on home; a pre-tournament "specials picks" CTA
present; per-league info is a single compact rank strip (not full cards); the previous-match card sits
under Next Match and shows the 3-way points breakdown; total points still shown; tests green.

---

## U12 — Multi-use join code + invite UX 🟢 Sonnet · ~4 h

Replaces single-use invite tokens (the real cause of the "friends couldn't join" report — invites
deactivate on first claim at `routers/league_memberships.py:91-93`) with a reusable, human-typable
league join code, and sidesteps the iOS PWA deep-link problem entirely. Keep the existing single-use
`invites` table for any future per-person invite need; the join code becomes the everyday share path.

- **U12.1** Migration + generation. Add `join_code` to `leagues` (e.g. `String(8)`, unique, indexed);
  backfill existing leagues. Add `generate_join_code()` — 6 chars from an unambiguous alphabet
  (exclude `I/O/0/1`). Generate on league creation. (~40 min)
- **U12.2** Backend endpoints (all rate-limited; reuse the `claim_invite` membership logic):
  - `GET /leagues/by-code/{code}` → minimal `{name, member_count, max_members, privacy}` for the
    confirm step; 404 if not found.
  - `POST /leagues/join-by-code` `{code}` (authenticated, **multi-use** — does NOT deactivate the
    code): add membership if not already a member and not at `max_members`.
  - `POST /leagues/{slug}/join-code/rotate` (admin) → regenerate the code.
  Tests: multi-use (two players join one code), full-league rejection, already-member 409. (~80 min)
- **U12.3** "Join a league" screen. Code input → `by-code` lookup → **confirm card showing the league
  name** ("Join *Robbo's League*?") → Join. Entry points: a button on `MyLeaguesPage` (alongside
  Discover) + the empty-state CTA. (~50 min)
- **U12.4** Invite/share UX on `LeagueHomePage` — prominent **Invite** button using `navigator.share`
  (clipboard fallback) with a message + link `{origin}/join/{code}`. Extend the existing `/join/:token`
  route (`App.tsx:113`, `JoinPage`) to also accept a **join code** so the link is a working second door
  (new users sign up then auto-join by code; logged-in users one-tap join). (~50 min)
- **U12.5** `/welcome` get-app landing — platform-aware "Add to Home Screen" instructions; the generic
  link you share with friends who don't have the app yet. This + join-by-code is the agreed answer to
  the PWA deep-link question (no universal-links work). (~30 min)

**Acceptance:** one reusable join code per league (rotatable), backfilled for existing leagues; two
different players can join the same code; the code lookup shows the league name for confirmation before
joining; an Invite button opens the native share sheet with the link + code; `/join/<code>` works for
both new and logged-in users; a `/welcome` install landing exists; single-use `invites` still function;
tests green.

---

## U13 — Knockout/schedule skeleton + progression 🔴 Opus (extended thinking ON) · ~5 h

The foundational, judgment-heavy batch — seeds the data both the schedule and knockout picks read, and
resolves placeholders → real teams as the tournament progresses. Run on Opus.

> **Before coding:** grep `wc2026-architecture.md` for any existing knockout-seeding / bracket
> progression phase. If a numbered phase already owns this, fold this batch into it rather than
> duplicating. The 2026 format is 48 teams → 12 groups of 4 → **R32 (incl. 8 best third-placed)** → R16
> → QF → SF → 3rd place → Final. All 104 match dates/venues are published in advance; only the *teams*
> are TBD.

- **U13.1** Seed the 32 knockout matches (R32 ×16, R16 ×8, QF ×4, SF ×2, 3rd ×1, Final ×1) with real
  kickoff dates/venues + **positional placeholder source refs** (e.g. `home_source="winner_group_a"`,
  `away_source="runner_up_group_b"`; later rounds reference prior matches, e.g. `winner_match_73`).
  Confirm the `matches` table allows null team FKs and add placeholder/source columns if absent
  (migration). Result: full 104-match calendar (72 group + 32 KO). (~90 min)
- **U13.2** Schedule tab knockout view. `SchedulePage.tsx:244-252` — instead of the generic
  "No matches found" `EmptyState`, render the seeded knockout rounds with placeholder labels
  ("Winner Group A" / "Runner-up Group B"), grouped by round. (~45 min)
- **U13.3** Knockout picks per-round list. `KnockoutPredictionsPage.tsx` (`KNOCKOUT_STAGES` `:23-30`)
  — render the seeded rows as a per-round placeholder list (replace the `BracketTeaser` empty state
  `:583-595`; keep the teaser only if truly zero rows). Picks save against the seeded match ids. (~60 min)
- **U13.4** Progression logic (**the Opus bit**): resolve placeholders → real teams as group standings
  finalize (incl. the best-third-placed qualification table and its group-letter mapping into R32) and
  as knockout results settle. Pure, well-tested resolver. (~90 min)
- **U13.5** Optional read-only mini bracket on `BracketPage` from the same seeded data — the
  "see the whole tree" overview (picking still happens in the per-round list). (~30 min)

**Acceptance:** all 104 matches seeded incl. 32 knockout slots with dates + positional placeholders;
the schedule knockout view shows the round skeleton (no "No matches found"); knockout picks render as a
per-round placeholder list and save; placeholders resolve to real teams correctly as standings/results
settle (unit tests for the best-third-placed mapping and round-to-round advancement); optional read-only
bracket renders; `pytest` + Vitest green.

---

## U14 — Golden Boot player typeahead (real squad data) 🟢 Sonnet · ~6 h

Promoted from the round-4 Deferred list now that official WC2026 26-man squads have published.
Replaces the free-text Golden Boot input with a searchable combobox constrained to real squad
players, so predictions **and** admin awards match by player **id** instead of the current fragile
case-insensitive string compare.

> **Watch-outs before coding:**
> - **Naming collision:** the app already has `routers/players.py` + a `profiles`/players concept for
>   *league participants*. Name the footballer table/router **`squad` / `squad_players`** — do NOT
>   overload "players".
> - **No combobox exists.** Web deps are Radix dialog/label/select/slot only — no `cmdk`, no
>   `@radix-ui/react-popover`. U14.6 must add the shadcn Combobox stack (`cmdk` +
>   `@radix-ui/react-popover`) or build a lightweight custom typeahead on the existing input.
> - **RLS (carry R11):** a new PostgREST-exposed table must follow the R11 lockdown pattern (enable
>   RLS, revoke anon/authenticated writes) or the Supabase advisor flags `rls_disabled_in_public`. The
>   squad list is non-secret, so add an anon/authenticated SELECT policy. Use the R11 migration as the
>   template.
> - Depends on the existing `teams` table being populated (it is — all 48 known post-qualification). FK
>   squad players to it.

- **U14.1** Squad dataset + idempotent loader. Source the official 48 × 26 ≈ 1,250-player squads into a
  committed `apps/api/src/data/squads_2026.json` (full name, known-as, team, position, shirt number) and
  a re-runnable seed/loader (data migration or `seed_squads.py` run on deploy). Cover all 48 teams.
  **Data sourcing is the long pole** — if it can't be done cleanly in one sitting, split this into a prep
  data-task and keep U14.2–U14.6 as the batch. (~120 min)
- **U14.2** `squad_players` table + migration + RLS. uuid id, full_name, known_as, team_id FK→`teams`,
  position, shirt_number (nullable), is_active (default true). Name index for search. Enable RLS +
  revoke anon/authenticated writes + add an anon/authenticated SELECT policy, mirroring the R11
  migration. (~45 min)
- **U14.3** Search endpoint. New `routers/squad.py` — `GET /api/v1/squad/search?q=&limit=20`,
  case-insensitive prefix/substring match on full_name/known_as over `is_active` rows, ranked, returns
  id + name + team + flag + position. Rate-limited per the §8.3 pattern. (~45 min)
- **U14.4** Prediction stores player id. `special_predictions` — add `predicted_player_id` (nullable
  FK→squad_players); keep `predicted_player_name` denormalised for display. Update the golden_boot upsert
  (`routers/specials.py:177-182`) to accept + store the id and resolve the name from it. Migration. (~45 min)
- **U14.5** Award by id. Replace the case-insensitive string compare at `routers/specials.py:300` (and
  the `winner_player_name` award field) with a `winner_player_id` id-match; admin picks the winner from
  the same squad list. Verify re-scoring credits exactly the players who picked the winner. (~45 min)
- **U14.6** Frontend combobox. Add the shadcn Combobox stack (`cmdk` + `@radix-ui/react-popover` — none
  exists today) and replace the free-text input (`SpecialsPage.tsx:254-275`) with a debounced typeahead
  querying `/squad/search`, showing name + team flag + position, selecting → stores the id.
  Loading/empty/error states. Reuse the same combobox in the admin award UI (U14.5). Vitest. (~60 min)

**Acceptance:** seeded `squad_players` covers all 48 teams (~26 each — test asserts counts);
`/squad/search` returns ranked matches and is rate-limited; the Golden Boot prediction stores a
`predicted_player_id` and the free-text path is gone from the UI; admin awards by selecting the winning
player (id match, not string); re-scoring credits exactly the players who picked the winner (test); the
new table has RLS enabled + anon writes revoked + anon SELECT allowed (no `rls_disabled_in_public`
advisor finding); the SpecialsPage combobox searches and selects a real player with team + flag;
`pytest` + Vitest + a11y green.

---

## Deferred (own batch, later)

- **Golden Boot player typeahead** — now scoped as **U14** above (official squads have published). Until
  U14 ships, Golden Boot stays the free-text input (`SpecialsPage.tsx:254-275`).
- **Public/private league split in the Leagues tab** — considered and declined for now: when viewing
  leagues you're *in*, membership matters more than visibility, and the privacy badge already
  distinguishes them. Keep My Leagues + a polished Discover.

---

## Close-out (round 4)

Per batch: push `feat/premium-polish-4` → `/phase-closeout U<n>` (CI poll + ff-merge; manual fallback if
the `U` prefix isn't recognised) → lean `session-log.md` entry → strike the row in the round-4 table
above. Independent of rounds 2–3 — ff-merge each batch as it goes green. `/next-batch-prompt polish` will
surface **U14** as the next un-struck batch.

---

# Round 5 — batches (U15–U17) — added 2026-06-02

**U15 (invite/share polish)** shipped ahead of being written up here — an ad-hoc batch taken after
round 4's U14, recorded below as a struck row for ledger completeness (commits `87aa800` +
`95a8aa9`). **U16 (home points-hero)** is the active batch, from a 2026-06-02 home-screen design
pass with the user: round 4's U11 rebalanced the dashboard but kept the `CrossLeagueSummaryWidget`,
which leads with **average rank** and buries total points as a tail fragment of a sentence. U16
flips the lead metric: **total points is the hero**, and per-league **rank movement** ("this result
moved you ↑2") is surfaced inline. **Independent of prior rounds** — U16 gets its own fresh branch
(`feat/premium-polish-8`; pick the next free number if taken), ff-merge once green.
`/next-batch-prompt polish` reads this file's `## U<n>` acceptance inline, so no manual pasting
needed.

**Decisions locked in the pass (a couple revise U11):**
- **Points hero = pure number.** The dashboard header is the global `total_points` (the one true
  cross-league number — predictions are scored once and count in every league, MD-1), large, with
  the player name as a subline. No secondary rank/breakdown on the hero.
- **Cross-league average-rank widget = removed.** *Reverses U11.2's "Keep
  CrossLeagueSummaryWidget".* Average rank is a per-league concept flattened into one mushy number
  (and meaningless for single-league players); per-league rank lives on the league rows instead.
- **"Recent activity" = inline, not a separate feed.** Movement shows as (a) a rank-delta badge on
  each league row and (b) a one-line impact on the Latest Result card — never a standalone feed
  (empty between matches, duplicates the rows).
- **Tapping a league = navigate to its leaderboard** (current behaviour; no inline expand).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U15~~ | ~~🟢 Sonnet~~ | ~~—~~ | ~~invite/share polish~~ | ✅ Shipped 2026-06-02 (87aa800, 95a8aa9) |
| ~~U16~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U16.1–U16.5~~ | ✅ Shipped 2026-06-02 (1efeb85, 98c3730) |
| ~~U17~~ | ~~🟢 Sonnet~~ | ~~~5.5 h~~ | ~~U17.1–U17.6~~ | ✅ Shipped 2026-06-03 (21afe57, b06bf61, 706c0c4) |

---

## ~~U15 — Invite/share polish~~ 🟢 Sonnet · ✅ shipped 2026-06-02

Shipped ahead of being written up here (ad-hoc, after round 4's U14); recorded for ledger
completeness — full detail in the commits + session-log.

- Rich invite share message + native share sheet (`navigator.share`) with clipboard fallback, plus
  a join-page lift. New `apps/web/src/lib/invite.ts`; edits to `JoinPage.tsx`,
  `LeagueAdminInvitesPage.tsx`, `LeagueHomePage.tsx`; tests `invite.test.ts` + `e2e/join.spec.ts`.
- **Commits:** `87aa800` (feat) + `95a8aa9` (e2e fix). **Close-out status:** CI/merge not captured
  at write-up time — confirm before relying on it as merged.

---

## U16 — Home points-hero + inline rank movement 🟢 Sonnet · ~3 h

Flips the dashboard's lead metric to total points and surfaces per-league rank movement inline,
reusing data the home page already fetches. Builds on U11 (dashboard order) and U11.3 (Latest
Result full breakdown — keep it, add the impact line beneath).

> **Watch-outs before coding:**
> - **Snapshot timestamp ties.** `LeaderboardSnapshot.snapshot_at` can tie across rows written in
>   the same scoring transaction — order each player's snapshots by `snapshot_at DESC` **with a
>   deterministic secondary key** (a monotonic snapshot id/sequence if one exists, otherwise the
>   triggering match's `kickoff_utc`), never `snapshot_at` alone, or the "latest two" — and hence
>   the delta — is non-deterministic.
> - **`per_league` already carries `rank`, `member_count`, `name`, `slug`** (see
>   `routers/me.py` `cross-league-summary`). The compact rows can read rank from there and **drop
>   their own `/leagues/{slug}/leaderboard` fetch** — which also sidesteps the C-2 duplicate-rows
>   bug on the dashboard. Verify the summary's rank source is snapshot-based and dedup-safe.
> - **Keep `avg_rank` in the response** (back-compat) even though the UI stops rendering it; a
>   later cleanup can drop it if no other consumer exists. Don't break the response shape.

- **U16.1** Points hero. Remove `CrossLeagueSummaryWidget` (`DashboardPage.tsx:27-76` def, `:368`
  render) and the plain `<h1>` greeting (`:360-363`). Add a `PointsHero` at the very top of the
  page: large `total_points` (mono, `text-4xl`+, primary) with a "POINTS" eyebrow and a smaller
  "Welcome back, {displayName}" subline. Pure number — no avg-rank, no breakdown. Reads
  `total_points` from the existing cross-league-summary query. (~30 min)

- **U16.2** Hero zero / pre-tournament state. Before any result is scored (`total_points === 0`),
  don't render a deflating bare "0" — keep the hero but swap the subline to a gentle nudge (e.g.
  "Your tally starts when the first results land · WC kicks off 11 Jun"). The tournament starts
  ~2026-06-11, so this is the launch-day state for every player. (~15 min)

- **U16.3** Backend — rank delta on the summary. Extend each `per_league` entry of
  `GET /api/v1/me/cross-league-summary` (`routers/me.py:42-132`) with `rank_delta: int | null` and
  `triggered_by_match_id: str | null`. For each (player, league): take the two most recent
  `LeaderboardSnapshot` rows (ordered per the tie-safe rule in the watch-out); `rank_delta =
  prior.rank − latest.rank` (positive = moved up); `triggered_by_match_id =
  latest.triggered_by_match_id`. `null` when fewer than 2 snapshots. Update the `CrossLeagueSummary`
  response model and the frontend `lib/types.ts` shape. Pytest: two snapshots → correct signed
  delta; single snapshot → null; equal ranks → 0; deterministic under tied `snapshot_at`. (~75 min)

- **U16.4** League rows from one call + delta badge. Repoint `CompactLeagueRow`
  (`DashboardPage.tsx:151-192`) to read `rank` / `member_count` / `rank_delta` from the
  cross-league-summary `per_league` array instead of issuing a per-league
  `/api/v1/leagues/{slug}/leaderboard` query each (N+1 → 1). Render a compact delta badge next to
  the rank: `↑2` (success), `↓1` (danger/muted), `▬` or hidden for 0/null. Tap still routes to
  `/leagues/{slug}/leaderboard`. (~45 min)

- **U16.5** Impact line on Latest Result. In `LatestResultCard` (`DashboardPage.tsx:198-276`),
  under the existing points breakdown, render a one-line movement summary when the card's
  `match_id` equals a `per_league` entry's `triggered_by_match_id`: e.g. "↑2 in The Steele Sheet ·
  ↑1 in Office League". Build the league→delta list from the per_league array filtered to that
  match; omit the line entirely when nothing traces to this result (no snapshot, deltas all 0, or
  match mismatch). This is the "score → consequence" narrative, attached to its cause. (~30 min)

**Acceptance:**
- No `CrossLeagueSummaryWidget` and no average-rank number anywhere on the dashboard.
- Dashboard top is the points hero: global `total_points`, pure number + "POINTS" + name; the
  zero / pre-tournament state is a gentle nudge, not a bare "0".
- `cross-league-summary` `per_league` entries return `rank_delta` + `triggered_by_match_id`; delta
  is signed correctly (up = positive), `null` below 2 snapshots, deterministic under tied
  `snapshot_at`; `avg_rank` still present (back-compat); pytest green.
- League rows render from the single summary call (no per-league leaderboard fetches remain on the
  dashboard) and show a ↑/↓/▬ delta badge; tapping a row opens that league's leaderboard.
- Latest Result shows the per-league movement impact line when the deltas trace to that match, and
  omits it otherwise.
- Home page issues one request for hero + rows + impact (the N+1 fetch is gone).
- Vitest covers the hero zero state, the delta-badge rendering, and the impact-line match/omit
  logic; all existing Vitest + a11y tests green.

---

## U17 — Home page redesign: stat strip + smart to-do + results roll-up 🟢 Sonnet · ~5.5 h

From a 2026-06-03 home-screen design pass with the user. U16 fixed the *lead metric* (points hero)
but left the page as six equal-weight full-width cards with no hierarchy, a single-match results card
that's invisible pre-tournament and thin on heavy match days, and three scattered "do something"
prompts (NextMatch "Predict now", `SpecialsCTA`, `WelcomeCard`). U17 restructures the home page into
**hierarchical zones** with an **adaptive top** that answers the two questions a player actually opens
the app with — *"what do I need to do?"* and *"how did I just do?"* — reusing the U16 backend. Own
fresh branch (`feat/premium-polish-9`; next free number if taken), ff-merge once green.

**Design decisions locked in the pass (a couple revise U16):**
- **Stat strip replaces the full-width hero.** Two compact tiles — `POINTS` + best-league `RANK`
  (with ↑/↓) — pinned at the very top. *Revises U16.1's full-width PointsHero* (the giant number ate
  the viewport for two glanceable facts; the user asked for points + next-match to stop being
  full-width).
- **Adaptive top zone.** Pre-tournament (nothing scored) the home leads with the "next up" to-do;
  once any result is scored it leads with the results roll-up. One page, two modes — the launch-day
  state (pre-11-Jun) is the to-do, not an empty results void.
- **One action surface, not three.** A single priority-ranked "Next up" card subsumes the NextMatch
  predict CTA and the standalone `SpecialsCTA`; `WelcomeCard` drops below it. Pick the single most
  important next action and make it the anchor.
- **Results = daily roll-up, not one match.** "Yesterday: +14 · 6 matches", tap to expand per-match
  breakdowns. *Revises U16.5's single `LatestResultCard`* (one match badly undersells a heavy day).
- **Cross-league movement = one summary line, ≥2 leagues only.** Single-league players are already
  served by the per-row badge (U16.4); a consolidated "↑2 Steele · ↓1 Office" line only appears at
  2+ leagues.

> **Watch-outs before coding:**
> - **Build on U16, don't undo it.** `cross-league-summary` (`routers/me.py`) already returns
>   `total_points`, per-league `rank` + `rank_delta` + `triggered_by_match_id`. The stat strip,
>   league rows, and movement composition all read from it — do **not** add new rank/delta queries.
>   The new `/me/home` endpoint is only for the *to-do* + *results roll-up* that the summary doesn't
>   carry.
> - **Snapshot timestamp ties (again).** Any snapshot ordering reuses the U16 tie-safe key
>   `(snapshot_at DESC, id DESC)`, never `snapshot_at` alone.
> - **Matchday clustering is by the match's UTC date, not the player's tz.** Group the roll-up on
>   `kickoff_utc::date` so it's deterministic server-side; the frontend renders each kickoff in
>   player-tz via `formatInTimeZone` as everywhere else (CLAUDE.md time rules). Never group on
>   `snapshot_at`.
> - **"Predicted?" must respect lock, not just existence.** A match past kickoff with no prediction
>   is a *missed* match, not an actionable to-do — exclude locked/kicked-off matches from
>   `upcoming_unpredicted` so the to-do never tells a player to predict a match they can no longer
>   enter.
> - **Reuse the breakdown chip markup.** Extract U16's Result/Goals/Exact chip row from
>   `DashboardPage.tsx` into a shared `PointsBreakdownRow` rather than duplicating it in the roll-up's
>   expanded rows.

- **U17.1** Backend — `GET /api/v1/me/home` (to-do + results roll-up). New endpoint in
  `routers/me.py`, returning two blocks:
  - `todo`: `specials_submitted` (bool — has the caller a submitted special prediction?),
    `specials_lock_at` (str|null), `upcoming_unpredicted` (int — scheduled, **not-yet-locked**
    matches with no prediction by the caller), `next_match`
    (`{ id, kickoff_utc, home_label, away_label, predicted }` | null).
  - `rollup`: the most recent completed **matchday** the caller predicted — `matchday` (UTC date
    str | null), `points_gained` (int), `match_count` (int), `matches` (list of
    `{ match_id, home_label, away_label, home_flag, away_flag, actual_home, actual_away,
    predicted_home, predicted_away, points_breakdown }`). `null`/empty before any result lands.
  Pydantic response models; reuse the tie-safe ordering. Pytest: to-do counts unpredicted upcoming
  and **excludes locked matches**; `specials_submitted` true/false; roll-up groups the latest UTC
  matchday and sums points; empty pre-tournament. (~90 min)

- **U17.2** Stat strip (replaces full-width hero). Replace `PointsHero` (U16.1) with a `StatStrip`:
  a 2-col row of compact tiles — `POINTS {total_points}` and `RANK #{best} {↑/↓ delta}`. "Best" =
  the caller's lowest rank number across `per_league` (append "best of {leagues_count}" when
  `leagues_count > 1`). Preserve the U16.2 zero/pre-tournament state (nudge subline under the strip,
  no bare "0"; rank tile shows "—"). Reads cross-league-summary only. (~45 min)

- **U17.3** "Next up" to-do card. New `NextUpCard` driven by `/me/home` `todo`. Priority ladder,
  top match wins:
  1. specials open + not submitted → "Make your Specials picks" → `/predictions/specials`
  2. `next_match` unpredicted + not locked → "Predict {home} vs {away} · locks in {countdown}" →
     `/predictions` (reuse `useCountdown`)
  3. `upcoming_unpredicted > 1` → "{n} matches open to predict" → `/predictions`
  4. all done → calm "You're all set · next lock in {countdown}" (no alarm colour, reassuring)
  Remove the standalone `SpecialsCTA` (`DashboardPage.tsx:282-308` def, `:407` render) and the
  duplicate "Predict now" button inside `NextMatchCard` (`:137-141`) — this card is now the single
  action surface. (~75 min)

- **U17.4** Results roll-up card. New `ResultsRollupCard` driven by `/me/home` `rollup`, replacing
  `LatestResultCard` (`DashboardPage.tsx:198-276`). Collapsed header:
  "{matchday}: +{points_gained} · {match_count} matches". Expand → per-match rows using the shared
  `PointsBreakdownRow` (extracted from U16's chip markup). Beneath, the cross-league movement impact
  line composed from cross-league-summary `per_league` filtered to the roll-up's match ids (reuse
  U16.5 logic, now over the whole cluster). Omit the entire card pre-tournament (`rollup` null).
  (~75 min)

- **U17.5** Cross-league movement summary + leagues. Keep U16's `CompactLeagueRow` rows. Above them,
  when `leagues_count >= 2` and any `rank_delta` is non-null/non-zero, render a one-line summary:
  "Across your leagues: ↑2 Steele · ↓1 Office" (same ↑/↓ glyph vocabulary as the row badges and the
  roll-up impact line). Omit at 1 league (the row badge covers it) or when there's no movement.
  (~30 min)

- **U17.6** Adaptive composition + WelcomeCard reposition. Assemble the page: `StatStrip` pinned at
  top; then **if `rollup` is present** (results exist) order = roll-up → next-up → leagues, **else**
  (pre-tournament) order = next-up → leagues (no roll-up zone). Move `WelcomeCard` below the next-up
  card (still dismissible). Net: ~3 hierarchical zones replacing today's six flat cards. (~30 min)

**Acceptance:**
- Home top is a 2-tile stat strip (Points + best Rank with ↑/↓), not a full-width hero; U16's
  zero/pre-tournament nudge is preserved (no bare "0").
- `GET /api/v1/me/home` returns `todo` (specials_submitted, specials_lock_at, upcoming_unpredicted
  **excluding locked**, next_match) and `rollup` (latest UTC matchday, points_gained, match_count,
  matches[]); empty/null pre-tournament; pytest green incl. the locked-match exclusion and matchday
  grouping.
- One "Next up" card drives all actions via the priority ladder; the standalone `SpecialsCTA` and the
  NextMatch "Predict now" button are gone (single action surface).
- Results show as an expandable daily roll-up (header sum + per-match breakdowns) reusing a shared
  `PointsBreakdownRow`; the card is omitted pre-tournament.
- A cross-league movement summary line appears only at ≥2 leagues with real movement; single-league
  relies on the row badge; U16 `CompactLeagueRow` rows + `rank_delta` badges unchanged.
- Top zone is adaptive: to-do leads pre-tournament, roll-up leads once results exist; `WelcomeCard`
  sits below the to-do.
- Home page issues at most two requests (cross-league-summary + `/me/home`); no per-league N+1
  reintroduced.
- Vitest covers the stat-strip tiles + zero state, the to-do priority ladder
  (specials-first / match-next / all-done), the roll-up expand + pre-tournament omit, the ≥2-league
  movement summary gate, and the adaptive ordering; all existing Vitest + a11y + pytest green.

---

## Close-out (round 5)

Per batch: push the batch branch (`feat/premium-polish-8` for U16, `feat/premium-polish-9` for U17,
or the next free number) → `/phase-closeout U<n>` (CI poll + ff-merge; manual fallback if the `U`
prefix isn't recognised) → lean `session-log.md` entry → strike the batch's row in the round-5 table
above. Independent of rounds 2–4 — ff-merge once green.

---

# Round 6 — home hub redesign — batches (U18–U19) — added 2026-06-03

From a 2026-06-03 home-screen design pass with the user (and a world-class UX review of the build).
U17 gave the home page hierarchical zones, but the user wants the home to become the daily **hub**:
a warmer top, the rank stat retired (it duplicates the Leagues strip), the time-critical to-do split
out from a browse-everything surface, an **upcoming-matches carousel** you can predict/update from
inline, and a read-only **specials** summary. The UX review converged the proposals on three points:
(1) **merge the greeting into the hero** so the top says something instead of stacking decorative
rows; (2) **cap the carousel** (~5–8) and link to Schedule so it stays a shortcut, not a 104-match
scroller; (3) **keep the bottom nav as-is** — make the home a *hub* whose sections deep-link to the
existing tabs (spokes) rather than re-tabbing. **Independent of prior rounds** — own fresh branch
per batch (`feat/premium-polish-10` for U18, next free number if taken), ff-merge once green.
`/next-batch-prompt polish` reads this file's `## U<n>` acceptance inline, so no manual pasting needed.

**Design decisions locked in the pass (some revise U17):**
- **Greeting merged into the hero.** One block — "Welcome back, {name}" subline + large
  `total_points` + a "next lock in {countdown}" line — not two stacked rows.
- **Rank retired from the hero.** *Revises U17.2's POINTS+RANK stat strip.* Per-league rank already
  lives on the Leagues rows (U16.4), which becomes the single home for rank.
- **Hero = Points + next-lock countdown.** Countdown is the soonest of `next_match.kickoff_utc` /
  `specials_lock_at` (when unsubmitted) — both already in `/me/home`; reuse `useCountdown`.
- **"How it works" = persistent collapsible, just below the hero.** *Revises U17.6's dismiss-forever
  `WelcomeCard`.* Default expanded; once collapsed it stays as a re-openable "How it works ▸" row
  (persisted), never gone forever.
- **Urgent vs. browse split.** A self-hiding **Urgent** zone carries only genuinely time-pressured
  actions (specials closing + unsubmitted; a not-yet-locked match unpredicted and locking soon); the
  browse/manage-ahead job moves to the carousel. No always-on "you're all set" card.
- **Upcoming-matches carousel (read + edit inline).** Horizontally scroll-snapped cards for the next
  ~5–8 upcoming matches; each shows your saved prediction or "not predicted," editable in place;
  ends with a **"See full schedule →"** card → `/schedule`. Group-stage scores **v1** (knockouts are
  winner-picks — a different mode — and open round-by-round later).
- **Specials = read-only summary strip.** Pick state + lock countdown, links out to the Specials page
  to edit. No inline editing / no dropdowns-in-a-carousel.
- **Bottom nav unchanged.** Keep Home · Schedule · Predict · Leagues · More (see `TabBar.tsx`). The
  home is a hub; its sections deep-link to those tabs. **Do not re-tab or drop Schedule** — the
  capped carousel + "See full schedule →" *strengthens* Schedule's distinct job rather than replacing
  it. Keep iconography consistent (Pencil = edit a prediction on both home cards and the Predict tab).
- **Phased.** U18 = home refresh on existing data (🟢 Sonnet). U19 = carousel + the shared
  prediction-editor extraction it depends on (🔴 Opus — stateful refactor of a core, well-tested page
  with offline/optimistic/realtime logic).

**Target home IA (after both batches):**
1. greeting + points hero (+ next-lock countdown)
2. how it works (collapsible, collapsed-by-default for returning users)
3. urgent (self-hiding)
4. upcoming-matches carousel  *(U19)*
5. results roll-up
6. specials strip (read-only)
7. leagues

> **Watch-outs before coding:**
> - **Builds on U17.** Close out / merge U17 first and branch from its tip; U18 revises the U17 stat
>   strip + WelcomeCard, it doesn't start from U16.
> - **Extract, don't fork the editor.** The match-prediction UX already exists as `PredictionCard`
>   (a *private* fn in `PredictionsPage.tsx`) wired to ~150 lines of editing logic (debounced
>   autosave `PUT /predictions/{matchId}`, **offline write-queue** via `enqueuePrediction`, optimistic
>   local state, error rollback, realtime result-flash). U19 must extract these into a shared
>   component + hook and have **both** the Predictions page and the home carousel consume them — never
>   a second, divergent editor on home.
> - **Cap the carousel.** Next ~5–8 only + "See full schedule →"; never render all 104 in a scroller
>   (bad carousel *and* it would make the Schedule tab redundant).
> - **Group-stage only (v1).** `/matches?stage=group`; exclude knockout/locked/kicked-off matches.
> - **De-dup specials.** The Urgent zone owns the unsubmitted-and-closing nudge; the strip is the
>   steady-state read-only summary — don't show the same "make your picks" prompt twice.
> - **Carousel a11y.** Keyboard-scrollable + ARIA list/group semantics + scroll-snap; score inputs
>   inside the track must stay operable on touch (scroll-vs-interact); respect reduced-motion.
> - **Request budget.** U18 stays on the existing two home calls (cross-league-summary + `/me/home`);
>   U19 adds `/matches?stage=group` + `/predictions/me` (document it; no per-card N+1).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U18~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U18.1–U18.6~~ | ✅ Shipped 2026-06-03 |
| ~~U19~~ | ~~🔴 Opus~~ | ~~~5 h~~ | ~~U19.1–U19.5~~ | ✅ Shipped 2026-06-03 |
| ~~U20~~ | ~~🔴 Opus~~ | ~~~5 h~~ | ~~U20.1–U20.8~~ | ✅ Shipped 2026-06-04 |

---

## U18 — Home hub: greeting-hero, collapsible how-it-works, urgent split, specials strip 🟢 Sonnet · ~3 h

Reshapes the U17 home into the hub top — all on the data the page already fetches (no new requests).

- **U18.1** Greeting + points hero (merge). Revise `StatStrip` (U17.2) into a single hero block:
  drop the RANK tile entirely; render "Welcome back, {displayName}" (subline) + large `total_points`
  (POINTS eyebrow, mono/primary) + a "next lock in {countdown}" line. Countdown = soonest of
  `next_match.kickoff_utc` / `specials_lock_at` (when unsubmitted) from `/me/home`; reuse
  `useCountdown`. Preserve the U16.2 zero/pre-tournament nudge (no bare "0"). Rank now lives only on
  the Leagues rows. (~45 min)
- **U18.2** "How it works" → persistent collapsible. Convert `WelcomeCard` from dismiss-forever
  (`sss_welcome_dismissed`) to a disclosure: a "How it works" header with a chevron, expand/collapse
  state persisted (new key e.g. `sss_howitworks_collapsed`), **default expanded**, rendered directly
  below the hero. Keep the three facts + "Full rules" link. Accessible disclosure (button
  `aria-expanded` + labelled region). (~40 min)
- **U18.3** Urgent zone (self-hiding). Rework `NextUpCard` (U17.3) into an **Urgent** section that
  renders **only** when there's a time-pressured action: specials open + unsubmitted, or a
  not-yet-locked `next_match` unpredicted (lead with its countdown), or `upcoming_unpredicted > 1`
  locking soon. When nothing is urgent → render nothing (drop the always-on priority-4 "all set"
  card; the hero countdown already reassures). (~40 min)
- **U18.4** Specials read-only strip. New compact `SpecialsStrip` (read-only) showing pick state +
  lock countdown, linking to `/predictions/specials`. Uses `/me/home` `specials_submitted` +
  `specials_lock_at` (no new request). Steady-state summary only — defers the unsubmitted-and-urgent
  nudge to U18.3 (no duplication). (Optional later: a `{n}/6` count via a small `/me/home` add.)
  (~25 min)
- **U18.5** Hub-and-spoke deep-links. Verify each home section routes to its destination: roll-up
  match → match detail; Leagues strip → `/leagues`; specials strip → `/predictions/specials`;
  (carousel "See full schedule" lands in U19). No bottom-nav structural change; keep Pencil = edit
  iconography consistent with the Predict tab. (~15 min)
- **U18.6** Compose + tests. Fixed, self-hiding order: hero → how-it-works → urgent → results roll-up
  → specials strip → leagues. Vitest: hero (points + countdown, **no** rank, zero state),
  how-it-works expand/collapse persistence, urgent self-hide when nothing urgent, specials-strip
  states, ordering. (~35 min)

**Acceptance:**
- Hero is one block — "Welcome back, {name}" + total points + next-lock countdown; **no rank tile**
  (rank only on the Leagues rows); the U16.2 zero/pre-tournament nudge is preserved.
- "How it works" is a persistent collapsible below the hero (not dismiss-forever); collapsed state
  persists across reloads; default expanded; accessible disclosure.
- The Urgent zone renders only when something is genuinely time-pressured and renders nothing
  otherwise (no always-on "all set" card).
- A read-only specials strip shows pick state + lock countdown and links to the Specials page; no
  inline editing; it does not duplicate the urgent specials nudge.
- Home sections deep-link to their tabs (hub-and-spoke); the bottom nav is unchanged.
- Home still issues only the two existing requests (cross-league-summary + `/me/home`).
- Vitest + a11y green; all existing tests pass.

---

## U19 — Upcoming-matches carousel + shared prediction editor 🔴 Opus · ~5 h

The judgment-heavy batch: extract the prediction-editing stack so home and the Predictions page share
one implementation, then build the carousel on top. Run on Opus.

- **U19.1** Extract `PredictionCard` to `apps/web/src/components/PredictionCard.tsx` (today a private
  fn in `PredictionsPage.tsx`) — props-driven, pixel- and behaviour-identical for the Predictions
  page. (~45 min)
- **U19.2** Extract the editor into `apps/web/src/hooks/usePredictionEditor.ts`: debounced autosave
  (`PUT /predictions/{matchId}`), optimistic local state, **offline write-queue** (`enqueuePrediction`),
  error rollback, and the realtime result-flash subscription. Refactor `PredictionsPage` to consume it
  with full parity; re-green its Vitest. (~90 min)
- **U19.3** `UpcomingMatchesCarousel` on home. Fetch `/api/v1/matches?stage=group` +
  `/api/v1/predictions/me`; show the next ~5–8 **scheduled, not-locked** matches as scroll-snapped
  cards reusing `PredictionCard` + `usePredictionEditor` (inline edit), each showing the saved
  prediction or "not predicted"; end with a "See full schedule →" card → `/schedule`. Knockouts
  excluded (v1). (~75 min)
- **U19.4** Carousel a11y + polish: keyboard-scrollable track, ARIA list/group semantics + labels,
  CSS scroll-snap, reduced-motion respected, score inputs operable on touch inside the track. (~45 min)
- **U19.5** Tests: Vitest for the carousel (cap, predicted/unpredicted states, inline edit-save via
  the shared hook, see-full-schedule link) and the extracted hook; PredictionsPage tests re-green;
  a11y green. (~45 min)

**Acceptance:**
- `PredictionCard` + `usePredictionEditor` are shared modules; `PredictionsPage` consumes them with no
  behavioural regression (offline / optimistic / realtime parity; its tests green).
- Home shows an upcoming-matches carousel capped at the next ~5–8 group-stage matches, each rendering
  the saved prediction or "not predicted," editable inline (debounced, offline-safe), ending with
  "See full schedule →" → `/schedule`.
- Knockout matches are excluded (group-stage scores v1).
- The carousel is keyboard-accessible, ARIA-labelled, scroll-snapped, and reduced-motion-safe.
- Added home requests are documented (`/matches?stage=group` + `/predictions/me`); no per-card N+1.
- Vitest + a11y green; all existing tests pass.

---

## Close-out (round 6)

Per batch: push the batch branch (`feat/premium-polish-10` for U18, then the next free number for
U19) → `/phase-closeout U<n>` (CI poll + ff-merge; manual fallback if the `U` prefix isn't
recognised) → lean `session-log.md` entry → strike the batch's row in the round-6 table above.
Independent of prior rounds — ff-merge once green. **U18 builds on U17**, so close out U17 first.

---

# Premium polish round 7 — snags backlog (U21–U24)

Source: user-reported snags, 2026-06-04. Design decisions were locked with the user in
that session (see **Decisions** below — do not re-litigate). Same workflow as earlier
rounds: one conceptual area + one model per batch, ship-able in a focused session, off the
next free `feat/premium-polish-<n>` branch (after U20's `feat/premium-polish-12`).

Mark batches complete by striking through the row.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U21~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U21.1–U21.5~~ | ✅ Shipped 2026-06-04 |
| ~~U22~~ | ~~🔴 Opus~~ | ~~~3.5 h~~ | ~~U22.1–U22.3~~ | ✅ Shipped 2026-06-04 |
| ~~U23~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U23.1–U23.3~~ | ✅ Shipped 2026-06-05 |
| ~~U24~~ | ~~🔴 Opus~~ | ~~~3 h~~ | ~~U24.1–U24.4~~ | ✅ Shipped 2026-06-05 |

**Dependencies:** U21 and U23 are independent. **U24 depends on U22** — the per-match
knockout lock from U22.1 defines when knockout predictions become visible in U24's profile
reveal. Suggested order: U21 → U22 → U23 → U24.

**Privacy invariant (applies to U22 + U24):** no endpoint may ever return a player's
prediction before that prediction locks. Reuse the existing lock gate; U24 must ship a
regression test asserting pre-lock predictions never leak.

---

## Decisions (locked 2026-06-04)

- **Avatars (U23):** full photo upload. New `profiles.avatar_url`; Supabase Storage bucket
  + access policy; client-side resize to ~512 px square, ~2 MB cap; no auto-moderation
  (invite-only league of ≤15 trusted people). Existing initials `Avatar`
  (`apps/web/src/components/ui/avatar.tsx`) is the fallback.
- **Knockout lock (U22.1):** switch from round-level to per-match. Keep the per-match
  kickoff lock; drop the round-level condition. Safe — sibling knockout ties are
  independent, so there's no info-leak reason for the round lock.
- **"Round" (U22.2) = stage:** group stage is ONE round; r32/r16/qf/sf/final each their
  own. "Round points" = points in the current (furthest-progressed) stage, resetting per
  stage.
- **"Today's points" (U22.2):** the viewer's local calendar day, computed per-viewer at
  query time from `profiles.timezone` (not a stored column, not UTC).
- **Profile reveal (U24) = all:** group predictions (reveal at lock), specials (reveal once
  the tournament starts), knockout bracket (reveal per-match).

---

## Current state already in the repo (verify, then build on it — do NOT rebuild)

- **Leaderboard** `apps/web/src/pages/LeaderboardPage.tsx`: rank, name (already links to
  `/players/:id`), total points, expand row with Match/Knockout/Special category sums.
  "By round" (`RoundLeaderboardPage`) + "History" views already exist. Snapshots are
  cumulative totals with `snapshot_at` + `triggered_by_match_id`
  (`apps/api/src/services/leaderboard.py`) — temporal deltas are DERIVABLE, not stored.
- **Match lock:** group matches lock per-match at kickoff (`apps/api/src/scheduler.py`
  `lock_due_matches`). Knockout predictions use round-level lock
  (`apps/api/src/routers/knockout_predictions.py` `_is_round_locked` → true if ANY match in
  the stage left `scheduled`); reveal gate 403s pre-lock. ← U22.1 changes this.
- **Team placeholders:** `apps/api/src/models/match.py`
  `home_team_placeholder` / `away_team_placeholder` (String(50), e.g. "Runner-up Group F",
  "Winner of Match 73"). Rendered raw in `SchedulePage.tsx` + `PredictionsPage.tsx` → overflow.
- **PageHeader** `apps/web/src/components/PageHeader.tsx` already supports a `back` chip and
  a `showBack` chevron — league sub-pages just don't pass them.
- **Theming** fully built: `apps/web/src/contexts/ThemeContext.tsx` (light/dark/system,
  persisted, updates the theme-color meta) + a 3-way toggle in Settings. `TopBar.tsx`
  doesn't expose it.
- **Dup-join** already enforced: `UniqueConstraint(league_id, player_id)`
  ("uq_league_memberships_league_player", `apps/api/src/models/league_membership.py`) +
  join endpoint returns ALREADY_MEMBER (`apps/api/src/routers/leagues.py` `join_league`).
  Only residual = one-human-two-accounts (a unique-verified-email control) — optional, low
  priority.
- **Player profile** ~70 % built: `apps/web/src/pages/PlayerProfilePage.tsx` (stats,
  best/worst round, head-to-head vs you, recent settled predictions w/ breakdown). Reveal
  gate is correct: `apps/api/src/routers/players.py` recent-predictions endpoint returns
  settled-only (`points_awarded IS NOT NULL`) + a shared-league check. U24 EXTENDS this to
  locked-but-unsettled predictions + specials + knockout, reusing the post-lock comparison
  logic in `MatchDetailPage` / `ComparePage`.
- **Avatar** initials component exists (`apps/web/src/components/ui/avatar.tsx`); the
  `Profile` model (`apps/api/src/models/profile.py`) has no avatar column.

---

## U21 — Quick polish 🟢 Sonnet · ~3.5 h

Five independent, low-risk fixes. Frontend-only except U21.4's test.

- **U21.1** (snag #3) Team-less match rendering: stop rendering the raw 50-char placeholder.
  Map to short codes (e.g. `2F`, `W73`, `RU-A`) with the full text on tap/`title`, plus a
  distinct "TBD" visual treatment. Apply in `SchedulePage.tsx`, `PredictionsPage.tsx`, and
  check `MatchDetailPage` + bracket surfaces.
- **U21.2** (snag #4) Back buttons: audit league sub-pages (members, settings, invites,
  join-requests, round leaderboard, history, compare) and pass `back` / `showBack` to
  `PageHeader` consistently.
- **U21.3** (snag #5) Dark-mode toggle in `TopBar.tsx`: an icon button in the right cluster
  wired to `useTheme().setMode`. Settings stays the 3-way (system/light/dark) source of
  truth; the TopBar control is a quick light/dark flip.
- **U21.4** (snag #6) Verify the dup-join guard with a test (constraint + ALREADY_MEMBER
  path, incl. re-join after leave reactivating the soft-deleted row). Optionally raise the
  multi-account / unique-email question with the user.
- **U21.5** (round-8 snag, folded in) League-header overflow — kill horizontal scroll on the
  league surfaces: `LeagueHomePage.tsx` header (lines 68–95: the Invite/Members/Invites/
  Settings cluster is `shrink-0 flex-wrap`, but the title side has no `min-w-0`/truncation →
  long league names push width) and `MyLeaguesPage.tsx` header (lines 85–97: title +
  Discover/Join/+New in a `justify-between` row with NO wrap). Add `min-w-0`/truncation, make
  the button clusters wrap, and guard the page container against `overflow-x`. **Do this as
  one pass with U21.2** — same league-header audit; apply the overflow fix to any sub-page
  header that needs it too. jsdom can't measure layout, so the unit test asserts the layout
  classes are present (proxy); real verification is the mobile-width (360 px) preview.

**Acceptance:**
- Team-less matches never overflow/truncate; the full placeholder is available on tap/title;
  "TBD" matches read as visually distinct from real fixtures.
- Every league sub-page has a working back affordance.
- The TopBar has a dark/light toggle that updates the theme immediately (incl. theme-color
  meta); Settings remains the 3-way control.
- A test covers the dup-join guard (same player can't double-join; re-join after leave works).
- No league surface scrolls horizontally at 360 px; long league names truncate; action /
  settings button clusters wrap (one audit pass with U21.2).
- Frontend tests + a11y green; backend test (U21.4) green.

## U22 — Knockout per-match lock + temporal leaderboard 🔴 Opus · ~3.5 h

Foundational lock change first, then the new leaderboard metrics.

- **U22.1** (snag #2) Knockout predictions lock per-match, not per-round: drop the
  round-level condition (`_is_round_locked`) in `knockout_predictions.py`, keep the
  per-match kickoff lock, and update the reveal gate to per-match.
- **U22.2** (snag #1) Backend temporal points per player/league: last-match points (points
  on the most recently settled match's prediction), today's points (viewer-local day via
  `profiles.timezone`), round points (current/furthest-progressed stage; group = one round),
  alongside the existing total.
- **U22.3** (snag #1) Surface on the leaderboard via a period toggle (Today / Round / Total)
  or inside the expand row — NOT four columns (mobile width).

**Acceptance:**
- A knockout prediction locks only at its own match's kickoff; a sibling tie kicking off no
  longer locks the rest of the round; reveal is per-match.
- The leaderboard exposes last-match / today / round / total points; "today" is viewer-local;
  "round" = the current stage and resets per stage.
- No new pre-lock leak (privacy invariant); existing snapshot/leaderboard behaviour intact.
- Backend + frontend tests green, incl. a per-match-lock test and a temporal-points test.

## U23 — Full-photo avatars 🟢 Sonnet · ~3.5 h

- **U23.1** Migration adding `profiles.avatar_url` (nullable) + a Supabase Storage bucket
  and access policy (avatars; public read of unguessable paths, owner write).
- **U23.2** Upload control in Settings: pick/crop to square, client-side resize to ~512 px,
  ~2 MB cap, type allow-list; persist the URL on the profile.
- **U23.3** Render the avatar everywhere identity shows (TopBar, leaderboard rows, player
  profile, league members), with the initials `Avatar` as the fallback when `avatar_url`
  is null.

**Acceptance:**
- A user can upload / replace / remove a photo avatar; it appears across TopBar, leaderboard,
  profile, and members; initials fallback when unset.
- Upload enforces type + ~2 MB + square ~512 px resize; no broken-image states.
- Migration applied (repo-root `/migrations`, sequential id); tests cover the endpoint +
  fallback rendering; a11y green.

## U24 — Reveal-all gated player profile 🔴 Opus · ~3 h

Depends on U22.1 (per-match knockout lock semantics).

- **U24.1** A shared reveal gate + extend the profile to show group predictions as soon as
  they lock (not only once settled), reusing the post-lock comparison logic.
- **U24.2** Specials section on the profile, revealed once the tournament has started.
- **U24.3** Knockout bracket section on the profile, revealed per-match (per U22.1).
- **U24.4** Regression test asserting predictions are NEVER returned before lock (group,
  specials, knockout), and ARE visible to league-mates immediately after lock.

**Acceptance:**
- `PlayerProfilePage` shows a player's group, special, and knockout predictions, each gated
  by its own lock; nothing is visible before lock; everything is visible to league-mates at
  lock.
- One shared gate is used by all three sections (no duplicated / divergent rules).
- The leak regression test is green; existing profile/stats tests stay green.

---

## Close-out (round 7)

Per batch: push the batch branch (next free `feat/premium-polish-<n>` after U20's `-12`) →
`/phase-closeout U<n>` (CI poll + ff-merge; manual fallback if the `U` prefix isn't
recognised) → lean `session-log.md` entry → strike the batch's row in the round-7 table
above. U21 and U23 are independent; **close out U22 before U24** (U24 builds on U22.1).

---

# Rebrand — Calcio (U25)

The app was previously named "The Steele Spreadsheet System" (SSS). The new name is
**Calcio** — Italian for football, doubles as a nod to "calculate". One focused session,
🟢 Sonnet, off a fresh `feat/rebrand-calcio` branch.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U25~~ | ~~🟢 Sonnet~~ | ~~~1.5 h~~ | ~~U25.1–U25.5~~ | ✅ Shipped 2026-06-05 |

---

### U25 — Calcio rebrand

- **U25.1** Brand token update (`apps/web/src/theme/tokens.ts`):
  - `brand.full` → `'Calcio'`
  - `brand.short` → `'Calcio'`
  - `brand.wordmarkTop` → `'Calcio'` (single word — no two-line split needed; keep the field
    for compat but set to `'Calcio'`; remove or blank `wordmarkBottom`)
  - `brand.tagline` → keep `'Still Email?'` (name-agnostic, still lands)
  - Update the file-header comment (currently references "The Steele Spreadsheet")
  (~10 min)

- **U25.2** PWA & meta name (`apps/web/index.html` + `apps/web/vite.config.ts`):
  - `index.html`: `<title>` → `Calcio`; `apple-mobile-web-app-title` `SSS` → `Calcio`;
    `og:title`, `twitter:title`, and meta `description` all updated
  - `vite.config.ts` PWA plugin manifest: `name: 'Calcio'`, `short_name: 'Calcio'`
  (~10 min)

- **U25.3** Wordmark component (`apps/web/src/components/Brand.tsx`):
  - Current component renders a two-line "The Steele / Spreadsheet System" logotype via
    `brand.wordmarkTop` / `brand.wordmarkBottom`, plus an `SSS` monogram variant.
  - New: render `brand.full` (`Calcio`) as a **single-line logotype** in the existing type
    treatment (heavy weight, emerald gradient). All size variants (`sm`, `md`, `lg`, default)
    must scale correctly.
  - If any SVG path or character-spacing code is hard-coded for three letters, replace it.
  - The "SSS monogram" avatar fallback (used in `avatar.tsx`) should become a `C` or `CA`
    initial — check `apps/web/src/components/ui/avatar.tsx`.
  (~40 min)

- **U25.4** Copy updates:
  - `AboutPage.tsx`: eyebrow → `"Calcio"`; update the "A Steele and Robbo Worldwide
    production" tagline to something neutral (e.g. "A friends league, built properly") —
    keep the `"Built by Craig Robinson and Lewis Steele"` tech-credit line unchanged (that's
    a builder credit, not a branding statement)
  - `BrowserOnboarding.tsx`: "The Steele Spreadsheet System is a private…" →
    "Calcio is a private World Cup 2026 prediction league."
  - `BrowserOnboarding.tsx`: update the "Previously administered with great distinction by
    Company CEO Lewis Steele via a spreadsheet…" flavour copy — tone is still warm/fun,
    just drop the personal name; e.g. "Previously run from a spreadsheet of legendary
    proportions, Calcio is the official upgrade."
  - `invite.ts`: update subject line and share-text body to reference Calcio
  - `IosSafariOverlay.tsx`: any visible app-name reference
  (~25 min)

- **U25.5** Test string updates:
  - `grep -rn "Steele Spreadsheet\|\"SSS\"\|'SSS'" apps/web/src/test/` — find every
    Vitest assertion that references the old name and update to `"Calcio"` / `'Calcio'`
  - Re-run `pnpm --dir apps/web test` and confirm all tests green
  (~15 min)

**Acceptance:**
- No user-visible string contains "The Steele Spreadsheet System" or bare "SSS"
- Browser tab title, PWA install prompt, iOS Add to Home Screen: all display "Calcio"
- `og:title` and `twitter:title` are "Calcio"
- Brand logo / logotype renders cleanly at all breakpoints and size variants
- Onboarding overlay, invite share text, iOS install overlay: all reference Calcio
- About page eyebrow is "Calcio"; builder credit line ("Craig Robinson and Lewis Steele") unchanged
- All Vitest tests green

## Close-out (U25)

`feat/rebrand-calcio` → `/phase-closeout U25` → lean `session-log.md` entry → strike U25
row above. Independent of U21–U24 — can ship in any order.

---

# Premium polish round 8 — snags backlog (U26)

Source: user-reported snags, 2026-06-04 (follow-up to round 7). Same workflow: one focused
🟢 Sonnet session, off the next free `feat/premium-polish-<n>` branch. Two independent,
low-risk frontend fixes — each already has a surface in the repo, so we **extend, not
rebuild**. Decisions locked with the user (see below — do not re-litigate). (The
leagues-overflow snag was folded into U21.5 — same league-header audit.)

Mark complete by striking through the row.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U26~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U26.1–U26.2~~ | ✅ Shipped 2026-06-05 |

**Dependencies:** none — the two items are independent of each other and of U21–U25.

---

## Decisions (locked 2026-06-04)

- **Mandatory updates (U26.1) = smart auto-reload.** The SW already self-activates
  (`skipWaiting`/`clientsClaim`); force the *page reload* (new JS) at a **safe moment** —
  tab refocus, next route change, or a short countdown — deferring while the predictions
  editor has unsaved edits. Add a periodic `update()` poll so long-lived PWA sessions still
  pick up new versions. No permanent "dismiss". NOT a hard immediate auto-reload (would
  interrupt mid-action / lose unsaved input).
- **Scoring examples (U26.2) = worked matrix of every achievable per-match total
  {0, 2, 3, 5, 10}.** 7 and 8 are impossible (an exact score implies correct result +
  combined goals, so it stacks straight to 10). Show predict-vs-actual + breakdown for each.
  Surface in both the Predictions quick-ref (collapsed) and the About page, from ONE shared
  scoring-data module so they can't drift. Reconcile the specials count/total to the actual
  implementation.

---

## Current state already in the repo (verify, then build on it — do NOT rebuild)

- **Update flow:** `registerType: 'prompt'` (`apps/web/vite.config.ts`); `UpdateBanner.tsx`
  shows a *dismissible* "A new version is available" banner. `apps/web/src/sw.ts` ALREADY
  calls `self.skipWaiting()` + `clientsClaim()` (lines 14–21) — the SW self-activates; only
  the page reload is optional. ⚠ **History:** they moved to `skipWaiting` because
  `IosSafariOverlay` (z-70) covered the banner (z-60) on iOS and deadlocked. Don't
  reintroduce a tap-dependent deadlock — any residual prompt must render ABOVE the overlay.
- **Scoring already documented in TWO places, neither with worked examples:**
  `apps/web/src/components/ScoringGuide.tsx` (compact quick-ref on `PredictionsPage`, match
  scoring 2/3/5/10 only) and `apps/web/src/pages/AboutPage.tsx` §"How scoring works" (match +
  knockout-winner escalating + specials + max-points). ⚠ AboutPage lists only **3 specials
  = 45 pts** and grand total **1380**; architecture §6.1 + the data model define **6
  specials = 80** and **≈1415**. Verify which the app actually implements; reconcile.
- **Authoritative scoring = `wc2026-architecture.md` §6.1.** Group/knockout match = 2
  (combined goals) + 3 (result) + 5 (exact), stacking to 10. Knockout-winner per round:
  R32 5 → R16 10 → QF 15 → SF 20 → 3rd 10 → Final 25. Specials 20/15/15/10/10/10.

---

## U26 — Clarity & mandatory updates 🟢 Sonnet · ~3 h

- **U26.1** (mandatory updates) Smart auto-reload for new versions. Keep the SW's
  `skipWaiting`/`clientsClaim`; add a periodic `registerSW` `update()` poll (~30–60 min);
  on `onNeedRefresh`, schedule a reload at a safe moment (tab `visibilitychange`→visible,
  next route change, or a short visible countdown), deferring while the predictions editor
  reports unsaved edits (wire a lightweight dirty-state signal if none exists). Remove the
  permanent-dismiss path; ensure any residual prompt renders above the iOS overlay (fix
  z-order) so it can't deadlock. Touches `UpdateBanner.tsx`, `vite.config.ts`, maybe `sw.ts`.
- **U26.2** (scoring clarity) Add a worked-examples matrix of every achievable per-match
  total — {0, 2, 3, 5, 10} — each as predict-vs-actual + the points breakdown, surfaced in
  `ScoringGuide.tsx` (collapsed) and `AboutPage.tsx`. Extract a shared scoring-data module
  (rows + worked examples + specials) consumed by both so they can't diverge. Reconcile the
  specials count/total to the actual implementation (fix the 45-vs-80 / 1380-vs-1415 split).

**Acceptance:**
- A new deploy reaches an already-open PWA session without the user tapping anything: the
  app reloads to the new version at a safe moment (not mid-edit), there's no way to
  permanently suppress the update, and no iOS-overlay deadlock.
- The Predictions quick-ref AND the About page each show worked examples for every
  achievable per-match total (0, 2, 3, 5, 10); both render from one shared source; the
  specials count + grand total match the implementation (no 45-vs-80 mismatch).
- Frontend tests green — incl. a scoring-examples render test asserting the five totals and
  an update-scheduling test (defers on unsaved edits, fires on refocus); a11y green.

---

## Close-out (round 8)

Push the batch branch (next free `feat/premium-polish-<n>`) → `/phase-closeout U26` (CI poll
+ ff-merge; manual fallback if the `U` prefix isn't recognised) → lean `session-log.md`
entry → strike U26's row above.

---

# Round 9 — live match hub + hero dashboard (U27)

Decided 2026-06-04 after reviewing U20. The live carousel slot removed in U20 and all the
rich live/score/points features below live here. 🔴 **Opus**.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U27~~ | ~~🔴 Opus~~ | ~~~5 h~~ | ~~U27.1–U27.7~~ | ✅ Shipped 2026-06-05 |

**Dependencies:** U27 builds on U20 (home v2). Close out U20 first.

---

## U27 — Live match hub + hero dashboard 🔴 Opus · ~5 h

### Backend changes required first

- **U27.B1** Add `elapsed_minutes: int | None` to `MatchResponse` — the live elapsed
  minute, populated by the result-fetcher when status = `live`. First verify the
  result-fetcher actually captures it (check the football-data API response shape); if not,
  leave it `null` and mark the display field optional.
- **U27.B2** Add `kickoff_utc: str` to `HomeRollupMatch` — so each per-match row in the
  hero rollup expansion can show date + time. The match `id` is already on the row so a
  client-side join to `['matches','group']` is a fallback for group stage, but adding it to
  the payload is cleaner and covers knockout rollups.

### Frontend items

- **U27.1 Live match hub section** — a new full-width section that appears between the
  hero and the pre-tournament checklist when ≥1 group match is live. Shows one card per
  live match (adaptive — one card wide on mobile, two columns on wider screens).
  Each live card:
  - Match header: `{home_flag} {home_code} {actual_home}–{actual_away} {away_code} {away_flag}`
    in a large prominent score, plus elapsed minutes (`{n}'`, or `HT`, or omitted if null).
  - Your prediction row: `You: {predicted_home}–{predicted_away}`.
  - Provisional points row: compute client-side using the existing shared scoring logic
    (`packages/shared/` scoring) against the *current* live score + your prediction. Label
    "Points if this stands: X".
  - Green live pulse (existing `.animate-ping` pattern).
  Remove the small hero corner chip for `kind='live'` once this section exists — the chip
  keeps `kind='next'` and `kind='last'` only.

- **U27.2 Hero dashboard section headings** — the hero card gets labelled sub-sections:
  "Points" (already present), "Daily summary" (the +N pts delta row, with a tap-for-detail
  chevron), and the section header above the live hub (rendered outside the card):
  `"Live now"` (only when live) or nothing. These headings use the same `text-lg font-bold`
  style as the other page sections.

- **U27.3 Daily summary always-visible league movement** — the cross-league movement
  summary (`↑2 The Steele Spreadsheet · ↓1 Office Pool`) currently lives inside the
  expanded rollup and in the Leagues section below. Bring the compact colour-coded summary
  (already colour-coded in U20) up to always show below the "+N pts" collapsed delta line,
  so it's visible without expanding.

- **U27.4 Pronounced score + prediction in breakdown** — inside the expanded rollup per-
  match row: make `actual_home–actual_away` larger (`text-base font-semibold`) and the
  "you: X–Y" prediction more visually distinct (a small pill or different colour). Add the
  match kickoff date/time using `kickoff_utc` from `HomeRollupMatch` (U27.B2).

- **U27.5 Next-match chip → inline below points** — when nothing is live, replace the
  top-right corner chip with an inline row below the points: `Next · {flag} {code} v {code}
  {flag} · in {countdown}`. This gives more space and removes the awkward side-by-side
  layout on narrow screens.

- **U27.6 Last-result chip cleanup** — when nothing live or upcoming, show the last FT
  result inline (same row style as U27.5) rather than a corner chip.

- **U27.7 Tests + a11y** — update DashboardPage tests for the new hub section and chip
  positions; update carousel tests (live already excluded from U20); Vitest + axe green.

**Acceptance:**
- When ≥1 match is live, a `"Live now"` hub section appears above the checklist with one
  card per live match showing score, elapsed minute (or omitted if backend null), your
  prediction, and provisional points.
- When 2+ matches are live simultaneously, the hub is multi-card (responsive grid).
- The hero shows "Daily summary" always-expanded league movement (colour-coded green/red)
  without requiring the user to tap.
- Per-match rollup rows show prominent score, visible prediction, and kickoff date/time.
- The next/last match slot uses the inline layout, not the corner chip.
- Backend: `elapsed_minutes` present on MatchResponse; `kickoff_utc` present on
  HomeRollupMatch.
- Typecheck clean; Vitest 290+ green; axe green; no regressions.

---

# Round 10 — audit follow-up (U28)

Single-item fix surfaced by the post-U27 code audit. 🟢 Sonnet.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U28~~ | ~~🟢 Sonnet~~ | ~~~15 min~~ | ~~U28.1~~ | ✅ Shipped 2026-06-05 |

---

## U28 — Audit follow-up: UpdateBanner className fix 🟢 Sonnet · ~15 min

- **U28.1** `UpdateBanner.tsx:141` — `"h-4 w-4 shrink-0animate-spin"` fuses two
  Tailwind utilities into one invalid class (missing space). Fix to
  `"h-4 w-4 shrink-0 animate-spin"`. Add a Vitest assertion in
  `UpdateBanner.test.tsx` that the refresh-icon SVG carries `animate-spin`
  so it can't silently regress.

**Acceptance:**
- The refresh icon has both `shrink-0` and `animate-spin` as separate classes.
- `UpdateBanner.test.tsx` asserts the icon carries `animate-spin`.
- No other UpdateBanner behaviour changes.
- Frontend tests + typecheck + lint green.

---

# Round 11 — snagging pass (U29) — added 2026-06-05

Ad-hoc snagging batch from a hands-on test pass: copy fixes, two bug fixes
(photo-upload RLS, public-league 422) and a few UX reworks. 🟢 Sonnet.
Recorded retrospectively for ledger completeness — shipped to staging before
write-up (commits `2bee43c` + `7ca3a67`).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U29~~ | ~~🟢 Sonnet~~ | ~~~6 h~~ | ~~U29.1–U29.9~~ | ✅ Shipped 2026-06-05 |

---

## U29 — Snagging pass: photo upload, leaderboard, copy + 2 bug fixes 🟢 Sonnet

15 user-flagged items from a hands-on pass, grouped:

- **U29.1** Optional signup photo. New avatar picker on `SignupPage.tsx`; uploads after the account exists (so it's authenticated). Shared `apps/web/src/lib/image.ts` (`resizeAvatar` + `uploadAvatarImage`).
- **U29.2** Remove the "In partnership with Robinsons" + "Still Email?" lockup from Login + Signup; deleted `PartnershipLockup.tsx` + `public/robinsons-logo.png`. (Reverses U8/U9.2; the `tokens.ts` `tagline` constant is now dead but left in place.)
- **U29.3** Remove the "Mark done" affordance from the Read-the-rules checklist row (`PreTournamentChecklist.tsx`); the row still auto-ticks on navigation.
- **U29.4** Scoring quick-ref also on Home — reuse `ScoringGuide` with an optional `storageKey`/`defaultOpen` (collapsed, own key) on `DashboardPage`.
- **U29.5** Share-message copy: "Join me on Calcio …" + "next iteration" (was "official upgrade") in `invite.ts` + `BrowserOnboarding.tsx`.
- **U29.6** League entry lands on the leaderboard directly: `/leagues/:slug` → redirect; ported the league header (Invite / Members / admin Settings / Invites + "Your position") into `LeaderboardPage`; removed `LeagueHomePage`.
- **U29.7** Leaderboard score breakdown shown inline as Match / KO / Special columns (removed the tap-to-expand dropdown; long-press → compare kept).
- **U29.8** Avatar dropdown (Profile → `/players/:id`, Settings) in `TopBar` via new `@radix-ui/react-dropdown-menu` + `ui/dropdown-menu.tsx`. Back buttons on Discover Leagues + Admin Players. Copy: "Upcoming" → "Upcoming Matches", "Leagues" → "My Leagues".
- **U29.9** Two bug fixes: (a) **photo-upload RLS** — re-architected to a backend service-role upload (`POST /api/v1/auth/me/avatar` + `services/storage.py`) that bypasses Storage RLS, since the app's custom JWT auth has no `auth.uid()`; enables bigger uploads (1024 px / 5 MB, migration `024`). (b) **public-league 422** — map privacy to the backend enum (`public_open` / `public_request`) + cap `max_members` at 50.

**Acceptance:**
- Signup shows an optional photo picker; Settings re-upload and the signup photo both succeed via the backend endpoint (no RLS error).
- Creating a public/open league returns 201 (no 422).
- No Robinsons / "Still Email?" lockup on either auth page; no "Mark done" on the rules row.
- Tapping a league lands on its leaderboard; Invite / Members / Settings still reachable; breakdown shows as inline columns.
- Avatar dropdown offers Profile + Settings; Discover Leagues + Admin Players have back chips; Home reads "Upcoming Matches" + "My Leagues"; scoring quick-ref present (collapsed) on Home.
- Frontend + backend tests, typecheck, lint, ruff, mypy green; staging CI green (commits `2bee43c` + `7ca3a67`).

---

# Round 12 — leaderboard snags (U30) — added 2026-06-05

Follow-up snags on the league/leaderboard surface from U29's rework. 🟢 Sonnet.
Shipped to staging before write-up (commit `89839a9`).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U30~~ | ~~🟢 Sonnet~~ | ~~~30 min~~ | ~~U30.1–U30.4~~ | ✅ Shipped 2026-06-05 |

---

## U30 — Leaderboard snags: position, medals, spacing, full name 🟢 Sonnet · ~30 min

- **U30.1** Remove the "Your position" card from the league/leaderboard header (`LeaderboardPage.tsx`); the caller's own row is highlighted in the table instead (`bg-primary/10`, lifted from `/5`). Drops the now-unused `myEntry` + Badge/Card imports.
- **U30.2** Rank column shows plain numbers — removed the 🥇🥈🥉 `MEDAL` map from the rows.
- **U30.3** Space out the inline breakdown columns: Match / KO / Special cells `px-1` → `px-2.5` (header + rows).
- **U30.4** Show the full league name at the top: stack the Invite / Members / admin Settings / Invites actions in a row *below* the title (was squeezing it side-by-side), and let the title wrap via a new opt-in `wrapTitle` on `PageHeader` (default truncate unchanged for every other page).

**Acceptance:**
- No "Your position" card; the caller's row is visibly highlighted in the table.
- Ranks render as 1, 2, 3… (no medals).
- Breakdown columns are visibly spaced.
- Long league names show in full (wrap, not truncate); actions sit below the title.
- Frontend typecheck, lint, 338 tests green; staging CI green (commit `89839a9`).

---

# Round 13 — Calcio logo rebrand (U31) — added 2026-06-06

Replace the stale Steele-era "S" mark and pitch icon with the new **Calcio "C"** identity. 🟢 Sonnet.
Shipped to staging before write-up (commit `74eef25`).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U31~~ | ~~🟢 Sonnet~~ | ~~~1 h~~ | ~~U31.1–U31.4~~ | ✅ Shipped 2026-06-06 |

---

## U31 — Calcio "C" logo: new mark + PWA icons + splash lockup 🟢 Sonnet · ~1 h

- **U31.1** New monogram mark — Concept 6 "Calcio C": a geometric monoline **C** (open centre-circle ring) cradling a football in its mouth, in the brass-gold wordmark gradient (`#F0DDA6 → #D4A24A → #A77C2A`) on graphite `#0B0E13`. One shape that reads from 512 px down to 16 px; pentagon panel drops out gracefully at favicon size. Replaces the "S" letterform (Steele) and the busy pitch icon.
- **U31.2** All PWA icons regenerated — `icon-192/384/512.png`, `icon-maskable-512.png` (0.9 scale inside safe zone), `apple-touch-icon.png` (0.875 scale), `favicon.svg` (flat brass, crisper at 16 px), `favicon.ico` (32 px PNG-in-ICO). `generate-icons.mjs` is the single source of truth; also emits `docs/logo-concepts/concept-6-calcio-c*.svg`.
- **U31.3** In-app `MarkSvg` in `Brand.tsx` updated to the new C geometry (gradient via `useId`-scoped `linearGradient` so multiple marks on one page stay valid SVG).
- **U31.4** Splash variant (`Brand` on Login / Signup / Welcome / Join / PIN-reset) now shows the mark above the CALCIO wordmark — the two render as a matched metallic pair. Previously the splash was wordmark-only with no graphic.

**Acceptance:**
- Home-screen install (Android + iOS) shows the gold C mark and is named **Calcio**.
- PWA manifest: `name` = `Calcio`, `short_name` = `Calcio`; all four icon sizes point at the new files.
- `icon-512.png` = 16929 bytes (verified live on staging).
- Login / Signup / Welcome splash shows mark above wordmark; axe a11y passes (mark is `aria-hidden`).
- Frontend typecheck, lint, 15 targeted tests green; staging CI green (9/9 jobs ✅, commit `74eef25`, SHA `6bfc2b4`).

---

# Round 14 — snagging pass (U32–U36) — added 2026-06-06

Snagging batch from a hands-on review with the user. Three 🟢 Sonnet UI batches
(scoring-ref placement; a clutch of frontend snags; the first-run onboarding + About +
checklist flow) and two 🔴 Opus feature batches (pre-match prediction reminders; biometric
unlock). Each batch = one focused session; ship to staging per batch (independent — don't
wait on the others). `/next-batch-prompt polish` surfaces them in number order as each is
struck. (The three Sonnet batches — U32/U33/U36 — can share one or two sessions to save
cold starts, per the orchestration discussion.)

**Decisions locked in the review (carry these):**
- **Header** = responsive, *not* uniform: mobile gets toggle-left + centred brand; desktop keeps today's layout (avoids the desktop nav collision).
- **Pre-match reminders** = a **daily digest of your unpredicted matches** as the primary nudge (not per-match spam), fired earlier than kickoff, only to players who haven't predicted. A per-match "here's your pick" confirmation is **opt-in, off by default.** New notification type + its own toggle, respecting quiet hours.
- **Biometrics** = the **lightweight local unlock gate** over the already-stored session (convenience, not a security upgrade) — *not* full server-side WebAuthn passkeys (a separate, larger batch if ever wanted). Front it with a feasibility spike.
- **Scoring copy** = the reference table + `/about` worked examples are already clear; only the first-run **tour** slide needs a concrete stacking example. "2 pts for goals only" is a real, intended outcome — make the tour show it.
- **First-run flow** = soft-guided, **not** forced. Sequence tour → notifications → a skippable **checklist launchpad** (read rules / set specials / first pick) that hands off to the persistent home checklist (`PreTournamentChecklist`). Don't hard-gate the app: specials + first pick lock at the opening match and late-joiners are supported, so blocking is wrong. "Both" = a guided intro **and** the standing checklist.
- **Prediction-deadline copy** = reassurance only. The app locks **at kickoff** (confirmed in code + `/about` + the tour), so phrase it "set them any time before kickoff — with time to spare," **not** a literal "5 minutes before." A real 5-min grace buffer is a separate backend change (see the note under U36), not this round.
- **About page** = already exists at `/about` and is reachable via the desktop nav + Settings; add a one-tap **avatar-dropdown** entry for mobile, and make "read the rules" require scrolling to the end (today it ticks on mount/click).

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U32~~ | ~~🟢 Sonnet~~ | ~~~45 min~~ | ~~U32.1–U32.2~~ | ✅ Shipped 2026-06-07 |
| ~~U33~~ | ~~🟢 Sonnet~~ | ~~3 h~~ | ~~U33.1–U33.4~~ | ✅ Shipped 2026-06-07 |
| ~~U34~~ | ~~🔴 Opus~~ | ~~~4 h~~ | ~~U34.1–U34.5~~ | ✅ Shipped 2026-06-07 |
| ~~U35~~ | ~~🔴 Opus~~ | ~~~4 h~~ | ~~U35.1–U35.5~~ | ✅ Shipped 2026-06-07 |
| ~~U36~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U36.1–U36.7~~ | ✅ Shipped 2026-06-07 |

---

## U32 — Scoring quick-ref placement 🟢 Sonnet · ~45 min

Just where the scoring quick-ref (`ScoringGuide`, U29.4) sits on the two main surfaces. The
tour copy + Back button moved to **U36** with the rest of the onboarding rework, so this
batch no longer touches the tour. All frontend, no new infra.

- **U32.1** (move scoring ref up on Home) — `DashboardPage.tsx`. The `<ScoringGuide storageKey="sss_scoring_guide_home_open" defaultOpen={false} />` currently renders at the **bottom** of the page (below the "My Leagues" section, ~line 578). Move it **above** the predictions area — directly above `<UpcomingMatchesCarousel />` (~line 557). Keep it collapsed by default (same storageKey).
- **U32.2** (collapse scoring ref on Predict) — `PredictionsPage.tsx` (~line 141) renders `<ScoringGuide />` **expanded** by default. Pass `defaultOpen={false}` and a **distinct** `storageKey="sss_scoring_guide_predict_open"` so the predict tab starts collapsed and doesn't share Home's open/closed state. (`ScoringGuide.tsx` already supports both props.)

**Acceptance:**
- Home: the scoring quick-ref sits **above** the upcoming-matches/predictions area, still collapsed by default (own storageKey).
- Predict tab: the scoring guide is **collapsed by default** via its own storageKey (independent of Home).
- Frontend typecheck, lint, tests green; staging CI green.

---

## U33 — Frontend snags: public badge, responsive header, profile avatar, long-press 🟢 Sonnet · ~3 h

Four independent UI snags. The badge fix is a real display bug; the rest are UX.

- **U33.1** (public-league badge shows blank — real bug) — the API serializes the **real** enum values `public_open` / `public_request` / `private` (`league.privacy.value`, `routers/leagues.py`), but the frontend still uses **stale short keys**: `LeagueSummary.privacy: 'open' | 'request' | 'private'` (`lib/types.ts:244`) and the `privacyLabel` maps (`MyLeaguesPage.tsx:26`, plus the `=== 'open'` ternary in `DiscoverLeaguesPage.tsx`). Result: public leagues render an **undefined/blank** badge while `private` shows "Private". (U29.9 fixed the create-side 422 but missed this read/display mapping.) Align the type + label maps to the real values and label them **"Public"** (`public_open`) / **"Public · request to join"** (`public_request`) / **"Private"**. Put the label map in **one shared helper** (e.g. `lib/leagues.ts`) consumed by both pages so it can't drift again.
- **U33.2** (responsive header) — `TopBar.tsx`. On **mobile** (`< md`) lay the bar out as `[theme toggle]` left · **centred Calcio brand** · `[avatar dropdown]` right. On **`md`+** keep today's layout unchanged (brand left, nav centred, toggle + avatar right). Use a single toggle instance with responsive ordering/placement — don't render two copies. (Note: TopBar gained the avatar dropdown in U29.8 and the Calcio mark in U31 — re-survey the current file before editing.)
- **U33.3** (update photo from your profile) — `PlayerProfilePage.tsx` (~line 307, `<Avatar … src={stats.avatar_url} />`). When viewing **your own** profile (`isSelf`), make the avatar a button that opens the existing avatar-update flow — reuse `lib/image.ts` (`resizeAvatar` + `uploadAvatarImage`) → backend `POST /api/v1/auth/me/avatar` (the service-role upload from U29.9), the same pipeline `SettingsPage` uses. Extract the SettingsPage avatar section into a shared component if that's cleaner than duplicating. Other players' avatars stay **view-only** (no editor).
- **U33.4** (block the long-press link callout) — `index.css`. Add `-webkit-touch-callout: none` to app interactive elements (extend the existing `header, nav, button, [role='button']` rule that already sets `user-select: none`, ~line 223). Scope to interactive elements only — **don't** kill text selection on body content (league join codes, player names must stay selectable). Complements the existing `useLongPress` contextmenu suppression.

**Acceptance:**
- Public/open leagues show a **"Public"** badge on both My Leagues and Discover (no blank badge); `public_request` reads "Public · request to join"; `private` reads "Private"; one shared label helper drives both pages.
- Mobile header: theme toggle top-left, Calcio brand centred, avatar right; **desktop header unchanged**; single toggle instance (no duplicate).
- On your **own** profile, tapping the avatar opens the photo-update flow and a new image saves end-to-end via the existing backend endpoint; other players' avatars are not editable.
- Long-pressing app buttons/links no longer triggers the iOS browser link/callout preview; intended text selection still works.
- Frontend typecheck, lint, tests green; staging CI green.

---

## U34 — Pre-match prediction reminders 🔴 Opus · ~4 h

The push stack, preferences (per-type toggles, global mute, quiet hours), and APScheduler
all exist. There's already a `deadline_warning` 15-min-before-kickoff broadcast to **all**
active players (`services/notification_triggers.py:300`), but it doesn't check who has
predicted and never references picks. This batch adds the targeted reminders.

> **Decisions (locked with the user):** primary nudge = a **daily digest of your unpredicted matches** ("You have 3 matches to predict today"), *not* per-match spam; fired earlier than kickoff and only to players who **haven't** predicted. A per-match **"here's your pick" confirmation is opt-in, off by default.** New notification type + its own preference toggle; respect the existing quiet-hours / global-mute system.

- **U34.1** Prediction-status query helper — "active players who have **not** submitted a prediction" for a given match (and for a set of matches kicking off in a window/day). Uses `predictions.submitted_at IS NOT NULL` + the active-players set. Pure, well-tested helper (service/query module). No "unpredicted players" query exists today.
- **U34.2** New notification type(s) + preference toggle(s) + migration — add `predict_reminder` (the unpredicted-digest) and `pick_confirmation` (opt-in) to `NotificationType` (`models/notification.py:13`) and to `NotificationPreferences` (`models/prediction.py:150`), defaulting **predict_reminder ON, pick_confirmation OFF**. Wire both into `_pref_enabled` (`push_notification_service.py:54`) and the prefs GET/PATCH (`routers/notifications.py`). Migration for the new pref columns.
- **U34.3** Daily unpredicted-digest job — a new APScheduler job (`scheduler.py`) that runs once per day and, for each active player with ≥1 **unpredicted** match kicking off that day, sends a **single** digest push ("You have N matches to predict today") deep-linking to `/predictions`. Only to unpredicted players; respects quiet hours, global mute, and the `predict_reminder` toggle. Be deliberate about the daily fire time vs player timezones / quiet hours (matches span US/Canada/Mexico zones; players are mostly UK).
- **U34.4** Opt-in per-match pick confirmation — for players who **have** predicted and enabled `pick_confirmation`, a pre-match push with their pick ("Your pick for England v France: 2–1 · kicks off 20:00"). Off by default; gated entirely by the toggle. Reuse the existing pre-kickoff window machinery.
- **U34.5** Tests — the unpredicted-players query; digest targeting (fully-predicted users excluded); toggle gating (both new types); quiet-hours / global-mute suppression; delivery rows in `NotificationLog`.

**Acceptance:**
- A **daily digest** push goes only to active players with ≥1 unpredicted match kicking off that day; players who've predicted everything get nothing; it deep-links to the predictions surface.
- The digest respects quiet hours, global mute, and the new `predict_reminder` toggle (default ON).
- `pick_confirmation` (default OFF) fires a per-match pick reminder **only** for users who enabled it and **only** for matches they've predicted.
- New notification type(s) + preference toggle(s) exist with correct defaults; migration applied; the prefs API round-trips them.
- Unit tests cover the unpredicted-players query, digest targeting, toggle gating, and quiet-hours suppression; `pytest` + Vitest green; staging CI green.

---

## U35 — Biometric unlock (local gate) 🔴 Opus · ~4 h

Greenfield — no WebAuthn / passkey / `navigator.credentials` code exists. Auth is Name + PIN
(bcrypt) + JWT with tokens in `localStorage`. This batch adds a **convenience** biometric
unlock over the already-stored session — **not** full server-side passkeys.

> **Decision (locked):** lightweight **local biometric gate** (guards re-entry to the stored session; framed as convenience, *not* a security upgrade), not server-side WebAuthn passkey registration/assertion (a separate, larger batch if ever wanted).
>
> **Before coding (spike):** confirm a platform authenticator works in the **installed** iOS/Android PWA — `window.PublicKeyCredential` + `isUserVerifyingPlatformAuthenticatorAvailable()`. iOS PWA WebAuthn can be finicky; if installed-PWA support is too flaky, fall back to a simpler in-app PIN re-prompt gate and **report what you found** rather than forcing it.

- **U35.1** Spike + capability detection — detect platform-authenticator availability and gate the **entire** feature behind it (hidden when unsupported). Decide the exact mechanism (WebAuthn `create`/`get` with a locally-stored credential id, user-verification required). Document the security model: it guards re-entry to a session whose refresh token still lives in `localStorage` — convenience, not hardening.
- **U35.2** Enrollment — a **Settings** toggle "Unlock with Face ID / fingerprint" that registers a platform credential (`navigator.credentials.create`, platform authenticator, `userVerification: 'required'`) and stores the credential id locally. (Server-side assertion verification is out of scope for the light gate.)
- **U35.3** Unlock gate — when enabled and a stored session exists, require a successful `navigator.credentials.get()` (user verification) before using the stored tokens / rendering authed content. Any failure/cancel falls back to the **PIN** (never a lockout).
- **U35.4** Settings UI + disable path — enable/disable, and graceful handling of unsupported/declined states. **PIN stays the source of truth and always works.**
- **U35.5** Tests — capability-gated rendering (hidden when no authenticator), enable/disable flow, unlock success and unlock-failure → PIN fallback. Mock `navigator.credentials` / `PublicKeyCredential`.

**Acceptance:**
- On a supported installed PWA, a Settings toggle enrolls a platform biometric; with it on, reopening the app requires a successful biometric **or** PIN fallback before authed content shows.
- Convenience-only: PIN always works as the fallback and source of truth; declining / cancelling never locks the user out.
- The feature is fully **hidden** when no platform authenticator is available.
- The security model is documented (guards re-entry to a stored session; not a server-side passkey).
- Tests cover capability gating, enable/disable, and unlock → PIN fallback; frontend (and any backend) tests green; staging CI green.

**U35 security model implemented:** the biometric switch is a local convenience gate only. The app checks `window.PublicKeyCredential`, `navigator.credentials.create/get`, and `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()` before showing the feature. Enrollment creates a platform WebAuthn credential with `authenticatorAttachment: 'platform'` and `userVerification: 'required'`, then stores only the credential id in `localStorage`. Re-entry calls `navigator.credentials.get()` with that local credential id before releasing the already-stored player into React auth state. There is no server challenge, public-key registration, assertion verification, phishing resistance claim, or replacement for the PIN login flow. The JWT refresh token still lives in `localStorage`; the gate merely hides authed UI until the local device ceremony succeeds or the user signs in with their PIN again.

**U35 spike note:** MDN documents `isUserVerifyingPlatformAuthenticatorAvailable()` as the cross-browser signal for a user-verifying platform authenticator in a secure, top-level context, including Face ID/Touch ID on Apple devices and device unlock on Android. Apple documents passkey/WebAuthn platform credentials for iOS/macOS browser apps. This implementation therefore uses WebAuthn `create`/`get` behind runtime detection, but installed iOS/Android PWA behavior still needs on-device staging verification because installed iOS web apps can differ from Safari tab behavior.

---

## U36 — First-run onboarding flow + About page + pre-tournament checklist 🟢 Sonnet · ~3.5 h

Ties the post-signup sequence, the persistent home checklist (`PreTournamentChecklist`,
U20.4), and the existing `/about` page (`AboutPage`) into one coherent first-run experience
— and makes "read the rules" actually mean reaching the end. Builds on U10.2
(`NotificationsPromptModal`) + U10.3 (`IntroTour`) + `FirstRunController` (`tour → notif →
done`). All frontend; **lock semantics do not change.**

> **Decisions (locked with the user):**
> - **Soft-guided, not forced** — add a skippable launchpad after the notif prompt; the standing home checklist remains. Never hard-block the app on predicting (specials + first pick lock at the opening match; late-joiners are explicitly supported per `/about`).
> - **Deadline copy = reassurance, not a hard 5-min lock.** The system locks **at kickoff** (`scheduler.lock_due_matches`, the `predictions` upsert guard, and the existing `/about` + tour copy all agree). Say "before kickoff — with time to spare," not a literal "5 minutes." If a real 5-minute grace buffer is wanted, that's a **separate backend change** (lock at `kickoff − 5m` across the lock job + upsert guard + every "lock at kickoff" string + tests) — flag it, don't bundle it here.

- **U36.1** Tour **Back** button — `IntroTour.tsx` (4-slide press-through, `slide` state ~line 81, Next/Skip only). Show a **Back** control when `slide > 0` that decrements `slide`; Next/Skip unchanged. (Moved from the old U32.4.)
- **U36.2** Tour scoring clarity — the scoring slide is prose-only; full worked examples live on `/about` + `ScoringGuide`. Add a concrete stacking example to the slide, explicitly covering the goals-only case (*"Predict 2–1 but it ends 1–2? You still bank 2 pts for the right total goals — result + exact stack on top."*), and point to "full rules" (`/about`). (Moved from the old U32.3.)
- **U36.3** First-run **checklist launchpad** — extend `FirstRunController.tsx` (`tour → notif → done`) with a final **`checklist`** step after `notif`: a skippable screen with the three pre-tournament actions as buttons — **Read the full rules** (`/about`), **Set your Specials** (`/predictions/specials`), **Make your first pick** (`/predictions`) — plus the reassurance copy (U36.4) and a "Skip for now / Go to app" exit. Gate once via localStorage (e.g. `sss_firstrun_launchpad_seen`, mirroring `isTourSeen`/`isNotifPromptSeen`). The home `PreTournamentChecklist` still tracks whatever is skipped.
- **U36.4** Deadline reassurance copy — in the launchpad **and** the home `PreTournamentChecklist`, make clear specials + the first-match pick stay open until the opening-match kickoff and can be set any time. Keep wording consistent with the accurate `/about` + tour "lock at kickoff" copy; do **not** assert a literal 5-minute cutoff (see decision).
- **U36.5** Persistent **About** entry on mobile — `/about` is in the desktop nav (`TopBar.tsx:23`) + Settings (`SettingsPage.tsx:491`, "About & scoring rules"), but the desktop nav is hidden on mobile. Add **"About / How it works"** to the **avatar dropdown** (the U29.8 menu, alongside Profile + Settings) so it's one tap on mobile, and reference that path from the launchpad ("reopen any time from the menu → About").
- **U36.6** About **"scroll to the end"** — `AboutPage.tsx` calls `markRulesRead()` on **mount** (~line 281), and `PreTournamentChecklist` also auto-ticks on the row click (`onLinkClick={tickRules}`, ~line 131), so "Read the rules" completes without reading. Replace both with a **bottom-sentinel `IntersectionObserver`**: mark read only when the user reaches the **end of the rules content** (place the sentinel after the "How it works through the tournament" section, before the build-credits / joke images). Add a top "scroll for the full rules" cue and a clear **end-of-rules marker / CTA** (e.g. "That's everything — set your Specials →").
- **U36.7** Tests — tour Back nav; `FirstRunController` order `tour → notif → checklist → done` + once-only gate; launchpad button routing; avatar-dropdown About entry; `markRulesRead` fires on reaching the sentinel (mock `IntersectionObserver`), not on mount/click.

**Acceptance:**
- After signup the flow runs **tour → notifications → checklist launchpad**, each skippable; nothing hard-blocks the app; the launchpad links to rules / specials / first pick and exits to the app.
- The home `PreTournamentChecklist` still tracks the three actions and latches dismissed when all complete.
- Onboarding + checklist copy makes clear specials + the first pick can be set any time **before kickoff** (no false "5-minute" claim); tour + `/about` wording stays consistent.
- The tour has a working **Back** button; the scoring slide shows a concrete stacking example (incl. goals-only = 2 pts) and points to `/about`.
- `/about` is reachable in **one tap from the avatar dropdown** on mobile (plus the existing nav + Settings paths).
- "Read the rules" completes only when the user **scrolls to the end of the rules** on `/about` (not on mount/click); a scroll cue + end-of-rules CTA are present.
- Frontend typecheck, lint, tests green; staging CI green.

---

# Round 15 — Marketing copy + About multi-league refresh (U37) — added 2026-06-06

Ad-hoc batch from a logo → slogan → copy session: value-prop hero on the login / welcome
splash, About refreshed for multi-league (incl. the per-match knockout correction), and the
founders' joke images. 🟢 Sonnet.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U37~~ | ~~🟢 Sonnet~~ | ~~~2 h~~ | ~~U37.1–U37.4~~ | ✅ Shipped 2026-06-06 |

---

## U37 — Marketing copy + About multi-league refresh 🟢 Sonnet · ~2 h

Shipped ad-hoc from a logo → slogan → copy session (no prior spec row); acceptance
reverse-engineered from what landed. U36 (onboarding) builds on this — U37 ships first.

- **U37.1** (tagline tokens + splash hero) — `apps/web/src/theme/tokens.ts`: replace the dead `tagline: 'Still Email?'` with `tagline` ("Predict once, compete everywhere.") + `taglineSub` (Scotland "28 years" line). Render a centred hero — headline + italic subhead — between `<Brand variant="splash" />` and the card on `LoginPage.tsx` + `WelcomePage.tsx`. No new CTAs, no eyebrow. Scotland subhead is intentionally seasonal — retire post-tournament from the token.
- **U37.2** (About → multi-league + clarity) — `AboutPage.tsx`: rewrite **"What is this?"** + **"Joining"** for the multi-league model (predict once / compete everywhere; private *or* public, instant or request-to-join; self-signup; join paths — invite link `/join/:token`, join code `/leagues/join`, discover `/leagues/discover`, create `/leagues/new`; fix "4–8 digit"→"4-digit"). Add a **"Deadlines — what's due when"** callout (Specials + first pick before the opener; **everything else — knockout score *and* winner picks included — locks per-match at each kickoff**, per U22.1). Clarify the two-prediction knockout model and why (a 90-min penalty draw can't imply the advancer); correct the stale per-round wording in About **and** the architecture doc (§3.8 + locking rules). Fold in **timezones** (kickoffs in your own tz), **hidden picks** (no one sees your predictions until lock), and **notifications** (reminder before kickoff).
- **U37.3** (credits + footer) — swap credit order to **"Built by Lewis Steele and Craig Robinson."**; add a **"Thanks for playing."** sign-off; footer → **"A Prestige Worldwide LLC Application"** (deliberate Step Brothers gag, not a real entity).
- **U37.4** (joke images) — add a `JokeFigure` helper (`<figure>` → bordered lazy `<img>` + required `alt` + optional caption + `imgClassName` so the two sponsor logos share a fixed height and captions align). 4 files in `apps/web/public/about/`: `founders-handshake.jpg` (full-width, no caption) + the `man-of-steele.jpg` / `robinsons.png` pair under an **"Executive Sponsors"** heading; `prestige-worldwide.jpg` above the footer. In-jokes on third-party imagery — fine for a private league; swap for original art before any public launch.

**Acceptance:**
- `/login` + `/welcome` show "Predict once, compete everywhere." + the Scotland subhead from the `brand` token (single source); no eyebrow; `'Still Email?'` gone.
- About reads multi-league, with a **Deadlines** callout (knockout locks **per-match**, matching U22.1); PIN copy reads **4-digit**; timezones, hidden-picks, and notifications are all covered.
- Credits read "Lewis Steele and Craig Robinson"; bottom reads "Thanks for playing." → "A Prestige Worldwide LLC Application" under an "Executive Sponsors" image pair.
- Four joke images render on `/about` (via `JokeFigure`, with alt text) and serve `200`.
- Frontend typecheck, lint (0 errors), 339 tests green; staging CI green.

---

# Round 16 — League-table tiebreakers (U38–U39) — added 2026-06-06

From a design chat with Lewis (the level-on-points problem): settle tied players with a
pure-**merit cascade** so a tied prize can be decided **in-app**. Two batches, sequential —
**U38** (🔴 Opus) does the scoring aggregation + strict ordering + cross-system consistency;
**U39** (🟢 Sonnet) puts the tiebreak components into the leaderboard rows and relocates the
points-source breakdown to the profile. U39 consumes U38's payload, so U38 ships first. Ship
to staging per batch.

> **Decisions (locked with the user):**
> - **Settle tied prizes in-app**, via a pure-**merit** cascade: points → most **exact scores** → most **correct results** → most **correct goals** → most **specials correct** → most **knockout-winner picks correct**.
> - **No timing-based or arbitrary break** — early-submission was explicitly rejected (rewards behaviour/timezone, not skill); no alphabetical/random either. A genuine all-axis tie is flagged for the **admin to settle** (split / one-off decider) — the only non-merit step, and essentially never reached.
> - **Leaderboard rows show exact / result / goals** (the visible tiebreak rationale, scoped to the active round pill); the **Match / KO / Special** points decomposition (U29.7) **moves to the player profile**. Deeper tiebreakers (specials / KO-winner) live on the profile / an expanded row, not as permanent columns.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U38~~ | ~~🔴 Opus~~ | ~~~4 h~~ | ~~U38.1–U38.5~~ | ✅ Shipped 2026-06-07 |
| ~~U39~~ | ~~🟢 Sonnet~~ | ~~~2.5 h~~ | ~~U39.1–U39.5~~ | ✅ Shipped 2026-06-07 |

---

## U38 — Tiebreaker scoring + strict ordering 🔴 Opus · ~4 h

The leaderboard today orders by `total_points` and **shares ranks** on a tie (standard
competition ranking — see the `dedupedLeaderboard` helper, U3.10, and the backend leaderboard
query). This batch replaces shared ranks with the merit cascade and makes the new order
consistent everywhere rank is computed.

> **Precondition:** confirm the per-prediction exact / result / goals components are persisted
> (they drive the existing breakdowns, so near-certain). If only the per-match total is stored,
> derive the counts from the scoring components / trigger. Likewise confirm specials-correct and
> knockout-winner-correct are derivable.

- **U38.1** Per-player tiebreak aggregates — counts of **exact scores**, **correct results**, **correct goals** across settled match-score predictions (group + knockout score), plus **specials correct** and **knockout-winner picks correct**. Expose them in the leaderboard payload, scoped to the round/stage filter where applicable (overall vs a selected round).
- **U38.2** Strict ordering / sort key — `points DESC → exact DESC → correct results DESC → correct goals DESC → specials correct DESC → KO-winner correct DESC`. Replace shared-rank ordering with this cascade. If **all** axes tie, mark a genuine shared position flagged for admin resolution — **no** timing/alphabetical/random break.
- **U38.3** Consistency across the rank system — apply the **same** sort key to leaderboard snapshots, rank-history, rank-delta / movement notifications, and the `dedupedLeaderboard` helper (U3.10), so rank never disagrees between the table, history, and pushes. Competition ranking now ties two players only when they're equal on every cascade axis.
- **U38.4** Admin-settle backstop — surface the true all-tie state so a prize can still be settled in-app without an arbitrary rule (minimal: a tie flag + an admin manual-order / override field; a full playoff mechanism is out of scope).
- **U38.5** Tests — aggregate correctness; the full cascade (fixtures that tie on points, then also on exact, then result, … asserting separation at each level); the all-axis-tie → shared/flagged case; snapshot / rank-history / notification consistency under the new key.

**Acceptance:**
- Two players level on points are separated by `exact → result → goals → specials → KO-winner`; the leaderboard reflects the new order.
- The **same** ordering drives snapshots, rank-history, rank-delta notifications, and the dedupe helper — no rank disagreement across surfaces.
- A genuine all-axis tie is marked a shared position and exposed for **admin settlement** (no timing/alphabetical/random break).
- Per-player tiebreak counts (exact/result/goals + specials/KO-winner) are returned in the leaderboard payload, scoped to the selected round/stage where applicable.
- `pytest` green (incl. cascade + consistency tests); staging CI green.

---

## U39 — Leaderboard tiebreaker columns + About rule 🟢 Sonnet · ~2.5 h

Surfaces U38's tiebreak components on the leaderboard and relocates the points-source
breakdown. Depends on U38's payload. All frontend.

- **U39.1** Leaderboard rows → tiebreak columns — replace the inline **Match / KO / Special** columns (U29.7) with **exact / result / goals**, scoped to the active round pill, under a small **"Tiebreakers"** (or "Precision") header so they're not read as a points decomposition. Keep the caller-row highlight (U30.1), plain ranks (U30.2), column spacing (U30.3).
- **U39.2** Relocate the points-source breakdown — move the full **Match / KO / Special** decomposition (incl. specials) to the **player profile** (`PlayerProfilePage`) as "how I earned my points," so nothing is lost. (Check whether the profile already shows part of this; enrich rather than duplicate.)
- **U39.3** Mobile width — ensure rank + name + points + three tiebreak columns fit a phone; expose the deeper tiebreakers (specials / KO-winner) on an expanded/tapped row or the profile, **not** as permanent columns.
- **U39.4** Document the rule — add a short **"How ties are broken"** section to `AboutPage` (points → exact → result → goals → specials → KO-winner → admin settles a genuine all-tie), consistent with the U37 Deadlines/About copy.
- **U39.5** Tests — rows render the tiebreak columns from the payload and scope to the round pill; the profile shows the Match/KO/Special decomposition; the About tiebreak section renders.

**Acceptance:**
- Leaderboard rows show **exact / result / goals** (scoped to the round pill) under a clear "tiebreakers" label; when players are level on points, the visible row order matches the columns.
- The **Match / KO / Special** points breakdown now lives on the **player profile** (incl. specials); nothing removed from the app, just relocated.
- The mobile leaderboard isn't overflowed; deeper tiebreakers are reachable (profile / expanded row) without permanent columns.
- `/about` documents the tiebreak order, consistent with existing copy.
- Frontend typecheck, lint, tests green; staging CI green.

---

# Round 17 — Home dashboard redesign (U40–U41) — added 2026-06-07

From a design chat (the home-screen rework): replace the stacked points hero +
expanding accordions + full-width live hub with a **two-tile command center** —
**Points** top-left, the **live/next match hub** top-right — that drills into
existing screens, and enrich the live "points if this stands" projection. Two
batches — **U40** (🟢 Sonnet) does the layout + match tile + drill-down rewiring
+ profile daily-recap; **U41** (🔴 Opus) adds the knockout advancement projection
to the live provisional. U41 enriches U40's match tile, so U40 ships first. Ship
to staging per batch.

> **Decisions (locked with the user):**
> - **Two-tile top row** — Points top-left (~38 %), the match hub top-right (~62 %), **side-by-side including on mobile** via an asymmetric split + a compact match card (the rejected first attempt only split at ≥lg).
> - **Match hub = one tile, three states** — `live → next → last`, defaulting to **next** when nothing's live; **swipe** between cards when ≥2 are live (guaranteed on final group matchdays — group pairs kick off simultaneously).
> - **Drill, don't expand** — kill the daily-summary and league accordions; every tile is a glanceable summary that taps through to an **existing** screen (`/players/:id`, `/leagues/:slug/leaderboard`, `/matches/:id`). The daily score moves onto the **profile**, covering both "today" and the full breakdown.
> - **`scoreMatchPrediction` ignores stage** (match score only, max 10); knockout **advancement** is a separate winner-pick prediction, so the live provisional must project + add it explicitly (U41).
> - **Bottom nav unchanged** this round — it's orthogonal (app sections vs dashboard shortcuts); the Schedule-vs-Predict overlap is noted for a possible later audit.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U40~~ | ~~🟢 Sonnet~~ | ~~~3.5 h~~ | ~~U40.1–U40.6~~ | ~~Shipped 78a93a1~~ |
| ~~U41~~ | ~~🔴 Opus~~ | ~~~2.5 h~~ | ~~U41.1–U41.4~~ | ~~Shipped 4c371b4~~ |

---

## U40 — Home dashboard redesign 🟢 Sonnet · ~3.5 h

Replaces the stacked hero + accordions + full-width live hub with a two-tile
command center that drills into existing screens. All frontend bar a small
profile-data reuse.

> **Precondition:** the home `rollup` (matchday `points_gained` + per-match breakdown,
> from `/api/v1/me/home`) already drives the current daily summary — reuse it for the
> profile's "latest matchday" block rather than adding a new endpoint. Confirm
> `PlayerProfilePage` can take a daily-points block without new API (else expose the
> rollup on the player endpoint).

- **U40.1** Top row — full-width "Welcome back" h1, then an **asymmetric** grid: **PointsTile (~38 %, left)** + **MatchTile (~62 %, right)**, side-by-side **including on mobile** (375 px). Replaces `GreetingHero`; nothing live → MatchTile shows the next fixture so the row is never half-empty.
- **U40.2** MatchTile state machine — `live → next → last`, defaulting to **next** when nothing's live (reuse `pickInlineSlot`). Compact card: team **codes** not names, scoreline, `LIVE · 67'`, condensed `You 2–1 · +10 if it stands`, with the provisional **breakdown** (result/goals/exact via `PointsBreakdownRow`).
- **U40.3** Multi-live swipe — horizontal carousel with dots (+ arrows on desktop) when ≥2 matches are live; default card = the biggest-stake match (predicted / nearest full-time).
- **U40.4** Restructure — remove `HeroDailySummary`, the standalone `LiveMatchHub` section, and the `CrossLeagueMovementSummary` line; fold "+N today" into PointsTile. Leagues become **compact rank rows** (no accordion). Final order: top row → leagues → upcoming → checklist/scoring.
- **U40.5** Drill-downs + profile recap — PointsTile → `/players/:id`; league row → `/leagues/:slug/leaderboard`; MatchTile → `/matches/:id` (predict form pre-lock). Add a **"latest matchday" points block to `PlayerProfilePage`** (reuse home `rollup`) so the Points drill covers today + the full breakdown.
- **U40.6** Tests — new layout structure; tile states (live/next/last); swipe renders one card per live match; drill-target links; profile daily block. Update the existing `DashboardPage.test.tsx` live-hub / inline-slot tests to the new shape.

**Acceptance:**
- Points sits top-left and the match hub top-right, side-by-side from mobile up (asymmetric split); with nothing live the MatchTile shows the next fixture.
- ≥2 live matches are swipeable with a clear position affordance; the default card is the highest-stake match.
- The daily-summary and standalone live-hub sections are gone; "+N today" lives in PointsTile and the full breakdown on the profile.
- Tapping Points → profile (with today's gain), a league row → that league's leaderboard, the match → match detail / predict.
- Frontend typecheck, lint, tests green; staging CI green.

---

## U41 — Live provisional: knockout advancement projection 🔴 Opus · ~2.5 h

Enriches U40's "points if this stands" so knockout matches also reflect projected
advancement points. Today the shared scorer is match-score-only; advancement is a
separate winner-pick, so it must be projected and added explicitly — only when the
live scoreline implies a definite advancer.

- **U41.1** Advancement projection — when a live knockout scoreline implies a **definite advancer**, look up the caller's knockout winner-pick for that tie and add its points to the provisional total.
- **U41.2** Edge cases — a level scoreline / draw heading to ET/pens → advancement **undetermined**: show match points only + an "advancement undecided" affordance; group-stage matches are unaffected (no advancement component).
- **U41.3** Combined breakdown — the provisional breakdown shows the **match** component and the **advancement** component distinctly.
- **U41.4** Tests — projection across won / level / ET states; group vs knockout; breakdown composition; the undecided state.

**Acceptance:**
- For a knockout match with a decisive live scoreline, "points if this stands" includes projected advancement points (from the caller's bracket pick), shown as a distinct breakdown line.
- A level knockout scoreline shows match points only + an undecided affordance; group matches are unchanged.
- Shared (`@wc2026/shared`) + web tests green; staging CI green.

---

# Round 18 — Calcio primary logo system (U42) — added 2026-06-07

Retrospective batch from the final logo approval session. U31 shipped the interim
gold "Calcio C" direction; this batch replaces it as the **primary app icon** with
the approved premium football prediction target: deep navy rounded-square tile,
white football/target mark, and one champagne-gold winning-prediction segment.
The gold tile remains available only as a secondary premium variant. 🟢 Sonnet.

Implementation began before this row was written; close-out still follows the
normal explicit `/phase-closeout U42` path after review, commit, push, and CI.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U42~~ | ~~🟢 Sonnet~~ | ~~~2 h~~ | ~~U42.1–U42.6~~ | ✅ Shipped 2026-06-07 |

---

## U42 — Calcio primary target-ball logo system 🟢 Sonnet · ~2 h

- **U42.1** Master SVG — create `apps/web/public/brand/calcio-icon-primary.svg` as the
  hand-authored source of truth. Requirements: pure vector, `viewBox="0 0 512 512"`,
  rounded-square `#071A3D` tile, warm-white football/target mark, one right-side
  `#D4A44B` prediction segment, no text, no raster, no filters, no shadows.
- **U42.2** Brand asset variants — add `calcio-icon-dark.svg`, `calcio-icon-gold.svg`,
  `calcio-mark.svg`, `calcio-mark-mono.svg`, and `calcio-mark-gold.svg` under
  `apps/web/public/brand/`. Gold tile is a secondary variant only, not the primary
  app icon.
- **U42.3** Generated raster exports — use existing lightweight tooling
  (`@resvg/resvg-js`, already present) to generate PNG exports from the master SVG:
  32, 64, 128, 180, 192, 512, and 1024 px. Do not add heavy image dependencies.
- **U42.4** App integration — wire the primary navy target-ball logo into favicon,
  Apple touch icon, PWA manifest icons, install/splash theme colours, notification
  icons where applicable, and social preview metadata. Existing app paths remain
  stable (`/favicon.svg`, `/favicon.ico`, `/apple-touch-icon.png`,
  `/icon-192.png`, `/icon-512.png`, etc.).
- **U42.5** Reusable component — add `CalcioLogo` (or existing naming convention)
  with `size`, `variant: primary | gold | mark | mono`, accessible label, and
  decorative mode. Update the existing `Brand` component so login/signup/welcome
  splash and TopBar/header branding use the primary navy target-ball icon while
  preserving current call sites (`variant="splash"`, `variant="compact"`, etc.).
- **U42.6** Brand note + verification — add `apps/web/public/brand/README.md` with
  primary-choice, palette, secondary gold variant, and usage rules. Validate SVGs,
  render at small sizes, run frontend lint/typecheck/build/tests, and do a local
  browser check of splash/header/preview assets.

**Acceptance:**
- `calcio-icon-primary.svg` is the master asset and remains pure vector; no
  AI-generated PNG or raster trace is used as source of truth.
- Primary app surfaces use the navy target-ball icon: favicon, PWA manifest icons,
  Apple touch icon, splash/loading/install contexts, visible splash/header brand,
  and social preview metadata.
- Gold tile variant exists but is not used as the primary app icon.
- `CalcioLogo` supports `primary`, `gold`, `mark`, and `mono`, including size,
  accessible label, and decorative mode.
- PNG exports exist for 32, 64, 128, 180, 192, 512, and 1024 px, generated from
  the SVG with existing tooling.
- Brand README documents palette and usage rules: no shadows, textures, outlines,
  gradients, random recolours, or AI PNGs as masters.
- Frontend lint, typecheck, build, and tests green; local browser verification
  confirms `/login` and the brand preview use `/brand/calcio-icon-primary.svg`.

---

# Round 19 — Dashboard home screen layout (U43) — added 2026-06-07

Three UX improvements to the dashboard top row, designed during a live preview
session. Surfaces more useful information and removes duplication between the two
top tiles. 🟢 Sonnet.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U43~~ | ~~🟢 Sonnet~~ | ~~~1 h~~ | ~~U43.1–U43.3~~ | ✅ Shipped 2026-06-07 |

---

## U43 — Dashboard home screen layout improvements 🟢 Sonnet · ~1 h

- **U43.1** Latest result priority — invert `pickInlineSlot` in `DashboardPage`
  so the top-right tile defaults to the most recently completed match (with score,
  prediction, and points breakdown) rather than the next upcoming fixture. Fall
  back to upcoming only when no matches have been completed yet. The carousel
  below already covers upcoming prediction actions so showing it twice in the top
  row was redundant.
- **U43.2** Prediction + breakdown in result tile — extend `MatchTileFixtureCard`
  to accept an optional `prediction?: PredictionResponse` prop. When `kind === 'last'`
  and a prediction with a points breakdown is present, replace the generic "Tap
  through…" CTA with: a `YOUR PICK: X–Y` label and a `PointsBreakdownRow`
  (✓/✗ Result / Goals / Exact + total pts). Wire up `predByMatch[inlineSlot.match.id]`
  at the call site. Fall back to the plain CTA text when no prediction exists.
- **U43.3** Matchday summary in points tile — replace the single inline-slot pill
  at the bottom of `PointsTile` with a compact per-match score list drawn from
  `rollup.matches`. Each row shows `FLAG CODE X–Y CODE FLAG` (left) and the
  points earned (right, green if > 0, muted dash if 0). The date + day total
  (`FRI 5 JUN · +12 pts`) sits as a header above the rows. When no rollup exists
  yet (pre-tournament), retain the "Next fixture" pill as the fall-back so new
  users still see something useful.

**Acceptance:**
- Top-right tile shows the latest completed match (score, prediction, breakdown)
  whenever at least one match has finished; shows upcoming fixture only
  pre-tournament.
- `MatchTileFixtureCard` renders `YOUR PICK: X–Y` + `PointsBreakdownRow` when a
  scored prediction exists for that match; falls back gracefully when it doesn't.
- `PointsTile` bottom section shows one compact row per `rollup.matches` entry
  (score + pts earned); no inline-slot pill is rendered when a rollup is present.
- Pre-tournament state (no rollup): "Next fixture" pill still appears.
- Frontend lint, typecheck, build, and tests green.

---

# Round 20 — Post-test snagging pass (U44–U47) — added 2026-06-07

Captured from a live review after family testing on Android + iOS. Four batches:
**U44** (🔴 Opus) hardens auth/session after a shared-device account leak; **U45–U47**
(🟢 Sonnet) are onboarding, league-table/hub, and home/shell polish. Ship in order —
U44 is security and time-sensitive (WC opens ~11 Jun). Review items 8, 9, 19 were
already satisfied (U43 result-tile breakdown / existing back-nav + row click); the U21
Young-Player filter was dropped (no squad birthdate data, not worth hand-sourcing).

> **Why U44 is Opus / first:** a tester (owner's dad) re-downloaded the Android PWA and
> landed in the owner's session — the `localStorage` refresh token (30 d) and the SW
> `api-user-data` cache survive a PWA reinstall (same origin). Not a server leak, but it
> exposes a dev auth-bypass shipping in `index.html`, no shared-device guard, and a long
> silent-refresh session. The biometric "Face ID" unlock is being reworked into a PIN
> re-lock regardless (WebAuthn on iOS always saves a passkey — testers found it
> unexpected, and the credential isn't used as a real login), and that re-lock doubles
> as the shared-device guard.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| ~~U44~~ | ~~🔴 Opus~~ | ~~~4 h~~ | ~~U44.1–U44.6~~ | ✅ Shipped 2026-06-07 |
| ~~U45~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U45.1–U45.6~~ | ✅ Shipped 2026-06-08 |
| ~~U46~~ | ~~🟢 Sonnet~~ | ~~~3 h~~ | ~~U46.1–U46.6~~ | ✅ Shipped 2026-06-08 |
| ~~U47~~ | ~~🟢 Sonnet~~ | ~~~1.5 h~~ | ~~U47.1–U47.5~~ | ✅ Shipped 2026-06-08 |

---

## U44 — Auth & session hardening 🔴 Opus · ~4 h

Triggered by a shared-device account leak in testing. Removes a shipped dev backdoor,
replaces the WebAuthn/passkey unlock with a PIN re-lock (which also guards shared
devices), tightens cache/session hygiene, and fixes the avatar-reset bug in the auth
response (same file, rides along).

- **U44.1** Remove the dev-mock auth bypass — delete the `__wc2026_dev_mock__` block in `apps/web/index.html` (it injects fake tokens + a `fetch` interceptor and ships in prod), or guard it strictly behind `import.meta.env.DEV` so it can never run in a production build.
- **U44.2** PIN re-lock replaces WebAuthn — remove `enrollBiometricUnlock`/`verifyBiometricUnlock` (`lib/biometricUnlock.ts`) and the Settings toggle; replace the `BiometricUnlockGate` (`ProtectedRoute`) with a "re-enter your PIN to unlock" gate on reopen. Keep "convenience only; PIN is the source of truth." Rationale: WebAuthn on iOS always saves a passkey to Apple Passwords (the `residentKey:'discouraged'` hint is ignored), which testers found unexpected, and the credential isn't used as a real login. [review item 12]
- **U44.3** Shared-device guard + session — the U44.2 re-lock is the primary guard (a reopened app demands the PIN before any data renders). Add an obvious "Signed in as <name> — not you? Log out" affordance at the unlock/launch screen, and shorten the 30-day refresh lifetime (or require periodic PIN re-entry) — pick a value and document it. [review item 22]
- **U44.4** Cache hygiene on identity change — clear the `api-user-data` (and `api-matches`) Cache Storage entries on **login**, not just logout/refresh-failure, so a previous user's cached leaderboard/stats can't be served offline to a new session (`AuthContext.login` → reuse `clearTokens`'s cache-delete). [review item 23]
- **U44.5** Avatar-reset fix (backend) — include `avatar_url=player.avatar_url` in the `PlayerInfo` built by `/auth/login` and `/auth/signup` (`apps/api/src/routers/auth.py`); it's currently omitted, so `avatarUrl` resets to null on every login and the top bar shows initials. [review item 11]
- **U44.6** Tests — PIN re-lock gate (locked → PIN → in; wrong PIN rejected); login clears the API caches; auth login/signup responses carry `avatar_url`; production build contains no dev-mock block; biometric code/tests removed.

**Acceptance:**
- No `__wc2026_dev_mock__` / fake-auth path in a production build.
- Reopening the installed app (with a stored session) requires the PIN before any data renders; "Log out / not you" is reachable from that screen.
- Logging in clears any prior user's `api-user-data`/`api-matches` cache.
- An uploaded avatar persists across logout/login (top bar shows the photo, not initials).
- Backend + frontend lint, typecheck, build, and tests green.

## U45 — About-first onboarding 🟢 Sonnet · ~3 h

Replaces the first-run swipe tour with landing directly on a reworked About page that
states the multi-league model up front and lets users set Specials without leaving.

- **U45.1** Land first-time users on About — drop the `IntroTour` swipe carousel from the first-run sequence and route new users to `/about` after auth (adjust `FirstRunController`/`FirstRunLaunchpad`). The tour's concepts already live in About. [review items 2 & 3]
- **U45.2** Multi-league hero — a prominent callout at the very top of About: "Predict once · join as many leagues as you like — your picks count in all of them" (the facts exist mid-paragraph in "What is this?" today; elevate + make scannable). [review item 14]
- **U45.3** Embed Specials in About — render the live Specials form (reuse `SpecialsPage`) at the bottom of About, with a top-of-page hint to scroll down and clear "editable until the opening match kicks off" messaging. First-match prediction stays on Home.
- **U45.4** Pre-tournament tasks guardrail — a compact "Your 2 pre-tournament tasks" block near the top of About (Specials + first pick) so users can act without reading the whole page.
- **U45.5** Checklist clarity — make the Pre-Tournament Checklist copy explicit that it's the only checklist and applies only before kickoff. [review item 4]
- **U45.6** Tests — first-run lands on About; Specials submit works from About; hero + guardrail render; tour no longer shown on first run.

**Acceptance:**
- A brand-new user lands on About after signup; no swipe tour.
- About's first screenful states "predict once / unlimited leagues" prominently.
- A user can submit Specials from the bottom of About; copy says they stay editable until kickoff.
- Frontend lint, typecheck, build, and tests green.

## U46 — League table, hub & actions 🟢 Sonnet · ~3 h

Makes leagues feel populated before results, consolidates league management, and tidies
the hub and leaderboard row.

- **U46.1** Roster from join — the league leaderboard lists every member at 0 pts as soon as they join (back-fill from the already-loaded member list, or default-0 server-side), so "No results entered yet" no longer shows for a populated league. [review item 17]
- **U46.2** League-actions ⋯ menu — replace the standalone header "Members" button with a single overflow menu: Members, Leave league (any member), Settings / Delete league (admins). [review item 18]
- **U46.3** Discoverable leave/delete — surface Leave (players) and Delete (admins) in that ⋯ menu, and optionally on the hub `LeagueCard`'s own ⋯; keep the existing type-to-confirm dialogs. [review item 20]
- **U46.4** Hub density — give `MyLeaguesPage` a responsive grid (1-col → 2-col on `md+`) and/or denser cards to remove the dead space. [review item 13]
- **U46.5** Row name fits — tighten the leaderboard tiebreaker column padding so the player's full name isn't truncated. [review item 10]
- **U46.6** Tests — roster renders pre-results; ⋯ menu actions present and role-gated; leave/delete reachable; name column fits at 375 px.

**Acceptance:**
- A league with members but no results shows the full roster at 0, not the empty state.
- Members / Leave / Settings / Delete are reachable from one ⋯ menu (role-gated), behind confirm dialogs.
- Hub shows 2 columns on desktop; the leaderboard shows full names on a phone.
- Frontend lint, typecheck, build, and tests green.

## U47 — Home & shell polish 🟢 Sonnet · ~1.5 h

Small, high-frequency tweaks to the dashboard top tiles, top bar, and metadata.

- **U47.1** Scoring ref under points — move the `ScoringGuide` quick-ref to directly below the `PointsTile` on Home (revisits U40.4's bottom placement — intentional). [review item 6]
- **U47.2** Drop the empty-state line — remove "Your tally starts when the first results land." from `PointsTile`. [review item 7]
- **U47.3** Centre the points — centre the `PointsTile` number + "Points" label (top block only; leave the matchday breakdown below left-aligned). [review item 15]
- **U47.4** Bigger logo — enlarge the Calcio logo in the top bar via a TopBar-specific size, not by changing the shared `Brand` compact variant. [review item 5]
- **U47.5** Multi-league metadata — update `index.html` description / og / twitter copy and the PWA manifest description to reflect multi-league rather than a single tournament. [review item 1]

**Acceptance:**
- Scoring ref sits directly under the points tile; the "tally starts" line is gone; the points number is centred.
- The top-bar logo is visibly larger with no regression to other `Brand` compact usages.
- Browser/SEO/manifest copy reads multi-league.
- Frontend lint, typecheck, build, and tests green.

---

# Round 21 — Live-tournament prediction checklist (U60) — added 2026-06-16

User feedback during the live tournament: it should be easy to see every match in
kickoff order with your prediction and prediction status. The current split makes
that awkward: `/schedule` is a fixture browser with no personal status, while
`/predictions` is a group-tab editor that is good for bulk entry but poor as a
deadline checklist.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| U60 | 🟢 Sonnet | ~3 h | U60.1–U60.6 | Pending |

## U60 — Chronological prediction checklist 🟢 Sonnet · ~3 h

Build a default "all matches" prediction surface in kickoff order, while preserving
the existing group editor as the high-density group-stage entry mode.

- **U60.1** Route + sub-nav model:
  - Make `/predictions` the chronological "All" prediction view.
  - Move the current group-tab editor to `/predictions/group` without losing the
    existing implementation; a simple component rename/split is fine.
  - Update `PredictionsSubNav` to show `All`, `Group`, `Knockout`, `Specials`, with
    `All` first and active on `/predictions`.
  - Update any first-run/home/nav links that intentionally mean "check what I still
    need to predict" to land on `/predictions`; use `/predictions/group` only for
    explicit group-stage bulk entry.

- **U60.2** Chronological score-prediction list:
  - Fetch all matches via `/api/v1/matches` (not `?stage=group`) plus
    `/api/v1/predictions/me`.
  - Sort by `kickoff_utc`, grouped under sticky local-date headings using the
    player's timezone.
  - Reuse `PredictionCard` and `usePredictionEditor` wherever practical so autosave,
    offline queueing, dirty-state preservation, result flash, points badges, and
    lock/live/completed handling stay consistent.
  - Include group and knockout matches; unresolved knockout placeholders should use
    the existing placeholder helpers and stay readable.

- **U60.3** Status and filtering affordances:
  - Each row/card must make the personal status obvious: `Predicted`, `Not predicted
    yet`, `Locked`, `Live`, `FT`, `No entry`, `Postponed`, or `Cancelled` as
    applicable.
  - Add a compact segmented/filter control for `All`, `Needs picks`, `Upcoming`,
    `Live/locked`, and `Completed` so a player can jump straight to missing picks.
  - Show a small summary near the top: total predicted, missing editable picks, live,
    and completed. Keep it dense; this is a tool surface, not a landing page.

- **U60.4** Save ergonomics:
  - Keep the existing debounced per-card save behaviour.
  - Add a `Save visible changes` action when any visible editable card is dirty.
  - Ensure `setPredictionsDirty` still protects update reloads while editing on both
    the new All view and the moved Group view.

- **U60.5** Schedule cross-link:
  - Do not turn `/schedule` into an editor.
  - Lightly surface personal prediction status on schedule cards by fetching
    `/api/v1/predictions/me` and showing a compact badge/text such as `Predicted 2-1`
    or `Missing` for editable matches.
  - Keep `/schedule` primarily a fixture browser; clicking still opens match detail.

- **U60.6** Tests + mobile verification:
  - Update `PredictionsPage.test.tsx` for the new default All view and moved group route.
  - Add coverage for chronological ordering, missing-pick filter, save-visible action,
    dirty-state signalling, and schedule personal-status badges.
  - Verify mobile density at 375 px: filter row scrolls, date headings stick cleanly,
    score inputs do not overflow, and long team/placeholders truncate gracefully.

**Acceptance:**
- `/predictions` shows all matches in kickoff order with the player's prediction/status
  visible for each match.
- `/predictions/group` keeps the existing A-L group-tab editing workflow.
- The predictions sub-nav reads `All`, `Group`, `Knockout`, `Specials`; the correct tab
  is active on each route.
- A player can filter the all-matches view to missing editable picks and save visible
  dirty changes.
- Live/locked/completed/cancelled/postponed states match the existing `PredictionCard`
  behaviour, including points badges and "No entry" after completed unpredicted matches.
- `/schedule` shows compact personal prediction status without becoming an editing page.
- Frontend lint, typecheck, build, and Vitest are green; add or update tests for the
  new routing, filters, status labels, and schedule badges.

---

# Round 22 — Platform-wide player profiles (U61) — added 2026-06-16

Live-tournament bug (user-reported): on **Global Standings** (`/leaderboard/global`),
clicking a player you don't share a league with — e.g. "Bradley R." — shows
"Player not found". The cause is not data (the profile is healthy): the profile
page's gating fetch `/api/v1/stats/{id}` enforces the cross-league read isolation
(**R12.1** — the `shared_league_player_ids` gate) and returns **403** for any
non-league-mate, and `PlayerProfilePage` renders any error as "Player not found".
The global board lists every player platform-wide, so every row outside your own
leagues is a dead link. Confirmed in prod: the viewer and Bradley Reid share no league.

Decision: **open all player-data reads platform-wide.** Any logged-in player can
view any other player's full profile, per-match prediction lists, and specials. The
**reveal gate stays the sole read-privacy boundary** (only post-lock predictions are
ever returned); auth, 404-on-missing/deleted, leaderboard membership scoping,
private-league enumeration (R12.3), and all write isolation are unchanged. This
deliberately retires R12.1 read isolation — a tested invariant — accepted because
only post-lock data is exposed and there is no PII beyond display names (§10.4).
Trade-off noted: scraping every player's post-lock pick history becomes trivial for
any authenticated user; rate-limiting these reads is an optional future hardening.

| Batch | Model | Effort | Items | Status |
|---|---|---|---|---|
| U61 | 🟢 Sonnet | ~2.5 h | U61.1–U61.6 | Pending |

## U61 — Drop cross-league read isolation (platform-wide profiles) 🟢 Sonnet · ~2.5 h

Remove the `shared_league_player_ids` 403/filter from every read endpoint that scopes
data to shared-league players, keeping the per-match/tournament reveal gate intact.
Mostly deletions; the bulk of the effort is flipping the R12 tenant-isolation tests
that assert the old behaviour.

- **U61.1** Hard-gate profile endpoints — delete the `shared = await
  shared_league_player_ids(...)` lookup and the `if id not in shared: raise 403` block,
  keeping the existence/`deleted_at` 404 check above each:
  - `routers/stats.py:146` — `GET /api/v1/stats/{id}` (the gating fetch — this alone fixes the bug)
  - `routers/players.py:82` — `GET /api/v1/players/{id}`
  - `routers/players.py:131` — `GET /api/v1/players/{id}/predictions/recent`
  - `routers/players.py:274` — `GET /api/v1/players/{id}/profile-predictions` (reveal gate stays)

- **U61.2** List / aggregate read endpoints — delete the `shared` lookup and the
  `if player_id in shared` / `if id not in shared: continue` filter so all players' rows
  return; keep the per-match/tournament reveal-gate 403 above each. Rename the now
  body-unused `player: CurrentPlayer` dependency to `_player` to satisfy ruff:
  - `routers/predictions.py:203` — `GET /api/v1/predictions/match/{id}` (powers MatchDetailPage)
  - `routers/knockout_predictions.py:199` — `GET /api/v1/knockout-predictions/match/{id}` (MatchDetailPage)
  - `routers/specials.py:292` — `GET /api/v1/specials/all` (not called by web; consistency)
  - `routers/predictions.py:237` — `GET /api/v1/predictions/player/{id}` (not called by web; consistency)

- **U61.3** Dead-code cleanup — with all 8 callers gone, `shared_league_player_ids`
  (`deps.py:13`) is unused. Delete the helper and drop the now-unused
  `from src.deps import shared_league_player_ids` import in `stats.py`, `players.py`,
  `predictions.py`, `knockout_predictions.py`, `specials.py`.

- **U61.4** Frontend — no code change required for the profile fix (rows resolve once the
  backend stops 403ing). Two notes:
  - MatchDetailPage (`/predictions/match/{id}`) now lists **every** player who predicted
    that match, not just league-mates — functions unchanged but the list can grow; a
    "my league / everyone" toggle is an optional follow-up, out of scope here.
  - Optional: have `PlayerProfilePage.tsx:455` reserve "Player not found" for a genuine
    404 (with the gate gone these endpoints no longer 403).

- **U61.5** Tests — this reverses **R12.1**:
  - In `test_r12_tenant_isolation.py`, flip to expect 200: `test_get_player_cross_league_returns_403`,
    `test_get_recent_predictions_cross_league_returns_403`, `test_get_stats_cross_league_returns_403`,
    `test_player_predictions_cross_league_returns_403`.
  - Invert `test_match_predictions_filters_cross_league_players` and
    `test_match_knockout_predictions_filters_cross_league_players` to assert cross-league
    players ARE included (still gated by reveal/lock).
  - In `test_profile_predictions.py`, flip `test_profile_predictions_non_league_mate_forbidden`
    (:240) to 200; keep `test_post_lock_predictions_visible_to_league_mate`; inspect
    `test_shared_gate_predicate` (:207) — if it covers `shared_league_player_ids` it is
    removed with the helper, if it covers the reveal predicate it stays.
  - Keep reveal-gate 403 tests (e.g. `test_get_all_specials_pre_lock_returns_403`, pre-lock
    match-prediction tests).
  - Add a regression test: a non-league-mate gets 200 from `/stats/{id}` and
    `/profile-predictions`, and a cross-league player appears in `/predictions/match/{id}`.
  - Rewrite the R12 module docstring: R12.1 no longer holds for reads; R12.2 (departed-member
    leaderboard drop-off) and R12.3 (private-league 404) remain.

- **U61.6** Docs — `wc2026-architecture.md` §10.4: add the new visibility model (any
  authenticated player can read any player's post-lock predictions/specials/stats
  platform-wide; the reveal gate is the read boundary; membership still governs leaderboard
  placement, private-league visibility, and writes). Update the "privacy invariant" comments
  in the touched routers to point at the reveal gate as the sole read boundary.

**Acceptance:**
- Clicking any Global Standings row (incl. a player in no shared league, e.g. Bradley R.)
  opens a fully-rendered profile — no "Player not found".
- `/api/v1/stats/{id}`, `/api/v1/players/{id}`, `/players/{id}/predictions/recent`, and
  `/players/{id}/profile-predictions` return 200 for any authenticated requester regardless of
  shared league; still 404 for a missing/soft-deleted player.
- Only post-lock predictions/specials are ever returned (reveal gate unchanged); pre-lock
  reveal-gate 403s still fire.
- `/predictions/match/{id}` and `/knockout-predictions/match/{id}` include all players'
  post-lock picks; `/specials/all` returns all players.
- `shared_league_player_ids` is removed and no router imports it.
- R12 suite updated (cross-league reads now 200 / included); reveal-gate and private-league
  (R12.3) tests still green; regression test for the global-standings scenario added.
- Backend ruff / mypy / pytest green; §10.4 documents the new visibility model.
