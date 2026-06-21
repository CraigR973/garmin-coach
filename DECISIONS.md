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

### 2026-06-19 — Zwift integration (validated) + training inputs
25. **Zwift workout delivery via `intervals.icu` relay** (validated end-to-end). App pushes a structured workout to his intervals.icu calendar (free API); intervals.icu's existing Zwift Training-Connections integration delivers it into Zwift's Custom Workouts. *Why:* Zwift's own Training API is partner-only (impractical for 1–2 users); piggybacking intervals.icu's approved partnership gives true "straight-from-app → Zwift". Power + timing came through **perfect** in testing.
26. **intervals.icu is a DELIVERY RAIL, not the system-of-record.** Our own Postgres owns the plan, knowledge base, and AI brain (keeps Decision #16). *Why:* owning the plan keeps us uncoupled and in control; intervals.icu/Zwift could change.
27. **intervals.icu is OUTPUT-only — activity ingestion stays DIRECT from Garmin.** *Why:* Garmin direct is richer (Performance Condition, Stamina); routing ingestion via intervals.icu would be a lossy middleman.
28. **Deterministic `.ZWO` export demoted to a no-dependency FALLBACK** (relay is primary). *Why:* the relay removes the manual step entirely; .ZWO stays as the always-works backup if intervals.icu is unavailable.
29. **Any write to his trainer is propose → he approves → push — never silent.** *Why:* he values control ("mould it, fix errors"); consistent with refine-then-lock (#16).
30. **Closed-loop coaching is now possible** (sense→decide→ACT). v2 elevated: on an Amber morning or a dynamic week-restructure, the app can regenerate the adjusted workout and (on approval) deliver it to Zwift — coaching becomes *executable*, not just advisory.
31. **Lead-time requirement softened.** He no longer hand-builds in Zwift, so "lead time" = the app auto-pushes workouts a couple of days ahead. Still surface the week-ahead in the UI. *Why:* delivery is now the app's job, not his.
32. **Cadence on Zwift repeated-interval (`IntervalsT`) blocks gets Zwift DEFAULTS (100 work / 90 rest), not our value** — intervals.icu stores cadence correctly; Zwift overrides it on repeat blocks. Likely fix: emit cadence-critical reps as **individual steps** (unconfirmed — verify on PC Zwift, mobile can't copy-to-edit). *Why it's not a blocker:* Zwift cadence is advisory, and power/timing are exact; Phase-2 polish, and our deterministic generator controls emit format per workout.
33. **Rønnestad 30/15 endorsed as a VO2 progression** of his Tue VO2 day (build weeks, ~Wk7+, **ERG off** due to 30s-surge lag, even-paced ~105–110% FTP / 15s easy). *Why:* best-evidenced VO2max protocol, age-appropriate; aligns with Copilot's move to 30/30 & 40/20. Feed into the plan generator + KB.

### 2026-06-20 — Phase 0b (hosting)
34. **Single Supabase project for both movie app and garmin-coach, isolated by schema.** Movie app uses `public`; garmin-coach uses `coach`. Free tier allows only 2 active projects; this avoids using a second slot. *Why:* trivial for a 1-2 user private app where schemas don't conflict; Alembic targets `coach` via `version_table_schema="coach"` and `SET search_path TO coach, public`.
35. **Supabase session-mode pooler (port 5432), not transaction mode (port 6543).** Railway containers are IPv6-only; Supabase's direct host (`db.*.supabase.co:5432`) is IPv4-only → "Network is unreachable". Supabase Supavisor pooler (`aws-1-eu-north-1.pooler.supabase.com`) is dual-stack. Session mode chosen over transaction mode because asyncpg creates named prepared statements (`__asyncpg_stmt_N__`) that conflict across pooler connections in transaction mode. *Why not transaction mode:* setting `prepared_statement_cache_size=0` disables asyncpg's local cache but doesn't stop it emitting `PREPARE` on the server; two connections sharing a backend get duplicate-name errors. Session mode maps 1:1 to a PG backend for the connection lifetime — prepared statements persist correctly.
36. **Vercel `vercel.json` at repo root (not `apps/web/`).** Vercel's monorepo auto-detection picks `vercel.json` from root; placing it in `apps/web/` caused `@coach/shared: workspace:*` to fail (Vercel used npm, not pnpm). Root config sets `buildCommand: "pnpm --dir apps/web build"` + `installCommand: "pnpm install --frozen-lockfile"`. *Why:* pnpm workspaces require pnpm; only root-level `vercel.json` lets us override the install command.
37. **Railway NOT connected to GitHub auto-deploy (deliberate for now).** Deploying via `railway up` (builds from local source and uploads). Connect to GitHub in Railway dashboard Settings > Source Repo when continuous deployment is wanted. *Why deferred:* faster to ship; auto-deploy can be wired once Phase 1 is stable.
38. **Alembic migration engine needs `prepared_statement_cache_size=0` when using transaction-mode pooler.** The app engine in `database.py` had this; the `_run_async_migrations()` engine in `migrations/env.py` did not — causing startup to crash before uvicorn even started. Fixed in commit 189527b. Moot in session mode but kept as defensive belt-and-suspenders.
39. **GitHub auto-deploy is ON for Railway + Vercel, superseding #37.** Railway service `api` is connected to `CraigR973/garmin-coach` on branch `main`; Vercel project `garmin-coach` is connected to the same repo with production branch `main` and Git deployments enabled. Vercel creates PR/branch previews; Railway stays main-only. *Why:* restores the staging story assumed by #18 (Vercel previews before merge) and removes manual `railway up` / `vercel --prod` as the normal path. Preview deploys still proxy `/api/*` to the production Railway API/DB, so previews are for visual review unless a separate backend environment is added later.

### 2026-06-20 — Phase 1 prep
40. **Codex has no shared project-level custom-prompt path to rely on.** Current OpenAI docs say Codex custom prompts are deprecated and loaded from the user-level `~/.codex/prompts`, while project `.codex/` layers cover config/hooks/rules. This repo keeps reviewable Codex wrapper sources in `.codex/prompts/`, but they must be copied or symlinked into `~/.codex/prompts/` to be invokable. *Why:* keeps the cross-tool procedures in-repo without pretending Codex will auto-load a project prompt folder that the official docs do not promise.

### 2026-06-20 — Phase 1 Batch 1
41. **`profiles` remains the private user table for v1, instead of renaming it to `users`.** Batch 1 extends `profiles` with Garmin/Hive/location metadata and adds the v1 coaching tables around it. *Why:* the stripped auth skeleton, refresh tokens, notification preferences, audit log, and live migration `001` already depend on `profiles`; renaming a live auth table during the data-model batch would add deployment risk without improving the product. The product/API can still describe these rows as users.

### 2026-06-20 — Phase 1 Batch 2
42. **Garmin credentials stay in environment/secrets; Postgres stores only non-secret user metadata.** The app logs into `garminconnect` with `GARMIN_EMAIL` / `GARMIN_PASSWORD` and persists Garmin's own garth token cache under `GARMIN_TOKENSTORE` (default `~/.garminconnect`). *Why:* v1 has 1-2 private users and no admin secret-management UI yet; this keeps credentials out of the repo, DB rows, logs, and tests while preserving unattended sync through Garmin's long-lived token cache.

### 2026-06-20 — Phase 1 Batch 3
43. **`weather_daily` stores explicit overnight wind max/gust columns, not only raw Open-Meteo JSON.** *Why:* sleep disruption depends on overnight environment, and Batch 3's acceptance criteria require overnight low/wind to be first-class queryable context for later morning analysis and thermal monitoring.

### 2026-06-20 — Phase 1 Batch 4
44. **Backfilled morning-analysis baselines live in a dedicated `metric_baselines` table, not ad-hoc JSON on `profiles` or recalculation-only code.** The 84-night spreadsheet importer upserts historical `sleep` + `daily_metrics` rows and then persists reproducible summary stats per metric (mean/median/quartiles/range/stddev) with the source window recorded. *Why:* Batch 6 needs inspectable, queryable baseline helpers, and storing them separately keeps the import rerunnable, the provenance explicit, and future baseline recomputes/admin refreshes simple.
45. **SpO2 and HRV baselines exclude spreadsheet rows before 2026-06-11, while the raw backfill still imports the full 84 nights.** *Why:* Mark's documented data-quality rule says strap-tightening on 11 Jun is the reliability boundary for those metrics; preserving all source rows keeps history intact, but baseline comparisons should not normalize against known-bad physiology data.

### 2026-06-20 — Phase 1 Batch 5
46. **The retained handover context is seeded lazily through an admin-only coaching-state API, then edited through versioned `knowledge_base` and `planned_workouts` records rather than hardcoded frontend defaults.** The first load of `/api/v1/admin/coaching-state` seeds the spec-backed knowledge-base sections plus a 13-week 2121 plan map and workout slate if the user has no retained state yet; subsequent edits create new versions and keep prior rows for audit/history. *Why:* Batch 5 needed a real, inspectable source of truth for the morning engine without introducing a one-off seed script or making the UI depend on bundle-local defaults. Lazy seeding keeps setup friction low for the private single-admin flow while preserving durable backend-owned state.

### 2026-06-20 — Phase 1 Batch 6
47. **Morning analysis uses a thin Anthropic Messages HTTP boundary with explicit prompt/version metadata, not an SDK wrapper or hidden prompt.** `MorningAnalysisService` assembles a stored context packet, stores `prompt_version`, `model_name`, raw response, verdict, and markdown in `analyses`, and the model/key/max-token settings come from environment variables. *Why:* this keeps the Claude call inspectable and fakeable in tests, avoids adding another runtime dependency, and preserves the packet that explains every daily verdict.

### 2026-06-20 — Phase 1 Batch 7
48. **Daily-loop adherence lives on `manual_entries`, linked to the active `planned_workouts` row and its version, instead of mutating the plan row itself or adding a separate table.** Manual check-ins still use `manual_entries` rows with no workout link; adherence rows set `planned_workout_id`, `planned_workout_version`, `adherence_status`, and `actual_workout_json`. *Why:* Batch 7 needed phone-friendly "did he do it / what changed?" capture tied to the exact planned version without overwriting the plan history. Reusing `manual_entries` keeps the schema small and lets later analyses read both subjective check-ins and adherence notes from one source of truth.

### 2026-06-20 — Phase 1 Batch 8
49. **Post-workout analysis reuses the `analyses` table with `analysis_type='post_workout'` and `activity_id`, and surfaces recent outputs on the daily dashboard rather than a separate page.** The hourly Garmin poll syncs recent activities, then generates at most one ride analysis per activity; the stored context packet includes activity summary, FTP-based power zones, time-series channels, plan context, and the morning verdict. *Why:* `analyses.activity_id` already existed for this boundary, so a new table would duplicate storage; the daily dashboard is where Mark already checks verdicts/adherence, so recovery protocol and tomorrow impact belong there for the v1 phone workflow.

### 2026-06-20 — Phase 1 Batch 9
50. **Notification nudges and alerts use `analyses` as the audit/idempotency log instead of a new table.** Evening sleep-protocol nudges, thermal alerts, and stale-source alerts write non-Claude rows with `analysis_type` values `evening_nudge`, `thermal_alert`, and `stale_source_alert`, a notification rule version, the push tag, and `sentCount`. *Why:* the app already needs date-scoped generated outputs with context packets and dedupe checks; reusing `analyses` keeps Batch 9 schema-free while preserving inspectable evidence for why a nudge did or did not send.

### 2026-06-21 — Phase 2 Batch 11
51. **`TokenResponse.player` and `PlayerInfo` schema class names kept unchanged during the player→user rename.** The Python internals (`get_current_user`, `CurrentUser`, etc.) were all renamed, but the JSON response key `player` and the Pydantic class `PlayerInfo` stay as-is. *Why:* the frontend `AuthContext.tsx` reads `data.player.id`, `data.player.display_name`, `data.player.role`, `data.player.timezone` — changing the wire-format key would break the live app without a coordinated frontend + backend deploy.
52. **`ActorType.player` and `ActionType.player_pin_reset` enum values left unchanged.** These are values stored in Postgres enum columns. *Why:* renaming stored enum values requires a DB-level `ALTER TYPE … RENAME VALUE` migration plus potentially backfilling existing rows — disproportionate risk for cosmetic renaming. They will remain as-is unless a substantive schema migration is needed for another reason.
53. **`login_key` rate-limit in `rate_limit.py` fixed to read `display_name` instead of `email`.** This was a pre-existing bug introduced when auth was ported from the WC2026 app (which used email login). *Why:* the Garmin Coach login endpoint uses `display_name` as the login identifier (Decision #20); the old `email` key lookup would have silently failed with `None` and produced a useless rate-limit key. Caught incidentally during the player→user rename pass.

### 2026-06-21 — Phase 2 Batch 12
54. **Zwift delivery approval state lives in `workout_delivery_proposals`, not on `planned_workouts`.** A proposal snapshots the planned workout version, structured workout IR, intervals.icu calendar payload, deterministic `.ZWO` XML, status, approval timestamp, and pushed intervals.icu event id. *Why:* `planned_workouts` remains the owned plan/history source of truth, while delivery is an explicit propose → approve → push workflow with a durable audit trail and no silent trainer writes (Decision #29).
55. **Cadence-critical workout output is flattened into individual steps.** The Batch 12 rail deliberately avoids `IntervalsT`/repeat-block emission in both intervals.icu text and `.ZWO` fallback output. *Why:* validated power and timing were exact, but Zwift overrides cadence on repeated-interval blocks (Decision #32); flat steps preserve our cadence intent until PC Zwift verification proves otherwise.
