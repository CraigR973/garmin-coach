# Decisions Log

Append-only. Each entry: the decision + *why*. Don't re-litigate a settled
decision — if you change course, add a new entry that supersedes the old one.
(See `ARCHITECTURE.md` for the full spec, `STATUS.md` for current state.)

---

### 2026-06-18 — Foundations
1. **Separate app + repo**, not part of WC2026. *Why:* different domain, different users.
2. **1–2 private users**, no public sign-up. *Why:* it's for Craig's dad (+ maybe one other) — lets us strip all multi-tenant/league machinery.
3. **Garmin via unofficial `garminconnect`**, not the official Health/Connect dev program. *Why:* immediate to prototype; garth token cache persists ~1yr so unattended sync works.
4. **The app generates the analysis itself** (calls Claude directly), Copilot out of the loop. *Why:* the analysis quality *is* the product; we control the prompt + persistent context.
5. **Hive + weather in v1.** *Why:* kills his manual temperature transcription — his #1 sleep lever.
6. **Web app, forking the WC2026 stack/infra.** *Why:* inherit a proven FastAPI/React/Postgres/scheduler/PWA foundation.
7. **Manual entry** stays for BP, subjective/RPE, food, supplements. *Why:* no other source exists for them.

### 2026-06-18 — Build approach
8. **Fork-and-gut WC2026**, don't build fresh. *Why:* day-one working CI/Docker/Railway/Vercel/auth/scheduler.
9. **Reusable starter template distilled LATER** (after this 2nd app), as a **clone-and-own template, not a shared runtime library**. *Why:* extracting from N=1 bakes in wrong abstractions; a library couples independent personal apps — a template gives reuse without coupling.
10. **Deploy live early** (Supabase + Railway + Vercel). *Why:* his dad can use it on his phone from early on.

### 2026-06-18 — Data sources (all validated against real data)
11. **Hive unattended sync = stored-creds re-login**, not refresh token. *Why:* his Hive account has no 2FA (so full login is headless), and pyhiveapi's `refresh_token` is bugged + Cognito device-tracking rejects bare refresh.
12. **Weather = Open-Meteo** (keyless). *Why:* free, no API key, has recent-history + forecast; KA1 2SD → lat 55.6045 / long -4.5249.

### 2026-06-19 — Product shape
13. **Knowledge-base layer is core.** *Why:* his hand-written "handover docs" exist because AIs forget context — the app's job is to hold that as living state.
14. **Verdict = Green/Amber/Red framework + age-adjustment** (sleep +4; REM band 65–90 min). *Why:* it's his own documented decision rule, and Garmin's scores are calibrated for young athletes.
15. **Ignore the phase-frequency cadence — daily always.** *Why:* his explicit preference (phases were only about reducing monitoring; he wants to continue daily).
16. **Training plan: stored in DB (retained) + per-day override; app generates future 13-wk blocks with refine-then-lock** (sequenced to v2). *Why:* unlike Copilot it never forgets the plan; refine-then-lock preserves the "mould it + fix errors" control he values.

### 2026-06-19 — Cross-tool workflow
17. **Built across Claude Code + Codex. `AGENTS.md` is canonical; `CLAUDE.md` is a symlink to it.** Repo is the single source of truth; Claude's private memory is a cache only. *Why:* smooth, drift-free handoffs between tools — neither depends on state the other can't see.

### 2026-06-19 — Batch workflow machinery (deferred build: pre-Phase-1)
18. **Lean batch command set (4), not WC's 7:** `batch-start`, `batch-verify`, `closeout`, `next-batch-prompt`. `closeout` folds WC's `phase-closeout` + `strike-batch` + `ship-prod` into one (commit → CI → merge to main → deploy → update STATUS/DECISIONS/ARCHITECTURE → strike the batch row). *Dropped:* `ship-staging` (Vercel/Railway give a **preview deploy per push** — that's the staging tier; eyeball the preview URL, then `closeout` promotes to the prod his dad uses) and standalone `strike-batch` (folded into `closeout`). *Why:* smaller single-user app + the `STATUS.md`/`handoff` docs already cover some of WC's ceremony. Built as tool-agnostic `docs/agent-commands/*.md` + thin Claude (`.claude/commands/`) and Codex (`.codex/prompts/`, exact path TBC) wrappers, right before Phase 1.
19. **Batch tags are TIER-based with a per-tool model map** (not Claude-only, not pinned to one tool). WC tagged each batch with a Claude model (🟢 Sonnet / 🔴 Opus). Here a batch carries a **complexity tier** (fixed by the batch — it reflects how hard the work is); you choose Claude *or* Codex per session and use the mapped model:

    | Tier | Work | Claude | Codex |
    |---|---|---|---|
    | 🔴 **High** | complex reasoning — analysis-engine prompt design, verdict/scoring logic, scheduler/sync edge cases, debugging | Opus | GPT-5.5 |
    | 🟢 **Mid** | well-specified implementation — CRUD, components, migrations, tests, mechanical refactors | Sonnet | GPT-5.4 |

    `batch-start` states the tier; `next-batch-prompt` notes the tier + this map. *Why:* decouples work-difficulty (the batch's call) from tool-choice (yours, per session), so any batch can run in either tool at the right capability level. (Codex model names per Craig's setup — update here if they change.)

### 2026-06-19 — Phase 0a (football domain strip)
20. **Display-name login, not email.** Profile has `display_name` + `pin_hash`; no email, no avatar, no site_role. *Why:* 1–2 private users; email auth adds complexity that buys nothing.
21. **No signup endpoint.** Admin seeds profiles directly in the DB (or via a future admin panel in Phase 2). *Why:* this is a private app — open signup is never needed; simpler security surface.
22. **`@coach/shared` package is a stub until Phase 1.** Only exports `Role` type. Scoring helpers, schemas, and Garmin/Hive types will be added in Phase 1 once the data model is settled from real spike JSON. *Why:* premature typing bakes in wrong shapes.
23. **Brand wordmark: text-only for Phase 0.** "GARMIN / COACH" two-line mono wordmark instead of the Calcio SVG icon. *Why:* no designer available yet; icon assets added in Phase 1/2 when identity is designed.
24. **`score-input.tsx`, `offlineQueue.ts`, `sw.ts` "predictions" references left in.** These are offline-queue infrastructure — the word "predictions" refers to offline-queued API writes, not football predictions. They will be renamed when the coaching submission flow ships in Phase 1. *Why:* renaming now with no replacement use is noise.
