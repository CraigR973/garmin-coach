# Code Re-Audit — Soak Prep (2026-05-30)

**Lens:** Senior software engineer, security-first.
**Trigger:** Multi-league (M-batches) is about to reach many more people than the original ~15-friend single pool. This is a fresh full re-audit, not a delta.
**Focus #1:** multi-league tenant isolation — the classic single-tenant → multi-tenant failure mode.
**Method:** static read of every data-returning router, the auth dependencies, the scoring fan-out service, and the prod guards. No DB needed for this pass.

Severity key: **C** blocks soak · **H** fix before wider rollout · **M** fix in a polish batch · **L** nice-to-have / informational.

---

## Architecture confirmed (so findings are read in the right frame)

- **Predictions are GLOBAL, not league-scoped.** `predictions`, `knockout_predictions`, `special_predictions` have **no** `league_id`. A player makes one prediction per match; it is scored once. (`league_id` at `models/prediction.py:109` belongs to `LeaderboardSnapshot`, not `Prediction`.)
- **Leaderboards are PER-LEAGUE.** Scoring computes a player's global totals, then fans out one `leaderboard_snapshots` row **per active league membership**, ranked within each league (`PARTITION BY lm.league_id`). Two leagues that share a player show the same point total for them but different ranks — intended multi-league semantics.
- **Three distinct "admin" notions now coexist:** `profiles.role == admin` (legacy global), `profiles.site_role == superadmin` (new site god-mode), and `league_memberships.role == admin` (per-league). See M1.

This frame matters: because predictions are global, the prediction endpoints not being league-scoped is *by design* — but it also means the legacy "show everyone's predictions" endpoints now leak across leagues (H1).

---

## Empirical verification (added 2026-05-30, after the static pass)

The static audit was followed by a live run on an **isolated, throwaway local Postgres 16.2** (pip-bundled `pgserver`, unix socket — physically cannot reach staging/prod). Schema built via `alembic upgrade head` (→ migration 014, all multi-league migrations + scoring trigger).

- **Full backend suite: `585 passed, 0 failed`** against a clean migrated DB (matches CI). This exercises the scoring function, the per-league snapshot fan-out, knockout round points, tie ranking, null-prediction handling, and admin result/override/cancel flows — so the **architecture-confirmed multi-league semantics above are empirically validated**, not just code-read. (Notably `test_group_match_inserts_leaderboard_snapshot_per_active_player` and `test_leaderboard_rank_with_tie` pass.)
  - Gotcha for future runs: the scoring-trigger tests assume an **unseeded** `groups` table. Running `python -m src.seed` first (which commits groups A–L) causes 19 spurious `uq_groups_name` failures — the `db_conn` fixture rolls back per-test but does not clear committed structural rows. Use a separate clean DB for the suite; keep the seeded DB for manual scenarios.
- **C1 confirmed empirically** (see C1 below): Supabase security advisor + `pg_class.relrowsecurity` + `information_schema.role_table_grants` on staging, plus a prod `curl`. Not a theoretical finding.
- **H1 / M2 remain code-confirmed** (read queries don't rejoin membership / don't share-league-scope). The passing suite does not assert against them because they are latent product gaps, not behaviours the engineers wrote tests for.

---

## Findings

### C1 — Supabase RLS disabled: the public anon key can read AND write 13 tables directly, bypassing the entire FastAPI auth layer
**Severity: CRITICAL — CONFIRMED 2026-05-30 (empirical evidence below). This is the most important finding in this audit.**
**Type: authentication bypass + scoring-integrity breach + full data-tamper/destroy.**

**Discovered & confirmed 2026-05-30** via the Supabase MCP (connected to the **staging** project `lesscrmlfijiokureomm`, the environment Lewis will soak against) plus a direct prod `curl`. Three independent checks agree:

1. **RLS is off (staging, `pg_class.relrowsecurity` + security advisor).** Confirmed **RLS disabled on 13 PostgREST-exposed tables, each with 0 policies**: `matches`, `predictions`, `knockout_predictions`, `special_predictions`, `leaderboard_snapshots`, `leagues`, `league_memberships`, `league_join_requests`, `push_subscriptions`, `notification_preferences`, `notification_log`, `audit_log`, `alembic_version`. (Good news, also confirmed: `profiles` (2 policies), `refresh_tokens` (3), `invites` (1), `groups` (1), `teams` (1) **do** have RLS enabled — so the worst PII/credential tables, names+PIN hashes+refresh tokens, are NOT anon-exposed.)
2. **anon has FULL DML, not just read (staging, `information_schema.role_table_grants`).** On every one of those 13 tables, **both** `anon` and `authenticated` hold `SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER`. So the public key can not only read — it can **overwrite predictions, rewrite leaderboard snapshots, forge memberships, edit match results, or `TRUNCATE` (wipe) any of these tables**.
3. **The door is reachable on prod (direct `curl` with the prod anon key).** `GET https://kznxjyaanotrejcevngy.supabase.co/rest/v1/{predictions,profiles,leagues,league_memberships,leaderboard_snapshots}` each returned **HTTP 200** (not 401) — i.e. the PostgREST data API is live and the anon role's grants are in force around FastAPI. The rows came back **empty only because prod is not seeded yet** (`matches` also returned `[]`; a seeded prod would show ~104 fixtures). **The exposure goes live the instant prod gets real data.**

**Why this is severe.** The frontend ships a Supabase client (`apps/web/src/lib/supabase.ts`) built with the **public** `VITE_SUPABASE_ANON_KEY` (extractable from the JS bundle by anyone). The app uses Supabase only for **realtime** (`.channel(...)` on leaderboard/matches/predictions — no direct table CRUD; all real writes go through FastAPI). **But** that same anon key works against the PostgREST data API (`https://<ref>.supabase.co/rest/v1/<table>`), so an attacker bypasses FastAPI entirely:
- **Read `predictions` directly, including PRE-LOCK.** FastAPI hides predictions until kickoff (`predictions.py:181` returns 403 while scheduled) — the REST API ignores that and exposes the raw table. **Anyone can see everyone's picks before a match → the game is broken.** This is the killer, and on staging there are **8 real predictions + 3 special_predictions behind the open door right now** (live data confirmed: 72 matches, 3 leagues, 4 memberships, 10 profiles).
- **Write/destroy `predictions` / `leaderboard_snapshots` / `league_memberships` / `matches`** → tamper scores, ranks, membership, results — or `TRUNCATE` them.
- **Read `audit_log`, `push_subscriptions`, `notification_log`** → internal activity + push endpoints.

This single issue **subsumes and outranks H1** — cross-league scoping in FastAPI doesn't matter if the whole DB is reachable around it. **Staging is live-exploitable today; prod is one seed-run away.** (I did NOT exercise any write — full DML is proven from the grant table, not by mutating data.)

**Confirm prod RLS state directly before seeding** (MCP here is staging-bound): open the Supabase dashboard advisor for `kznxjyaanotrejcevngy`, or run the same `pg_class.relrowsecurity` query against the prod connection string. The `curl` already proves the data API + anon grants are reachable; the only open question is whether prod's RLS flags match staging (they almost certainly do — same migrations, and migrations never enable RLS).

**Fix (needs care — don't blanket-enable RLS or realtime breaks):**
1. Enable RLS on all 13 tables.
2. The app subscribes to realtime on `matches`, `leaderboard_snapshots`, `predictions`, `knockout_predictions` — those need a policy for the `anon`/`authenticated` role to SELECT *only what's safe to broadcast*. **`predictions`/`knockout_predictions` must NOT be anon-readable pre-lock** — either move realtime to a lock-safe view/column set, broadcast only `matches`+`leaderboard_snapshots`, or drive result-detection from `matches` alone.
3. All other exposed tables: enable RLS with **no policy** (deny-all to anon) — the backend uses the service key and bypasses RLS.
4. Alternatively/additionally, lock down the PostgREST data API at the project level (restrict exposed schemas / revoke anon grants on `public`) since the frontend only needs realtime, not REST.
This is a real design task → its own batch (proposed R11, ahead of everything else).

---

### H1 — Legacy global read endpoints leak data across leagues
**Severity: HIGH (for the wider rollout; downgrade to M if cross-league visibility is deemed acceptable — this is a product call).**
**Type: privacy / tenant isolation. Read-only, post-lock only — NOT a scoring-integrity or write breach.**

Several endpoints return another player's data with **no check that the requester shares a league** with the target:

| Endpoint | File:line | Leaks |
|---|---|---|
| `GET /api/v1/predictions/match/{match_id}` | `routers/predictions.py:173` | Every player's post-lock prediction + display name for a match. **No UUID needed** — dumps all. |
| `GET /api/v1/predictions/player/{player_id}` | `routers/predictions.py:217` | A player's post-lock predictions. |
| `GET /api/v1/players/{player_id}` | `routers/players.py:70` | display_name, role, timezone, created_at. |
| `GET /api/v1/players/{player_id}/predictions/recent` | `routers/players.py:110` | A player's recent settled predictions + points. |
| `GET /api/v1/stats/{player_id}` | `routers/stats.py:112` | A player's aggregate stats. |
| `GET /api/v1/specials/all` | `routers/specials.py:223` | All players' specials (post-lock). |

All require only `CurrentPlayer` (any authenticated user). In the original single-pool app this was correct. With many leagues of strangers, an authenticated member of League A can read display names, timezones, full post-lock prediction history, and stats of players who share **no** league with them.

Mitigants (why not Critical): read-only; only **post-lock** data is returned (no pre-lock prediction leak — that path is correctly gated, see "Positives"); points/predictions are global anyway so no *competitive* advantage is exposed; the per-player ones need the target UUID.

**Recommendation:** scope each to "requester shares ≥1 active league with target." For `match/{match_id}`, filter returned rows to players who share a league with the requester. This needs a product decision — booked as a batch candidate, not a one-line fix.

---

### M1 — Site-admin authority is split across two fields
**Severity: MEDIUM (footgun / clarity; no live breach found).**

`/api/v1/admin/*` gates on `profiles.role == admin` (`auth.py:181`, `require_admin`). The league-admin **superadmin bypass** gates on `profiles.site_role == superadmin` (`routers/leagues.py` `_is_superadmin`). Two separate columns both mean "site-wide god-mode," set in two places (`bootstrap_admin` sets both today).

Boundary currently holds: creating a league grants only `league_memberships.role == admin`, **not** the global flags, so a league admin **cannot** reach `/admin/*`. Verified — no escalation today.

Risk is future drift: a migration or a hand-rolled admin that sets one flag but not the other yields a confusing half-admin (can bypass league checks but not enter results, or vice-versa).

**Recommendation:** pick one source of truth (prefer `site_role`) and route both `require_admin` and `_is_superadmin` through it, or add a startup invariant that the two never disagree.

---

### M2 — Players who leave a league still appear on its leaderboard
**Severity: MEDIUM (correctness + minor cross-league visibility).**

`recompute_leaderboard_snapshot` correctly fans out only to active memberships (`WHERE lm.deleted_at IS NULL`, `services/leaderboard.py:104`). But the read query `_leaderboard_entries` (`routers/leaderboard.py:83`) selects the latest snapshot **per player filtered only by `league_id`** — it never rejoins current membership. A player who left League X stops getting *new* snapshots, but their pre-departure snapshots (with `league_id = X`) remain, so `DISTINCT ON (player_id)` keeps surfacing them at their final score.

Result: leaving a league does not remove you from its leaderboard.

**Recommendation:** join the leaderboard read to current `league_memberships` (`player_id`, `league_id`, `deleted_at IS NULL`) so departed members drop off. Same fix should cover `_leaderboard_history` and the round leaderboard.

---

### M3 — Private-league metadata readable by any authenticated user
**Severity: MEDIUM (enumeration / info-leak).**

`GET /api/v1/leagues/{slug}` returns name/description/member_count to **any** authenticated caller; only the `members` list is membership-gated. A non-member who knows or guesses a slug learns a private league's existence and metadata.

Mitigant: slugs are not trivially enumerable. But they appear in invite links / URLs and could be shared or guessed.

**Recommendation:** for `privacy == private`, return 404 to non-members/non-invitees (treat private leagues as invisible by slug), or restrict the metadata to members + holders of a valid invite.

---

### M4 — `environment` guard is a brittle string match
**Severity: MEDIUM (deploy footgun — could mount destructive endpoints in prod).**

- Dev/test fixture endpoints mount when `settings.environment != "production"` (`main.py:124`). `test_helpers` can lock matches and mutate fixtures.
- The prod weak-secret validator relaxes only when `environment == "development"` (`config.py`).

So a deploy with `environment` set to anything **other than exactly** `"production"` (`"prod"`, `"staging"`, `""`, a typo) mounts `test_helpers` into a prod-like environment **while still enforcing prod secrets** — the two guards disagree on what "prod" means.

**Recommendation:** make `environment` an explicit enum (`development | staging | production`), validate it at startup, and base both guards on the same value. Fail closed (no test_helpers) for anything unrecognized.

---

### L1 — `leaderboard_snapshots` grows unbounded and accumulates stale rows
**Severity: LOW (perf / housekeeping; compounds M2).**

The table is append-only: every scoring event inserts one row per active membership across the whole system. Old rows are never pruned, and departed-member rows are never cleaned (M2). At 104 matches × many leagues this grows fast and keeps stale snapshots queryable.

**Recommendation:** retention job (keep latest N per `player_id` + `league_id`, or prune snapshots whose membership is now deleted).

### L2 — Dead router object
`compare.router` (`routers/compare.py:24`) is defined but never mounted — only `compare.league_router` is (`main.py:121`), and the file has no `@router.*` endpoints. Remove the unused object to avoid implying a global compare surface exists.

### L3 — `RANK()` vs `DENSE_RANK()`
Leaderboard ranking uses `RANK()` (`services/leaderboard.py:67`), so ties leave gaps (1, 1, 3). Confirm this is the intended display before soak — trivial to switch if not.

---

## Positives (deliberately called out — this is a balanced report)

- **No SQL injection surface** — all raw SQL is parameterized; no f-string/`%`-built queries anywhere in `src/`.
- **Prediction scores bounded** `0–20` (`predictions.py:35-36`) — no absurd inputs.
- **Leaderboard read + write are correctly league-scoped** (`league_id` filter on every snapshot query) and **membership is enforced** via `LeagueMemberDep` on all three leaderboard endpoints.
- **Site-level admin actions are gated** — results, standings override, specials award, player management all require `AdminPlayer`; **league creators get only league-scoped admin** and cannot reach `/admin/*`. The most dangerous boundary holds.
- **Predictions are hidden pre-lock** — `GET /predictions/match/{id}` returns 403 while `match.status == scheduled` (`predictions.py:181`); per-player views filter to `status != scheduled`. No pre-kickoff prediction leak.
- **`test_helpers` is excluded from production** (subject to M4's string-match caveat).
- **Scoring fan-out is sound** — per-league partitioned ranking, active-membership filter, `session.flush()` before reading sums so in-memory mutations are seen.

---

## Coverage — what this pass did and did NOT cover

**Audited this pass (rigorously):** all data-returning routers (`leagues`, `league_memberships`, `league_join_requests`, `leaderboard`, `players`, `stats`, `compare`, `predictions`, `knockout_predictions`, `specials`, `admin`), the auth admin dependency, the leaderboard scoring service, and the prod/test guards.

**Deferred to later passes (flagged so nothing is silently assumed-good):**
- Frontend (React) code-level review — folded into Stage 1B UX/UI audit.
- JWT lifecycle / refresh rotation / rate-limit tuning — spot-checked (bounds + parameterization OK), not re-audited line-by-line (R-batches previously hardened these).
- `football_data` sync service, `knockout_advancement` service — not re-read this pass.
- Alembic migration correctness — not re-read this pass.
- League **invite token** generation/entropy — handled in the invite flow (not `leagues.py`); spot-check pending.

---

## Suggested batch mapping (for triage)

- **R11 (do first, before soak — BLOCKER):** C1 (Supabase RLS / anon-key data-API bypass) — CONFIRMED on staging (live data behind an open door) and reachable on prod. Enable RLS + lock down the data API. Staging is exploitable *now*, so this gates handing staging to Lewis, not just prod launch.
- **R12 (backend isolation):** H1 (cross-league read scoping), M2 (leaderboard departed-member filter), M3 (private-league metadata).
- **R13 (hardening/clarity + cleanup):** M1 (unify admin authority), M4 (environment enum + fail-closed), L1 (snapshot retention), L2 (dead router), L3 (confirm RANK semantics).

These extend the existing R-series so `/phase-closeout`, `/next-batch-prompt`, `/strike-batch` tooling keeps working.
