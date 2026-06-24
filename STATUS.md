# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Phase:** **v1→v3 roadmap complete** (every batch in `docs/phase-batches.md` is `Shipped`) → now in
post-roadmap operate/soak mode. **Done 2026-06-24: a full year of Garmin history backfilled into prod.**
A new resumable admin CLI — `apps/api/src/garmin_history_backfill.py` (PR #27, CI green) — walked
2025-06-24 → 2026-06-24 reusing the idempotent `GarminSyncService` and loaded a **gapless 366/366 days**
of daily metrics + sleep (non-null readiness 366, HRV 363, RHR 366, VO2max 179 sparse; 363 scored nights)
plus **673 activity summaries** straight into prod Supabase. That lit up the v3 long-horizon engines on
real data (verified directly against prod): `trends/seasonal?bucket=season` → **5 season windows**;
`trends/year-on-year` → a real **June-2026-vs-June-2025** comparison (sleep +8.3%, duration −10.7%,
readiness −13.9%) instead of `insufficient_history`, with HRV/SpO2 correctly suppressed before the #45
reliability cutoff (DECISIONS #85). **Next step:** merge PR #27; the operate/soak + auth Phase 3 path
below is otherwise unchanged.

**Gotchas (backfill):** summaries-only (`--no-activity-details`) — per-second time-series for the ~673
historical activities was deliberately skipped (volume + 429 cost); re-run without the flag for a date
window if deep per-ride analysis is ever needed. The CLI is resumable (per-day commit + skip-existing),
which proved essential: agent-sandbox background jobs get reaped at turn boundaries, yet the run reached
full coverage across several restarts. Garmin egress + the prod `GARMIN_TOKENSTORE_B64` work via
`railway run` from the dev box. Prod had ~no prior history before this (the 84-night xlsx backfill was
never applied to prod), so this is the first real history load. Hive indoor-temp history is un-backfillable
(no historical API) and intentionally absent.

---

**Roadmap completion record (v3):** **Batch 23 merged to `main` (PR #26, squash merge `ddc739f`, 2026-06-23)** —
auto-generated handover-doc export, the #13 capstone. CI green across all 6 jobs on the PR (ruff, mypy,
pytest, alembic, security-audit, web build) plus Vercel preview. **This was the final v3 batch — the whole
v1→v3 roadmap is now complete; every batch in `docs/phase-batches.md` is `Shipped`.** Batch 22 merged + live
(PR #25, `86205e5`); Batch 21 (PR #24, `1c8ad85`); Batch 20 (PR #23, `e1cd2cc`); Batch 19 (PR #21). All v2
batches + auth remediation are live. **Production smoke confirmed (2026-06-23, review session):** prod serves
the latest SHA (`e94ad7c`), web `/` → 200, and every V3 endpoint is live + 401 auth-gated — `handover`,
`handover/export`, `strength-brief`, `reviews/{weekly,monthly}`, `trends/{seasonal,year-on-year,narrative}`,
`experiments`. Full local suite also re-run green (see Log). **Authenticated prod E2E confirmed
(2026-06-23):** minted a one-time device token (revoked after) and hit every V3 GET endpoint — all 200 with
real data; graceful-degradation paths (`insufficient_history`, sample gates) fire correctly and the handover
export renders a real 3.2 KB doc. Only a browser UI click-through remains optional (local stack blocked — see Log).

**Verify (prod, Batch 23):** `/api/v1/health` SHA should be `ddc739f…`; web `/` → 200;
`GET /api/v1/handover` and `GET /api/v1/handover/export` → 401 unauthenticated (auth-gated, non-mutating),
and they appear in the deployed OpenAPI (dev/staging only — prod docs are disabled by design).

**Batch 23 shipped (auto-generated handover-doc export — 🔴 High, DECISIONS #84):**
- `services/handover.py`: deterministic `build_handover_packet` (pure, DB-free) composes the full retained
  state — KB (only the six known sections `profile`/`data_quality_rules`/`age_adjustment`/`sleep_protocol`/
  `training_plan`/`active_hypotheses`, in hand-doc order), current plan/block + upcoming active workouts,
  `metric_baselines`, the most recent weekly + monthly reviews (Batch 20), the seasonal year-on-year
  comparison (Batch 21, reused via `TrendsService`), experiments + their latest deterministic evaluation
  (Batch 22, reused via `ExperimentEvaluationService`), and the strength brief (Batch 19) — with the
  data-quality rules echoed under `dataQualityGuardrails`. `render_handover_markdown` (pure, no model)
  renders the portable markdown handover doc so the **export always works and faithfully reflects current
  state** (the #13 round-trip), surfacing L/R balance only as a rule. `HandoverService.run` polishes the doc
  through the **Batch 20 Anthropic boundary** (handover-specific system prompt), stored in `analyses` as
  `handover_export`, idempotent per day, fakeable without `ANTHROPIC_API_KEY`.
- `routers/handover.py`: `GET /api/v1/handover` previews packet + deterministic markdown + latest narrative
  and **never writes** (experiments listed with `seed=False` so a GET can't lazy-seed); `POST …/run`
  generates + records; `GET …/export` downloads the deterministic markdown as a `text/markdown` attachment.
  No migration, no new cron.
- Frontend: new `HandoverPage.tsx` + `/handover` route + TabBar "Handover" tab; `handoverEnvelopeSchema` in
  `@coach/shared`. Deterministic export preview, "Download .md" (client-side Blob, no extra round-trip), and
  "Generate narrative" wired to `/run`.
- Tests: 9 backend (`test_handover.py`) — pure packet composition + the faithful markdown render + the
  empty-state + L/R-balance-only-as-rule guards + DB-backed preview-never-writes / run-stores /
  idempotent-per-day — all green against a **real local Postgres**; 1 web vitest. Backend **296 passed**,
  ruff + mypy clean (61 files); shared typecheck + 7 tests; web lint 0 errors, 20 vitest (1 new), vite build
  (incl. `tsc`) OK.

**Batch 22 shipped (hypothesis evaluation — extends the Batch 17 tracker #72, DECISIONS #83):**
- `services/experiment_evaluation.py`: deterministic, advisory engine reusing the Batch 17 insights math
  (`_slope`/`pearson`/`compute_drivers`). Dispatches on the experiment `slug` to three pure DB-free
  evaluators — **gate** (collagen: consecutive age-adjusted-74+ night streak → gate met = `supported`),
  **correlation** (early_waking_0400: Pearson-rank overnight low °C / sleep-stress vs an `awake_sleep_sec`
  disruption proxy → strong = `supported`, none = `refuted`; alcohol/late-snack flagged as unmeasured),
  **group_compare** (recovery_week_disruption: recovery- vs build-week mean age-adjusted sleep from
  `plan_blocks.block_type` → recovery worse = `supported`). Each skips below its #71 sample gate (5 / 8 / 4
  per group). **Recommendation only — the engine and `/evaluate` never write status;** concluding stays the
  human-gated terminal `POST /…/status` action (#72). User experiments fall back to correlation when they
  declare `candidateDrivers`, else `no_evaluator`.
- `routers/experiments.py`: `GET /api/v1/experiments/{id}/evaluate` previews (never writes);
  `POST /api/v1/experiments/{id}/evaluate/run` records an `experiment_evaluation` audit row in `analyses`,
  idempotent per (experiment, subject date). `canConclude` is surfaced so the PWA only offers conclude when
  legal. No migration, no new cron.
- Frontend: new `ExperimentsPage.tsx` + `/experiments` route + TabBar "Tests" tab; `experimentListEnvelope`
  / `experimentEvaluationEnvelope` schemas in `@coach/shared`. Each card evaluates the evidence and offers
  "Conclude as <recommendation>" wired to the existing conclude path.
- Tests: 17 backend (`test_experiment_evaluation.py`) — pure recommendation mapping + sample gates, the
  never-auto-conclude guard, idempotent audit — all green against a **real local Postgres**; 1 web vitest.
  Backend **287 passed**, ruff + mypy clean (59 files); shared 7 tests; web lint 0 errors, 19 vitest, vite
  build (incl. `tsc`) OK.

> **Batches 21 + 22 are confirmed live.** This session's egress reached `*.railway.app` / `*.vercel.app`
> (no proxy 403), so the Batch 22 closeout verified production directly: `/api/v1/health` → `sha=86205e5`,
> web `/` → 200, the experiments + evaluate routes 401 auth-gated. Since Batch 22 sits on top of Batch 21
> on `main`, the Batch 21 deploy is implicitly confirmed too. If a future session's egress *does* block
> those hosts (as in the Batch 20 closeout), re-run the live checks manually.

**Batch 21 shipped (year-on-year & seasonal trends — 🔴 High, DECISIONS #82):**
- `services/trends.py`: pure `compute_trend_windows` buckets daily history into comparable **month**
  (`2026-07`) / **season** (`2026-summer`, meteorological; Dec → next year's winter) windows with
  per-metric count/mean/median/min/max over 9 metrics (sleep score/duration, HRV, readiness, RHR,
  VO2 max, SpO2, indoor peak, outdoor overnight low). **SpO2/HRV reliability cutoff (#45)** applied in
  the aggregation — pre-2026-06-11 rows dropped from those 2 gated metrics only and surfaced as
  `excludedCount` (#44 provenance). `compute_year_on_year` does same-period-vs-prior-year deltas,
  needing ≥5 samples on *both* sides else `insufficient_history` (expected until ~Mar 2027).
  `TrendsService` thin DB wrapper. Optional narrative reuses the **Batch 20 Anthropic boundary**
  (`AnthropicReviewClient` gained a backward-compatible `system_prompt` override) → stored in
  `analyses` as `seasonal_trend`, idempotent per window (per-bucket `prompt_version` disambiguates
  month vs season at a shared start date). Insufficient history → reported deterministically, model
  never called. No migration, no new cron, human/API-triggered (#71).
- `routers/trends.py`: `GET /api/v1/trends/seasonal`, `/year-on-year`, `/narrative` (all preview,
  never write) + `POST /api/v1/trends/narrative/run` (generate+store). `bucket` ∈ {month, season},
  400 otherwise.
- Frontend: `TrendsPage.tsx` + `/trends` route + TabBar "Trends" tab; `trendsSeasonalEnvelopeSchema`
  / `trendsYearOnYearEnvelopeSchema` / `trendsNarrativeEnvelopeSchema` in `@coach/shared`.
- Tests: 14 backend (`test_trends.py`) all green against a **real local Postgres**; 2 web vitest.
  Backend **270 passed**, ruff + mypy clean (58 files); shared typecheck + 7 tests; web lint 0 errors,
  18 tests, vite build OK. CI on PR #24 green across all 6 jobs.

**Batch 20 shipped (weekly & monthly deep reviews — 🔴 High, DECISIONS #81):**
- `services/reviews.py`: deterministic `compute_review_rollup` (pure, DB-free) over sleep / recovery /
  load+adherence / verdicts / thermal; `ReviewService` reuses Batch 19 strength brief + Batch 17
  insights; thin Anthropic boundary (#47, fakeable) stores narrative in `analyses` as
  `weekly_review` / `monthly_review`. Calendar-aligned windows (ISO week / calendar month) →
  idempotent per period. No migration, no new cron, human/API-triggered (#71).
- `routers/reviews.py`: `GET /api/v1/reviews/{period}` (preview, never writes) + `POST
  /api/v1/reviews/{period}/run` (generate+store), `{period}` ∈ {weekly, monthly}, 404 otherwise.
- Frontend: `ReviewsPage.tsx` + `/reviews` route + TabBar "Reviews" tab; `reviewEnvelopeSchema` in
  `@coach/shared`.
- Tests: 14 backend (`test_reviews.py`) all green against a **real local Postgres**; 2 web vitest.
  Backend 256 passed, ruff + mypy clean; shared typecheck + 7 tests; web lint 0 errors, 16 tests,
  vite build OK. CI on PR #23 green across all 7 jobs.

**Batch 19 shipped + live:**
- `GET /api/v1/strength-brief` live, 401 unauthenticated (auth-gated — correct)
- `strengthBrief` field now present in `GET /api/v1/daily-loop` response
- Advisory-only: no verdict/recovery fields, no migration, no LLM, no new cron

**Local dev env note (this session):** fresh container had no `apps/api/.venv` — recreated it
(`python3.12 -m venv` + `pip install -r requirements*.txt`). DB-backed tests ran against a local
Postgres 16 cluster (`pg_ctlcluster 16 main start`; role/db `coach`/`garmin_coach_test`, schema
`coach`, `alembic upgrade head` → 008). None of this is committed; it's container-local scaffolding.

**Auth simplification context:** Phases 1 and 2 are live; Phase 3 (destructive PIN/JWT cleanup)
still pending after soak. See `docs/reviews/auth-simplification-plan.md`.

**Verified (prod, 2026-06-23):** `/api/v1/health` returns `sha=3737338`; web `/` 200;
`/api/v1/strength-brief` 401 (live and auth-gated). CI run #135 green on PR HEAD; 187 passed /
55 skipped; ruff + mypy clean.

**v3 batch plan:** Batches 19–23 in `docs/phase-batches.md`. Batches 19–21 `Shipped`; Batches 22–23
`Planned`. Batch 22 (hypothesis evaluation) is the next unshipped batch.

**Live endpoints:**
- Frontend: https://garmin-coach-one.vercel.app (Vercel, auto-deploy from GitHub `main`; `~/.local/bin/vercel --prod` is break-glass)
- Backend: https://api-production-e2bc7.up.railway.app/api/v1/health (Vercel/Railway auto-deploy from GitHub `main`; Git-backed again — `/health` reports the live commit SHA. `railway up --service api` is break-glass)
- DB: Supabase project `pzqmswvozjnkxbqqowuj` (eu-north-1), `coach` schema, migrations 001-008 applied (008 = device-token `purpose`/`used_at`, deployed with auth Phase 1)

**Hosting identifiers (non-secret):**
- GitHub repo: https://github.com/CraigR973/garmin-coach (private)
- Supabase project ref: `pzqmswvozjnkxbqqowuj` (shared with movie app via `coach` schema isolation)
- Railway project: `d43542f3-5165-420d-a14d-298832d23904`, service `api`
- Vercel project: `garmin-coach` (`garmin-coach-one.vercel.app`)
- DB connection: Supabase session-mode pooler `aws-1-eu-north-1.pooler.supabase.com:5432`

**Post-closeout follow-ups (not blocking Batch 16):**
1. Rotate Mark's production PIN away from the temporary smoke value (`1234`).
2. ~~Set `INTERVALS_API_KEY` in Railway so `auto_push_due` can actually deliver.~~
   **Done (2026-06-22):** `INTERVALS_API_KEY` is set in Railway (service `api`,
   production) alongside `INTERVALS_ATHLETE_ID=i618709` / `INTERVALS_BASE_URL`; the
   active deploy (`12e1ab82`, 2026-06-22 13:09) carries it. The delivery rail was
   smoke-verified against the **live** intervals.icu API: a throwaway script drove
   the real `build_structured_workout_ir → build_intervals_payload →
   IntervalsIcuClient.create_workout_event` path, intervals.icu created event
   `117784365`, and the script deleted it again (HTTP 200) — so the key, auth, and
   payload shape all work. Not yet exercised: a real production `auto_push_due`
   delivery (would write a real event to Mark's calendar).

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
- Historical note: the 2026-06-21 production smoke initially found API/auth/
  daily-loop live for Mark, but the real daily data loop was empty before Batch
  18's scheduler wiring shipped. That gap is now closed and shipped.
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
- Hive production auth now depends on `HIVE_TOKENSTORE_B64` because Mark's account
  uses AWS Cognito `SMS_MFA`; if the token blob is cleared or expires, reseed it
  with `scripts/bootstrap_hive_tokenstore.py` and Mark's phone.
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
- Batch 13 adds executable coaching. `analyses` now also stores delivery audit
  rows with `analysis_type` `workout_proposed` / `workout_pushed`. The new
  `workout_autopush` scheduler job (07/13/19 `Europe/London`) only pushes
  **already-approved** proposals within `today+2`; with `INTERVALS_API_KEY` unset
  the push returns 503 and proposals correctly stay `approved` (un-delivered) —
  Amber regeneration and approval still work without the key because they never
  call intervals.icu. Adjusted proposals are ordinary `workout_delivery_proposals`
  rows; their `structured_workout_ir.origin` is `amber_regeneration` /
  `red_substitution` and `structured_workout_ir.adjustment` records the cut.
- Batch 14 adds dynamic weekly restructuring. It is **human-triggered via
  `GET/POST /api/v1/restructure/*`, not a scheduler job** (DECISIONS #64) — there is
  no automatic weekly restructure cron by design. `apply_for_week` versions changed
  `planned_workouts` days and creates `proposed` `workout_delivery_proposals` with
  `structured_workout_ir.origin="weekly_restructure"`; they only reach Zwift via the
  existing approve→push rail. The VO2 progression now lives in
  `services/vo2_progression.py` — edit protocols/`RONNESTAD_FROM_WEEK` there, not
  inline in `coaching_state`. `analyses` now also stores `weekly_restructure` audit
  rows (`subject_date=week_start`).
- Batch 17 adds monitoring + insight. `analyses` now also stores
  `ftp_drift` / `early_warning` / `driver_correlation` audit rows (written only by
  `POST /api/v1/insights/run`, idempotent per `subject_date` — GET previews never write)
  and `experiment_update` rows. The insight engines are **deterministic and
  human/API-triggered, not a scheduler job** — there is no automatic insight cron by design
  (DECISIONS #71). FTP drift needs ≥4 rides with both power and HR in the window; driver
  correlations need ≥8 paired nights. Experiments lazy-seed the 3 standing hypotheses on the
  first `GET /api/v1/experiments`; a concluded experiment is terminal (no further status
  change or observations).

## Log
- **2026-06-24** — **Historical Garmin backfill → a full year of real data in prod.** Built a resumable
  admin CLI (`apps/api/src/garmin_history_backfill.py`, PR #27) that walks a date range reusing the
  idempotent `GarminSyncService` (per-day commit, `--skip-existing`, exponential backoff, `--throttle`,
  `--dry-run`, `--no-activity-details`); 7 pure + 3 DB-backed tests, ruff/mypy clean, PR CI green.
  Probed Garmin first (read-only, `~/garmin-spike/history_probe.py`) → confirmed a full year exists back
  to 2025-06-24 incl. real historical readiness; dry-ran 7 days through the prod path; then backfilled
  2025-06-24 → 2026-06-24 into prod Supabase: **366/366 days** daily metrics + sleep (readiness 366,
  HRV 363, RHR 366, VO2max 179 sparse; 363 scored nights) + **673 activity summaries**. Survived repeated
  background-job reaping via resumability. Verified the v3 engines against prod: `trends/seasonal` =
  **5 season windows**; `trends/year-on-year` computes **June-2026 vs June-2025** (sleep +8.3%, dur −10.7%,
  readiness −13.9%); HRV/SpO2 suppressed pre-#45 cutoff as designed. Found prod had ~no prior history (the
  84-night xlsx backfill was never applied to prod) — first real history load. DECISIONS #85. Next: merge
  PR #27. Throwaway probe/count/verify scripts live in `~/garmin-spike/` + `/tmp` (not in repo).
- **2026-06-23** — V3 review + verification session (no code changed). Pulled `main` (local was 13 commits
  behind origin — V3 had been built in other sessions and merged via PRs #21–#26). Independently re-ran the
  full suite green: backend pytest **226 passed / 70 DB-skipped** (= 296; DB tests skip with no local
  Postgres, CI runs them green), ruff + ruff-format + mypy clean (61 files); web **20 vitest** + lint (0
  errors) + build OK; shared typecheck + 7 tests. Code-reviewed the V3 invariants: strength brief reads only
  `exclude_from_recovery=True` activities and never touches the verdict (#49/#80); experiment `/evaluate` is
  recommendation-only, conclude stays human-gated (#72); handover GET uses `seed=False` (no lazy-seed);
  exports/previews are deterministic + fakeable without `ANTHROPIC_API_KEY`; trends/eval degrade on thin
  history (gates 5/8/4, YoY ~Mar 2027). **Production smoke confirmed** (prod on `e94ad7c`, web 200, all V3
  endpoints 401 auth-gated). Removed a stale Phase-0a git worktree (`agent-a6ce35123fdd45e57` on `fc923e2`).
  **Authenticated prod E2E (done):** local full stack was blocked (no local Postgres; `brew install
  postgresql@16` fails on outdated Command Line Tools; Docker unavailable), so ran the prod API path instead —
  minted a one-time device token for Mark via `railway run … python -m src.activate` (revoked by token-hash
  afterward; verified 401), then GET-checked every V3 endpoint authenticated: `strength-brief` (trend + 2
  sessions), `reviews/{weekly,monthly}`, `trends/{seasonal,year-on-year,narrative}`, `handover` (+ `/export`
  3.2 KB markdown), `experiments` (3 seeded), `experiments/{id}/evaluate` — all HTTP 200, `errors=[]`, with
  graceful `insufficient_history`/sample-gate behaviour on real (thin) data. Avoided the cost-incurring
  `/run` paths. A browser UI click-through is the only thing still not exercised (optional).
- **2026-06-23** — Closeout: merged Batch 23 (PR #26, squash merge `ddc739f`) — auto-generated handover-doc
  export, the #13 capstone. CI green across all 6 jobs on the PR (ruff, mypy, pytest, alembic,
  security-audit, web build) plus Vercel preview. Struck the Batch 23 row `Shipped`, ticked `ARCHITECTURE.md`
  §7, DECISIONS #84 already recorded on batch-start. The merge is on `main` and auto-deploys via Railway +
  Vercel exactly as every prior batch. **This was the final v3 batch — the v1→v3 roadmap is now complete;**
  every row in `docs/phase-batches.md` is `Shipped`. **Production smoke** to be confirmed via the live-confirm
  commands in the "Now" block (`/api/v1/health` SHA `ddc739f…`; web `/` 200; `GET /api/v1/handover` 401
  auth-gated) — run manually if this session's egress blocks `*.railway.app`/`*.vercel.app`. No further
  unshipped batches.
- **2026-06-23** — Batch 23 (auto-generated handover-doc export — the #13 capstone) implementation ready on
  `claude/batch-start-23-1u534n`. Added `services/handover.py` (deterministic `build_handover_packet`
  composing KB + plan/block + baselines + recent reviews + seasonal YoY + experiments-with-evaluations +
  strength brief into one inspectable packet, reusing every prior batch's service rather than recomputing;
  `render_handover_markdown` renders the portable markdown doc deterministically — no model — so the export
  always works and faithfully reflects retained state, the #13 round-trip; `HandoverService.run` polishes it
  through the Batch 20 Anthropic boundary with a handover-specific system prompt, stored in `analyses` as
  `handover_export`, idempotent per day), `routers/handover.py` (`GET /api/v1/handover` preview never writes
  — experiments listed `seed=False`; `POST …/run` generate+store; `GET …/export` downloads the deterministic
  markdown attachment), registered in `main.py`. Frontend: `HandoverPage.tsx` + `/handover` route + TabBar
  "Handover" tab, `handoverEnvelopeSchema` in `@coach/shared`, client-side `.md` download from the returned
  markdown. Recorded DECISIONS #84. No LLM dependency for the export floor, no migration, no new cron.
  Verified backend pytest **296 passed** (9 new, run against a real local Postgres so the DB-backed
  preview/run/idempotency tests actually execute), ruff + mypy clean (61 files); shared typecheck + 7 tests;
  web lint 0 errors, 20 vitest (1 new), vite build (incl. `tsc`) OK. Awaiting `/closeout 23`.
- **2026-06-23** — Closeout: merged Batch 22 (PR #25, squash merge `86205e5`) — hypothesis evaluation. CI
  green across all 6 jobs on the PR (ruff, mypy, pytest, alembic, security-audit, web build) plus Vercel
  preview. **Production verified directly** (egress reached the hosts this session): `/api/v1/health` →
  `sha=86205e5`, web `/` → 200, and `GET /api/v1/experiments`, `GET …/{id}/evaluate`,
  `POST …/{id}/evaluate/run` all live + 401 unauthenticated (auth-gated, non-mutating). Struck the Batch 22
  row `Shipped`, ticked `ARCHITECTURE.md` §7, DECISIONS #83 already recorded on batch-start. Next unshipped
  batch: **Batch 23** (auto-generated handover-doc export — the #13 capstone, lands last).
- **2026-06-23** — Batch 22 (hypothesis evaluation) implementation ready on `claude/batch-start-22-e66o78`.
  Added `services/experiment_evaluation.py` (deterministic, advisory evaluator reusing the Batch 17
  `_slope`/`pearson`/`compute_drivers` math; dispatches on experiment `slug` to gate/correlation/group_compare
  evaluators that each surface their evidence window + reasons and skip below #71 sample gates; maps to a
  `supported`/`refuted`/`inconclusive` recommendation that **never** changes status — concluding stays the
  human-gated terminal `POST /…/status` action #72), wired `GET /api/v1/experiments/{id}/evaluate` (preview,
  never writes) + `POST /…/evaluate/run` (records an `experiment_evaluation` audit row in `analyses`,
  idempotent per experiment+subject-date keyed on `context_packet.experimentId`). Frontend: new
  `ExperimentsPage.tsx` + `/experiments` route + TabBar "Tests" tab, two new `@coach/shared` schemas; each
  card evaluates and offers "Conclude as <recommendation>" through the existing conclude path. Recorded
  DECISIONS #83. No LLM, no migration, no new cron. Verified backend pytest **287 passed** (17 new, run
  against a real local Postgres so the DB-backed evaluate/run/idempotency/never-auto-conclude tests actually
  execute), ruff + mypy clean (59 files); shared typecheck + 7 tests; web lint 0 errors, 19 vitest (1 new),
  vite build (incl. `tsc`) OK. Awaiting `/closeout 22`.
- **2026-06-23** — Closeout: merged Batch 21 (PR #24, squash merge `1c8ad85`) — year-on-year & seasonal
  trends. CI green across all 6 jobs on the PR (ruff, mypy, pytest, alembic, security-audit, web build)
  plus Vercel preview. Struck the Batch 21 row `Shipped`, ticked `ARCHITECTURE.md` §7, DECISIONS #82
  already recorded on batch-start. The merge is on `main` and auto-deploys via Railway + Vercel exactly
  as every prior batch. **Production smoke** to be confirmed via the live-confirm commands in the "Now"
  block (`/api/v1/health` SHA `1c8ad85…`; web `/` 200; `GET /api/v1/trends/year-on-year` 401 auth-gated)
  — run manually if this session's egress blocks `*.railway.app`/`*.vercel.app`. Next unshipped batch:
  Batch 22 (hypothesis evaluation).
- **2026-06-23** — Batch 21 (year-on-year & seasonal trends) implementation ready on
  `claude/batch-start-21-dw9s27`. Added `services/trends.py` (pure `compute_trend_windows` bucketing
  daily history into month/season windows with reproducible per-metric count/mean/median/min/max over
  9 metrics, honouring the SpO2/HRV reliability cutoff #45 *in the aggregation* with an explicit
  `excludedCount` per #44; `compute_year_on_year` same-period-vs-prior-year deltas requiring ≥5
  samples both sides else graceful `insufficient_history`; `TrendsService` thin DB wrapper; optional
  narrative reuses the Batch 20 Anthropic boundary via a new backward-compatible `system_prompt`
  override, stored in `analyses` as `seasonal_trend`, idempotent per window, insufficient-history
  reported deterministically without calling the model), `routers/trends.py`
  (`GET /api/v1/trends/seasonal|year-on-year|narrative` previews never write; `POST
  /narrative/run` generate+store), registered in `main.py`. Frontend: `TrendsPage.tsx` + `/trends`
  route + TabBar "Trends" tab, three trend schemas in `@coach/shared`. Recorded DECISIONS #82.
  Deterministic windowing + narrative boundary, no migration, no new cron. Verified backend pytest
  **270 passed** (14 new, run against a real local Postgres so the DB-backed preview/run/idempotency
  tests actually execute), ruff + mypy clean (58 files); shared typecheck + 7 tests; web lint 0
  errors, 18 vitest (2 new), vite build OK. Awaiting `/closeout 21`.
- **2026-06-23** — Closeout: merged Batch 20 (PR #23, squash merge `e1cd2cc`) — weekly & monthly deep
  reviews. CI green across all 7 jobs on the PR (ruff, mypy, pytest, alembic, security-audit, web
  build, Vercel preview). Struck the Batch 20 row `Shipped`, ticked `ARCHITECTURE.md` §7, DECISIONS
  #81 already recorded on batch-start. **Production smoke could not be run from this session** — its
  egress policy blocks `*.railway.app` / `*.vercel.app` (proxy 403 on CONNECT), so the live
  `/api/v1/health` SHA, web `/` 200, and `GET /api/v1/reviews/weekly` 401 checks are pending a manual
  30s confirm (commands in the "Now" block). The merge is on `main` and auto-deploys via Railway +
  Vercel exactly as every prior batch. Next unshipped batch: Batch 21 (year-on-year & seasonal trends).
- **2026-06-23** — Batch 20 (weekly & monthly deep reviews) implementation ready on
  `claude/batch-start-config-wdq8ms`. Added `services/reviews.py` (pure `compute_review_rollup`
  aggregating a period's sleep/recovery/load+adherence/verdicts/thermal into reproducible
  averages/counts/by-type/first-vs-second-half trends; `ReviewService` reuses Batch 19
  `StrengthBriefService` + Batch 17 `InsightsService`; thin Anthropic Messages boundary reused from
  Batch 6 `#47`, fakeable, stores narrative + prompt/model metadata in `analyses` as
  `weekly_review` / `monthly_review`), `routers/reviews.py` (`GET /api/v1/reviews/{period}` preview =
  never writes; `POST /…/run` generate+store; calendar-aligned windows → idempotent per period; #71),
  registered in `main.py`. Frontend: `ReviewsPage.tsx` + `/reviews` route + TabBar tab,
  `reviewEnvelopeSchema` in `@coach/shared`. Recorded DECISIONS #81. Deterministic rollup + narrative
  boundary, no migration, no new cron. Verified backend pytest **256 passed** (14 new, run against a
  real local Postgres so the DB-backed preview/run/idempotency tests actually execute), ruff + mypy
  clean; shared typecheck + 7 tests; web lint 0 errors, 16 vitest, vite build OK. Awaiting
  `/closeout 20`.
- **2026-06-23** — Closeout: merged Batch 19 (PR #21, merge `3737338`) — strength watching-brief
  engine live. CI run #135 green on branch HEAD (`b998c43`); Railway auto-deployed to `3737338` within
  minutes; production smoke passed: `/api/v1/health` returns the merge SHA, web `/` 200,
  `/api/v1/strength-brief` 401 (live and auth-gated). Struck the Batch 19 row `Shipped`, ticked
  `ARCHITECTURE.md` §7, DECISIONS #80 already recorded on batch-start. Next unshipped batch:
  Batch 20 (weekly & monthly deep reviews — 🔴 High tier, reintroduces Claude narrative boundary).
- **2026-06-23** — Batch 19 (strength watching-brief) implementation ready on
  `claude/batch-start-19-mtq4cs`. Added `services/strength_brief.py` (pure-function
  `is_strength_activity` delegates to `exclude_from_recovery` from Batch 8, no new
  classification logic; `compute_strength_rollup` computes 4w/12w `WindowStats` — session
  count, duration, load proxy, sessions/week — and derives trend from first/second-half
  rates of the 4w window; `StrengthBriefService.brief` is a thin read-only DB wrapper,
  never writes), `routers/strength_brief.py` (`GET /api/v1/strength-brief`, `as_of` param,
  `{data, meta, errors}` envelope), wired `StrengthBriefResult` into `DailyLoopSnapshot` and
  `strengthBrief` into `DailyLoopData`, registered the router in `main.py`. 19 tests:
  15 pure-function (classification, rollup engine, recovery-isolation invariant via
  `__dataclass_fields__` check + flag-mutation guard), 4 DB-backed (empty history, counts only
  excluded activities, ignores >12w window, cycling flag untouched). Deterministic, no LLM,
  no migration, no new cron (DECISIONS #80). Backend: 187 passed / 55 skipped, ruff clean,
  mypy clean. Awaiting `/closeout 19`.
- **2026-06-23** — v3 planning session: decomposed the `ARCHITECTURE.md` §6 v3 "long
  game" roadmap into Batches 19–23, appended as the `## v3 batch plan` section in
  `docs/phase-batches.md` (all rows `Planned`). One batch per roadmap bullet: 19 strength
  watching-brief (🟢, deterministic, preserves the #49 recovery-isolation invariant), 20
  weekly & monthly deep reviews (🔴, reintroduces the #47 Claude narrative boundary), 21
  year-on-year & seasonal (🔴, degrades gracefully until ~Mar 2027), 22 hypothesis
  evaluation (🔴, extends the Batch 17 tracker #72 — recommends a conclusion, never
  auto-concludes), 23 auto-generated handover-doc export (🔴, the #13 capstone, lands last).
  Cross-cutting: narrative outputs reuse the thin Anthropic boundary while rollups stay
  deterministic; human/API-triggered, not new crons (#64/#71); migration-free, outputs in
  `analyses` + `knowledge_base`. Decision numbers assigned at `/batch-start` (next free #80).
  Docs-only; no code touched.
- **2026-06-23** — Closeout: merged auth Phase 2 (PR #19, `0187e6a`) — the PWA cutover to
  device-token-first login, with the PIN form demoted behind a "Use a PIN instead" fallback toggle.
  Frontend-only (`LoginPage`); CI green; full web vitest 14 passed (2 new LoginPage tests). Verified
  live by confirming the new invite copy in the prod Vercel bundle (`/assets/index-AGSoHWQE.js`),
  `/login` 200, no console errors. Auth Phases 1+2 now complete and live; only the destructive Phase 3
  remains (closes P1-1/P1-3/P3-1/2/3, retires the `1234` PIN). Updated `STATUS.md`, `ARCHITECTURE.md`
  §1/§7, `DECISIONS.md` #79, and ticked Phases 1-2 in `auth-simplification-plan.md`.
- **2026-06-23** — Closeout: merged the auth Phase 1 work and the P3 hardening to `main`
  (now Git-backed, superseding the break-glass deploys). PR #18 (auth Phase 1 — device-token
  activation alongside PIN; migration 008; Decisions #73-74/#77) and PR #17 (P3-5/6/7 — secret
  validator ≥32+distinct, backup `PGPASSWORD`, prod API docs disabled; Decision #78) both CI-green;
  squash-merged to `main` (`4f646cb`, then `764adb1`). Verified prod secrets are 64-char + distinct
  before merging #17 (P3-5 gates startup). Production verified on `764adb1`: `/api/v1/health` 200 with
  a real SHA (no more `sha="unknown"`), `/api/docs|redoc|openapi.json` all 404, web `/` 200,
  `/api/v1/daily-loop` 401. Backed up the previously local-only auth branch to origin in the process.
  The v1+v2 review is now closed except the deferred auth Phases 2-3 (which close P1-1/P1-3/P3-1/2/3)
  and optional P3-4/P3-9. Updated `docs/reviews/v1-v2-review.md`, `ARCHITECTURE.md` §1/§7, `DECISIONS.md`
  #77-78.
- **2026-06-23** — Live activation route debugging + production fix-up. Break-glass deployed the
  backend to Railway and the web app to Vercel production so Phase 1 auth could be exercised
  end-to-end. Found and fixed three production-only web bugs while reproducing `/activate` in a
  headless browser: (1) the frontend crashed on load if `VITE_API_URL` was unset in production;
  (2) after removing that guard, production still fell back to `http://localhost:8000` instead of
  same-origin, so CSP blocked `/api/v1/auth/activate`; (3) after fixing the API base, `/activate`
  wrote the device token directly to local storage and then navigated before `AuthContext` knew the
  user was signed in, bouncing the route back to `/login`. Fixed by treating unset
  `VITE_API_URL` as same-origin in production and routing activation through
  `AuthContext.activateDevice()`. Verified the repaired production flow in headless Chromium, then
  minted a fresh one-time Mark link from inside the live Railway container. Current follow-up is
  the real phone smoke. Note: because the backend is on a break-glass Railway upload rather than a
  Git-backed deploy, `/api/v1/health` now reports `sha=\"unknown\"`.
- **2026-06-22** — Auth simplification Phase 1 implementation ready locally (additive, reversible).
  Finished the interrupted device-token work from the v1/v2 review plan: `auth.py`
  `get_current_user` now accepts JWT **or** opaque device tokens; `refresh_tokens` gained additive
  `purpose` / `used_at` support plus migration `008`; `POST /api/v1/auth/activate` now exchanges
  a single-use activation code for a long-lived device token; added admin CLI
  `python -m src.activate --profile <name>` to mint `.../activate#code=...` links; wired the web
  `/activate` page plus dual-mode token storage so device-token auth works without removing PIN
  login yet. Verified backend auth tests (**19 passed**), backend ruff, backend mypy, and web
  build; web lint showed warnings only (no errors). Next: real phone activation smoke, then decide
  on Phase 2 cutover timing.
- **2026-06-22** — Post-v2 review + first fix. Ran a full code/security/functional
  review (`docs/reviews/v1-v2-review.md`): static checks + read-only prod smoke green;
  surfaced one moderate dep CVE (`react-router`) and a cluster of auth findings. Fixed
  the one substantive safety gap — **P1-2 Red-never-VO2 at the delivery gate** (PR #14,
  CI green; Decision #75). Agreed to simplify auth to **passwordless device tokens**
  (Decision #73–74; plan in `docs/reviews/auth-simplification-plan.md`), deferring
  Cloudflare Access. Open quick wins: rotate the prod PIN off `1234`, bump
  `react-router-dom`, add dependency/secret scanning to CI.
- **2026-06-22** — Verified the intervals.icu delivery rail against the **live** API
  (post-Batch-17 follow-up, not a batch). Found `INTERVALS_API_KEY` was already set in
  Railway (service `api`, production) with the matching key, alongside
  `INTERVALS_ATHLETE_ID=i618709` / `INTERVALS_BASE_URL`; the active deploy (`12e1ab82`,
  13:09) carries it, so the prior "set the key" follow-up was stale. A throwaway local
  smoke drove the real production code path (`build_structured_workout_ir →
  build_intervals_payload → IntervalsIcuClient.create_workout_event`): intervals.icu
  created event `117784365`, then the script deleted it (HTTP 200). So key, auth, and
  payload shape all work and production `auto_push_due` can deliver. Not yet exercised: a
  real prod `auto_push_due` run (would write a live event to Mark's calendar). Updated the
  follow-up note above; no code change.
- **2026-06-22** — Closed out Batch 17. Opened + merged PR #13 to `main` (merge commit
  `88cdcd1`); CI run #109 green on the PR HEAD (`c027e1f`, all 5 jobs: ruff, mypy, alembic
  up/down, pytest, web build). Railway + Vercel auto-deployed `88cdcd1`: `/api/v1/health`
  returns the merge SHA, the Vercel same-origin `/api/v1/health` rewrite returns the same SHA,
  the web URL is `HTTP 200`, and the non-mutating Batch 17 smoke passed — all seven
  `/api/v1/insights/*` + `/api/v1/experiments/*` routes are live, 401 unauthenticated, and
  exposed in the deployed OpenAPI. Struck the Batch 17 row `Shipped`, ticked `ARCHITECTURE.md`
  §7, DECISIONS #71-72 already recorded on batch-start. **All v2 batches (11–18) are now
  shipped — Phase 2 is complete;** next is the Phase 3 long-game roadmap (not yet decomposed
  into batches).
- **2026-06-22** — Batch 17 (monitoring + insight) implementation ready on
  `claude/batch-start-17-d661xy`. Added `services/insights.py` (deterministic
  `detect_ftp_drift` from ride-efficiency trend with evidence window; `detect_early_warning`
  from HRV/sleep/readiness slope, fires on ≥2 degrading trends before a Red, `already_red`
  when a Red is present; `compute_drivers` Pearson ranking of sleep/recovery movers over
  history; `InsightsService.run` records `analyses` audit rows for findings only, idempotent
  per date), `services/experiment_tracker.py` (lazy-seeded 3 standing hypotheses in the
  existing `experiments` table, validated `active`⇄`paused`→`concluded` lifecycle, `analyses`
  audit), `routers/insights.py` (`GET /api/v1/insights/*` read-only + `POST /run`),
  `routers/experiments.py` (`GET/POST /api/v1/experiments/*`), both wired in `main.py`. Chose
  deterministic pure-function engines + no migration + human/API-triggered (not a scheduler
  cron) — consistent with Batches 13/14/16 and Decision #64 (DECISIONS #71-72). Backend-only
  per the batch's acceptance criteria. Verified backend pytest **206 passed** (26 new, real
  local Postgres), ruff check + format clean, mypy clean (51 files). Awaiting `/closeout 17`.
- **2026-06-22** — Closed out Batch 16. Opened + merged PR #12 to `main` (merge commit
  `70ca906`); CI run #104 green on branch HEAD (`5e8e764`). Railway + Vercel auto-deployed
  `70ca906`: `/api/v1/health` returns the merge SHA, the Vercel same-origin
  `/api/v1/health` rewrite returns the same SHA, the web URL is `HTTP 200`, and the
  non-mutating Batch 16 smoke passed — `GET /api/v1/block-generator` is live, 401s
  unauthenticated, and the deployed OpenAPI exposes all five `/api/v1/block-generator{,
  /generate,/refine,/lock,/discard}` routes. Struck the Batch 16 row `Shipped`, ticked
  `ARCHITECTURE.md` §7, recorded DECISIONS #69-70 on batch-start. Next unshipped batch:
  Batch 17 (monitoring + insight).
- **2026-06-22** — Batch 16 (app-generated 13-week blocks) implementation ready on
  `claude/batch-start-16-ig4vqh`. Added `services/block_generator.py` (deterministic
  `generate_block_plan` reusing the shared 2121 block templates + Batch 14 VO2 toolkit;
  `BlockGeneratorService` generate/refine/lock/discard; refine-then-lock draft as JSONB
  in `knowledge_base` `section='generated_block'`, versioned; `generate` 409s on an
  unlocked draft; `lock` versions `plan_blocks` + active `planned_workouts` so locked
  blocks feed the daily loop + Zwift rail on approval), `routers/block_generator.py`
  (`GET/POST /api/v1/block-generator/*`), shared Zod schemas, `BlockGeneratorPage.tsx`
  + Builder tab/route. Chose a deterministic generator over an LLM call (DECISIONS #69)
  so the 2121 shape + 30/15 progression + refine/lock versioning are testable invariants
  that hold without `ANTHROPIC_API_KEY`; no migration (DECISIONS #70). Verified backend
  pytest 180 passed (16 new, real local Postgres), ruff + format + mypy clean; shared
  typecheck + tests green; web lint 0 errors, 12 tests (5 new), vite build succeeds.
  Awaiting `/closeout 16`.
- **2026-06-22** — Closed out Batch 15. PR #11 opened + merged to `main` (merge
  commit `8ee1ed4`); CI run #100 green on branch HEAD (`5b442a1`); CI run #102
  green on `main`. Railway health verified at SHA `8ee1ed4`. Smoke: `GET
  /api/v1/holiday` returns 401 unauthenticated (live and auth-gated). Struck Batch
  15 row Shipped, ticked `ARCHITECTURE.md` §7, DECISIONS #66-68 already recorded on
  batch-start. Next unshipped batch: Batch 16 (app-generated 13-week blocks).
- **2026-06-21** — Batch 15 (holiday pause/resume) implementation ready on
  `claude/batch-start-15-l8yuvm`. Built `services/holiday_pause.py` (pure helpers +
  `HolidayPauseService.pause`/`resume` — holiday = recovery-week equivalent, 2121
  continuation: Build1→Build2, Build2→repeat Build1), `routers/holiday.py`
  (`GET/POST /api/v1/holiday{/pause,/resume}`), 7 pure-function + 7 DB-backed tests,
  5 shared Zod schemas, `HolidayPage.tsx` + 4 vitest tests, TabBar Holiday tab.
  No migration (windows in `knowledge_base` JSONB, DECISIONS #66-68). Verified:
  backend 7 passed / 7 skipped (DB tests skip without DATABASE_URL), ruff check +
  format clean, mypy clean; frontend 7 passed, eslint 0 errors, vite build succeeds.
  Awaiting `/closeout 15`.
- **2026-06-21** — Closed out Batch 14. Opened + merged PR #10 to `main` (merge
  commit `efc2d7a`); CI run #95 was already green on the branch HEAD (`1ac1838`).
  Railway + Vercel auto-deployed `efc2d7a`: `/api/v1/health` returns the merge SHA,
  the Vercel same-origin `/api/v1/health` rewrite returns the same SHA, the web URL
  is `HTTP 200`, and the non-mutating Batch 14 smoke passed — `GET
  /api/v1/restructure/week-ahead` + `POST /api/v1/restructure/apply` are live, 401
  unauthenticated, and exposed in the deployed OpenAPI. Struck the Batch 14 row
  `Shipped`, ticked `ARCHITECTURE.md` §7, recorded DECISIONS #63-65. Next unshipped
  batch: Batch 15 (holiday pause/resume).
- **2026-06-21** — Batch 14 (dynamic weekly restructuring) implementation ready on
  `claude/batch-start-14-gajkdx`. Added `services/weekly_restructure.py` (pure
  permutation engine `plan_week_restructure` enforcing the VO2↔Sweet-Spot no-stack
  rule as a hard constraint and defer-on-fatigue as a lexicographic objective;
  `assess_recovery_signal` from readiness/HRV/verdict-trend; `WeeklyRestructureService`
  that versions changed `planned_workouts` days, audits in `analyses`
  `weekly_restructure`, and proposes changed bike workouts via the Batch 12/13 rail —
  never pushed), the shared `services/vo2_progression.py` VO2 toolkit (30/30 → Rønnestad
  30/15 from Wk7, ERG off) wired into both `coaching_state` seeding and the deferred-VO2
  regeneration, and `routers/restructure.py` (`GET/POST /api/v1/restructure/*`,
  human-triggered, not a scheduler job). No migration. Recorded DECISIONS #63-65; added
  the Batch 14 paragraph to `ARCHITECTURE.md` §2. Verified backend pytest **150 passed**
  (10 new, run against a real local Postgres so the DB-backed versioning/delivery tests
  actually run), ruff check + format clean, mypy clean. Not yet committed/merged; awaiting
  `/closeout 14`.
- **2026-06-21** — Closed out Batch 13. Opened + merged PR #9 to `main` (merge
  commit `e6e3107`). CI on the branch HEAD initially failed on a **pre-existing**
  broken test (`test_get_daily_loop_hides_stale_hive_temperature`) that had left
  `main` CI red since Batch 18 — it seeded a Profile and its FK children in a single
  flush, which CI's current SQLAlchemy orders child-before-parent; fixed by
  committing the profile first (`c596114`), after which all five CI jobs went green.
  Railway + Vercel auto-deployed `e6e3107`: `/api/v1/health` returns the merge SHA,
  the Vercel same-origin `/api/v1/health` rewrite returns the same SHA, and the
  non-mutating Batch 13 smoke passed — `GET /api/v1/workout-delivery/week-ahead` is
  live and 401s unauthenticated, and the deployed OpenAPI exposes it. Struck the
  Batch 13 row `Shipped`, ticked `ARCHITECTURE.md` §2/§7, recorded DECISIONS #61-62.
  Next unshipped batch: Batch 14 (dynamic weekly restructuring). Follow-ups: rotate
  Mark's PIN off `1234`; set `INTERVALS_API_KEY` in Railway for live auto-push.
- **2026-06-21** — Batch 13 (executable coaching) implementation ready on
  `feat/batch-13-executable-coaching`. Built the closed loop on the Batch 12 rail:
  `services/executable_coaching.py` with a deterministic `adjust_ir_for_verdict`
  (Amber = 75% duration + drop a zone + cap at threshold/no HIT; Red = half
  duration + cap ≤60% FTP so VO2 is structurally impossible; Green = pass-through)
  and `ExecutableCoachingService` (`regenerate_for_verdict` Amber-only + idempotent,
  `auto_push_due` approved-only within `today+2`, `analyses` audit). Refactored the
  rail with `WorkoutDeliveryService.propose_from_ir` + `list_week_ahead`; added
  `GET /api/v1/workout-delivery/week-ahead`; wired the 06:30 job to regenerate on
  Amber and a new `workout_autopush` cron (07/13/19 local). Frontend: shared
  workout-delivery/week-ahead zod schemas, a new `/delivery` PWA page (tab "Plan")
  for propose→approve→push + the week-ahead, and its test. No migration (DECISIONS
  #61-62). Verified: backend pytest 124 passed / 16 DB-skipped, ruff + format +
  mypy clean; web test 3/3, build, lint (pre-existing warnings only); shared
  typecheck + test green. Incidentally reformatted two pre-existing files newer
  ruff flagged to keep CI's `ruff format --check .` green. Not yet committed/merged;
  awaiting `/phase-closeout 13`.
- **2026-06-21** — Closed out Batch 18. Verified the docs-only closeout deploy on
  live `707850d`: Railway `/api/v1/health` returned the closeout SHA, Vercel
  served `HTTP 200`, and the strict authenticated smoke still passed
  (`health`/`login`/`daily_loop`, `subjectDate=2026-06-21`, `verdict=Red`). Struck
  the Batch 18 row as `Shipped`, ticked `ARCHITECTURE.md`, and moved the handoff
  target to Batch 13. One operational follow-up remains outside the shipped batch:
  rotate Mark's production PIN off the temporary smoke value `1234`.
- **2026-06-21** — Closed the real Hive freshness gap for Batch 18. After
  deploying `41defe9`, the honest strict smoke correctly failed because
  `thermalState.latestTemperatureC` was now hidden when stale. Built and shipped a
  second fix on `38cecb6`: `run_hive_temperature_poll()` now stamps a successful
  poll from the fresh sync time when Hive's `heating` product `lastSeen` is older
  than the 45-minute freshness window, while the daily-loop API still applies the
  same freshness rule when deciding whether to surface a current temperature.
  Verified locally: pytest `21 passed, 4 skipped`, ruff clean. Pushed to `main`,
  waited for Railway deploy, manually ran the production Hive poll, confirmed the
  latest `temperature_readings.captured_at_utc` is now
  `2026-06-21T19:31:54.566473`, and reran the strict live smoke successfully:
  `health` PASS, `login` PASS, `daily_loop` PASS (`subjectDate=2026-06-21`,
  `verdict=Red`). Batch 18 is now ready for explicit closeout; Mark's production
  PIN still needs rotating off the temporary smoke value `1234`.
- **2026-06-21** — Proved the production daily loop end to end, then found the
  remaining Hive honesty gap. With `HIVE_TOKENSTORE_B64` already set, manually ran
  the live production `run_morning_weather_sync()` and `run_hive_temperature_poll()`
  via `railway run`; production now has today's Garmin `daily_metrics`, `sleep`,
  weather, and morning analysis rows. Temporarily reset Mark's production PIN via
  `src.seeds` so the strict smoke could log in; strict smoke then passed on live
  `8b62caa` with `subjectDate=2026-06-21` and `verdict=Red`. Follow-up traced the
  Hive payload: the `heating` product still reports `lastSeen=1781622656874`
  (`2026-06-16T15:10:56.874Z`) even though the hub is fresh, so the old gate was
  satisfied by a non-null but stale `latestTemperatureC`. Built a local fix
  (DECISIONS #60) that applies the same 45-minute freshness rule to
  `/api/v1/daily-loop`: stale Hive rows still show `capturedAtUtc`, but no longer
  surface a current temperature value. Targeted pytest/ruff green locally; not yet
  committed or deployed. Batch 18 remains open until that fix ships and the strict
  smoke passes again under the honest rule.
- **2026-06-21** — Shipped the 18.4 Hive fix and cleared two of the 18.3
  blockers. Opened PR #8, fixed a CI `ruff format` miss (CI lints from `apps/api`,
  so only `environment_sync.py` mattered — collapsed one `raise`), merged to `main`
  (merge `8b62caa`); CI green, Railway deployed (deployment `66298001`,
  `/api/v1/health` = `8b62caa`). **Anthropic credits confirmed good** via a live
  test call to the prod key (HTTP 200). **Garmin** already confirmed working
  earlier. Hive code is now live but **prod Hive still fails until
  `HIVE_TOKENSTORE_B64` is seeded** (one-time SMS-2FA login on Mark's phone) — the
  one human-gated step left. Remaining for 18.3: seed Hive → tomorrow's 06:30 job
  populates today's Garmin daily metrics/sleep + analysis → run strict smoke with
  Mark's PIN → strike the row.
- **2026-06-21** — Built the Hive headless-auth fix (sub-task 18.4) after
  root-causing the poll failure (desktop session, **uncommitted**). `HiveClient`
  now resumes via Cognito `REFRESH_TOKEN_AUTH` from a base64 `HIVE_TOKENSTORE_B64`
  {username, refresh_token} blob, mirroring the Garmin token-blob pattern; full
  password login is kept only as a fallback and rejects SMS_MFA with a pointer to
  the blob. Added `scripts/bootstrap_hive_tokenstore.py` (one-time SMS-2FA seed),
  the `hive_tokenstore_b64` setting + `.env.example`, and
  `structlog.processors.format_exc_info` in `logging_config.py` so scheduler
  tracebacks stop being dropped. New tests cover the resume path, the SMS_MFA
  rejection, no-secret error surfaces, and traceback rendering; backend 115
  passed / 11 skipped, ruff + mypy clean. Not yet committed/deployed; Hive in prod
  stays broken until this ships and Mark seeds `HIVE_TOKENSTORE_B64` via SMS.
- **2026-06-21** — Batch 18 18.3 verification (desktop session). Code side green:
  scheduler tests 25 pass, ruff/mypy clean, prod serves SHA `12ccc99`. Checked
  live prod via Railway CLI: env now fully provisioned, and the **Garmin token is
  confirmed working** — the 17:16 UTC hourly poll logged `garmin activity poll
  complete` (16 activities, 11,407 samples, no 429), clearing the old 429 blocker.
  **Root-caused the recurring Hive failure:** prod `HiveClient` only does a full
  email/password login, but Mark's Hive account requires Cognito SMS_MFA and prod
  has no refresh-token store, so every poll raises `HiveLoginError`
  (`hive temperature poll failed`); the spike's cached refresh token is now invalid
  too, so Hive has no headless path until re-seeded via SMS-2FA. Also found
  `logging_config.py` drops exception tracebacks (no `format_exc_info`), which hid
  the cause. Anthropic credits still unconfirmed. 18.3 stays open; the critical
  path is now Hive headless auth, not Garmin. `AGENTS.md`/`CLAUDE.md` "Hive — no
  2FA" note is inaccurate and should be corrected.
- **2026-06-21** — Batch 18 code merged + deployed (closeout partial). Merged
  PR #7 `claude/start-batch-18-dbwx9r` → `main` (merge commit `08d3010`), main CI
  run #79 green (pytest/ruff/mypy/alembic/web build), Railway auto-deployed and
  `/api/v1/health` reports `08d3010`, non-mutating smoke 1/1. **Did not strike the
  row Shipped:** the strict daily-loop smoke (18.3) could not be run from the work
  session — it needs Mark's PIN plus a live Railway `GARMIN_TOKENSTORE_B64` and
  Anthropic credits, which were the standing production blockers. Honest state:
  the sync wiring is implemented, tested, and live, but the gate that the live
  verdict runs on real readiness/sleep is verified only by unit tests, not yet by
  a production smoke. Run the strict smoke with Mark's PIN to finish closeout.
- **2026-06-21** — Phase 2 Batch 18 implementation ready on
  `claude/start-batch-18-dbwx9r`: wired `GarminSyncService.sync_daily` into the
  06:30 `morning_weather_sync` job via a new `_sync_garmin_daily` helper that runs
  *before* the analysis loop (weather → commit → garmin daily → commit →
  analysis), so the morning verdict reads today's real readiness + sleep. Made
  the fetch 429-safe by adding an exponential-backoff `backoff` option to
  `_retry_sync` (used at `backoff=2.0`), and isolated each profile's sync in its
  own try/except so one Garmin failure (429/MFA/token) is logged and skipped.
  Added scheduler tests (daily-sync counts, per-profile error isolation, empty
  short-circuit, backoff growth, and weather→daily-sync→analysis ordering).
  Recorded DECISIONS #58. Verified backend pytest (111 passed, 11 DB-skipped),
  ruff check + format, and mypy (clean, 38 files). The strict production smoke
  (18.3) is deferred to `/closeout` — it needs the deployed Railway job to run
  with a live Garmin token + Mark's PIN.
- **2026-06-21** — Batch 12 closed out **rail-only** (Craig's call): merged PR #6
  to `main` (merge commit `67f9ad4`), CI green (pytest/ruff/mypy/alembic/web
  build), Railway + Vercel auto-deployed. Shipped the Zwift delivery rail
  (migration `007`, propose→approve→push), the `GARMIN_TOKENSTORE_B64` token-blob
  auth path, and the Anthropic fail-closed validator (DECISIONS #56). CI caught a
  latent Batch 12 DB test bug (FK violation from `add_all([profile, workout])` in
  one flush) — fixed by seeding the profile first. **Found + deferred:** the
  strict daily-loop data gate is unmet because production has no Garmin
  daily-metrics/sleep sync (`sync_daily` unwired); split into Batch 18 and
  recorded as DECISIONS #57. Strict smoke not run (needs Mark's PIN and the
  missing daily sync).
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
