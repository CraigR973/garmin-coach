# Phase 0 — session kickoff prompts

Two self-contained sessions to finish Phase 0. Run **in order** (Session 2 assumes
the strip is committed). Each prompt follows the cross-tool standard: read the
canonical docs first, run the `handoff` at the end. Tier per `DECISIONS.md` #19.

---

## Session 1 — Strip the football domain
**Model:** 🟢 Mid — **Claude Sonnet 4.6** (or Codex GPT-5.4) · **Thinking:** medium
**Where:** either tool.

```
Work in ~/garmin-coach (NOT the wc_2026_predictor repo). This is Phase 0a — strip the football domain.

First read, in order: STATUS.md, AGENTS.md (canonical instructions), ARCHITECTURE.md (spec), DECISIONS.md (why). The repo was forked from the WC2026 predictor to inherit its infra; your job is to remove the football/predictions domain and leave a clean, BUILDING skeleton (auth + empty dashboard) with zero football references.

KEEP (infra): auth, config, database, middleware, rate-limit, logging, base + refresh-token models, health route, the APScheduler harness, web-push service, email, backup, the shadcn/ui kit, ThemeContext/AuthContext, the api client + token refresh, PWA/service worker, and generic hooks (online status, push subscription, install prompt).

REMOVE (domain): all match/prediction/leaderboard/group/league/knockout/squad/specials/survey models, routers, services (incl. football_data/result_sync — but preserve the external-client + scheduler PATTERN as a thin reference), their migrations, the football frontend pages/components and football-specific hooks, and packages/shared scoring (scoring.ts/scoring.test.ts). Replace the dashboard with an empty placeholder. Rename @wc2026/shared -> @coach/shared (package.json, workspace, all imports). Update root/app package.json names, .github/workflows/ci.yml (drop football-specific steps), and README.

GOTCHAS: never cd (absolute paths only — a blocked cd shows as a fake ENOSPC error). Python is ~/.local/bin/python3.12 (system python3 is 3.7 and breaks installs) — create apps/api/.venv with it. Do NOT model anything on the football tables; the real data model comes later from ~/garmin-spike/out/ JSON + ARCHITECTURE.md §5.

VERIFY before finishing: api venv installs deps and backend imports / `ruff check` / pytest collection pass on what remains; `pnpm --dir apps/web build` succeeds; no dangling football imports; the app renders a login + empty dashboard. Commit in logical stages (Conventional Commits; there is NO GitHub remote yet — commit locally only).

Do NOT provision hosting or deploy — that's the next session. Finish with the handoff in docs/agent-commands/handoff.md (update STATUS.md Now/Log/Gotchas, commit).
```

---

## Session 2 — Provision hosting + deploy the skeleton
**Model:** 🟢 Mid — **Claude Sonnet 4.6** · **Thinking:** medium-high · *escalate to **Opus 4.8** if deploys get stuck (High-tier debugging).*
**Where:** **Claude Code** (needs the Supabase + Vercel MCP tooling; Codex won't have them). **Craig must be present** to authenticate accounts.

```
Work in ~/garmin-coach, in Claude Code (this session needs the Supabase + Vercel MCP tooling). Run AFTER the strip session. This is Phase 0b — provision hosting and deploy the skeleton live.

First read: STATUS.md, AGENTS.md, ARCHITECTURE.md, DECISIONS.md. Goal: get the football-free skeleton deployed and reachable, mirroring WC2026's setup (Supabase DB + Railway API + Vercel web), so Craig's dad can open it on his phone.

STEPS:
1. GitHub: create a new PRIVATE repo and push main (no remote exists yet). Use gh.
2. Supabase: create a new project (use the Supabase MCP), get the connection string, run the auth/base migrations.
3. Railway: new project + service, deploy the backend (Dockerfile / railway.toml), set env (DB URL, JWT secrets — generate FRESH, never reuse WC's).
4. Vercel: new project, deploy the frontend, set env (API base URL). Use the Vercel skills/CLI.
5. Wire env vars across all three (use .env.example as the manifest). Record non-secret identifiers (project IDs, URLs) in STATUS.md; keep secrets only in each platform's env store — never commit them.
6. VERIFY live: the Vercel URL loads the login page; the backend /health endpoint responds; a preview deploy works.

NOTES: never reuse WC2026's secrets. Craig must be present to authenticate Supabase/Railway/Vercel/GitHub where the MCP/CLI can't act autonomously — pause and ask him to authorize when needed. Never cd (absolute paths).

Finish with the handoff: mark Phase 0 COMPLETE in STATUS.md (record the URLs/IDs), add a DECISIONS.md entry if anything notable, then commit + push.
```
