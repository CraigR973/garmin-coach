# V1 + V2 Review — Code, Security & Functional

**Date:** 2026-06-22 · **Reviewer:** Claude (Opus 4.8), pair-review pass
**Scope:** Full app at `main` HEAD `80d898a` (Phase 1 batches 1–10 + Phase 2 batches 11–18).
**Deliverable:** this report. No code was changed during the review.

> How to read this: findings are prioritised **P1 → P3**. P1 = address before
> relying further; P2 = should fix soon; P3 = informational / nice-to-have. Each
> finding cites `file:line`. A **What's right** section and a **feature coverage
> matrix** follow, then an honest **coverage & methodology** note.

---

## Update — 2026-06-22 (status of these findings)

Actions taken since this review was written:

- **P1-2 (Red-never-VO2 delivery gap) — FIXED.** Closed by [PR #14](https://github.com/CraigR973/garmin-coach/pull/14): `auto_push_due` now re-checks the morning verdict and blocks a VO2 proposal on a Red day, and `regenerate_for_verdict` substitutes a recovery spin on Red. Recorded as Decision #75.
- **P1-1 (lockout), P3-1 (refresh race), P3-2 (change-pin), P3-3 (reset-token logged) — SUPERSEDED.** The agreed move to passwordless device-token auth (Decision #73–74; plan in [auth-simplification-plan.md](auth-simplification-plan.md)) deletes this machinery, so these are not worth fixing in isolation. **Do not** spend effort on them.
- **P2-1 (web CSP/headers) — now load-bearing** for the auth plan; it lands in that plan's Phase 3.
- **Still-open quick wins:** rotate the production PIN off `1234` (interim), bump `react-router-dom` (P2-2), add dependency/secret scanning to CI (P2-3).

## Update — 2026-06-23 (closeout — supersedes the items above)

- **P2-1 / P2-2 / P2-3 — SHIPPED** ([PR #16](https://github.com/CraigR973/garmin-coach/pull/16); Decision #76): `vercel.json` CSP/security-headers (verified live on the prod origin), `react-router-dom` 6.30.4, and a `security-audit` CI gate (`pnpm audit --prod` + `pip-audit`). P2-1 landed early — not in Phase 3 as line 20 anticipated.
- **P3-5 / P3-6 / P3-7 — SHIPPED** ([PR #17](https://github.com/CraigR973/garmin-coach/pull/17); Decision #78): stricter prod secrets validator (≥32 + distinct), DB backup via `PGPASSWORD`, and prod API docs disabled (verified: `/api/docs` → 404 in prod).
- **Auth Phase 1 — SHIPPED** ([PR #18](https://github.com/CraigR973/garmin-coach/pull/18); Decision #77): additive device-token activation alongside PIN. This is the path that **closes** P1-1, P1-3, P3-1/2/3 once Phases 2-3 remove the PIN/JWT/lockout machinery — until then those remain open and the PIN is still `1234`.
- **Still open:** P1-3 (PIN `1234`, live until Phase 3); P1-1, P3-1, P3-2, P3-3 (close with Phase 2-3); P3-4 (scheduler isolation) and P3-9 (hygiene) — optional. P3-8 accepted, no action.

---

## Executive summary

The codebase is in good shape for a private two-user health app: clean
architecture, deterministic safety logic (the Green/Amber/Red verdict and the
insight maths are testable pure functions, **not** delegated to the LLM), no SQL
or command injection, no committed secrets, and a verified-live security-header
posture on the API. Static checks are clean and the test suite is green in CI.

The issues worth acting on cluster in two places:

1. **Auth brute-force posture** — the account-lockout mechanism is present in the
   schema but **never actually wired in**, so a 4-digit PIN on real health data
   is protected only by an in-memory rate limiter that resets on every redeploy.
   Compounded by the production PIN still being the temporary `1234`.
2. **The "Red never VO2" safety guarantee** is enforced in the workout
   *transform* but **not at the delivery gate** — a pre-approved VO2 session can
   still auto-push to Zwift on a Red morning.

Plus two quick web-hardening wins (no CSP/anti-framing headers on the SPA origin;
a moderate `react-router` CVE) and a CI gap (no dependency/secret scanning).

None of these are emergencies, but #1, #2 and the PIN rotation are worth doing
before the app is leaned on day-to-day.

---

## Verification results (Track C)

| Check | Result |
|---|---|
| `ruff check` + `ruff format --check` | ✅ Clean (79 files) |
| `pytest` (local, no Postgres) | ✅ **157 passed, 49 skipped** (DB-backed tests skip without a local DB) |
| `pytest` DB-backed (49) | ✅ Covered by CI run #109 (green) — not re-runnable locally (no Docker/Postgres in this environment) |
| `mypy` | Not re-run locally (fiddly without CI's layout); ✅ gated green in CI #109, no source changed since |
| Live prod smoke (read-only) | ✅ API health 200; **all unauth feature routes 401**; API security headers present; web origin 200; same-origin proxy OK |
| `pnpm audit` | ⚠️ **1 moderate** (`react-router-dom` — see P2-2) |
| `pip-audit` (OSV, installed env) | ✅ Runtime stack clean; only `pip` itself flagged (toolchain, see P3) |

Live smoke detail (against `https://api-production-e2bc7.up.railway.app` and
`https://garmin-coach-one.vercel.app`):

```
API /api/v1/health                       -> 200  sha 80d898ab (== main HEAD ✓)
/api/v1/daily-loop                       -> 401
/api/v1/insights/ftp-drift               -> 401
/api/v1/experiments                      -> 401
/api/v1/workout-delivery/week-ahead      -> 401
/api/v1/admin/coaching-state             -> 401
API security headers                     -> CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy ✓
web /                                     -> 200
web /api/v1/health                       -> 200 (same sha; Vercel→Railway proxy ✓)
web security headers                      -> HSTS only ⚠️ (see P2-1)
```

---

## P1 — Address before relying further

### P1-1 · Account lockout is dead code; brute-force defense is ephemeral
**Where:** `apps/api/src/auth.py:28-29` (`MAX_FAILED_ATTEMPTS`, `LOCKOUT_DURATION` — unreferenced),
`apps/api/src/routers/auth.py:132-177` (login never touches the counters),
`apps/api/src/models/profile.py:38-39` (`failed_login_count` / `locked_until` exist),
`apps/api/src/rate_limit.py:16-19` (comment claims a durable DB lockout that doesn't exist).

`failed_login_count` and `locked_until` are written **only** in `pin_reset`
(`routers/auth.py:352-353`, resetting them) — never incremented on a wrong PIN
and never checked at login. So the *only* brute-force protection is the in-memory
`slowapi` limiter `@limiter.limit("5/15 minutes")` keyed by `display_name`+IP,
which by design **resets on every process restart / Railway redeploy** and is
per-IP. `rate_limit.py` calls the DB lockout "the durable brute-force guard" —
but it isn't implemented.

**Impact:** a 4-digit PIN = 10,000 combinations guarding personal health data,
with only resettable, per-IP throttling. A redeploy (or IP rotation) reopens the
window.

**Fix:** wire up the lockout that the schema already anticipates — increment
`failed_login_count` on a wrong PIN, set `locked_until = now + LOCKOUT_DURATION`
once it hits `MAX_FAILED_ATTEMPTS`, reject login while `locked_until` is in the
future, and reset both on success. Then correct the `rate_limit.py` comment.
(Alternatively, if you intend to rely on the limiter alone, at least make it
persistent and fix the comment — but a DB lockout is the right call here.)

### P1-2 · "Red never VO2" is enforced in the transform but not at delivery
**Where:** `apps/api/src/services/executable_coaching.py:179-225` (`regenerate_for_verdict` is **Amber-only** — returns `[]` for Red at line 195-196),
`apps/api/src/services/workout_delivery.py:341-369` (`push()` has **no verdict re-check**),
`apps/api/src/services/executable_coaching.py:227-265` (`auto_push_due` pushes all approved-unpushed within today+2).

The `adjust_ir_for_verdict` transform correctly makes VO2 *arithmetically
impossible* on Red (every step capped at `RECOVERY_CAP_PCT=60`% FTP, vs VO2 at
`HIT_FLOOR_PCT=106`%). **But** the live daily loop only invokes that transform on
**Amber**; the `red_substitution` branch is never reached in production (only by
unit tests). And `push()`/`auto_push_due` deliver any *already-approved* proposal
within today+2 without re-checking the day's verdict.

**Consequence:** if a VO2 session is approved ahead of time — exactly the
week-ahead workflow `auto_push_due` exists to serve (Decision #31) — and that
morning turns **Red**, nothing supersedes or blocks it. The VO2 workout
auto-pushes to Zwift at 07:00 despite the Red verdict.

**Impact:** the headline safety invariant ("Red never emits VO2") can be violated
at the point that actually matters — what lands on the bike.

**Fix (pick one):**
- On a Red verdict, run a `red_substitution` regeneration that supersedes /
  un-approves same-day approved bike proposals (mirror the Amber path); **or**
- Re-validate the day's morning verdict inside `auto_push_due`/`push` and
  skip-or-substitute when Red.
- Either way, add a regression test: *"a Red day does not auto-push an approved
  VO2 proposal."* (There is currently no test covering this path.)

### P1-3 · Production PIN is still the temporary `1234`
**Where:** your own STATUS follow-up #1; the value is also baked into
`scripts/smoke_daily_loop.py:9` as the documented smoke PIN.

A trivially-guessable 4-digit credential on real health data, made worse by P1-1
(no working lockout). **Fix:** rotate Mark's PIN to a non-default value via the
seed helper and update the smoke env out-of-band (don't commit the new value).

---

## P2 — Should fix soon

### P2-1 · No security headers on the web (SPA) origin — confirmed live
**Where:** `vercel.json` has no `headers` block; `apps/web/index.html` has no CSP
meta. Live check: the Vercel origin returns **only HSTS**.

The SPA origin is where any XSS would execute and where **30-day refresh + access
tokens live in `localStorage`** (`apps/web/src/lib/tokens.ts:14-18`; the
`middleware.py:32-34` comment acknowledges this). With no CSP it's
XSS-exfiltratable, and with no `X-Frame-Options`/`frame-ancestors` it's
iframe-able (clickjacking). The API's strong CSP (`default-src 'none'`) protects
JSON responses, **not** this origin.

**Fix:** add a `headers` block to `vercel.json` for the app origin — `CSP`
(scoped to self + the API), `X-Frame-Options: DENY` / `frame-ancestors 'none'`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`. Given
the health-data sensitivity this is the highest-value web hardening.

### P2-2 · `react-router-dom@6.30.3` open-redirect (moderate)
**Where:** `pnpm audit` → GHSA-2j2x-hqr9-3h42 (open redirect via protocol-relative
`//` path). Fixed in `>=6.30.4`. **Fix:** bump `react-router-dom` to `6.30.4+`
and refresh the lockfile. Low exploitability here (app controls its routes) but a
one-line change.

### P2-3 · CI has no dependency / secret / SAST scanning
**Where:** `.github/workflows/ci.yml` runs ruff, mypy, pytest, alembic up/down,
web build — and nothing else. The react-router CVE (P2-2) would have been caught
automatically by `pnpm audit` in CI. **Fix:** add `pnpm audit` + `pip-audit -r
requirements.txt` gates (and optionally secret scanning / CodeQL). Note: I could
not run `pip-audit -r requirements.txt` in this sandbox (it builds a resolver
venv that fails under the uv-managed Python, and PyPI egress was flaky) — **CI is
the right place** for the canonical Python audit.

---

## P3 — Informational / nice-to-have

- **P3-1 · Concurrent-refresh race (web).** `apps/web/src/lib/api.ts:63-76`: the
  401 handler calls `silentRefresh()` *un-deduped* (the `refreshPromise` singleton
  guards only the proactive path at `:38-46`). Because the backend rotates +
  revokes refresh tokens single-use (`routers/auth.py:206`), several parallel 401s
  can revoke each other's new tokens → spurious logout. Route the reactive path
  through the same `refreshPromise`.
- **P3-2 · `change_pin` doesn't revoke sessions.** `routers/auth.py:291-305`
  changes the PIN but leaves existing refresh tokens valid (unlike `pin_reset`,
  which revokes all — `:355-359`). After a PIN change you'd usually expect other
  sessions invalidated.
- **P3-3 · PIN-reset token logged.** `routers/auth.py:328-332` writes the
  auth-bearing reset JWT to `log.info` (by design, since there's no email rail) —
  but logs can flow to Sentry/aggregators. Consider a shorter TTL or out-of-band
  delivery.
- **P3-4 · Scheduler isolation is asymmetric.** `scheduler.py`: the morning Garmin
  *daily* sync isolates per profile (`_sync_garmin_daily:179-200`), but the
  weather fetch (`:228-241`) and hourly *activity* fetch (`:323-335`) do not — one
  profile's failure aborts the whole job for everyone. Negligible at 1–2 users;
  tidy for symmetry.
- **P3-5 · Prod secrets validator is shallow.** `config.py:69-90` rejects only the
  two known placeholder strings; it doesn't enforce a minimum secret length or
  that `jwt_access_secret != jwt_refresh_secret`. Add length + distinctness checks.
- **P3-6 · Backup DSN exposes the DB password to `ps`.** `services/backup.py:41-50`
  passes the password inside the `pg_dump` DSN argv. Safe exec form (no shell), but
  prefer `PGPASSWORD`/`.pgpass`. Single-tenant container = low risk.
- **P3-7 · Public API docs.** `/api/docs`, `/api/redoc`, `/api/openapi.json`
  (`main.py:79-81`) are unauthenticated, exposing the full schema of a private
  app. Consider gating/disabling in production (the smoke currently relies on the
  OpenAPI).
- **P3-8 · LLM prompt-injection surface (low).** Free-text `notes`/`feel`
  (`morning_analysis.py:486-498`) flow verbatim into the Claude prompt
  (`:392-397`). Because the verdict is computed deterministically, injection can
  only alter *narrative text*, never the safety decision — acceptable, just be
  aware.
- **P3-9 · Hygiene.** Test warnings: 2× `coroutine ... never awaited` in
  `tests/test_notifications.py` (mock not awaited) + 1× Starlette deprecation
  (`HTTP_422_UNPROCESSABLE_ENTITY` → `..._CONTENT`). Venv `pip` 25.0.1 has 5 CVEs
  (toolchain only). ~20 stale local/remote `feat/*`/`claude/*` branches — prune.
  `models/profile.py:15-19` keeps a `SiteRole` "compatibility" enum that looks
  vestigial — confirm it's still needed. STATUS "live deploy `88cdcd1`" line is
  now stale (actual `80d898a`).

---

## What's right (don't regress these)

- **Deterministic safety logic.** The Green/Amber/Red verdict
  (`morning_analysis.py:652-724`) and all insight maths (`insights.py`) are pure,
  testable functions — the LLM writes narrative only. Division-by-zero is guarded
  everywhere in `insights.py` (`_slope`, `pearson`, FTP `pct_change`).
- **Token handling.** JWT algorithms pinned to `HS256` (no alg-confusion / `none`
  attack), refresh tokens stored as SHA-256 hashes with rotation + revocation on
  use, constant-time login via a dummy bcrypt hash (no user enumeration).
- **No injection.** Pure parameterised SQLAlchemy (only a static `SELECT 1`); the
  single process-exec (`pg_dump`) uses the exec form with a strict filename regex +
  resolved-path containment. No committed secrets in source.
- **API posture verified live.** All six security headers present; every feature
  route 401s unauthenticated; admin editor correctly `AdminUser`-gated while
  insight/experiment routes use `CurrentUser`.
- **Privacy hygiene.** Sentry scrubs display names and disables default PII
  (`main.py:40-57`); the Anthropic boundary sends the API key only as a header,
  never logs it.
- **Fail-closed config.** Environment is an enum (rejects unknown strings); prod
  startup refuses placeholder/missing secrets.

---

## Feature coverage matrix (batches 1–18)

| Feature | Batch | How verified this pass | Status |
|---|---|---|---|
| Auth (name+PIN+JWT, refresh rotation) | core | Code-reviewed; live 401s; 157 local tests | ✅ (see P1-1/P1-3) |
| Data model + migrations 001–007 | 1 | CI alembic up/down green | ✅ |
| Garmin sync | 2 | Not deep-read; CI tests + STATUS live runs | ➖ test-backed |
| Hive + weather sync | 3 | Not deep-read; CI tests | ➖ test-backed |
| 84-night backfill + baselines | 4 | Not deep-read; CI tests | ➖ test-backed |
| Training plan + KB editor | 5 | `coaching_state` admin-gating confirmed | ✅ |
| Morning analysis / verdict | 6 | **Deep-reviewed** (deterministic verdict) | ✅ |
| Daily-loop surfaces | 7 | Live 401; CI tests | ✅ |
| Post-workout analysis | 8 | Not deep-read; OpenAPI live; CI tests | ➖ test-backed |
| Nudges + thermal monitoring | 9 | `push_notification_service` reviewed | ✅ |
| Hardening / release polish | 10 | Security headers verified live | ✅ |
| player→user rename | 11 | Confirmed (`UserRole` etc.); CI tests | ✅ |
| Zwift delivery rail | 12 | **Deep-reviewed**; STATUS live event create+delete | ✅ |
| Executable coaching | 13 | **Deep-reviewed** | ⚠️ P1-2 |
| Weekly restructuring | 14 | Not deep-read; CI tests | ➖ test-backed |
| Holiday pause/resume | 15 | Live 401; CI tests | ➖ test-backed |
| App-generated 13-week blocks | 16 | Live 401; CI tests | ➖ test-backed |
| Monitoring + insight | 17 | **Deep-reviewed** (deterministic, guarded); live 401 | ✅ |
| Scheduler daily-data wiring | 18 | **Deep-reviewed** | ✅ (see P3-4) |

✅ verified · ⚠️ finding raised · ➖ relied on green CI + live smoke, not individually code-reviewed

---

## Coverage & methodology (honest limits)

**Deep-read this pass:** the auth core (`auth.py`, `routers/auth.py`,
`rate_limit.py`, `config.py`, `middleware.py`, `main.py`, `models/profile.py`),
the safety-critical path (`morning_analysis.py`, `executable_coaching.py`,
`workout_delivery.py`, `scheduler.py`, `insights.py`), `backup.py`,
`push_notification_service.py`, and the web token/api/header surface
(`tokens.ts`, `api.ts`, `vercel.json`).

**Verified live:** read-only production smoke on Railway + Vercel (health, 401s,
headers, proxy).

**Not individually code-reviewed** (lower risk; covered by the 206-test CI suite
but not line-read here): `garmin_sync`, `environment_sync`, `sleep_history`,
`post_workout_analysis`, `nudge_alerts`, `weekly_restructure`, `holiday_pause`,
`block_generator`, `coaching_state` service, `experiment_tracker`,
`vo2_progression`; most frontend pages/components; the migration bodies; shared
Zod schemas. A second pass could extend depth here if desired.

**Could not run in this environment:** DB-backed tests (no Docker/Postgres),
`mypy` (CI-only layout), `pip-audit -r requirements.txt` (sandbox limits — ran
OSV against the installed env instead). All three are green/clean in CI.

---

## Suggested remediation order

1. **Rotate the production PIN off `1234`** (P1-3) — minutes, removes the most
   concrete live exposure.
2. **Add the `vercel.json` security-headers block** (P2-1) and **bump
   `react-router-dom`** (P2-2) — small, high-value web hardening.
3. **Decide and fix the Red-delivery gap** (P1-2) — confirm intended behavior,
   then close the gate + add the regression test.
4. **Wire up the account lockout** (P1-1) — the schema already anticipates it.
5. **Add dependency/secret scanning to CI** (P2-3) so 2–4 don't recur silently.
6. Mop up P3 items opportunistically.
