# S2 — UX / UI / accessibility / premium-polish review

**Method:** local `vite` dev server with `/api` proxied to the **staging** backend
(dev-only `vite.config.ts` / `.env.local` changes, since reverted), logged in as the
admin (Craig) on staging. Walked at 375 px mobile + desktop, dark + light themes.
Driven via the browser-preview tools (a11y snapshot + screenshot + computed styles).

## Verdict
**The app genuinely meets the "premium" bar and is strongly accessible.** Proper
landmark structure (`banner`/`main`/`navigation`), descriptive link/control labels,
real `tablist`/`tab`/`dialog` roles, AA-passing contrast in both themes, polished
dark *and* light modes, and a clean mobile→desktop responsive story. This confirms
the completeness audit's read that the *player-facing* product is excellent.

## Coverage (live)
Login · Signup · Home dashboard · "More" sheet · Admin Dashboard · Admin Results ·
Admin Sync Status · Predict (Group stage) — across dark/light + mobile/desktop.

## Confirmed strengths
- **Entry (login/signup):** brass CALCIO wordmark + confident tagline/voice; contrast all AA on the dark theme (subtitle ≈7.5:1, "Forgot PIN?" ≈5.2:1, emerald CTA w/ near-black text ≈7.6:1); labeled inputs; segmented PIN with per-digit a11y labels; timezone picker covering all WC host regions.
- **Dashboard:** landmarks + descriptive labels ("Open next match MEX versus RSA"), live countdown, real fixtures with timezone-correct kickoffs, points tile, My-Leagues hub.
- **Predict:** `tablist` Groups A–L, Specials/Group/Knockout sub-nav, custom score-steppers (no native inputs), per-match countdown + Open/PREDICTED states, labeled "Save Group A".
- **Themes & responsive:** dark + light both polished and AA-contrast; desktop reflows to a centered max-width, 2-column league grid, full names.

## New findings (this pass)
- **[P2 · a11y] Score-stepper chevrons** — verify the up/down controls in `score-input.tsx` have explicit accessible labels (e.g. "increase Mexico score") and announce the value to screen readers.
- **[P2 · UX] Admin Sync Status surfaces raw escaped JSON** — the "RECENT ERRORS" panel shows `{"reason":"Server error 500: {\"message\":...}"}` verbatim to the admin; format into a friendly line.
- **[minor] Desktop keeps the mobile bottom TabBar** rather than a desktop nav — defensible for a phone-first PWA; note only.
- **[minor] Cold load fires 3× `POST /auth/refresh` → 401** before login (handled gracefully, just noisy).
- **[P1 carry] `apps/web/.env.local` points local dev at PRODUCTION** — restored as found; recommend pointing local dev at staging/localhost to avoid accidental prod writes during development.

## Live confirmations of existing backlog items
- **GAP-02** (admin Results page is display-only — no entry/override affordance) — confirmed in the running UI.
- **GAP-03** (no knockout-advance control) — confirmed absent from both the "More" sheet and the Admin Dashboard "MANAGE" section (Sync/Results/Players/Invites/All Leagues).
- **C-P1** (football-data 5xx not retried) — confirmed live: staging Sync Status shows a 2026-05-27 `sync_failed` on a football-data **500**, `consecutive_failures: 1`.
- **football-data 403 reframed** — staging's own key **last synced OK 2026-05-30**, so the 403 was the *local `.env`* key; the Railway prod key must be verified (see backlog).

## Design-audit (2026-05-25) reconciliation
- **C-1 brand voice** — addressed (tagline + recurring brass wordmark / mono eyebrows).
- **C-3 native selects** — addressed (custom score-input + segmented PIN; native `<select>` only for timezone, which is the appropriate exception).
- **C-2 leaderboard dedup** — not directly exercised; dashboard showed no duplicates. Verify on a populated leaderboard.
- **C-4/C-5/C-6 (elevation / motion / empty states)** — elevation and empty states look improved (e.g. Results empty state); motion polish not verifiable from static captures.

## Not deep-tested live — recommend spot-check
Schedule, Match Detail, Knockout **bracket visualisation**, Specials form, Leaderboard
+ history chart + round leaderboard, Player profile, Head-to-Head compare, Notification
preferences, **Settings (confirm timezone is NOT editable — GAP-06)**, Group standings,
Join-by-code, and full **keyboard-only** navigation.
