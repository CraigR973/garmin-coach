# S3 — Staging→prod parity (E) + service limits/expiry (F)

Probed live on 2026-06-08 with the project's own keys/endpoints (read-only). Items
needing billing dashboards are listed under "Open — needs your access".

---

## E — Staging→prod parity

### Verified healthy
- **Prod is serving current `main`.** `GET /health` `sha` = `da12869…` == local `main` HEAD exactly (ship-prod R8.1 SHA gate passes).
- **Prod migrations at head.** `GET /health/ready` → `{"status":"ready","db":"ok"}`, i.e. the backend booted *after* `alembic upgrade head` succeeded on the prod DB.
- **Prod frontend up.** `https://wc2026-prod.vercel.app` → HTTP 200.
- **⚠️ backend silent-break env vars are validly set.** The prod boot validator (`config.py`) rejects placeholder/empty `JWT_*`, `SUPABASE_SERVICE_KEY`, `FOOTBALL_DATA_API_KEY`, `VAPID_PRIVATE_KEY` and a localhost `FRONTEND_ORIGIN` when `ENVIRONMENT=production`. Prod booting healthy ⇒ all of these (per `docs/runbooks/env-manifest.md`) are correctly configured.

### Gaps / to verify
- **[P1] Prod DB identity + seed unconfirmed from here.** The Supabase MCP is connected to project `lesscrmlfijiokureomm`, but memory records the prod ref as `kznxjyaanotrejcevngy`. The *connected* DB is fully seeded (104 scheduled matches, 48 teams, 12 groups, 18 profiles) and shares the same migrations — but I could not confirm **prod's** data from outside. Action: confirm which Supabase project backs prod, and that prod has the full **104-match seed including the 32 seeded knockout rows** (knockout advancement maps resolved teams onto these seeded rows — if prod predates that seed, advancement breaks).
- **[P2] `/ship-prod` R8.5 synthetic targets an auth-gated route.** `GET /api/v1/matches/upcoming` returns `{"detail":"Not authenticated"}`; the documented post-deploy synthetic curls it unauthenticated and asserts a `data` key, so the gate would misfire. Fix: point the synthetic at a genuinely public route (`/health`) or send a token.

---

## F — Service limits & expiry

| Service | Status | Notes / action |
|---|---|---|
| **football-data.org** | 🚨 **P0** | App calls `GET /v4/competitions/2000/matches` → **HTTP 403** "restricted… check your subscription". The `/competitions` list works (key is valid) but the **WC competition is not in this key's plan**. Daily quota ~50 req (`x-requests-available: 49`, ~24h reset). **Auto result-fetch is dead with this key.** Action: upgrade football-data to a tier covering FIFA World Cup 2026 match data, OR commit to manual entry (needs the GAP-02 admin UI built). |
| **GitHub Actions** | ✅ no risk | Repo is **public** → unlimited free CI minutes. |
| **Railway** (backend) | ⏳ verify | Backend runs 24/7 + APScheduler → continuous spend. Deploy-scoped API token can't introspect plan. **Highest-uncertainty risk** — a credit/trial lapse mid-tournament = full outage. Action: confirm plan tier, monthly credit/usage trend, and any trial expiry covers Jun 11 – Jul 19. |
| **Supabase** | ⏳ verify | Free tier pauses after 7 days inactivity (a live scheduler should keep prod active, but confirm), 500 MB DB / egress caps. Connected project healthy. Action: confirm prod plan + usage headroom. |
| **Vercel** | ⏳ verify | Hobby bandwidth/build caps trivial for ~15 users; confirm plan + commercial-use terms for a private league. |
| **Resend** | ✅ ok | 3,000 emails/mo free — ample for 15 players. |
| **Sentry** | ⏳ verify | Free event quota; confirm not near exhaustion. |
| **Tokens** | ⏳ verify | Couldn't read the `GITHUB_TOKEN` PAT expiry header — confirm it (used by ship CI polling) doesn't expire mid-tournament. Confirm football-data key validity once the plan is sorted. |

---

## Security findings from the live DB (complement code audit B)

The Supabase advisors caught DB-state issues that a code-only audit cannot see:

- **[P0] RLS disabled on `public.leaderboard_tiebreak_overrides`** (advisor level **ERROR**). The migration-015 lockdown (enable-RLS-no-policy = deny-all to the public anon key via PostgREST) **missed this one table**. With the public anon key, tiebreak overrides may be readable/writable directly through PostgREST, bypassing the backend — i.e. **standings tampering**. Fix: migration to `ENABLE ROW LEVEL SECURITY` + deny-all policy; applies to staging **and** prod. ([linter 0013](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public))
- **[P1] Scoring/trigger functions have a mutable `search_path`** (advisor WARN): `calculate_match_points`, `matches_score_results`, `matches_set_result_entered_at`, `set_updated_at`. Set an explicit `search_path` to remove the privilege-escalation/predictability vector on the scoring path. ([linter 0011](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable))
- **[P2] Perf-only:** `auth_rls_initplan` on `profiles`/`refresh_tokens` policies (wrap `auth.*` in `(select …)`), ~20 unindexed FKs, several unused indexes. All negligible at 15–18 users / 104 matches — defer.
- **Confirmed intended:** many tables show `rls_enabled_no_policy` (INFO) — that is the deliberate deny-all lockdown (backend uses the service key which bypasses RLS), not a problem.

---

## Open — needs your dashboard access
1. **Railway** — plan tier, credit/usage, trial expiry (existential — backend uptime through Jul 19).
2. **Supabase** — confirm which project is prod (`kznxjyaanotrejcevngy` vs connected `lesscrmlfijiokureomm`), plan, usage; verify prod 104-match seed.
3. **Vercel** — plan + commercial-use terms.
4. **Sentry** — event-quota headroom.
5. **`GITHUB_TOKEN` PAT** — expiry date.
