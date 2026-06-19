# Final pre-production review — plan & findings index

Final review before promoting the World Cup 2026 Prediction League to production.
Kickoff is **2026-06-11**. Decision (2026-06-08): **full premium review, ship when
ready** — in-tournament deploys are acceptable outside the ±30-min kickoff freeze.

## Locked decisions
- **Scope:** complete review across all six workstreams before any prod push.
- **Execution:** code-analysis tracks (A/B/C) run as parallel read-only subagents,
  consolidated here. UX (D) and Infra (E/F) are separate focused sessions.
- **Deep pass:** user triggers `/code-review ultra` (multi-agent cloud review of the
  branch) alongside S1. No dedicated `/security-review` pass — security depth comes
  from the manual audit (B) + ultra.

## Workstreams & sessions
| # | Workstream | Session | Findings file | Status |
|---|---|---|---|---|
| A | Completeness / missing features | S1 | `docs/final-review/completeness.md` | ✅ done — 3 P0, 4 P1, 5 P2 |
| B | Security audit | S1 | `docs/final-review/security.md` | ✅ done — 1 P0, 4 P1, 6 P2 |
| C | Code quality | S1 | `docs/final-review/code-quality.md` | ✅ done — 1 P0, 3 P1, 3 P2 |
| D | UX / UI / a11y / premium polish | S2 | `docs/final-review/ux.md` | ✅ done — premium & accessible; 2 P2 nits; live-confirmed P0s |
| E | Staging→prod parity | S3 | `docs/final-review/infra.md` | ✅ done — prod healthy; 1 gap to verify |
| F | Service limits / expiry | S3 | `docs/final-review/infra.md` | ✅ probed — 1 P0; Railway/Supabase/Vercel need your dashboards |

External: `/code-review ultra` — ✅ received 2026-06-08; folded into backlog (2 regressions + red suite + a11y nit).

## ⏸ Status (2026-06-08): PAUSED before remediation
All six review tracks complete. Remediation is held until the inputs below land, so the fix scope is final before any code changes.

**Inputs — all received/verified 2026-06-08:**
1. ✅ **`/code-review ultra`** — folded in (2 regressions + red-suite + CI-gap + a11y nit).
2. ✅ **football-data prod key** — reads the full 104-match WC schedule (HTTP 200). Auto-fetch will work; no longer a blocker.
3. 🚨 **Railway** — on **Trial**, ~$2.95 / ~9 days left → cannot cover the 38-day tournament. **NOW P0** — upgrade to a paid plan ASAP (your action).
4. ✅ **Supabase** — prod confirmed (`kznxjyaanotrejcevngy`), Free tier, seeded. Minor flags only (pause-if-backend-down, no Free backups, 2-project limit).
5. ✅ **Vercel** Pro · **Sentry** enabled (confirm monthly quota) · **`GITHUB_TOKEN`** no expiry.

**Ready for remediation.** Batches: **R0** (your action) upgrade Railway off Trial · **R1** security P0s (IDOR, tiebreak RLS, dep bumps, fn search_path) · **R2** tournament-ops (auto-advance fix, 5xx retry, admin result-entry + knockout-advance UI, invite-create) · **R3** P1 (the 2 ultra regressions, **add the missing vitest CI job**, rate-limit/CSP/scheduler-state, GAP-04/05/06/07, realign 9 red tests) · **P2** polish.

## Sequence
1. **S1/S2/S3 analysis** (parallel, read-only) → each writes its findings file.
2. **Consolidate** all findings into the triaged backlog below (P0→P1→P2).
3. **Remediation** (sequential, `fix/` branch) → `/ship-staging` → soak → re-verify.
4. **Prod cutover** via `/ship-prod` gates — ship when ready.

## Severity rubric
- **P0** — blocks go-live: correctness bug affecting scoring/results, security hole,
  data-loss risk, or a service that will fail during the tournament.
- **P1** — should fix before prod: meaningful UX/quality/parity gap, missing
  acceptance criterion, degraded-but-not-broken behaviour.
- **P2** — polish / nice-to-have: cosmetic, minor refactor, post-launch follow-up.

## Triaged backlog
_(populated as findings land)_

### P0
- [ ] **[F] 🚨 Railway is on a TRIAL that runs out mid-tournament** *(verified 2026-06-08 — most urgent item)*. ~**$2.95 / ~9 days** of credit left; the tournament runs **38 days** (Jun 11 → Jul 19). The 24/7 backend + scheduler will stop ~**Jun 17–20**, taking the entire app down. **Hard fuse — add a payment method and move to a paid plan (Hobby/Pro) now, well before the credit lapses.**
- [x] **[B] Cross-league IDOR — knockout-prediction view.** `GET /api/v1/knockout-predictions/match/{match_id}` (`apps/api/.../knockout_predictions.py:171-207`) omits the `shared_league_player_ids` filter its group-prediction sibling uses → any authed user can read knockout picks + player names of unrelated private leagues once a match locks. Fix: copy the `shared` filter from the group endpoint; add regression test alongside `test_r12_tenant_isolation.py` (~3 lines).
- [x] **[C] Auto result-fetch never advances the next knockout round.** `sync_results` / `_apply_finished` (`result_sync.py`) never call `sync_knockout_bracket` — only the manual admin paths do. On the tournament's primary auto-fetch path, R16+ fixtures stay on TBD placeholders and can't be scored. Fix: call `sync_knockout_bracket` after applying finished results in the auto path; add a scheduler-level test.
- [x] **[A] GAP-01: Admin invite-create is broken** *(verified)*. `admin/InvitesPage.tsx:87` POSTs to `/api/v1/admin/invites`, but `admin.py` defines only GET (314) + DELETE (324) — no POST. The working create route is `POST /leagues/{slug}/invites` (`league_memberships.py:350`). Fix: rewire the page to the per-league endpoint, or remove it if the per-league invite UI is the live onboarding path (confirm in S2).
- [x] **[A] GAP-02: No admin UI for manual result entry / override** *(UI gap verified)*. `ResultsPage.tsx` is display-only; backend override endpoints exist (`admin.py:787,857`). This is the manual fallback when auto-fetch fails — and auto-fetch has its own P0 above. Fix: add a result entry/override form.
- [x] **[A] GAP-03: No admin UI to advance the knockout bracket** *(verified)*. `POST /knockout/advance` exists (`admin.py:1200`) but no frontend trigger anywhere; `AboutPage.tsx:517` even tells users the admin will trigger it. Today it requires a manual `curl` after the group stage. Fix: add an admin advance control.
- [x] **[F] football-data WC access — RESOLVED 2026-06-08.** The **prod** key (Railway) returns **HTTP 200** for `GET /v4/competitions/2000/matches` with the full **104-match** WC schedule (103 TIMED + 1 SCHEDULED). Auto result-fetch will work in prod. (The local `.env` key was a different, restricted key — 403; harmless.) ⬇ No longer a blocker. NB: the C-P0 auto-**advance** bug + GAP-02/03 manual-fallback gaps still stand.
- [x] **[E/Sec] RLS disabled on `leaderboard_tiebreak_overrides`** *(Supabase advisor ERROR)*. Migration-015 lockdown missed this table → the public anon key may read/write tiebreak overrides via PostgREST, bypassing the backend (standings tampering). Fix: migration enabling RLS + deny-all policy (migration 027); apply to staging **and** prod.

### P1
- [x] **[B] Login rate-limit key is broken.** `login_key` (`rate_limit.py:43-55`) keys on `display_name`, which `LoginRequest` never sends (email+pin only) → the per-credential brute-force bucket never engages on a 4-digit PIN (10k space); only the DB lockout protects. Fix: key on email (+ IP).
- [x] **[B] Rate limiter is in-memory.** `Limiter(...)` has no `storage_uri` (`rate_limit.py:16`) → counters aren't shared across instances and reset on every Railway deploy. Fix: back with a persistent store (Redis) or document the single-instance assumption.
- [x] **[B] No CSP + refresh token in localStorage.** 30-day refresh token lives in `localStorage` (`tokens.ts`); `SecurityHeadersMiddleware` (`middleware.py:24-32`) sets HSTS/XFO/nosniff but no Content-Security-Policy → one XSS exfiltrates a long-lived credential. Fix: add a CSP. (No CSRF surface — Bearer header, not cookie.)
- [x] **[B] Dependency CVEs.** PyJWT 2.12.1 + Starlette 1.0.0 on known-vulnerable versions (`pip-audit`); low practical exposure (HS256 + static secrets, no JWKS). Fix: bumped PyJWT ≥2.13.0 (→2.13.0), Starlette ≥1.0.1 (→1.2.1) in requirements.txt + pyproject.toml.
- [x] **[C] football-data 5xx + network errors not retried.** Only HTTP 429 is retried; a single 5xx aborts the sync cycle, and httpx network errors aren't wrapped as `FootballDataError`, so they bypass the consecutive-failure counter and the admin alert. Fix: retry 5xx with backoff; wrap network errors as `FootballDataError`.
- [x] **[C] Scheduler state is process-local.** `_consecutive_failures` and the pick-confirmation dedup set are module globals → lost on restart (alert threshold dodgeable, confirmations re-send) and wrong under >1 worker. Fix: persist this state.
- [ ] **[C] Flaky frontend test suite.** PredictionsPage / DashboardPage / PlayerProfilePage tests fail non-deterministically under load (per-test 5s timeout / concurrency too tight); logic is sound. Fix: raise timeout / lower concurrency — could destabilize CI on the way to prod.
- [x] **[A] GAP-04: No admin UI for match postpone / cancel / reschedule.** Backend state-machine endpoints exist; no frontend surface → live match changes need direct API calls.
- [x] **[A] GAP-05: No admin UI for group-standings override.** `POST /groups/{name}/override-standings` exists (`admin.py:365`, verified) but has no UI.
- [x] **[A] GAP-06: Timezone not changeable after signup.** A wrong timezone at signup is locked in for the 6-week tournament; expose it in account settings.
- [x] **[A] GAP-07: Missing manual early match-lock endpoint.** Spec-required `POST /admin/matches/{id}/lock` was never built → if a kickoff moves earlier, predictions can stay open past the real start.
- [x] **[F] Railway — VERIFIED 2026-06-08:** on **Trial**, ~$2.95 / ~9 days credit left → insufficient for the 38-day tournament. **⬆ ELEVATED TO P0 (see top of P0).**
- [x] **[F] Supabase — VERIFIED 2026-06-08:** prod = `kznxjyaanotrejcevngy`, **Free** tier, prod data present (seed confirmed in the prod app). Acceptable at this scale; residual flags: 7-day idle-pause **if the backend ever stops** (compounds the Railway risk), no managed backups on Free (rely on the app's backup runbook), and the 2-free-project org limit is reached. Consider Pro for headroom + backups.
- [x] **[F] Vercel / Sentry / token — VERIFIED 2026-06-08:** Vercel **Pro** (no bandwidth/commercial concern); `GITHUB_TOKEN` has no expiry; Sentry **enabled** (DSNs set on Railway + Vercel). Only residual: confirm the Sentry monthly event quota isn't near its cap (low risk at this scale).
- [x] **[E] Prod DB seed — VERIFIED 2026-06-08:** data present in the prod app (Schedule + groups render). Recommend a quick `select status, count(*) from matches group by 1` on prod to confirm the 32 knockout rows specifically.
- [ ] **[Sec] Public repo — scan git history for committed secrets.** Code audit checked source/bundle, not full history; repo is public.
- [x] **[Sec] Scoring trigger functions have mutable `search_path`** *(advisor WARN)*: `calculate_match_points`, `matches_score_results`, `matches_set_result_entered_at`, `set_updated_at`. Fixed via migration 028 (`ALTER FUNCTION ... SET search_path = public`).
- [x] **[Ultra] 15-min deadline warning never sent** *(regression)* — `notification_triggers.py:336` dedups via a module-global set keyed by `match.id` only; the new 60-min `check_deadline_warnings` job marks the match ~45 min before the 15-min run, which then hits `continue`. Players get "60 min" but never "15 min". Fix: key the set by `(match.id, warning_minutes)`.
- [x] **[Ultra] FirstRunController redirects every returning user to `/about` on every open** *(regression — feels P0 for daily UX)* — the initial guard reads the **global** `sss_tour_seen`, but the controller only writes the **per-user** key (`markTourSeen(player.id)`) since U49, so the global key is never set → `step='about'` → navigate fires every load. Fix: read the per-user key in the guard.
- [x] **[Ultra] `main` @ `da12869` shipped with a RED suite** — 9 deterministic failures across 6 files (TopBar mock missing `DropdownMenuSeparator` + a 30-vs-46 logo-size contradiction; AboutPage hero copy + non-clickable tasks; DashboardPage `DeltaBadge` removed; MyLeaguesPage "Open league"→"View →"; plus the 2 regression tests). Contradicts the "CI ✅" session-log notes. Fix: realign the 6 stale test files + resolve the logo-size contradiction. (Supersedes the S1-C "flaky" framing for these 9.)
- [x] **[Ultra/E · CI GAP — verified] Frontend unit tests are not run in CI.** `ci.yml` runs ruff / mypy / pytest / alembic + "Build web" (eslint + tsc + vite **build** only) + prod-bundle-check + Playwright e2e/smoke — there is **no `vitest` job**, and the staging-deploy `needs:` list omits one. So `pnpm --dir apps/web test` is never gated → CI concluded **success** on `da12869` (verified via the Actions API) despite the red unit suite. **This is *why* the 2 regressions + 9 red tests reached `main` under "CI ✅".** Fix: add a frontend unit-test job to `ci.yml` and to the deploy `needs:` list.

### P2
- [ ] **[B] 6 hardening items** — see `docs/final-review/security.md`.
- [ ] **[C] Redundant snapshot fan-out** — `total_points` re-sums the three components via extra correlated subqueries; fine at 15 players, just inefficient.
- [ ] **[C] Dead `stage` param** in the scoring path.
- [ ] **[C] No scheduler-level test** for the `sync_results` job.
- [ ] **[A] 5 completeness P2s** — see `docs/final-review/completeness.md`.
- [ ] **[E] Fix `/ship-prod` R8.5 synthetic** — it targets the auth-gated `/matches/upcoming`; point it at `/health` or send a token.
- [ ] **[Perf] DB micro-opts (advisor)** — `auth_rls_initplan` on profiles/refresh_tokens, ~20 unindexed FKs, unused indexes. Negligible at 15–18 users; defer.
- [ ] **[D · a11y] Score-stepper chevrons** — give the up/down controls in `score-input.tsx` explicit labels + value announcement.
- [ ] **[D · UX] Admin Sync Status raw-JSON error** — format the "RECENT ERRORS" reason into a friendly line instead of escaped JSON.
- [ ] **[D] `apps/web/.env.local` points local dev at PRODUCTION** — repoint to staging/localhost to avoid accidental prod writes in dev.
- [ ] **[Ultra · a11y] `LeaderboardPage.tsx:187` `shortenName()`** reduces the link's accessible name (full name → "Alexandria S."), hurting screen-reader users. Keep the full accessible name on the link.

## Confirmed solid
- **[B] Security:** server-side prediction-deadline enforcement; fail-closed `reveal_gate` for pre-lock privacy; consistent league membership/admin authz; no mass-assignment; Supabase RLS lockdown (migration 015 — ⚠️ except `leaderboard_tiebreak_overrides`, see P0); no server secrets in the `dist` bundle; fail-closed secret validation (`config.py`); parameterized SQL; single-use refresh-token rotation + revoke-on-logout/reset; constant-time login with no account enumeration.
- **[C] Quality:** trigger↔Python-twin scoring parity, knockout draw→penalty handling, bracket purity/idempotency, timezone handling, and migration downgrade reversibility all verified healthy.
- **[A] Completeness:** player-facing flows (join / predict / knockouts / specials / leaderboard / history / profile / H2H / notifications / PWA / offline) are present; the gaps cluster in **admin tournament-operations UI**.
- **[D] UX/a11y:** premium feel confirmed live (login/signup/dashboard/predict/admin) across dark+light+mobile+desktop; strong landmarks, labels, and AA contrast. Design-audit C-1/C-3 resolved.

## Analyzer status (S1)
- mypy / ruff check / ruff format / frontend `tsc`: **PASS clean**.
- Backend pytest: **639 passed, 126 skipped** (DB tests skip locally by design); shared scoring **21/21**.
- Frontend vitest: **flaky** (see P1) — passes some runs, 3–4 failures others.
- `pnpm audit` / `pip-audit`: not runnable offline in the subagent → **must run in CI before promotion** (B also flagged PyJWT/Starlette CVEs).
