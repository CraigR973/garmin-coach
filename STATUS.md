# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** 2 in progress — Batch 12 (Zwift delivery rail) started on branch
`feat/batch-12-zwift-delivery-rail`. The backend delivery rail is implemented
locally with migration `007`, but Batch 12 is **not ready for closeout** until
the production daily-loop gate is fixed and strict smoke passes.

**Live endpoints:**
- Frontend: https://garmin-coach-one.vercel.app (Vercel, auto-deploy from GitHub `main`; `~/.local/bin/vercel --prod` is break-glass)
- Backend: https://api-production-e2bc7.up.railway.app/api/v1/health (currently reports SHA `ee54fd5`)
- DB: Supabase project `pzqmswvozjnkxbqqowuj` (eu-north-1), `coach` schema, migrations 001-006 applied; migration 007 is pending on the Batch 12 branch

**Hosting identifiers (non-secret):**
- GitHub repo: https://github.com/CraigR973/garmin-coach (private)
- Supabase project ref: `pzqmswvozjnkxbqqowuj` (shared with movie app via `coach` schema isolation)
- Railway project: `d43542f3-5165-420d-a14d-298832d23904`, service `api`
- Vercel project: `garmin-coach` (`garmin-coach-one.vercel.app`)
- DB connection: Supabase session-mode pooler `aws-1-eu-north-1.pooler.supabase.com:5432`

**Next:** Fix the two remaining production daily-loop blockers before Batch 12
review/`/closeout`: seed a reusable Garmin garth token cache or persistent
Railway tokenstore so daily metrics/sleep can sync without MFA, and add
Anthropic API credits (or swap to a funded key). Then rerun the strict smoke:
`API_URL=https://api-production-e2bc7.up.railway.app SMOKE_DISPLAY_NAME=Mark SMOKE_PIN=<real-pin> SMOKE_STRICT_DAILY_LOOP=1 python3 scripts/smoke_daily_loop.py`.
Only after that passes should Batch 12 be pushed/reviewed for `/closeout`.

## Gotchas
- Python is **3.12** (`~/.local/bin/python3.12`); api venv at `apps/api/.venv`.
- Node.js: use `~/.nvm/versions/node/v20.20.2/bin/node` + pnpm (system node v14).
- `TokenResponse.player` and `PlayerInfo` schema class names in `routers/auth.py` are intentionally kept unchanged — the frontend `AuthContext.tsx` reads `data.player.*` and changing the field names would break the auth flow.
- `ActorType.player` and `ActionType.player_pin_reset` enum values in `models/notification.py` are intentionally unchanged — they are stored DB enum strings; renaming would require a DB enum migration + data migration.
- DB Postgres enum type `player_role` (for the `role` column on `profiles`) is unchanged — only the Python class was renamed to `UserRole`. The `Enum(UserRole, name="player_role", create_type=False)` constructor keeps the DB type name.
- Pre-existing mypy error: `pyhiveapi import-not-found` in `services/environment_sync.py:107` — not introduced by Batch 11; no `type: ignore` covers it because mypy doesn't infer `import-not-found` from a bare comment.
- Railway service `api` is connected to GitHub `CraigR973/garmin-coach`, branch `main`. Push to `main` deploys production backend; `railway up --service api` is break-glass.
- Vercel project `garmin-coach` is connected to GitHub `CraigR973/garmin-coach`, production branch `main`, Node `20.x`. Push to `main` deploys production frontend; PR/branch pushes create previews.
- Production web API wiring is intentionally same-origin: `VITE_API_URL=""`, calls go to `/api/*`, and root `vercel.json` rewrites to Railway. Do not set it to the Railway URL unless deliberately switching to cross-origin.
- Vercel previews currently proxy `/api/*` to the production Railway API/DB, so use previews for visual review and avoid mutating real data there.
- Supabase pooler: **session mode (port 5432)** only — asyncpg named prepared statements conflict in transaction mode (port 6543).
- Admin profiles must be seeded directly in DB (no signup endpoint by design — Decision #21).
- Mark seed helper is
  `MARK_PIN=1234 PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m src.seeds`
  after migration `003` is applied; replace `1234` with the real PIN and never commit it.
- 2026-06-21 production smoke found API/auth/daily-loop live for Mark, but the
  real daily data loop was empty. Railway production now has the expected
  Garmin, Hive, Anthropic, Supabase service, and intervals vars plus
  `ENVIRONMENT=production`; the remaining blockers are Garmin token/MFA and
  Anthropic API credits. Confirm today's daily-loop payload has non-null Garmin
  metrics/sleep, `morningAnalysis`, Hive thermal values, and weather before
  Batch 12 review.
- Batch 12 adds `INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID` (default `i618709`),
  and `INTERVALS_BASE_URL` for the output-only intervals.icu rail. Missing
  `INTERVALS_API_KEY` makes push return 503; proposal and `.ZWO` export still work.
- Railway CLI auth is valid again as of 2026-06-21. Non-secret production vars
  set with `--skip-deploys`: `GARMIN_TOKENSTORE=/app/.garminconnect`,
  `INTERVALS_ATHLETE_ID=i618709`, and
  `INTERVALS_BASE_URL=https://intervals.icu/api/v1`.
- Garmin sync uses `GARMIN_EMAIL` / `GARMIN_PASSWORD` from the environment plus
  `GARMIN_TOKENSTORE` for garth's persisted token cache; the app does not store
  Garmin secrets in Postgres.
- Batch 4 one-shot import command is
  `PYTHONPATH=/Users/craigrobinson/garmin-coach/apps/api /Users/craigrobinson/garmin-coach/apps/api/.venv/bin/python -m src.sleep_history_backfill --dry-run "/Users/craigrobinson/Downloads/Dad Fitness/12 Weeks Sleep Data 15.06.26.xlsx"`
  then rerun without `--dry-run` to write the backfill.
- Batch 5 adds an admin-only retained-state editor at `/coach-state`; its first load seeds the knowledge-base sections plus a 13-week 2121 workout slate if the user has no existing retained state yet.
- Batch 6 adds the morning analysis engine. It requires `ANTHROPIC_API_KEY`
  for live generation; `ANTHROPIC_MODEL` defaults to `claude-sonnet-4-6`.
  The 06:30 weather sync triggers analysis after weather data lands, but logs
  per-profile analysis failures without failing the whole weather job.
- Batch 8 adds the post-workout analysis engine. The hourly Garmin activity poll
  syncs recent activities and triggers ride analyses once per activity; live
  generation uses the same `ANTHROPIC_API_KEY` / model settings as morning
  analysis. Strength sessions remain excluded from recovery decisions.
- Batch 9 adds notification-backed evening nudges and alerts. `analyses` now
  stores non-Claude notification audit rows with `analysis_type` values
  `evening_nudge`, `thermal_alert`, and `stale_source_alert`; `sentCount=0`
  can mean muted/quiet-hours/no subscription/no VAPID, not necessarily a rule
  failure.

## Log
- **2026-06-21** — Rechecked Batch 12 production gate after the Railway secrets
  were added. Masked env audit shows `ENVIRONMENT=production` plus Garmin, Hive,
  Anthropic, Supabase service, and intervals vars present; API health reports
  SHA `ee54fd5`. Hive/weather one-off run completed (`profiles=1`,
  `readings=1`, `days=9`), but morning analysis failed because Anthropic
  returned HTTP 400 `credit balance is too low`, and Garmin daily sync is still
  blocked by an empty `/app/.garminconnect` tokenstore: fresh login hit Garmin
  429/MFA in the non-interactive run and no reusable local garth token cache was
  found under the expected home/spike paths. DB snapshot for Mark still shows no
  2026-06-21 daily metrics, sleep, or morning analysis, so the strict
  daily-loop gate is not passed yet.
- **2026-06-21** — Railway CLI re-auth completed via browserless device code.
  Set safe non-secret production defaults with `--skip-deploys`:
  `GARMIN_TOKENSTORE=/app/.garminconnect`, `INTERVALS_ATHLETE_ID=i618709`, and
  `INTERVALS_BASE_URL=https://intervals.icu/api/v1`. Masked production env audit
  now shows these remaining missing values: `ENVIRONMENT`, `GARMIN_EMAIL`,
  `GARMIN_PASSWORD`, `HIVE_EMAIL`, `HIVE_PASSWORD`, `ANTHROPIC_API_KEY`,
  `SUPABASE_SERVICE_KEY`, and `INTERVALS_API_KEY`. Do not set
  `ENVIRONMENT=production` until `SUPABASE_SERVICE_KEY` is present because the
  production settings validator will reject startup without it.
- **2026-06-21** — Batch 12 started on
  `feat/batch-12-zwift-delivery-rail`: added migration `007` and
  `workout_delivery_proposals` to snapshot planned workout version, structured
  IR, intervals.icu payload, deterministic `.ZWO`, approval state, and pushed
  event id; added `/api/v1/workout-delivery` propose/list/approve/push/ZWO
  endpoints; added output-only intervals.icu client config; converted bike
  `planned_workouts` into flat cadence-safe delivery steps; added strict
  daily-loop smoke checks and runbook/env docs. Local verification: backend
  pytest `102 passed, 11 skipped`; ruff check clean; mypy clean; Alembic head is
  `007` when run with UTF-8 locale. Production gate is still blocked: Railway CLI
  token refresh failed with `invalid_grant`, and the masked variable audit before
  token failure showed missing `ENVIRONMENT`, Garmin, Hive, Anthropic, intervals,
  and Supabase service vars.
- **2026-06-21** — Baked the production daily-loop smoke findings into Phase 2
  planning. The live Railway API served SHA `72a84b4`, Mark could log in after
  direct seed, and `/api/v1/daily-loop` returned `subjectDate=2026-06-21`, but
  Garmin daily metrics/sleep, morning analysis, Hive thermal values, weather,
  and analysis rows were all empty; the first post-seed Hive poll logged
  `hive temperature poll failed`; Railway was missing the expected Garmin/Hive/
  Anthropic vars and logged `environment="development"`. `docs/phase-batches.md`
  now treats this as Batch 12 phase `12.0` and as a hard production gate before
  substantive Zwift delivery work.
- **2026-06-21** — Phase 2 Batch 11 closed out: merged PR #5
  `claude/batch-start-11-2l9lof` to `main` (merge commit `652723b`), GitHub CI
  run #66 passed (`conclusion: success`). All 5 jobs green: ruff, mypy, alembic
  upgrade+downgrade (migration 006 `if_exists=True` fix required after first
  push), pytest, web build. Railway auto-deploys migration 006 on startup.
- **2026-06-21** — Phase 2 Batch 11 implementation complete on
  `claude/batch-start-11-2l9lof`: (11.1) replaced broken ForgotPin email-form
  with static "Contact Craig" card; (11.2) deleted dead `services/email.py` and
  removed `resend_api_key`/`email_from` config fields + `.env.example` entries;
  (11.3) renamed WC2026 "player" internals — `PlayerRole`→`UserRole`,
  `get_current_player`→`get_current_user`, `CurrentPlayer`→`CurrentUser`,
  `AdminPlayer`→`AdminUser` in auth; `player_id`→`user_id` columns in
  `push_subscriptions`, `notification_preferences`, `refresh_tokens` via
  Alembic migration `006`; `"Player not found"` HTTP detail strings updated;
  fixed pre-existing `login_key` bug in `rate_limit.py` (was reading `email`
  from request body; login uses `display_name`); (11.4) fixed `score-input.tsx`
  JSDoc from "predictions/match-detail" to "score/check-in input". Backend: 96
  tests passed, ruff clean, mypy 1 pre-existing error only. Frontend: vite build
  + vitest 2/2 passed.
- **2026-06-21** — Phase 2 planning session: decomposed the `ARCHITECTURE.md`
  §6 v2 roadmap (and Decisions #25–33) into Batches 11–17, appended as the
  `## v2 batch plan` section in `docs/phase-batches.md` (all rows `Planned`).
  Sequencing: Batch 11 clears the Phase 1 retrospective tech debt first — chiefly
  the WC2026 "player"→user rename, which gets more expensive per added endpoint —
  then Batch 12 (Zwift delivery rail) lands as the foundational dependency for
  executable coaching (13), dynamic restructuring + Rønnestad 30/15 (14), holiday
  pause/resume (15), app-generated 13-week blocks (16), and monitoring/insight
  (17). v2's "real-time evening thermal alerts" roadmap item is already covered by
  the shipped Batch 9, so no separate batch. Docs-only change; no code touched.
- **2026-06-21** — Phase 1 Batch 10 closed out: merged PR #3
  `claude/batch-start-config-bz2y11` to `main` (merge commit `8c47869`), GitHub
  CI run #60 passed (`conclusion: success`). Batch 10 delivered: non-mutating
  smoke script (`scripts/smoke_daily_loop.py`) with 10 unit tests; full
  observability runbook (`docs/runbooks/sync-and-analysis.md`); security pass —
  removed dead email-verify token helpers from `auth.py`, added
  `Permissions-Policy` header with middleware tests; PWA polish — daily-loop
  `NetworkFirst` SW caching and offline stale-data banner in the dashboard.
  96 backend tests pass, ruff/mypy clean, vite build succeeds. All 10 Phase 1
  batches are now shipped; v1 is live for daily use.
- **2026-06-20** — Phase 1 Batch 10 implementation ready on
  `claude/batch-start-config-bz2y11`: added non-mutating smoke script
  (`scripts/smoke_daily_loop.py`) with testable parser helpers and unit tests;
  new `docs/runbooks/sync-and-analysis.md` covering per-job log events, failure
  modes, and recovery for all six scheduler jobs; security pass — removed dead
  `create_email_verify_token`/`decode_email_verify_token` from `auth.py`, added
  `Permissions-Policy` header restricting camera/microphone/geolocation with
  middleware tests; PWA polish — daily-loop NetworkFirst SW caching (24 h offline
  fallback) and offline stale-data notice in the dashboard. Verified backend
  `pytest` (96 pass, 10 DB-skipped), `ruff check`, `ruff format --check`, and
  `mypy src`; frontend `vitest`, `eslint` (pre-existing fast-refresh warnings
  only), and `vite build`.
- **2026-06-20** — Phase 1 Batch 9 closed out: fast-forwarded
  `feat/batch-9-nudges-thermal-monitoring` to `main`, GitHub CI passed on commit
  `7a9e4ec`, Railway deployed the backend and `/api/v1/health` reported SHA
  `7a9e4ecc49e39cad3cecaf0ce1c04dfebe0cff73`, Vercel production returned
  `HTTP 200`, and the same-origin `/api/v1/health` rewrite returned the same
  SHA. Batch 9's non-mutating smoke check confirmed the `/api/v1/notifications/preferences`
  endpoint is live (PWA terminology cleanup) and the deployed SHA matches.
  Scheduler-only features (evening nudge, thermal monitoring, stale-source alerts)
  are validated by CI tests; `sentCount=0` is expected until live VAPID keys and
  user subscriptions are in place. Batch 9 marked shipped; next up is Batch 10
  hardening + release polish.
- **2026-06-20** — Phase 1 Batch 9 implementation ready on
  `feat/batch-9-nudges-thermal-monitoring`: added a 20:00 local sleep-protocol
  nudge, evening thermal/source monitoring scheduler, notification event
  idempotency/audit storage in `analyses`, timezone-aware quiet-hours delivery,
  thermal rules for pre-cool/seal/>19.5-20C thresholds, distinct stale-source
  alerts for Garmin/Hive/weather, and PWA notification terminology cleanup.
  Verified backend `pytest` (DB-backed tests skipped without `DATABASE_URL`),
  `ruff check`, `ruff format --check`, and `mypy src`; frontend `vitest`, `eslint` (existing
  fast-refresh warnings only), and `vite build`.
- **2026-06-20** — Phase 1 Batch 8 closed out: fast-forwarded
  `feat/batch-8-post-workout-analysis` to `main`, fixed the branch CI mypy
  portability issue in commit `f202093`, and GitHub CI passed on `main` run
  `27886013267`. Railway deployed the backend and `/api/v1/health` reported
  SHA `f202093d195746937f207180feb1b963450b204d`; Vercel production returned
  `HTTP 200`; the same-origin `/api/v1/health` rewrite returned the same SHA;
  and the protected `/api/v1/daily-loop` endpoint returned `401` without
  credentials. Batch 8's non-mutating production smoke check passed by
  confirming the deployed OpenAPI exposes `postWorkoutAnalyses` and
  `PostWorkoutAnalysisOut`. Batch 8 marked shipped; next up is Batch 9 nudges
  + thermal monitoring.
- **2026-06-20** — Phase 1 Batch 8 implementation ready on
  `feat/batch-8-post-workout-analysis`: added an hourly Garmin activity poll,
  idempotent post-workout ride analysis generation stored in `analyses` against
  `activity_id`, context packets covering activity summary, FTP-based power
  zones, HR/cadence/respiration, Performance Condition, Stamina, Training
  Effect, the active plan, and the morning verdict, plus daily-dashboard
  surfacing for recovery protocol and tomorrow impact. Strength/wrist-HR
  activities are excluded from recovery decisions. Verified backend `pytest`
  (DB-backed tests skipped without `DATABASE_URL`), `ruff check`, and
  `mypy src`; shared `vitest` + `tsc`; frontend `vitest`, `eslint` (existing
  warnings only), and `vite build`.
- **2026-06-20** — Phase 1 Batch 7 closed out: fast-forwarded
  `feat/batch-7-daily-app-loop-surfaces` to `main`, GitHub CI passed on commit
  `cb65532`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 7's non-mutating
  production smoke check passed by confirming the shipped OpenAPI exposes the
  new `/api/v1/daily-loop`, manual-entry, and adherence routes, and the live
  protected `/api/v1/daily-loop` endpoint returned `401` without credentials.
  Batch 7 marked shipped; next up is Batch 8 post-workout analysis.
- **2026-06-20** — Phase 1 Batch 7 implementation ready on
  `feat/batch-7-daily-app-loop-surfaces`: added a player-facing
  `/api/v1/daily-loop` envelope API for today's verdict, metrics, plan,
  thermal state, manual check-in, adherence capture, and data-quality
  guardrails; stored adherence on `manual_entries` linked to the planned
  workout/version via migration `005`; and replaced the placeholder dashboard
  with the phone-first daily loop UI plus targeted backend/frontend tests.
  Verified backend `pytest` (DB-backed tests skipped without `DATABASE_URL`),
  `ruff check`, and targeted `mypy` on the new daily-loop files; full
  `mypy src` in this shell still reports the existing untyped third-party
  imports for `garminconnect` and `pyhiveapi`. Verified shared `vitest` +
  `tsc`; frontend `vitest`, `eslint` (existing warnings only), and `vite build`.
- **2026-06-20** — Phase 1 Batch 6 closed out: fast-forwarded
  `feat/batch-6-morning-analysis-engine` to `main`, GitHub CI passed on commit
  `9be8b40`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 6's non-mutating
  production smoke check passed by confirming the deployed backend SHA plus CI's
  Postgres-backed packet assembly/storage/verdict coverage for the morning
  analysis engine. Batch 6 marked shipped; next up is Batch 7 daily app loop
  surfaces.
- **2026-06-20** — Phase 1 Batch 6 implementation ready on
  `feat/batch-6-morning-analysis-engine`: added the morning analysis packet
  assembler from active KB, daily/sleep/manual/environment/baseline/plan data;
  encoded the Green/Amber/Red verdict framework including Red-never-VO2 and
  guarded Low-readiness reconciliation; added a thin Anthropic Messages boundary
  with prompt/version metadata stored in `analyses`; and wired the 06:30 local
  weather sync to trigger morning analysis. Verified backend `pytest`,
  `ruff check`, and `mypy src` locally; DB-backed tests skipped without
  `DATABASE_URL`.
- **2026-06-20** — Phase 1 Batch 5 closed out: fast-forwarded
  `feat/batch-5-training-plan-kb` to `main`, GitHub CI passed on commit
  `82015cd`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 5's non-mutating
  production smoke check passed by confirming the deployed OpenAPI exposes the
  new `/api/v1/admin/coaching-state`, knowledge-base, and planned-workout
  override routes. Batch 5 marked shipped; next up is Batch 6 morning analysis
  engine.
- **2026-06-20** — Phase 1 Batch 5 implementation ready on
  `feat/batch-5-training-plan-kb`: added an admin-only `/api/v1/admin/coaching-state`
  envelope API that lazily seeds the knowledge base and a 13-week 2121 plan,
  versioned knowledge-base edits plus per-day workout overrides, shared schemas
  for the retained-state payloads, and a new `/coach-state` internal editor UI
  with retained version history. Verified backend `pytest`, `ruff check`, and
  `mypy src`; shared `vitest` + `tsc`; frontend `eslint`, `vitest`, and `vite build`.
- **2026-06-20** — Phase 1 Batch 4 closed out: merged PR #2
  `feat/batch-4-backfill-baselines` to `main`, GitHub CI passed on merge commit
  `8f3a125`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 4's non-mutating
  smoke check passed by parsing the real `12 Weeks Sleep Data 15.06.26.xlsx`
  workbook on `main` (84 rows, 24 Mar-15 Jun window, expected SpO2/HRV
  reliability exclusions). Batch 4 marked shipped; next up is Batch 5 training
  plan + knowledge base.
- **2026-06-20** — Phase 1 Batch 4 implementation ready on
  `feat/batch-4-backfill-baselines`: added an admin-only XLSX backfill command
  for `12 Weeks Sleep Data 15.06.26.xlsx`, imported 84-night historical
  `sleep` + `daily_metrics` rows with rerun-safe dry-run/apply behavior,
  persisted queryable `metric_baselines` summaries for morning analysis, and
  excluded pre-2026-06-11 SpO2/HRV rows from baseline calculations per the
  existing data-quality rule. Verified backend `pytest`, `ruff check`, and
  `mypy src` locally.
- **2026-06-20** — Phase 1 Batch 3 closed out: merged PR #1
  `feat/batch-3-hive-weather-syncs` to `main`, GitHub CI passed on merge commit
  `7f06d1f`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production returned `HTTP 200`, and the same-origin
  `/api/v1/health` rewrite returned the deployed SHA. Batch 3 marked shipped;
  next up is Batch 4 84-night backfill + baselines.
- **2026-06-20** — Phase 1 Batch 3 implementation ready on
  `feat/batch-3-hive-weather-syncs`: added Hive `pyhiveapi` re-login wrapper,
  real-fixture Hive temperature parsing/upserts, Open-Meteo Kilmarnock daily +
  overnight weather parsing/upserts, overnight wind columns, and scheduler jobs
  for 15-minute Hive polling plus 06:30 Europe/London weather sync. Verified
  backend pytest/ruff/mypy and shared package test/typecheck locally; DB-backed
  idempotency tests skipped without `DATABASE_URL`.
- **2026-06-20** — Phase 1 Batch 2 closed out: merged
  `feat/batch-2-garmin-sync-foundation` to `main`, GitHub CI passed on merge
  commit `8ab4e27`, Railway deployed the backend and `/api/v1/health` reported
  that SHA, and Vercel production returned `HTTP 200`. Batch 2 marked shipped;
  next up is Batch 3 Hive + weather syncs.
- **2026-06-20** — Phase 1 Batch 2 implementation ready on
  `feat/batch-2-garmin-sync-foundation`: added Garmin Connect client/login
  wrapper with token-cache strategy, Garmin fixture parsers, daily/sleep/activity
  sync upserts, time-series channel extraction for power/HR/cadence/respiration/
  Performance Condition/Stamina, and no-secret failure tests. Verified backend
  pytest/ruff/mypy locally; one Postgres idempotency test skipped without
  `DATABASE_URL`.
- **2026-06-20** — Phase 1 Batch 1 closed out: merged
  `feat/batch-1-data-model` to `main`, GitHub CI passed on merge commit
  `b2733ca`, Railway deployed the backend and `/api/v1/health` reported that
  SHA, Vercel production was Ready and the web URL loaded. Batch 1 marked
  shipped; next up is Batch 2 Garmin sync foundation.
- **2026-06-20** — Phase 1 Batch 1 implementation ready on
  `feat/batch-1-data-model`: added `002` v1 coaching schema, SQLAlchemy domain
  models, Mark profile seed helper, shared Zod/TS schemas, data-shape audit, and
  tests. Verified backend pytest/ruff/mypy plus shared package test/typecheck.
- **2026-06-20** — Phase 1 prep complete: added `docs/phase-batches.md`,
  tool-agnostic batch procedures, Claude wrappers, Codex prompt-source wrappers
  with the user-level `~/.codex/prompts` caveat, and fixed stop hooks to point at
  `garmin-coach` + `/closeout`.
- **2026-06-20** — Auto-deploy verified end-to-end on `main` before this handoff
  log commit: GitHub CI green on `05f3c71`; Railway auto-deployed it and
  `/api/v1/health` returned that SHA; Vercel production deploy was Ready.
  Incidental CI cleanup: formatted two API files and added typed `RESEND_API_KEY`
  / `EMAIL_FROM` settings defaults used by the email service.
- **2026-06-20** — Auto-deploy enabled after Craig approved the switch: Railway service
  `api` connected to GitHub `CraigR973/garmin-coach` branch `main`; Vercel project
  `garmin-coach` connected to the same repo with production branch `main`, Git
  deployments enabled, and Node pinned to `20.x`. Recorded DECISIONS #39.
- **2026-06-20** — Phase 0b deploy review follow-up: added fresh/ongoing deploy runbooks,
  fixed stale `.env.example` Supabase pooler guidance, ignored Supabase CLI scratch files,
  pinned Node to 20.x for Vercel, made production `VITE_API_URL=""` same-origin wiring
  explicit in code/config, and ticked Phase 0b complete in ARCHITECTURE. Auto-deploy remains
  a pending explicit decision; no Decision #39 recorded yet.
- **2026-06-20** — Phase 0b complete: GitHub repo created, Supabase `coach` schema live,
  Railway backend healthy, Vercel frontend live. Main connectivity blocker was Railway's
  IPv6-only networking vs Supabase's IPv4-only direct host; resolved via Supabase session-mode
  pooler (`aws-1-eu-north-1.pooler.supabase.com:5432`). See DECISIONS #34-38.
- **2026-06-19** — Zwift delivery validated end-to-end (app→intervals.icu→Zwift; power/timing exact, cadence nuance noted). Folded Zwift/intervals.icu relay, executable-coaching, Ronnestad 30/15 + softened lead-time into ARCHITECTURE.md §2/§6 + DECISIONS #25-33. (No code change — spec only.)
- **2026-06-19** — Phase 0a complete: stripped football domain from backend and
  frontend. 148 backend files changed (1041 ins / 48814 del); 161 frontend files
  changed (748 ins / 27045 del). Backend: 42 tests pass, ruff clean.
  Frontend: TypeScript passes, vite build succeeds.
- **2026-06-19** — Phase 0 started: seeded repo, wrote project docs, set up
  cross-tool structure, pruned WC cruft. Data sources validated via spikes.
