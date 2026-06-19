# Design Audit — Round 2 — 25 May 2026

**App:** The Steele Spreadsheet System
**Branch:** `feat/premium-polish` (no implementation yet)
**Surface walked:** staging (`https://wc2026-staging.vercel.app`) via local dev build proxied at staging backend, iPhone viewport (375 × 812)
**Reviewer:** UI/UX audit pass 2, framed against Nielsen heuristics, Apple HIG mobile principles, and a "premium app" bar — i.e. could a friend opening this on their phone plausibly believe a small studio built it.

The first uplift took the app from "competent" to "native-feeling". The bar for this pass is "expensive-feeling". This document is the gating artefact for Phase 2 and Phase 3 — no implementation has started.

---

## Methodology

- Cold-loaded every route on a 375 × 812 viewport
- Walked the 5 prompt-mandated journeys (first-time invite, daily returner, match day, knockout transition, end of tournament) — match day and knockout transition are partially synthetic because seed data has no live or knockout fixtures, so those findings are derived from source plus pre-tournament state
- Captured both dark and light mode for the dashboard and settings
- Captured the "More" sheet and admin section as a separate concern
- Read the source for every page touched, plus `Brand`, `TopBar`, `TabBar`, `PageTransition`, `EmptyState`, `theme/tokens.ts`, `index.css`
- Recorded baseline bundle figures for Phase 4 comparison

## Phase 1 baseline (lock these so Phase 4 has a comparison point)

| Metric | Value |
|---|---|
| Main entry chunk (`index-BOeeKr3L.js`) gzip | **8.54 kB** |
| `react-vendor` chunk gzip | 53.83 kB |
| `query` chunk gzip | 12.76 kB |
| `supabase` chunk gzip | 53.30 kB |
| `LeaderboardHistoryPage` chunk gzip (recharts) | **107.97 kB** — dominant cost on a lazy route |
| `framer-motion` chunk gzip | 36.75 kB |
| Service-worker precache | 48 entries, **1221.18 KiB** |
| Build time | 53.7 s (Vite + SW build) |

**Lighthouse mobile (deployed staging):** to capture before Phase 3 — see open question Q-12.

## Severity legend

- 🔴 **high** — visible quality damage; a paying user would notice; fix this pass
- 🟡 **medium** — meaningful polish gap; fix unless cost is high
- 🟢 **nit** — observed but small; only fix if cheap

---

## Cross-cutting findings (the big picture)

### C-1 🔴 The wordmark is excellent; the rest of the brand voice isn't doing it justice

The brass JetBrains-Mono wordmark on the splash is the strongest single visual asset in the app. Everything around it — the "Still Email?" tagline, the avatar pill, the page headings — doesn't pick up that thread. The result: a premium logo surrounded by competent-but-anonymous chrome. Premium apps have **one** clear brand voice that recurs every 200–400 px of scroll. Right now the brand fades as soon as you leave `/login`.

**Recommendation:** Pick one brand-voice element to repeat at known cadence — e.g. a 1-px brass divider, a brass micro-icon next to every page title's eyebrow, OR a subtle brass underline on the active tab. Lock the choice and apply it everywhere.

### C-2 🔴 Backend leaderboard returns 9 rows for 3 players, all ranked #4

`GET /api/v1/leaderboard` (staging) currently returns Craig × 3, Jim × 3, TestPlayer × 3, all `rank: 4`, all `total_points: 0`. This is a backend bug — but the frontend faithfully renders it (`Leaderboard`, `Dashboard.MiniLeaderboard`, `PlayerProfile`). Until the backend is fixed, both the dashboard mini-table and the full leaderboard look broken to any newcomer.

**Recommendation:**
1. Fix the backend bug (separate ticket — out of scope here, but flag it).
2. **Also** dedupe defensively on the client by `player_id` so the UI never amplifies a backend regression like this. With 0 points across the board, frontend should also display `rank: 1` (tied first) rather than the wrong server value.

### C-3 🔴 Native `<select>` everywhere it doesn't belong

`LoginPage`, `SpecialsPage`, `ComparePage` all drop a raw `<select>` into otherwise styled forms. The chevron is grey, the font is platform default, the dropdown chrome is OS-native. This breaks the design system at exactly the points where the user makes their most committed choices (signing in, picking the World Cup winner, picking who to compare).

**Recommendation:** Replace with the shadcn `Select` (Radix) the rest of the app already uses, or with a custom pill-style picker that matches the brand voice. Make sure mobile native pickers still appear for `<input type="time">` where the OS UI is genuinely better.

### C-4 🟡 The design system has the tokens but the pages don't fully use the elevation story

`tokens.ts` defines `surface` → `surface-elevated` → `surface-overlay` → `surface-overlay`-on-`surface-overlay`. In practice almost every card is `bg-surface` on `bg-bg`. There's almost no layered depth — no card on card, no sticky elevated header with a different bg, no sheet overlay tinted differently from the underlying card. Premium apps use 3 elevation tiers visually; this app uses 1–2.

**Recommendation:** Audit each page for one place where the next tier of elevation would tell a story (e.g. the sticky date header in Schedule should be `surface-elevated` not `bg/95`; the "Your Prediction" card on `MatchDetail` should be `surface-elevated` to lift it out of the page).

### C-5 🟡 Motion is conservative, but the transitions that exist are too quick to register

220 ms `out-quart` on page transitions is fine, but it's the *only* signature motion. There are no list-item stagger entries, no entry transitions on cards, no spring on the score-input numbers when they change, no celebration moment when a prediction is saved (`Save` button just sits there). The app currently feels efficient but never delighted.

**Recommendation:** Pick three to four motion moments to invest in:
1. Score input — spring when the number changes (subtle 1.1× pop)
2. Predictions saved — `Save` button briefly becomes "Saved ✓" with a checkmark draw
3. Leaderboard rank delta — when a rank shifts, the arrow does a 200 ms scale-tap pulse
4. Splash to dashboard — a 380 ms wordmark-to-corner motion (logo shrinks/moves to top-left into TopBar position) instead of a hard cut

These are cheap, but they're the difference between "competent" and "felt".

### C-6 🟡 Empty states are written well; visually they're identical and feel inert

Every empty state is the same dashed-border card with title + description. That's consistent (good) but it also means the bracket empty state, the knockout-picks empty state, the round-leaderboard empty state and the results-history empty state all look the same. Bracket is a *centrepiece* of the tournament and deserves a richer state — even a faded greyscale silhouette of the bracket shape would set expectation.

**Recommendation:** Tier empty states by content weight:
- **Anchor pages** (Bracket, Knockout Picks, Round Leaderboard) — get a custom illustration cue (SVG, single colour, ~3 KB), a countdown to when the page will populate, and one link to a related screen the player can use *now*
- **Secondary pages** (Compare, Results history) — keep the current EmptyState
- **Admin pages** — keep current

### C-7 🟡 Back-button placement is inconsistent and on the wrong side

Several pages put a `← Leaderboard` / `← Admin` / `← Groups` button in the **top-right** action slot (`PageHeader`). Across iOS, Android and the web at large, back is bottom-left or top-left. Putting it top-right where the primary CTA usually lives is consistently surprising. iOS users especially will reach left.

**Recommendation:** Move back affordance to top-left, keep right slot for forward actions (Edit, +New, etc.). Or remove the back chip altogether and rely on the system back gesture / tab bar — most of these are not deep stacks.

### C-8 🟡 Welcome-name uses brass gradient on the name itself — competing with the logo

`Welcome back, Craig` renders "Craig" with the same `wordmark-h` gradient as the page logo. Two brass text moments per screen dilutes both. The logo is brand; the welcome is human. They should look different.

**Recommendation:** Drop the gradient on the name and rely on weight contrast (`font-semibold` is enough). Reserve the wordmark gradient for the wordmark alone.

### C-9 🟢 "Still Email?" tagline is unexplained on first contact

A new invite recipient sees the wordmark and "Still Email?" with no context. It's clearly an inside joke (suggesting "we used to do this by email") — and that's the brand voice — but a first-time user just sees a non-sequitur.

**Recommendation:** Two options. Either lean in (and have the About / Help surface explicitly tell the story: "We used to do this in a spreadsheet, by email, every four years…"), or move it from the login splash to the About page only.

### C-10 🟢 The bottom tab "More" position visually clashes with the dashboard "Standings" pill

The mini-leaderboard heading on the dashboard says "Standings" and the bottom-tab item also says "Standings". On a short viewport both are visible simultaneously and it's unclear whether tapping one is the same as tapping the other (in fact they go to the same destination via different routes — `/leaderboard` and `/leaderboard` through the tab).

**Recommendation:** Rename the dashboard mini-section to **"Top of the table"** or **"Leaders"** to differentiate from the tab item.

### C-11 🟢 No dedicated About / Tournament info page

The app has no surface explaining what the league is, the scoring rules, how knockouts open, or who built it. The Settings page is the catch-all but it's purely device/account. A first-time invite recipient who is curious has nowhere to go.

**Recommendation:** Add an About / How it works page in the More sheet. Make it the home of the brand voice (tagline explanation, scoring summary, knockout-flow diagram, attribution). 1 short page; high leverage.

### C-12 🟢 Streak metric shows "0 🔥" — emoji is wrong at zero

PlayerProfile shows `0🔥` for current streak when there is no streak. Fire-emoji means "on fire" — a zero streak isn't on fire.

**Recommendation:** Show `—` (or hide the emoji until streak ≥ 2). Same logic for `AVG SUBMIT TIME: 602h before` which is meaningless once converted from hours.

### C-13 🟢 Light mode is good but unverified — most of the audit was dark

Light mode looks polished in the slices I sampled (settings, dashboard). But it's not tested page-by-page. A premium app ships with both modes pixel-checked.

**Recommendation:** Phase 4 should include a screen-by-screen pass in light mode. This is a check, not new work.

---

## Per-page findings

### `/login` — Login splash

**Visual:** Wordmark + `Still Email?` italic tagline + card with name select / PIN input / sign-in button.

- 🟡 **L-1** The card is roughly 60% down the viewport. On a 375×812 phone the user has to scroll **slightly** to see the Sign-in button comfortably (or thumb reaches it but the bottom hand position is awkward). Move card up; let the splash logo breathe in the top 35%, place the form in the middle 40%, leave 20–25% under the button.
- 🔴 **L-2** Name input is a **native `<select>`** (see C-3). Visual rough edge at the most-trafficked entry.
- 🟢 **L-3** The PIN input is a plain `<input type="password">` with letter-spacing. A 4-digit PIN deserves a 4-cell segmented input — more iOS-banking-app-like, easier on the eye, and signals what to type.
- 🟢 **L-4** No "Trouble signing in?" hint. If a player forgets their PIN they're stuck. The PIN-reset runbook is admin-side, so the link should say "Ask the league admin for a reset".

### `/join/:token` — Invite acceptance

**Walked with an invalid token (no unclaimed invites in staging).**

- 🟡 **J-1** Invalid-token state shows "Invalid invite token" + "Ask the admin for a new invite link." No way back to `/login`, no way for a returning player to recover. Add a `Go to sign-in` link.
- 🟢 **J-2** The error red `#EF4444` against the dark surface is fine, but the rest of the card is empty — feels like a 404 in a sleek shell. Lean into a one-line "What's this app?" so a curious mis-clicker still gets *something*.

### `/` — Dashboard

**Visual:** TopBar + Welcome heading + Rank/Points stat cards + Next-match countdown + Latest-result + Mini-standings + Quick-link cards.

- 🔴 **D-1** Mini-standings shows the dup-rows bug from C-2.
- 🔴 **D-2** "Welcome back, Craig" — name uses wordmark gradient (see C-8).
- 🟡 **D-3** **Five visually similar cards in a row** before the user gets anything actionable. Stat × 2, countdown × 1, latest × 1, mini-table × 1, then 3 quick-links. Premium dashboards lead with **one** moment (the next match, with countdown front-and-centre) and let the rest stack as secondary depth.
- 🟡 **D-4** The "—" rank / "—" points placeholder flashed during my walk **after** real data had been fetched once (Refresh in light mode). Indicates a React Query stale/fetch race that surfaces as a UX flicker. Add a placeholder skeleton with `useInitialData` from the cache, or hold last-known values until refetch resolves.
- 🟡 **D-5** "Next Match: 17d 4h" is the most important number on the screen pre-tournament. It's rendered at `text-2xl` — same size as other stats. Premium move: dedicate a card to it, make it the largest visual element, add a "Predict now" CTA on the card.
- 🟢 **D-6** "0 pts" pill on Latest Result with no entry currently reads `0pts no entry` — close to it visually but readable. After the first scored match this becomes the most-glanced element, so the pill needs more contrast between "earned points" and "no entry" — colour alone isn't enough.
- 🟢 **D-7** Quick links (Predictions, Knockout Picks, Specials) are below-the-fold on a small phone. Consider moving them above the mini-table — most players come here to predict, not to gloat.

### `/schedule` — Fixture list

**Visual:** Page header + stage filter pills (All, Group, R32, R16, QF, SF, 3rd, Final) + date-grouped match cards.

- 🟡 **S-1** "3rd" filter pill is the awkward-truncated edge piece — visible scroll affordance, but the label is non-obvious (could read as "3rd place" or "3rd round"). Use **"3rd place"** explicitly.
- 🟡 **S-2** The countdown under each kickoff time (`17d 4h` etc.) duplicates information that appears on the dashboard, the match-detail page and the predictions list. Five places to show the same countdown is too many. Drop it from the schedule list — keep just kickoff time — and the cards become 20% shorter.
- 🟢 **S-3** Country codes (MEX, RSA, KOR, CZE) next to flags is the right call for narrow screens, but they're at `text-sm` next to a `text-sm` "vs" — typography contrast is flat. Bump team codes to `font-semibold` (or `font-medium tracking-tight`), keep "vs" as a small muted divider.
- 🟢 **S-4** "Estadio Azteca, Mexico City" venue line is small (`text-xs text-text-muted`) but valuable. Premium apps would treat venue as part of the story (small icon? city flag?). Optional.

### `/predictions` — Group-stage predictions

**Visual:** Predictions sub-nav (Group / Knockout / Specials) + group selector (Group A–H) + match score-input cards.

- 🟡 **P-1** **Two rows of pills** on a mobile width (sub-nav + group selector) eats ~84 px of vertical space. Collapse the group selector into a single picker (`Group A ▾`) that opens a sheet, OR rely on horizontal scroll only with no first row.
- 🟡 **P-2** Score inputs are chevron-up + big number + chevron-down. They are *huge* — fine for tapping, but each match card is ~135 px tall. On Schedule a match is ~64 px. Tap-target is 44 px; the score input could be 60 px and still comfortably tappable, returning ~30% vertical density. More matches in view = more sense of progress.
- 🟡 **P-3** No "save" affordance. When does a prediction commit? On every chevron tap? On focus loss? On a Save button at the bottom? On `MatchDetail` there's an explicit `Save`; on the list view there is none. This is a Nielsen-2 problem: the user's mental model and the app's behaviour don't match.
- 🟢 **P-4** No batch-edit affordance. A new player loading their first day of matches has 6+ open matches and no "predict all 0–0 and refine" starting point. Default values would be welcome — even just "?–?" rather than `0–0` so the player knows they haven't committed.

### `/predictions/knockout` — Knockout picks

- 🟡 **K-1** Empty state is bare text on a dashed card (see C-6). Bracket is the **centrepiece feature** of the knockout phase; pre-tournament empty state should hint at the shape of what's coming.

### `/predictions/specials` — Tournament specials

**Visual:** Three cards (Tournament Winner, Golden Boot, Top Scoring Team) with icon + question + native `<select>` or text input + Update button + points pill.

- 🔴 **Sp-1** Native `<select>` for "Which team lifts the trophy?" — for the highest-value single pick in the league. See C-3.
- 🟡 **Sp-2** Lock-in banner reads `🔒 Locks in 17d 4h — at the opening match kickoff.` Functional but understated. This is the only chance to enter these picks. Make it a sticky banner under the page header, slightly elevated, with the countdown ticking.
- 🟡 **Sp-3** Icon set on the cards (trophy / star / lightning) is inconsistent — three different "kinds" of icon. Either go all-lucide-line (current trophy + star) or all-illustration. Lightning bolt feels off-brand for "team that scores most".
- 🟢 **Sp-4** "Update" button label is incorrect when no pick has been made yet. First save should say "Save"; subsequent saves can say "Update".
- 🟢 **Sp-5** Saved-state confirmation is invisible. After "Update" there's no toast, no checkmark animation, no obvious "you have set this pick". Add a saved-state visual (button briefly becomes "Saved ✓").
- 🟢 **Sp-6** `3 / 3` pill in the title — nice progress indicator but currently the same dim grey as other badges. When the count is `3 / 3` (complete), upgrade it to the success variant (green outline).

### `/bracket` — Knockout bracket

- 🟡 **B-1** Pre-tournament empty state is a single dashed card with "Bracket isn't ready yet". The bracket *is* the showpiece of the second half of the tournament. Give it a teased, greyscale silhouette of the 16-match R32 column with placeholder slots — players should be able to picture what's coming. (~5 KB of SVG.)
- 🟢 **B-2** The actual bracket SVG (when populated) uses `BOX_W = 168 BOX_H = 52` per match — that's wider than the viewport. Horizontal scroll is expected; what's missing is a mini-map / current-position indicator. (Not testable here; flagged for tournament.)

### `/groups` — All groups

**Visual:** 8 group cards (A–H), each a mini standings table.

- 🟡 **G-1** All zeros pre-tournament means the same number `0` × 7 columns × 4 teams × 8 groups = 224 zeros on the page. The card becomes a wall of nothing. Pre-tournament state should switch to "Opening fixtures" — first match of each group with kickoff time — until matches start scoring.
- 🟢 **G-2** "Details →" link in the upper-right of each card is a tap target ~24 px tall — below the 44 px iOS standard. The whole card should be tappable.

### `/groups/:name` — Group detail

- 🔴 **GD-1** **9-column standings table on a 375 px viewport** (#, Team, P, W, D, L, GF, GA, GD, Pts — actually 10 cols). Numbers are tight against each other; on a real phone this is borderline unreadable when populated. Drop columns by default — show P, W, D, L, Pts; reveal GF/GA/GD on tap or in landscape.
- 🟡 **GD-2** Back button on the right (see C-7).
- 🟢 **GD-3** `(CZE)` suffix after `Czech Republic` is redundant with the flag immediately to its left. Drop it.
- 🟢 **GD-4** Bottom of page is empty whitespace pre-tournament. Surface upcoming fixtures for this group + "Predict Group A matches →" CTA.

### `/matches/:id` — Match detail

- 🟡 **MD-1** Score editor on this page is **smaller and styled differently** than the one on `/predictions`. Inconsistent — pick one score-input pattern and apply everywhere.
- 🟡 **MD-2** "Last saved · updated 1 time" is awkward. Use a relative timestamp ("Saved 2 minutes ago"). Source-checked: the string is built ad hoc — easy to centralise.
- 🟡 **MD-3** Match-header card is `p-6` and dominant — but the **prediction editor below it** is smaller. The hierarchy is inverted: I came here to predict, not to read team names. Flip — make prediction card the hero, header card the secondary frame.
- 🟢 **MD-4** Pre-lock state hides other players' predictions (correct for privacy). But there's no "X other players have submitted" anonymous count — a low-leak social cue that builds league atmosphere. Add a "5 of 7 players predicted" line.

### `/leaderboard` — Overall standings

- 🔴 **LB-1** Duplicate rows + wrong rank (see C-2).
- 🟡 **LB-2** Four sub-nav tabs (Overall, By round, History, Compare) is heavy for a primary table page. Consider collapsing — Compare belongs in the More sheet; History deserves its own surface; By round could be a filter chip above the table rather than a separate route.
- 🟡 **LB-3** "Tap a row for breakdown · long-press to compare" hint at the very bottom (off-fold on most phones). Move it to under the page header.
- 🟢 **LB-4** Rank-delta arrow column (`—` for unchanged) is very subtle. After a few rounds this will be the most-looked-at signal in the app; treat it with more importance.

### `/leaderboard/history` — Rank history chart

- 🟡 **LH-1** Recharts dot-plot, not a connected line plot. With more than a couple of rounds, lines tell the story better than dots — "I was 7th, climbed to 3rd over the group stage" is a narrative, not a scatter.
- 🔴 **LH-2** **107 kB gzipped (recharts)** for a single chart on one secondary page. This is the biggest single bundle cost in the app. Evaluate replacing with a hand-rolled SVG line chart — for the dataset (≤15 players × ≤104 matches) it would be ~3 KB of code.
- 🟡 **LH-3** Craig's player chip is green outlined — green is the brand primary used for emphasis. Using it as a per-player colour conflicts with brand. Use neutral player chip colours; reserve primary for app-level emphasis.

### `/leaderboard/round/:stage` — Round-stage leaderboard

- 🟢 **RL-1** Round filter pills (Group Stage / R32 / R16 / Quarter…) — "Quarter" is truncated. Use abbreviations consistent with the schedule page filter (QF, SF, F).

### `/compare` — Head-to-head

- 🔴 **Cmp-1** Native `<select>` × 2 (see C-3). Most committed UI on the page — picker-style.
- 🟡 **Cmp-2** Selectors are right-aligned, leaving large empty left-half — unbalanced. Centre the picker pair, or place A and B side-by-side full width.
- 🟢 **Cmp-3** Long-press affordance is double-mentioned (intro paragraph + empty state). Trim to one location.

### `/players/:id` — Player profile

- 🟡 **PP-1** Streak `0🔥` (C-12).
- 🟡 **PP-2** `AVG SUBMIT TIME: 602h before` — un-converted hours. Format as `25d 2h before` or `~ a month before kickoff`.
- 🟡 **PP-3** Best/Worst round both `Group Stage 0 pts` pre-tournament — collapse to "No round results yet" until there's variance.
- 🟢 **PP-4** Recent Predictions table: `0` pts in red colour reads as "you failed". When the actual result is `?–?` (unplayed), the points cell should be `—` or neutral, not red `0`.

### `/settings` — Settings

- 🟢 **Set-1** "Subscribe" button visible even when permission is `denied` — should switch to "Open browser settings" with platform-specific deep-link copy.
- 🟢 **Set-2** Long preference labels (`Deadline warning (15 min before kickoff)`) wrap to two lines on mobile — fine, but consider shortening to `Deadline reminder` and putting the timing in a sub-label below.
- 🟢 **Set-3** Quiet hours uses two native time inputs — acceptable since `<input type="time">` opens the right OS UI on every platform. Leave alone.

### `/admin/*` — Admin pages

- 🟢 **A-1** Admin Dashboard 2-1 stat grid (Active Players, Upcoming Locks / Pending Results) is asymmetric. Use 1-1-1 or add a fourth stat.
- 🟢 **A-2** `Sync Now` button is small for a primary admin action. Make it full-width on mobile.
- 🟢 **A-3** Invites page has no Pending / Claimed filter — fine for now (5 invites), but consider it pre-tournament.
- 🟢 **A-4** Players page `Remove` button is bright filled red — appropriate for destructive — but tap target is small. Increase padding and require a confirmation step.

### Mobile "More" sheet

- 🟢 **More-1** "Sign out" rendered in error red is more alarming than the action warrants. Tone down to a normal text colour with a small icon; reserve red for true destructive.
- 🟢 **More-2** Two "Admin" groups in the navigation chrome (Admin Dashboard, Invites, Players) but Sync and Results aren't in the More sheet — only reachable via Admin Dashboard. Either surface all admin pages in the sheet or none, but not partial.

---

## Per-journey findings

### Journey 1 — First-time invite recipient

**Steps walked:** opened `/join/<token>` (invalid), then `/login` (no account).

- 🔴 First impression in the browser is `Still Email?` with **zero context**. New players have no idea what they signed up for. Add either a one-line "the invite-only World Cup 2026 prediction league" subtitle, or link to an About page.
- 🟡 Once on `/login`, there is no public information about the app. A curious recipient cannot learn anything before signing in. Premium apps onboard before the auth wall.
- 🟡 After signing in, the dashboard dumps the player straight into a wall of 5 cards. There is **no first-run experience** (no "Welcome — here are the 6 things you can do" coachmark). Even a single dismissable banner ("Make your group-stage predictions before 11 June — earn up to 459 points") would re-orient the player to the season.

### Journey 2 — Daily returner

**Simulated:** open app → check Standings → see what's next → predict upcoming matches.

- 🟡 The Standings link from the dashboard goes to the same destination as the bottom-tab Standings (which is correct), but the duplicate-Craig data makes the table look broken. After C-2 is fixed this is probably fine.
- 🟡 "See what's next" — Dashboard surfaces only the **single** next match. The premium move is to surface today's slate (could be 3 matches on a typical World Cup day) with a one-tap "Predict today's 3 matches" CTA.
- 🟢 Tab navigation between Home / Schedule / Predict / Standings / More is fast and clean. Page transitions feel snappy.

### Journey 3 — Match day

**Synthetic — no live fixtures in staging.**

- 🔴 There is **no "live match" surface** anywhere in the navigation. During an actual live match the player has no obvious place to land that says "this is happening now". Source check confirms: live matches are displayed in `Schedule` and `MatchDetail` with the `live` badge, but nothing on the dashboard surfaces a live match more prominently than a scheduled one.
- 🟡 The dashboard's "Next match" card transforms into "Kicked off" once countdown expires — but doesn't update to show live score, doesn't link to a live surface, doesn't celebrate that the tournament is happening. Premium: when a match is live, replace the "Next match" card with a live score card and a low-key animation pulse.
- 🟡 No live-score notification surface in-app. Push notifications cover deadlines, locks, and results — but no "match started" or "goal scored" toast.

### Journey 4 — Knockout transition

**Synthetic — bracket empty in staging.**

- 🔴 When the bracket flips from "not ready" to populated, there is **no celebration moment**. The empty state simply gets replaced with the bracket. Premium apps would mark this transition with an in-app toast ("The bracket is set — make your knockout picks") and surface the new state on the dashboard for at least 48 hours.
- 🟡 Knockout-picks page once active needs a "X of 8 picks made" progress chip (like Specials' `3/3` pill). Source check: not implemented yet.

### Journey 5 — End of tournament

**Synthetic.**

- 🔴 The final whistle is the most important moment of the year. Currently there is no "final standings" surface that looks different from any other day's leaderboard. Premium apps drop a confetti/medal moment, expose the year's MVP picks (best Special, longest streak, biggest comeback), and offer a shareable "I came X in The Steele Spreadsheet System 2026" card.
- 🟡 The trophy-medal emoji (🥇🥈🥉) is already in the mini-leaderboard — good — but the real moment deserves more: a podium illustration on the dashboard for the final round, a tap-to-share medal asset.

---

## Open questions for the user

Each of these has a recommended direction. I'll lock in your answer before Phase 3 implementation.

- **Q-1** Dark mode is the default and looks better. Light mode is functional. Do you want me to **commit to dark-only** for round 2 and remove the toggle (one fewer codepath to maintain), or keep light/system as supported and pixel-check both in Phase 4? *Recommended: keep both; the Settings toggle is already shipped and removing it would be a regression in optionality.*
- **Q-2** "Still Email?" — keep as-is, move to About page only, or replace? *Recommended: keep on login (the joke lands if you "get it") but add a brief subtitle on first visit only.*
- **Q-3** The brand-voice repeating element (C-1) — pick one: (a) 1-px brass divider under page headers, (b) brass micro-icon next to eyebrows, (c) brass underline on active tab. *Recommended: (a) — quietest, most premium.*
- **Q-4** Welcome line gradient on the name (C-8) — drop the gradient on "Craig"? *Recommended: yes.*
- **Q-5** Recharts → hand-rolled SVG (LH-2) — would save 107 KB gzipped. Worth the implementation cost, or leave on a lazy route? *Recommended: replace — the route is in the primary nav.*
- **Q-6** Standings-column reduction (GD-1) — agreed to drop GF/GA/GD by default and reveal on tap? *Recommended: yes.*
- **Q-7** Score-input pattern unification — keep the big chevron-up/down on `/predictions`, or unify with the smaller pattern on `MatchDetail`? *Recommended: keep big inputs on `/predictions` (it's a prediction-entry page); make `MatchDetail` use the same component.*
- **Q-8** Bracket pre-tournament teaser — invest in a greyscale R32 silhouette (B-1)? *Recommended: yes, ~half a day.*
- **Q-9** Live match surface (Journey 3) — add a "Live now" card to the dashboard during live matches and a route `/live` for the live surface? *Recommended: yes — single-card dashboard treatment, no new route needed.*
- **Q-10** First-run coachmark — add a one-time dismissable "Here's how it works" overlay for new players? *Recommended: no — too easily mistaken for an ad. Better to add an About page (C-11) and surface it once on first dashboard load.*
- **Q-11** Final-whistle celebration (Journey 5) — invest in podium + shareable card for the end of the tournament? *Recommended: yes — it's the moment the app exists for.*
- **Q-12** Should I capture a real Lighthouse-mobile run against staging right now (manual) as Phase 1 baseline, or just diff against deployed prod post-Phase-3? *Recommended: do it now (5 minutes) so we have a single number to compare to.*
- **Q-13** End-of-pass scope guard — there are ~80 findings here. Realistically Phase 3 can land **8–12** of the highs/mediums in a coherent batch. Which areas matter most to you? *Recommended priority:*
  1. C-1 brand-voice element (single low-cost change that lifts every page)
  2. C-3 / L-2 / Sp-1 / Cmp-1 — kill native `<select>` everywhere
  3. C-7 — back-button placement consistency
  4. C-8 / D-2 — welcome line cleanup
  5. C-6 / B-1 — bracket empty state premium treatment
  6. D-3 / D-7 — dashboard rebalance (next match hero, predict CTAs above the fold)
  7. C-5 — three motion moments (score, save-confirm, rank-delta)
  8. PP-1 / PP-2 — streak and submit-time copy fixes
  9. LB-1/LB-3 — leaderboard hint placement + (frontend dedupe pending C-2 backend fix)
  10. New logo (Phase 2 deliverable)

---

## Phase 2 next steps (in parallel with your review)

I am about to draft 5 logo SVG concepts in `docs/logo-concepts/` per the brief — typographic monogram, geometric duality mark, bold pure letterform, illustrative grid/ball hybrid, and a playful option. I'll push them in the same branch and pause for your direction-pick before Phase 3.

---

## Notes for the implementation pass (Phase 3)

- Local dev build was proxied at staging via a temp edit to `vite.config.ts` (`server.proxy['/api']` re-targeted) and an empty `.env.local`. **These changes will be reverted before any commit lands** — they were for the audit walk only.
- All audit screenshots reside in the chat-side preview captures only (no checked-in files). If you want a permanent record, I can save them under `docs/design-audit-2026-05-25/` when we move to Phase 3.
- Bundle baseline above is the comparison target for Phase 4.
