# Auth simplification — passwordless device tokens (Option B)

**Status:** Agreed, not yet started · **Decision:** `DECISIONS.md` #73–74 · **Origin:** `docs/reviews/v1-v2-review.md` (P1-1, P1-3, P2-1, P3-1/2/3)
**Date:** 2026-06-22

> Replaces the inherited **display-name + 4-digit-PIN + JWT** login with a
> **passwordless, revocable device token** provisioned once via a one-time
> activation link. Cloudflare Access ("Option C") is deferred — see #74.
> This doc is the file-level runbook; the *why* lives in `DECISIONS.md` #73–74.

## Why (one paragraph)

The v1+v2 review found the bulk of the auth code and attack surface is the
brute-force/reset machinery around a 4-digit PIN — and it's half-built: the DB
lockout is unwired (`rate_limit.py` wrongly calls it "the durable brute-force
guard"), the PIN-reset token is logged, and the prod PIN is still `1234`. A
256-bit device token makes brute-force moot, deletes the PIN/reset/change-pin/
refresh endpoints and both JWT secrets, and is a net code reduction. It keeps the
app gated (it's on a public URL with health + home-occupancy data and can write to
Mark's Zwift), without a domain or any new infra.

## Target picture

```
You (admin), once per device:  CLI mints a single-use activation link  ──►  send to Mark privately
Mark taps link once ──► PWA exchanges the code for a long-lived device token ──► stores it
Thereafter:  open PWA ──► every /api call carries the token ──► API hashes it, looks it up,
                          resolves the Profile.  No PIN, no login screen, ever.
```

## The model

- **Device token** — a 256-bit opaque random string (`secrets.token_urlsafe(32)`),
  stored only as a **SHA-256 hash** in the DB (the existing `refresh_tokens` table
  shape already does exactly this: `user_id`, `token_hash`, `device_hint`,
  `expires_at`, `revoked_at`). The raw token is the bearer credential the phone
  holds; it's long-lived (e.g. 1 year) and revocable (delete/`revoked_at` the row).
- **Verify path** — `get_current_user` hashes the presented token and joins to the
  Profile in one indexed lookup. No JWT decode, no rotation.
- **Provisioning** — admin-only, out-of-band. A CLI mints a **short-lived,
  single-use activation *code*** (not the durable token) and prints a
  `…/activate#code=…` link. The durable token never travels in a shareable link,
  and the `#fragment` keeps the code out of server/proxy logs. The PWA exchanges
  the code once (`POST /api/v1/auth/activate`) for the device token.
- **Identity** — `token → profile`. Two users (Craig + Mark) = two tokens;
  `require_admin` still reads `profile.role`. Lost phone = revoke + mint a new link.

## Phased plan (each phase ships independently; nothing deleted until Phase 3)

### Phase 1 — Add the device-token path alongside PIN (additive, fully reversible)
- **CLI:** `python -m src.activate --profile <name>` → mints a single-use code,
  prints the `…/activate#code=…` link. Bootstraps your own device too (no
  chicken-and-egg). Activation codes can live in the existing token table with a
  `purpose` discriminator + `used_at` (small additive migration) or a tiny new table.
- **API:** `POST /api/v1/auth/activate {code}` → validate code (unused, unexpired),
  create a device token, mark code used, return the token. Light rate-limit on this
  one route.
- **API:** teach `auth.get_current_user` to accept **either** today's PIN-issued JWT
  **or** a device token (try JWT decode; on failure, do the token-hash lookup).
- **Frontend:** `pages/ActivatePage.tsx` at `/activate` — read `location.hash`, call
  activate, store the token via `lib/tokens.ts`, `history.replaceState` to strip the
  hash, redirect to dashboard.
- **Acceptance:** activate your own phone via a link; PIN login still works; existing
  tests stay green. **Reversible:** nothing removed.

### Phase 2 — Cut the frontend over, hide the login form
- **Frontend:** `contexts/AuthContext.tsx` — on load, if a device token exists →
  `GET /api/v1/me` for identity; else show an "ask Craig for a link" screen instead
  of the PIN form. Drop the silent-refresh / refresh-on-401 logic in `lib/api.ts`
  (a 401 now means "token revoked → request a new link", not "rotate").
- **Ops:** mint Mark's link, send over a private channel, he activates once.
- **Acceptance:** Mark uses the app with no PIN; backend PIN endpoints still exist as
  a fallback. **Reversible:** re-enable the login route if needed.

### Phase 3 — Delete the PIN/JWT machinery (first destructive step; after Phase 2 is stable)
- **Backend remove:** `routers/auth.py` `login`/`refresh`/`logout`/`change_pin`/
  `pin_reset_request`/`pin_reset` + their schemas; the bcrypt PIN helpers and HS256
  token helpers in `auth.py` (`create/decode_*`, `hash_pin`, `verify_pin`,
  `create_pin_reset_token`); the auth-specific keys in `rate_limit.py`
  (`login_key`, `refresh_token_key`). `get_current_user` becomes device-token-only.
  Keep a minimal `POST /api/v1/auth/revoke` ("sign out this device").
- **Frontend remove:** `pages/LoginPage.tsx`, `components/PinInput.tsx`,
  `pages/ForgotPinPage.tsx`, `pages/PinResetPage.tsx`; trim `lib/tokens.ts` to a
  single device token (+ cached profile).
- **Ship the headers:** add the `vercel.json` `headers` block — CSP (self + API),
  `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `X-Content-Type-Options:
  nosniff`, `Referrer-Policy`, `Permissions-Policy`. This is what contains the
  `localStorage`-token risk, so it lands here (review P2-1).
- **Tests:** replace auth tests with device-token activate/verify/revoke coverage.

### Phase 4 — Schema + config cleanup
- **Migration:** drop `profiles.pin_hash`, `profiles.failed_login_count`,
  `profiles.locked_until`; tidy the token table (device tokens + activation codes via
  the `purpose` discriminator). Leave the `player_pin_reset` audit enum value in place
  (renaming stored enum values is disproportionate — per #52).
- **Config:** remove `jwt_access_secret` / `jwt_refresh_secret` from `config.py` and
  Railway (no JWTs remain → two fewer required secrets). Simplify CORS if fully
  same-origin.
- **Docs:** this file → `Status: Done`; tick `DECISIONS.md` #73–74; update
  `ARCHITECTURE.md` (auth section), `STATUS.md`, `.env.example`.

## What gets deleted (the win)

- Findings cleared: **P1-1** (unwired lockout), **P1-3** (the `1234` PIN), **P3-1**
  (refresh race), **P3-2** (change-pin doesn't revoke), **P3-3** (reset-token logged).
- `routers/auth.py` shrinks to `me` + `activate` + `revoke`; both JWT secrets gone;
  four frontend auth files deleted; net **less code than today**.
- Brute-force is moot (256-bit token) so no lockout/rate-limit is load-bearing.

## Security posture

- **Residual (accepted):** the token sits in `localStorage` (JS-readable) — the one
  thing Option C's HttpOnly cookie would close. Mitigated by the Phase 3 CSP header;
  low probability on a 2-user app with no third-party content. This is the knowing
  trade for £0 / no domain.
- **Link delivery:** send activation links over a private channel; single-use +
  revocable keeps the blast radius small.
- **Upgrade path:** Option C (Cloudflare Access) stays available later — swap the
  credential source in `get_current_user` for Cloudflare's verified
  `Cf-Access-Jwt-Assertion`; everything downstream (`token → profile`, `require_admin`)
  is unchanged.

## Gotchas

- **Offline PWA:** unchanged — cached data shows; live calls need the token (always
  present once activated).
- **Re-provisioning:** new phone / cleared browser = mint a fresh link (~30s).
- **Scheduler/backups:** unaffected — they hit the DB directly, not the gated HTTP
  layer.
