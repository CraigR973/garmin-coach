# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** 0a — football domain stripped.

**Done:** Phase 0a complete — football/WC2026 domain stripped from backend and
frontend; clean garmin-coach auth skeleton committed.

**Backend:**
- Profile: display_name + PIN auth, no email/avatar
- Auth router: display_name login, no signup/email/verify
- Scheduler: daily_backup job only
- Migration 001: garmin-coach schema (profiles, push_subscriptions, etc.)
- Migrations 002–033 deleted
- 42 backend unit tests pass; ruff + mypy clean

**Frontend:**
- 28 football pages deleted; kept Login, ForgotPin, PinReset, Dashboard, Settings, Offline
- @wc2026/shared → @coach/shared (no football types/scoring)
- AuthContext: display_name login, no signup/email
- App.tsx: 3 protected routes (/, /settings, /offline)
- TopBar + TabBar: minimal nav (Home, Settings)
- Brand: no CalcioLogo, Garmin/Coach two-line wordmark
- TypeScript typecheck passes; vite build succeeds

**Next:** Phase 0b — provision hosting:
1. Create new Supabase project + run migration 001
2. Create Railway service + set env vars (JWT secrets, DB URL, VAPID)
3. Create Vercel project + link frontend
4. Create GitHub repo + push main branch

**Then Phase 1:** data model from real JSON shapes (`~/garmin-spike/out/`),
three sync jobs (Garmin, Hive, weather), 84-night backfill, morning analysis.

## Gotchas
- Python is **3.12** (`~/.local/bin/python3.12`); api venv exists at `apps/api/.venv`.
- `cryptography` wheel: install with `--only-binary :all:` before other deps on macOS.
- Repo has **no GitHub remote yet** and is **not deployed**.
- Node.js: use `~/.nvm/versions/node/v20.20.2/bin/node` + pnpm (system node is v14).
- `score-input.tsx`, `offlineQueue.ts`, `sw.ts` still have "predictions" domain
  references — these are offline-queue infrastructure, not football code; update in Phase 1.
- `apps/api/src/auth.py` still has `create_email_verify_token` / `decode_email_verify_token`
  dead code (WC2026 leftover) — harmless, remove in a future cleanup pass.

## Log
- **2026-06-19** — Phase 0a complete: stripped football domain from backend and
  frontend. 148 backend files changed (1041 ins / 48814 del); 161 frontend files
  changed (748 ins / 27045 del). Backend: 42 tests pass, ruff clean.
  Frontend: TypeScript passes, vite build succeeds.
- **2026-06-19** — Phase 0 started: seeded repo, wrote project docs, set up
  cross-tool structure, pruned WC cruft. Data sources validated via spikes.
