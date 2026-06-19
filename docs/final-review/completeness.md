# Feature Completeness Audit — Pre-Production Review
**Date:** 2026-06-08  
**Auditor:** Claude Sonnet 4.6 (static analysis only; no dev server run)  
**Scope:** All 61 architecture phases + M1–M10 multi-league phases + U-series polish batches through U49

---

## Method

1. Extracted feature/acceptance criteria from `wc2026-architecture.md` §6 and §16, and `docs/multi-league-architecture.md`.
2. Traced each criterion to implementing code (routers, pages, migrations, services).
3. Identified functional gaps, missing UI surfaces, and spec deviations.
4. Reviewed `docs/soak-review/code-audit-2026-05-30.md` for known issues and their resolution status.

---

## 1. Feature Coverage Matrix

### §6 Key Features

| Feature | Spec | Backend | Frontend | Status |
|---|---|---|---|---|
| 6.1 Scoring (group) | §6.1 | `migrations/004_scoring_function.py`, `021_scoring_knockout_draws.py` | `packages/shared/src/scoring.ts` | ✅ Complete |
| 6.1 Scoring (knockout, draw-void removed) | Phase 12.1 | `021_scoring_knockout_draws.py` | `packages/shared/src/scoring.ts` | ✅ Complete |
| 6.1 Scoring (specials, 6 types) | Phase 12.2 | `022_specials_expansion.py`, `routers/specials.py` | `pages/SpecialsPage.tsx` | ✅ Complete |
| 6.2 Per-match prediction locking | §6.2 | `routers/predictions.py:114` (`status!=scheduled OR kickoff_utc<=now`) | `PredictionCard.tsx` | ✅ Complete |
| 6.2 Specials lock at opening match | §6.2 | `routers/specials.py:117–121` (uses `specials_revealed()`) | `SpecialsPage.tsx` | ✅ Complete |
| 6.2 Admin early lock (`POST /admin/matches/{id}/lock`) | §6.2 spec | **Missing** — not in `routers/admin.py` | **Missing** | ❌ Missing |
| 6.3 Group standings (FIFA tiebreakers) | §6.3 | `routers/groups.py` | `GroupsPage.tsx`, `GroupDetailPage.tsx` | ✅ Complete |
| 6.3 Admin standings override (API) | §6.3 | `admin.py:365` (`POST /admin/groups/{name}/override-standings`) | **No UI** — API exists, no form in admin pages | ⚠️ Partial |
| 6.4 Knockout bracket build + advance | §6.4 | `services/knockout_advancement.py`, `admin.py:1204` (`POST /admin/knockout/advance`) | **No UI** — API only | ⚠️ Partial |
| 6.4 Bracket visualisation | §6.4 | — | `pages/BracketPage.tsx` | ✅ Complete |
| 6.5 Special predictions (6 types) | §6.5 | `routers/specials.py` + `admin_router` | `pages/SpecialsPage.tsx` | ✅ Complete |
| 6.5 Admin award specials | §6.5 | `specials.py:303` (`POST /api/v1/admin/specials/award`) | `SpecialsPage.tsx` (AdminAwardPanel) | ✅ Complete |
| 6.6 Live leaderboard (Realtime) | §6.6 | `routers/leaderboard.py` | `pages/LeaderboardPage.tsx` | ✅ Complete |
| 6.6 Leaderboard history chart | §6.6 | `leaderboard.py:182` | `pages/LeaderboardHistoryPage.tsx` | ✅ Complete |
| 6.6 Round leaderboard | §6.6 | `leaderboard.py:222` | `pages/RoundLeaderboardPage.tsx` | ✅ Complete |
| 6.7 Head-to-head comparison | §6.7 | `routers/compare.py` | `pages/ComparePage.tsx` | ✅ Complete |
| 6.8 Player stats | §6.8 | `routers/stats.py` | `pages/PlayerProfilePage.tsx` | ✅ Complete |
| 6.9 Match schedule | §6.9 | `routers/matches.py` | `pages/SchedulePage.tsx` | ✅ Complete |
| 6.10 Admin result entry (manual fallback) | §6.10 | `admin.py:787` (`POST /admin/results/{id}`) | **No form in ResultsPage** — read-only list only | ❌ Missing UI |
| 6.10 Admin result override | §6.10 | `admin.py:862` (`PUT /admin/results/{id}`) | **No override button in ResultsPage** | ❌ Missing UI |
| 6.10 Auto-fetch status banner + Sync Now | §6.10 | `admin.py:1055,1111` | `pages/admin/SyncPage.tsx` | ✅ Complete |
| 6.11 Invite system (per-league) | §6.11 | `league_memberships.py:349` (`POST /leagues/{slug}/invites`) | `pages/LeagueAdminInvitesPage.tsx` | ✅ Complete |
| 6.11 Admin global invite create | §6.11 | **`POST /api/v1/admin/invites` does not exist** in backend | `admin/InvitesPage.tsx` POSTs to non-existent endpoint | ❌ Broken |
| 6.12 Push notifications (all 10 types) | §6.12 | `services/notification_triggers.py` | `pages/SettingsPage.tsx` | ✅ Complete |
| 6.12 Notification preferences + quiet hours | §6.12 | `routers/notifications.py:183,213` | `SettingsPage.tsx` | ✅ Complete |
| 6.13 Match state machine (postpone/cancel) | §6.13 | `admin.py:677,719` | **No admin UI** — API only | ⚠️ API-only |
| 6.13 Reschedule handling + scheduler re-registration | §6.13 | `admin.py:615`, `scheduler.py` | **No admin UI** — API only | ⚠️ API-only |
| 6.14 Prediction audit trail | §6.14 | `predictions.py:114` enforces server-side lock; `submitted_at`, `update_count` columns | — | ✅ Complete |
| 6.15 Manual backup API + runbook | §6.15 | `admin.py:1275` (`POST /admin/backup`) | Dashboard link | ✅ Complete |
| 6.15 Pre-tournament automated backup | §6.15 | `scheduler.py:224` (daily at 03:00 UTC) | — | ✅ Complete |

### §16 Phase Acceptance Criteria — Summary

All 61 phases have shipped (as confirmed by `docs/phase-batches.md` — all rows struck through). Multi-league phases M1–M10 also shipped. The following specific acceptance criterion deviations were identified:

| Phase | Criterion gap |
|---|---|
| 2.1 / 6.11 | `POST /api/v1/admin/invites` endpoint never implemented in backend; frontend `admin/InvitesPage.tsx` calls it → 404/405 at runtime |
| 5.1 | Phase marks manual result entry as complete; however the admin UI (`/admin/results`) is read-only — no form was built in that page |
| 5.6 / 6.10 | Admin dashboard shows upcoming locks, pending overrides widget — but the "pending overrides" list has no clickable action to enter/override a result |
| 6.2 spec | `POST /admin/matches/{id}/lock` never implemented |
| 7.1 | `POST /admin/knockout/advance` exists but no frontend page to trigger it |

---

## 2. Multi-League Feature Coverage

| Feature | Status | Evidence |
|---|---|---|
| Signup with email + name + PIN | ✅ | `auth.py:187`, `pages/SignupPage.tsx` |
| Login by email | ✅ | `auth.py:387` |
| Email verification flow | ✅ | `auth.py:268,292`, `pages/VerifyEmailPage.tsx` |
| Self-service PIN reset (email token) | ✅ | `auth.py:310,354`, `pages/ForgotPinPage.tsx`, `pages/PinResetPage.tsx` |
| League create / update / delete | ✅ | `leagues.py:304,610,693` |
| League join (by invite / by code / open) | ✅ | `auth.py:531,645`, `leagues.py:724` |
| Leave league | ✅ | `leagues.py:796` (last-admin guard present) |
| League discovery (public_request, public_open) | ✅ | `leagues.py:418` |
| Per-league admin: promote / demote | ✅ | `league_memberships.py:189,232` |
| Per-league admin: remove member | ✅ | `league_memberships.py` |
| Per-league admin: PIN reset | ✅ | `league_memberships.py` |
| Per-league leaderboard / history / round | ✅ | `leaderboard.py` league_router |
| Per-league stats / compare | ✅ | `stats.py` league_router, `compare.py` league_router |
| Cross-league dashboard summary | ✅ | `me.py:48` cross-league-summary, `DashboardPage.tsx` |
| Timezone set at join/signup | ✅ | `JoinPage.tsx:84`, `SignupPage.tsx:46` |
| **Timezone change after account creation** | ❌ | No `PATCH /me/timezone` or `PATCH /me/profile` endpoint; `SettingsPage.tsx` has no timezone selector |
| Email change (self-service) | ❌ (out of scope per multi-league §9) | Explicitly deferred to v1.1 |

---

## 3. Prioritised Gap List

### P0 — Blocks Go-Live

#### GAP-01: `POST /api/v1/admin/invites` endpoint does not exist
**Severity:** P0  
**Evidence:** `apps/api/src/routers/admin.py` has only `GET /invites` and `DELETE /invites/{id}`. The invite creation endpoint is `POST /api/v1/leagues/{slug}/invites` (in `league_memberships.py:349`), not `POST /admin/invites`. The frontend `apps/web/src/pages/admin/InvitesPage.tsx:87` POSTs to `/api/v1/admin/invites` → **will receive a 405 Method Not Allowed or 404 in production**.  
**Impact:** Superadmin cannot generate invite links for the legacy "The Steele Spreadsheet" league. The admin invite flow is broken.  
**Fix:** Either add `POST /api/v1/admin/invites` to `routers/admin.py` (scoped to the Steele league by superadmin), or update `admin/InvitesPage.tsx` to call `POST /api/v1/leagues/steele-spreadsheet/invites` (requires the slug to be known). Former is safer; the latter requires frontend to know the Steele slug.

---

#### GAP-02: No admin UI for manual result entry or result override
**Severity:** P0  
**Evidence:** `apps/web/src/pages/admin/ResultsPage.tsx` is a **read-only list** (lines 76–124). It shows results with Auto/Manual/Override source badges but has no form to enter a result or override one. Backend endpoints `POST /admin/results/{match_id}` (`admin.py:787`) and `PUT /admin/results/{match_id}` (`admin.py:857`) exist and work, but are unreachable via the UI.  
**Impact:** If auto-fetch fails or returns a wrong result, admin has no in-app mechanism to correct it. The spec (§6.10) describes this as the "Manual entry fallback" and "Override flow" — primary admin operational tool during the tournament. Runbook `docs/runbooks/kickoff-change.md` and `auto-sync-broken.md` instruct admin to use the UI, which doesn't exist.  
**Fix:** Add a "Enter/Override Result" form or modal to `ResultsPage.tsx`. Minimum: score inputs + extra-time/penalties flags + a submit button wired to the appropriate POST/PUT endpoint.

---

#### GAP-03: No admin UI for knockout bracket advancement
**Severity:** P0  
**Evidence:** `POST /api/v1/admin/knockout/advance` is implemented in `admin.py:1204` and calls `services/knockout_advancement.py:advance_to_r32`. The admin dashboard (`admin/DashboardPage.tsx:320–338`) links to: Sync, Results, Players, Invites, All Leagues — **no bracket/knockout advance link**. No frontend page for this action exists anywhere.  
**Impact:** After the group stage completes (11 June + 12 days), admin must advance to R32 via direct API call (`curl` or API docs). This is the most time-critical tournament operation. The About page (`AboutPage.tsx:517`) tells players that "the admin reviews standings and triggers the advance to Round of 32" — implying a UI flow exists, but it doesn't.  
**Fix:** Add an admin page (or section on admin dashboard) with a "Advance to Round of 32" button, calling `POST /api/v1/admin/knockout/advance`.

---

### P1 — Fix Before Production

#### GAP-04: No admin UI for match postponement, cancellation, or rescheduling
**Severity:** P1  
**Evidence:** `admin.py` has `postpone_match` (line 682), `cancel_match` (line 724), and `reschedule_match` (line 615). The frontend has **no admin UI** for any of these. There is no admin match management page. The match status states `postponed` and `cancelled` are well-handled in the player-facing UI (prediction cards, schedule), but triggering these transitions requires direct API access.  
**Impact:** If a match is delayed or cancelled during the tournament (common at major tournaments), admin must use `curl` with a JWT. Runbook `docs/runbooks/cancelled-match.md` documents the API calls but no UI shortcut.  
**Fix:** Add an admin match management section listing upcoming matches with "Postpone", "Cancel", and "Reschedule" action buttons.

---

#### GAP-05: No admin UI for group standings override
**Severity:** P1  
**Evidence:** `admin.py:365` (`POST /admin/groups/{name}/override-standings`) exists. The admin dashboard has no link to a group management page. No frontend page or component calls this endpoint (confirmed: `grep -rn "admin/groups" apps/web/src/` returns zero hits).  
**Impact:** If the group stage produces a tie that the automated FIFA tiebreaker rules can't resolve (drawing of lots — §6.3 step 7), admin must manually pin team positions via API. This is a known operational requirement during the group stage (3-way ties are not uncommon).  
**Fix:** Add a group standings admin page or inline override control to the group standings view (visible to superadmin only).

---

#### GAP-06: Timezone not changeable after account creation
**Severity:** P1  
**Evidence:** Timezone is captured at join (`JoinPage.tsx:84`) and signup (`SignupPage.tsx:46`). There is no `PATCH /me/timezone` (or `PATCH /me/profile`) endpoint in any router, and `SettingsPage.tsx` has no timezone section. Players whose device timezone differs from what they entered at signup, or who travel during the 6-week tournament, see all kickoff times in the wrong timezone with no in-app way to correct it.  
**Fix:** Add `PATCH /api/v1/auth/me` endpoint accepting `{ timezone: string }`, and add a timezone selector to `SettingsPage.tsx`.

---

#### GAP-07: `POST /admin/matches/{id}/lock` spec endpoint missing
**Severity:** P1 (degrades P0 if a match is moved up on same day)  
**Evidence:** §6.2 specifies "Admin can manually lock a match early (e.g. if a game is moved up) via `POST /admin/matches/{id}/lock`". This endpoint is not in `routers/admin.py` (confirmed: no `lock` function, no lock route). The only lock mechanism is the APScheduler time-triggered job.  
**Impact:** If a match kicks off early (common for fixture swaps), predictions remain open past the real kickoff until the scheduler fires on the original time — players can peek at early scores.  
**Fix:** Add `POST /api/v1/admin/matches/{id}/lock` to `routers/admin.py`; it should transition `status → locked`, set `locked_at`, fire the push notification, and cancel the scheduler job.

---

#### GAP-08: Left-league players remain on leaderboard
**Severity:** P1 (fixed in the soak round for most read paths, but worth re-verifying)  
**Evidence:** `docs/soak-review/code-audit-2026-05-30.md:M2` reported this; `routers/leaderboard.py:145,192,254` now joins to `LeagueMembership.deleted_at.is_(None)`. **Status: Fixed.** Flagged here for QA to verify the fix is complete across all three leaderboard endpoints (main, history, round).

---

### P2 — Polish / Nice-to-Have

#### GAP-09: `window.confirm()` still used in one place
**Severity:** P2  
**Evidence:** `apps/web/src/pages/LeagueAdminInvitesPage.tsx:53` — `window.confirm('Generate a new join code? The old link will stop working immediately.')`. All other destructive confirm dialogs were migrated to styled dialogs in a prior polish batch, but this one remains.  
**Fix:** Replace with a shadcn/ui `AlertDialog` consistent with the rest of the app.

---

#### GAP-10: Admin `compare.router` dead object still in `compare.py`
**Severity:** P2  
**Evidence:** `docs/soak-review/code-audit-2026-05-30.md:L2` reported this. Confirmed: `routers/compare.py` defines only `league_router`; there is no `@router.*` endpoint, and the dead `router` object was removed from main.py. **Status: Already fixed.** No action needed.

---

#### GAP-11: Site-admin authority split across two fields
**Severity:** P2  
**Evidence:** `docs/soak-review/code-audit-2026-05-30.md:M1`. `profiles.role == admin` (legacy) and `profiles.site_role == superadmin` (new) coexist. The boundary holds today (`bootstrap_admin.py` sets both), but a future migration that sets one but not the other could create a half-admin.  
**Fix:** Route both `require_admin` and `_is_superadmin` through `site_role` only, or add a startup invariant asserting the two never disagree.

---

#### GAP-12: Cross-league player data visible to non-shared-league members for specials
**Severity:** P2  
**Evidence:** `GET /api/v1/specials/all` (`specials.py:261`) returns all players' specials with no league-membership check. In a multi-league world, a player in League A can see specials of players in League B who share no league with them.  
**Impact:** Low competitive impact (specials are locked pre-tournament), but privacy-inconsistent with the per-league data model.  
**Fix:** Filter `specials/all` to players who share at least one active league with the requester (use `shared_league_player_ids` from `deps.py`).

---

#### GAP-13: `leaderboard_snapshots` grows unbounded with no retention policy
**Severity:** P2  
**Evidence:** `docs/soak-review/code-audit-2026-05-30.md:L1`. Append-only table with no pruning job. At 104 matches × N leagues × 15 players/league this is manageable for the tournament duration but will compound over multiple tournaments.  
**Fix:** Add a retention job (keep latest N rows per `player_id` + `league_id`, or prune snapshots with soft-deleted memberships).

---

#### GAP-14: No pre-tournament automated backup timestamp (spec says "night before opening match")
**Severity:** P2  
**Evidence:** §6.15 specifies "A backup is taken automatically the night before the opening match." The scheduler (`scheduler.py:224`) runs a **daily backup at 03:00 UTC** which satisfies this in practice, but there is no explicit pre-tournament one-shot job keyed to the opening match date.  
**Impact:** Negligible — daily backup at 03:00 UTC on 10 June 2026 covers this. Minor spec deviation.  
**Fix:** None urgent. Could add a DateTrigger backup job keyed to opening match kickoff minus 12h for clarity.

---

#### GAP-15: No email change flow for existing accounts
**Severity:** P2 (explicitly out of scope per multi-league §9, but notable for post-launch)  
**Evidence:** `docs/multi-league-architecture.md:§9` explicitly defers email change to v1.1. Players who entered a typo at signup have no self-service fix; a superadmin SQL update is the only path.  
**Fix:** Deferred to v1.1 per design decision.

---

## 4. Items Verified Correct (Not Gaps)

The following were checked and found correctly implemented:

- **Server-side prediction deadline**: `predictions.py:114` checks both `status != scheduled` AND `kickoff_utc <= now()` — predictions cannot be saved after kickoff even if the scheduler job hasn't fired.
- **RLS lockdown (C1 from soak)**: Migration 015 enables RLS and revokes write grants on all 13 PostgREST-exposed tables. Fixed.
- **Cross-league data leak (H1 from soak)**: `predictions.py:203,237` and `players.py:82,131,274` all use `shared_league_player_ids` guard. Fixed.
- **Left-league leaderboard appearance (M2)**: All three leaderboard read paths rejoin `LeagueMembership.deleted_at.is_(None)`. Fixed.
- **Private league metadata leak (M3)**: `leagues.py:562` returns 404 to non-members for private leagues. Fixed.
- **Environment enum (M4)**: `config.py:9` uses `StrEnum` — invalid values fail fast. Fixed.
- **PinInput max-length bug**: `PinInput.tsx:12` now accepts `maxLength` parameter (defaults to 4 for normal login, extensible). Fixed.
- **window.confirm removal**: Removed from InvitesPage and PlayersPage; only `LeagueAdminInvitesPage.tsx:53` remains.
- **Special predictions (all 6 types)**: Tournament winner, Golden Boot, Top Scoring Team, Player of the Tournament, Young Player, Golden Glove — all implemented end-to-end including award UI.
- **Knockout draw scoring**: Phase 12.1 removed the draw-void branch; exact knockout draw now scores 10 points.
- **Per-match knockout prediction lock (U22.1)**: `knockout_predictions.py:117` locks per-match kickoff, not per-round.
- **Push notifications (all 10 types)**: All 10 trigger types wired in `notification_triggers.py` and dispatched by scheduler + result sync + admin actions.
- **Pre-tournament specials lock**: `specials.py:117–121` uses `specials_revealed()` from `reveal_gate.py` — locked at opening match kickoff.
- **Leaderboard tiebreaker cascade**: `leaderboard.py:63–321` implements 5-axis merit cascade (points, exact, correct result, correct goals, ko-winner correct). `migration 026` adds `leaderboard_tiebreak_overrides` for manual settlement.
- **Leave-league last-admin guard**: `leagues.py:816` — "LAST_ADMIN: promote another member to admin before leaving".
- **League admin promotion/handover**: `league_memberships.py:189` (promote), `league_memberships.py:232` (demote). No dedicated handover UI but promotion effectively achieves it.
- **E2E Playwright suite**: `apps/web/e2e/` has auth, join, predictions, leaderboard, compare, admin, multi-league tests. Phase 11.7 complete.
- **Offline support**: Service worker, `useOfflineQueue.ts`, offline fallback page. Phase 11.2 complete.
- **Backup and restore**: API endpoints exist, `docs/runbooks/restore.md` present, daily backup scheduled.

---

## 5. Summary Counts

| Severity | Count | Findings |
|---|---|---|
| P0 | 3 | GAP-01, GAP-02, GAP-03 |
| P1 | 4 | GAP-04, GAP-05, GAP-06, GAP-07 |
| P2 | 5 | GAP-09, GAP-11, GAP-12, GAP-13, GAP-14 |
| Already fixed | 2 | GAP-08 (verify), GAP-10 (confirmed fixed) |

---

## 6. Recommended Pre-Launch Sprint

Order of priority:

1. **GAP-01** — Fix the broken admin invite creation (the invite flow is the entry point for all players).
2. **GAP-02** — Add result entry/override form to admin ResultsPage (critical during the tournament).
3. **GAP-03** — Add admin UI for knockout advancement (needed ~12 days after tournament starts).
4. **GAP-07** — Add manual match lock endpoint (pre-kickoff safety net).
5. **GAP-04** — Add admin match management UI (postpone/cancel/reschedule).
6. **GAP-05** — Add group standings override UI (needed if 3-way tie at group stage end).
7. **GAP-06** — Add timezone change to SettingsPage (player quality-of-life, tournament spans 6 weeks).

Items GAP-09 through GAP-15 are post-launch polish or explicitly deferred.
