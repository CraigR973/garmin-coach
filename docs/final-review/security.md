# Security Audit — World Cup 2026 Prediction League

**Date:** 2026-06-08
**Scope:** Pre-production review of the FastAPI + PostgreSQL backend (`apps/api`), the React/Vite frontend (`apps/web`), Alembic migrations, and the committed `apps/web/dist` bundle.
**Auth model:** Name/email + 4-digit PIN (bcrypt) → JWT access (24h) + refresh (30d). Bearer-header transport (no auth cookies). Multi-league with per-league membership roles + a global `site_role` superadmin.

## Summary

Overall the backend is in good shape for a private ~15-player league. Authorization is consistently enforced through `require_league_member` / `require_league_admin` dependencies and a shared `shared_league_player_ids` helper; the prediction deadline is enforced **server-side** at the data layer; a single `reveal_gate` module is the source of truth for prediction privacy; RLS is enabled on Supabase-exposed tables; and no server-side secrets leak into the built frontend bundle. The findings below are the gaps worth closing before prod.

| Severity | Count |
|---|---|
| P0 | 1 |
| P1 | 4 |
| P2 | 6 |

---

## P0 — exploitable

### P0-1 — Cross-league IDOR: knockout-prediction match view leaks all leagues' picks
**Severity:** P0
**File:** `apps/api/src/routers/knockout_predictions.py:171-207` (`match_knockout_predictions`)

The group-prediction equivalent (`apps/api/src/routers/predictions.py:175-216`) correctly filters returned rows to league-mates: it computes `shared = await shared_league_player_ids(player.id, db)` and keeps only `pred.player_id in shared`. The knockout endpoint does **not**. After a knockout match locks (kickoff passes), `GET /api/v1/knockout-predictions/match/{match_id}` returns the `predicted_winner_id`, `player_name`, and `points_awarded` of **every player in the system**, including players the caller shares no league with.

Predictions are global (one prediction per player per match across all leagues), so this is a genuine cross-tenant data exposure: any authenticated user can enumerate the knockout picks and display names of users in completely separate private leagues. It violates the same privacy/tenant-isolation invariant that the group endpoint, `players.py`, `compare.py`, and `specials.py` all uphold.

**Fix:** Mirror the group endpoint. After fetching rows, compute `shared = await shared_league_player_ids(player.id, db)` and include only `pred` where `pred.player_id in shared`. Add a regression test (see `test_r12_tenant_isolation.py`) asserting a non-shared player's knockout pick is absent.

---

## P1 — fix before prod

### P1-1 — Login brute-force limiter keys on a field the login body never sends
**Severity:** P1
**File:** `apps/api/src/rate_limit.py:43-55` (`login_key`) vs `apps/api/src/routers/auth.py:77-80` (`LoginRequest`)

`login_key` builds the per-credential rate-limit bucket from `data.get("display_name", "")`, but `LoginRequest` only has `email` and `pin` — there is no `display_name` in the login body. The key therefore always collapses to `login::<IP>`. Two consequences:
1. The intended *per-credential* lockout (5 attempts / 15 min against one account) does not exist; the only IP-based bucket is shared across **all** accounts from that IP, so an attacker hammering many accounts from one IP trips a single shared bucket (and conversely, distributed IPs each get a fresh 5-attempt budget against the same account).
2. The DB-level lockout (`MAX_FAILED_ATTEMPTS=5`, `auth.py:419-429`) is the real backstop and does work — but a 4-digit PIN has only 10,000 combinations, and the slowapi limiter is the first line of defence that is currently misconfigured.

**Fix:** Change `login_key` to read `email` (e.g. `f"login:{data.get('email','').lower()}:{get_remote_address(request)}"`). Add a test that 6 wrong-PIN attempts for one email from one IP returns 429.

### P1-2 — Rate limiter uses in-memory storage (per-process, not shared, resets on deploy)
**Severity:** P1
**File:** `apps/api/src/rate_limit.py:16` — `limiter = Limiter(key_func=get_remote_address)` (no `storage_uri`)

slowapi defaults to in-process memory storage. On Railway this means: (a) limit counters are **not shared** if more than one instance/replica ever runs, and (b) every deploy/restart resets all counters. Combined with P1-1, the brute-force protection that should gate the 10k-space PIN is weaker than intended. The DB lockout still protects individual accounts, but auth/`signup`/`pin-reset` abuse limits are effectively soft.

**Fix:** Configure a shared store, e.g. `Limiter(key_func=..., storage_uri=settings.redis_url)` backed by Redis (Railway add-on), or at minimum document that the API must run as a single instance and accept reset-on-deploy. The DB lockout (P1-1 backstop) should be treated as the authoritative control regardless.

### P1-3 — No Content-Security-Policy header; tokens in localStorage are XSS-exfiltratable
**Severity:** P1
**Files:** `apps/api/src/middleware.py:24-32` (`SecurityHeadersMiddleware`); `apps/web/src/lib/tokens.ts:16-28` (`storeTokens`/`getAccessToken`/`getRefreshToken`)

Access and refresh tokens are stored in `localStorage`. The 30-day refresh token in `localStorage` is readable by any JavaScript that runs in the origin, so a single XSS gives an attacker a long-lived credential they can exfiltrate. The security-headers middleware sets HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, and `Referrer-Policy`, but sets **no `Content-Security-Policy`** — the main defence-in-depth control against XSS is absent. (Note: because auth is a Bearer header and not a cookie, there is no classic CSRF surface — that part is fine.)

**Fix (defence-in-depth, do at least one):**
- Add a CSP. For the SPA this is typically served by Vercel for the HTML document (`default-src 'self'; ...`), but the API can also emit one for its own JSON responses. The high-value control is the document CSP shipped with the frontend.
- Consider moving the **refresh** token to an `HttpOnly; Secure; SameSite=Strict` cookie (access token can stay in memory). This is a larger change but removes the long-lived-credential-in-JS exposure. At ~15 trusted users the residual risk is low, so a CSP + keeping the audit note is a reasonable minimum.

### P1-4 — Dependency CVEs: PyJWT and Starlette on vulnerable versions
**Severity:** P1
**File:** backend dependency lock (PyJWT 2.12.1, starlette 1.0.0; also aiohttp 3.13.5, urllib3 2.6.3, idna 3.13) — `pip-audit` over `apps/api/.venv`

`pip-audit` reports 16 advisories across 6 packages. The security-relevant ones:
- **PyJWT 2.12.1 → 2.13.0** (PYSEC-2026-175/177/178/179). This is the JWT library at the core of auth (`apps/api/src/auth.py`). Most advisories target `PyJWKClient`/JWKS fetching and detached-JWS, which this app does **not** use (it pins `algorithms=["HS256"]` with static secrets and never fetches JWKS), so the practical exposure is low — but a JWT library on a known-vulnerable version is not acceptable for a prod auth path.
- **starlette 1.0.0 → 1.0.1** (PYSEC-2026-161): `Host` header is not validated before `request.url` is reconstructed (host/path injection). FastAPI is built on Starlette; relevant if any code reflects `request.url`.
- aiohttp 3.13.5 → 3.14.0, urllib3 2.6.3 → 2.7.0, idna 3.13 → 3.15: cross-origin redirect header/cookie leakage and decompression issues; lower relevance (server-side HTTP clients used only against football-data.org / Supabase).

`pnpm audit --prod --audit-level high` on the frontend returns **only 1 moderate** (nothing high/critical) — acceptable.

**Fix:** Bump PyJWT to ≥2.13.0 and starlette to ≥1.0.1 (verify FastAPI 0.136.1 compatibility), then aiohttp/urllib3/idna. Re-run `pip-audit` in CI and fail on high/critical.

---

## P2 — hardening

### P2-1 — Dev-only fixture endpoints have no auth and seed a superadmin with PIN 1111
**Severity:** P2
**File:** `apps/api/src/routers/test_helpers.py` (mounted by `apps/api/src/main.py:126-129` only when `environment == development`)

`/api/v1/test/seed` creates a `SiteRole.superadmin` account (`__smoke_admin__`, PIN `1111`), `/api/v1/test/lock-now/{id}` mutates match state, and `/api/v1/test/cleanup` deletes data — all **unauthenticated**. The only guard is `settings.environment == Environment.development` (and the config validator treats `staging` as production, `config.py:41`), so this is correctly gated off in staging/prod. The residual risk: a misconfigured `ENVIRONMENT=development` on a public host instantly exposes a known-PIN superadmin and destructive endpoints.

**Fix:** Keep the environment gate (good), but additionally guard the router behind a startup assertion or a shared-secret header so an env-var slip is not a single point of total compromise. At minimum, document `ENVIRONMENT` as a deploy-critical security variable in the env manifest.

### P2-2 — `avatar_url` accepts any HTTPS URL, stored and rendered to all league-mates
**Severity:** P2
**File:** `apps/api/src/routers/auth.py:804-838` (`update_avatar`, `PATCH /me/avatar`)

The only validation is `body.avatar_url.startswith("https://")` and a 2048-char cap. A player can set their avatar to any external HTTPS URL, which is then rendered as an `<img src>` in leaderboards/member lists for everyone in their leagues. Not SSRF (the server never fetches it), but it allows off-domain content embedding / request-logging of league-mates' IPs via a tracking pixel, and bypasses the intended Supabase-Storage-only path used by the `POST /me/avatar` upload route.

**Fix:** Restrict accepted `avatar_url` to the Supabase Storage public-URL prefix (`settings.supabase_url + "/storage/v1/object/public/avatars/"`), or drop the URL-setter entirely and require the upload endpoint (which already namespaces by `player_id`).

### P2-3 — Admin-issued temporary PINs are weak and returned in the response body
**Severity:** P2
**Files:** `apps/api/src/routers/admin.py:340-362` (`reset_player_pin`, 6-digit); `apps/api/src/routers/league_memberships.py:459-505` (`reset_member_pin`, 4-digit `1000–9999`)

Admin PIN resets generate a numeric temp PIN and return it in the JSON response (`temp_pin`). The league-admin variant is only 4 digits. The temp PIN is not flagged "must change on next login," so a player may keep an admin-known 4-digit PIN indefinitely. For a 15-person trust group this is low risk, but it means a league admin can knowingly set and read a member's working credential.

**Fix:** Force a PIN change on next login after an admin reset (a `pin_reset_required` flag checked at login), and prefer the emailed self-service reset flow (`/auth/pin/reset-request`) which never exposes the credential to a third party. At minimum make both temp PINs 6 digits.

### P2-4 — CORS `allow_headers=["*"]` / `allow_methods=["*"]` with credentials
**Severity:** P2
**File:** `apps/api/src/main.py:94-100`

Origin is correctly pinned to a single `settings.frontend_origin` (and the config validator rejects empty/localhost origins in prod, `config.py:73-74`) — this is the important part and it is done right. However `allow_headers=["*"]` and `allow_methods=["*"]` are broader than necessary alongside `allow_credentials=True`. Auth is a Bearer header (not cookies), so the credentialed-CORS risk is minimal, but tightening to the actual method/header set is good hygiene.

**Fix:** Enumerate `allow_methods=["GET","POST","PUT","PATCH","DELETE"]` and `allow_headers=["Authorization","Content-Type","X-Correlation-ID"]`.

### P2-5 — 4-digit PIN policy with no complexity / no compromised-PIN rejection
**Severity:** P2
**File:** `apps/api/src/routers/auth.py:73,79,113,125-126,139` (all PIN fields are `pattern=r"^\d{4}$"`)

PINs are exactly 4 digits (10,000-space). bcrypt with default cost (`bcrypt.gensalt()`, cost 12 — good, `apps/api/src/auth.py:38-39`) makes online brute-force slow, and the DB lockout caps attempts, but there is no rejection of trivial PINs (`0000`, `1234`, `1111`) and no rate-limit-correct first line (see P1-1). The whole scheme rests on the lockout working.

**Fix:** Reject a denylist of common PINs at signup/change/reset, and ensure P1-1/P1-2 are fixed so the limiter actually backstops the small keyspace. Consider 6-digit PINs given the value of admin accounts.

### P2-6 — Email-verification / PIN-reset tokens signed with the access-token secret
**Severity:** P2
**File:** `apps/api/src/auth.py:115-158` (`create_email_verify_token`, `create_pin_reset_token` use `settings.jwt_access_secret`)

Email-verify (24h) and PIN-reset (30 min) tokens are JWTs signed with `jwt_access_secret` and distinguished only by a `scope` claim. The scope check (`auth.py:134-135,156-157`) prevents an access token from being used as a reset token and vice-versa, so this is not currently exploitable — but reusing the access secret for out-of-band action tokens means a single secret rotation invalidates everything at once and widens the blast radius of an access-secret leak to include account-recovery.

**Fix:** Sign action tokens (email-verify, PIN-reset) with a dedicated secret, or at least keep the explicit `scope` check (already present) and document the coupling. Low priority given the scope guard.

---

## Positives confirmed (no action needed)

- **Server-side prediction deadline:** `upsert_prediction` rejects writes once `match.status != scheduled or kickoff_utc <= now` (`predictions.py:114-118`); knockout writes reject at per-match kickoff (`knockout_predictions.py:117-118`); specials lock at tournament open (`specials.py:194-196`). Enforced at the API, not just the UI.
- **Prediction privacy:** single `reveal_gate.py` source of truth, fail-closed (`now_utc()`, `match_prediction_revealed`, `specials_revealed`); pre-lock picks are never returned (except the P0-1 knockout-view gap, which is a *cross-league* leak after lock, not a pre-lock leak).
- **Authorization:** league routes consistently use `require_league_member` / `require_league_admin` (`leagues.py:107-140`); cross-player reads gate on `shared_league_player_ids` (`players.py`, `predictions.py`, `stats.py`, `specials.py`, `compare.py`); admin actions gate on `SiteRole.superadmin` via `require_admin` (`auth.py:186-193`). No player-facing endpoint mutates `role`/`site_role` (no privilege-escalation mass-assignment).
- **Supabase RLS:** migration `015_r11_rls_lockdown.py` revokes anon/authenticated writes and enables RLS on all 13 exposed tables; only `matches` + `leaderboard_snapshots` (non-secret) keep an anon SELECT policy. `SUPABASE_SERVICE_KEY` is backend-only (`storage.py`), never referenced in frontend source.
- **No secret leakage to browser:** `apps/web/dist` greps clean for `SUPABASE_SERVICE_KEY`, `VAPID_PRIVATE_KEY`, `JWT_*_SECRET`, `FOOTBALL_DATA_API_KEY`, `RESEND_API_KEY`, `service_role`, JWT-shaped strings, and Resend keys. The bundle contains only `VITE_VAPID_PUBLIC_KEY` and Supabase **anon** placeholders (real anon key injected at deploy by Vercel) — all public-safe.
- **Secrets loading:** `config.py` fails closed in non-dev environments — rejects placeholder JWT secrets, empty service/VAPID/football-data keys, and localhost CORS origin at startup (`config.py:56-77`).
- **SQL injection:** all queries use SQLAlchemy Core/ORM with bound parameters; no string-interpolated SQL in request paths. The only f-string SQL is in migration `015` over a hardcoded table allowlist (no user input).
- **Refresh-token hygiene:** opaque refresh JWT, sha256-hashed at rest (`refresh_tokens.token_hash`), single-use rotation on `/refresh` (old revoked, new issued, `auth.py:484-498`), revoked on logout and on PIN reset (all tokens, `auth.py:373-377`).
- **Login timing:** constant-time dummy bcrypt verify when the email is unknown (`auth.py:404`); generic "Invalid credentials" for not-found / locked / wrong-PIN; generic response for PIN-reset-request (no account enumeration, `auth.py:144-146,326-351`).
- **Football-data ingestion:** responses parsed through pydantic models, rows updated under `SELECT ... FOR UPDATE`, manual results never overwritten by auto-sync (`result_sync.py`). Admin/scheduler-only trust boundary.
- **Sentry PII scrubbing:** `send_default_pii=False` + `before_send` strips `display_name`/`username` (`main.py:46-63`).
- **No CSRF surface:** auth is a Bearer header, not a cookie.
