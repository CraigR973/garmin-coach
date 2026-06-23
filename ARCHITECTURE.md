# Garmin Coach — Architecture & Spec

Private AI fitness & sleep coach for one user ("Mark", Craig's dad), optionally a
second. Automates the twice-daily check-in he does by hand today: pulls his data,
holds his context permanently, and generates a morning verdict + post-workout
analysis with Claude.

**Product thesis:** he currently writes "handover" docs by hand to give an AI the
context it keeps forgetting. This app's core job is to **hold that knowledge as
living, editable state** so he never writes one again.

---

## 1. Stack (inherited from WC2026, gutted of the football domain)

- **Backend:** FastAPI + async SQLAlchemy + asyncpg, Postgres (Supabase), Alembic, APScheduler, pywebpush. Python **3.12** (`~/.local/bin/python3.12` — system `python3` is 3.7).
- **Frontend:** React 18 + Vite + Tailwind + shadcn/ui + recharts + react-hook-form + react-query. PWA (workbox) so it installs on his phone.
- **Shared:** `packages/shared` (Zod schemas + TS types) — swap WC scoring for fitness types.
- **Auth:** **passwordless device tokens** (primary — one-time activation link), with name + PIN + JWT kept as a hidden fallback (auth-simplification Phases 1-2 live — DECISIONS #73–74/#77/#79; the PIN path is removed in Phase 3). Stripped of WC's leagues/groups/invites/email — **1–2 private users, no sign-up**.
- **Hosting:** Supabase (DB) + Railway (API) + Vercel (web). Deploy live early.
- **Envelope/conventions:** `/api/v1/`, `{data, meta, errors}`, snake_case DB / camelCase JSON, UTC `*_utc` columns, IANA timezone per user (`Europe/London`).

## 2. Data sources — ALL validated against real data (18–19 Jun 26)

| Source | Library/API | Auth | Notes |
|---|---|---|---|
| **Garmin** | `garminconnect` (unofficial) | email+pw, garth token cache (~1yr, no re-MFA) | Full coverage incl. Performance Condition (`directPerformanceCondition`) + Stamina (`directAvailable/PotentialStamina`) in activity time-series |
| **Hive** | `pyhiveapi` (sync) | email+pw, account uses AWS Cognito **SMS_MFA** | Live indoor temp via `API(token).getAll()` → `parsed[i].props.temperature`. Headless operation resumes from a cached Cognito refresh token (`HIVE_TOKENSTORE_B64`) via `REFRESH_TOKEN_AUTH`; seed once with `scripts/bootstrap_hive_tokenstore.py` (DECISIONS #59). |
| **Weather** | Open-Meteo | none (keyless) | KA1 2SD = Kilmarnock, **lat 55.6045, long -4.5249**. `past_days` + `wind_speed_unit=mph` gives daily high/low + overnight low/wind |

Spikes live in `~/garmin-spike/` (outside this repo). Raw sample JSON in `~/garmin-spike/out/` (Garmin) and `out_hive/` (Hive) — **canonical reference for real field shapes**.

**Sync jobs (APScheduler):** Hive temp poll every ~15 min; morning Garmin+weather sync ~06:30 local → triggers morning analysis; hourly activity poll → on new ride triggers post-workout analysis. NB Training Readiness is time-of-day live → morning analysis must read in the morning. `recoveryTime` is in MINUTES.

### Workout delivery — OUTPUT (validated 19 Jun 26)

Push direction only — *not* a data source (ingestion stays direct-from-Garmin). The app emits a structured workout → POST to his **intervals.icu** calendar (free API; athlete `i618709`) → intervals.icu's approved Zwift Training-Connections integration delivers it into Zwift's Custom Workouts automatically. **Power + timing proven exact** end-to-end. intervals.icu is a **delivery rail, NOT the system-of-record** (our DB owns the plan). Deterministic **`.ZWO` export** is the no-dependency fallback. Any write to his trainer is **propose → approve → push**, never silent. Cadence nuance: Zwift overrides cadence on repeated-interval blocks with defaults (100/90) — emit cadence-critical reps as individual steps (confirm on PC). Spike: `~/garmin-spike/intervals_spike.py`.

Batch 12 stores delivery state separately from the plan in
`workout_delivery_proposals`: each proposal snapshots the `planned_workouts`
version, generated structured-workout IR, intervals.icu calendar payload, `.ZWO`
XML, approval state, and pushed event id. intervals.icu credentials live only in
environment variables (`INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`) and the app
never ingests activity data from intervals.icu.

Batch 13 makes the rail *executable* (`services/executable_coaching.py`): on an
Amber morning verdict the 06:30 job regenerates today's bike workout into an
adjusted proposal (deterministic IR transform — cut duration 20-30%, drop a
zone, remove HIT; Red can never emit VO2), the human approves it on the
`/delivery` week-ahead PWA page, and a `workout_autopush` job pushes approved
proposals a couple of days ahead. Proposal/push provenance lives in the IR
snapshot and every step is audited in `analyses` (`workout_proposed` /
`workout_pushed`), so no schema change was needed.

Batch 14 makes the *week* adaptive (`services/weekly_restructure.py`): a
deterministic permutation engine reorders the week's bike sessions so VO2 and
Sweet-Spot are never on the same/adjacent days (hard rule), and, when a recovery
signal (readiness / HRV / morning-verdict trend) shows fatigue, defers hard
sessions later in the week. Applying a restructure versions the changed
`planned_workouts` days, audits it in `analyses` (`weekly_restructure`), and
proposes the changed bike workouts through the same rail — reaching Zwift only on
approval. It is human-triggered via `GET/POST /api/v1/restructure/*`, not the
scheduler. The VO2 progression (incl. Rønnestad 30/15 from ~Wk7, ERG off) is a
shared `services/vo2_progression.py` toolkit used by both the plan seed and the
restructurer. No new migration.

Batch 16 generates whole future blocks (`services/block_generator.py`): a
deterministic generator emits a structured 13-week 2121 block (2 build / 1
recovery ×3, wk12 taper, wk13 consolidation) from profile/FTP, reusing the shared
block templates + the Batch 14 VO2 toolkit so generated VO2 days carry the 30/15
progression. The draft is a **refine-then-lock** workflow (Decision #16): it lives
as JSONB in `knowledge_base` at `section='generated_block'`, each generate/refine/
lock versions the row, and only `lock` writes the owned plan — versioning
`plan_blocks` + active `planned_workouts` so the block feeds the daily loop and
delivers via the Zwift rail under the existing approve → push gate. Human-driven
via `GET/POST /api/v1/block-generator/*` with a `/builder` PWA page; `generate`
refuses to clobber an unlocked draft so refinements are never silently lost
(DECISIONS #69). No new migration.

Batch 17 turns the accumulated history into proactive insight
(`services/insights.py` + `services/experiment_tracker.py`), all deterministic
(no LLM) and migration-free. **FTP-drift detection** reads the trend in ride
efficiency (watts-per-heartbeat) and flags rising/falling/stable with the
evidence window surfaced; **early-warning alerts** measure the HRV/sleep/readiness
slope and fire when ≥2 trends degrade *before* a Red (a Red already present is
`already_red`, not early); **driver/correlation analysis** ranks the strongest
Pearson movers of sleep/recovery over the 84-night+ history. These are surfaced
read-only via `GET /api/v1/insights/{ftp-drift,early-warning,drivers}` and audited
to `analyses` only for actual findings via `POST /api/v1/insights/run`. The
**experiment tracker** manages Mark's standing hypotheses (collagen, recovery-week
disruption, 04:00 waking) in the existing `experiments` table with a validated
`active`⇄`paused`→`concluded` lifecycle and an `analyses` audit trail, via
`GET/POST /api/v1/experiments/*` (DECISIONS #71-72).

## 3. Knowledge Base (the persistent context — replaces his handover docs)

Editable structured state fed into every analysis. Source: his handover doc (see
memory `reference_garmin_app_handover`). Includes:

- **Profile:** age 57, FTP 280W, VO2max 54, HRV band 43–57ms, RHR 45, BP ~108/68, fitness age 48.
- **Data-quality rules (AI MUST obey):** never reference L/R power balance (single-sided meter, doubled); SpO2/HRV reliable only from 11 Jun (strap re-tightened); exclude wrist-HR strength sessions from recovery; ignore the constant/broken "Duration" column in his Excel export.
- **Age-adjustment:** sleep score +~4; age-appropriate REM 65–90 min (Garmin uses young-adult bar).
- **Sleep protocol & thresholds:** pre-cool to 17°C, seal ~22:00, peak >19.5–20°C = thermal disruption; coherence breathing 20:00 (non-negotiable); bedtime 23:15; snack ≤21:30.
- **Training plan** (structured, stored, versioned — see §5).
- **Active hypotheses:** collagen (don't reintroduce before 7 consecutive 74+ nights), recovery-week sleep disruption, 04:00 waking.

## 4. Analysis engine (the heart — Claude generates it)

Assembles a context packet (KB + DB data + rolling trend + plan) and calls Claude.

- **Morning:** sleep analysis (age-adjusted) · physical-metrics read · **Metrics-vs-Baselines table** (baselines computed from his 84-night history) · thermal/environment review vs his targets · **Green/Amber/Red workout verdict** for today's full plan (cycling + strength).
  - **Verdict framework:** GREEN = HRV balanced+stable, sleep ≥70 (age-adj ≥74), subjective ≥5. AMBER = HRV low/mild-unbalanced, sleep 60–69 → cut duration 20–30%, drop a zone, no HIT. RED = HRV unbalanced+declining, sleep <60 → sub/rest; **never VO2 on Red**. Reconcile a "Low" Garmin readiness as load-driven when recovery signals are good.
- **Post-workout:** performance (power/HR/zones/cadence/PC/stamina/TE) · workout rating · guided recovery protocol (specific, timed) · impact on tomorrow.
- **Output rules:** bold each bullet headline; sleep summary line; ignore the phase-frequency system (he wants DAILY always); specific recovery suggestions.

Validated 19 Jun with a real sample → his verdict "fantastic." Demonstrated 5 wins over his Copilot flow: age-adjustment, plan-awareness, no wrong-screenshot errors, causal thermal insight, trend memory.

## 5. Data model (sketch — build from real JSON shapes in `~/garmin-spike/out/`)

- `profiles` (pin_hash, timezone, lat/long, Garmin user profile pk, Hive home id;
  Garmin secrets stay in environment/secrets and garth token cache for v1)
- `daily_metrics` (readiness, recovery_time_min, training_status, stress, body_battery, hrv_*, rhr_*, weight_kg, vo2max)
- `sleep` (score, qualifier, stage secs, spo2, resp, restless, factors_json)
- `metric_baselines` (persisted 84-night summary stats for morning analysis, with reliability cutoffs such as pre-11 Jun SpO2/HRV exclusion)
- `activities` (+ `activity_timeseries`: power/hr/cadence/resp/performance_condition/stamina)
- `temperature_readings` (Hive poll) · `weather_daily` (daily high/low,
  overnight low/wind, precipitation, sunrise/sunset)
- `manual_entries` (BP, subjective, RPE, feel, supplements, food, plus
  adherence captured against the planned-workout version that was actually done)
- `planned_workouts` (structured intervals; **versioned** — VO2 sessions get revised mid-block) · `plan_blocks` (13-wk 2121: 2 build/1 recovery/wk12 taper/wk13 consolidation)
- `workout_delivery_proposals` (approval-gated Zwift delivery snapshots:
  structured IR, intervals.icu payload, deterministic `.ZWO`, status/event id)
- `analyses` (stored Claude outputs) · `experiments` (tracked hypotheses) · `knowledge_base`

Seed `sleep`/`daily_metrics` with his **84-night backfill** (`12 Weeks Sleep Data` xlsx, 24 Mar–15 Jun; trust all cols except Duration).

Phase 1 Batch 1 implements this as additive migration `002`: the inherited
`profiles` table remains the private auth/user table, with Garmin Coach metadata
added to it, and the v1 domain tables live beside it. Data-shape evidence is in
`docs/v1-data-shape-audit.md`.

## 6. Roadmap

**v1 — daily loop:** 3 syncs + 84-night backfill; store plans (ingested from his docs) + per-day override; morning + post-workout analysis; manual check-in; adherence ("did he do it?"); evening nudges; data-quality guardian; thermal monitoring.

**v2 — the coach:** **Zwift workout delivery** (via intervals.icu) + **executable coaching** — on an Amber morning or a week-restructure, regenerate the adjusted workout and (on approval) push it straight to his trainer, so coaching is *acted on*, not just advised; dynamic weekly restructuring (never stack VO2+Sweet-Spot; defer on fatigue); holiday pause/resume (holiday=recovery-week-equiv; pre-holiday Build1→Build2 on return, Build2→repeat Build1); app-generated 13-wk blocks (refine-then-lock, conversational; Rønnestad 30/15 in the VO2 progression toolkit); real-time evening thermal alerts; early-warning drift alerts; driver/correlation analysis; experiment tracker; FTP-drift detection. `.ZWO` export as no-dependency fallback.

**v3 — long game:** strength watching-brief; hypothesis tracking; weekly/monthly deep reviews; year-on-year/seasonal; auto-generated handover-doc export.

## 7. Phase 0 status (live state in `STATUS.md`)

- [x] Repo seeded from WC2026 infra + cross-tool structure
- [x] **Phase 0a** — football domain stripped; clean auth skeleton (`@coach/shared`)
- [x] **Phase 0b** — provision Supabase + Railway + Vercel + GitHub
- [x] Deployable skeleton: auth + empty dashboard live
- [x] **Phase 1 Batch 1** — data model + profile seed shipped
- [x] **Phase 1 Batch 2** — Garmin sync foundation shipped
- [x] **Phase 1 Batch 3** — Hive + weather syncs shipped
- [x] **Phase 1 Batch 4** — 84-night backfill + baselines shipped
- [x] **Phase 1 Batch 5** — training plan + knowledge base shipped
- [x] **Phase 1 Batch 6** — morning analysis engine shipped
- [x] **Phase 1 Batch 7** — daily app loop surfaces shipped
- [x] **Phase 1 Batch 8** — post-workout analysis shipped
- [x] **Phase 1 Batch 9** — nudges + thermal monitoring shipped
- [x] **Phase 1 Batch 10** — v1 hardening + release polish shipped
- [x] **Phase 2 Batch 11** — Phase 1 debt clean-up shipped (player→user rename, migration 006, dead email service, ForgotPin, score-input JSDoc)
- [x] **Phase 2 Batch 12** — Zwift delivery rail shipped (intervals.icu push + `.ZWO` fallback, propose→approve→push, migration 007; Garmin `GARMIN_TOKENSTORE_B64` auth + Anthropic fail-closed validator). Production daily-loop *data* gate (non-null daily metrics/sleep/morning analysis) deferred to Batch 18 — prod has no Garmin daily-metrics/sleep sync yet (DECISIONS #57)
- [x] **Phase 2 Batch 13** — executable coaching (closed loop): an Amber morning verdict deterministically regenerates today's bike workout (75% duration, drop a zone, no HIT — `adjust_ir_for_verdict`) into an approval-gated proposal; Red can never emit VO2; approved proposals auto-push a couple of days ahead (`workout_autopush` job); the week-ahead + propose→approve→push surface is the `/delivery` PWA page; every proposal/push is audited in `analyses` (DECISIONS #61-62). No new migration
- [x] **Phase 2 Batch 18** — production daily-loop data sync shipped (06:30 job now syncs Garmin daily metrics/sleep before morning analysis; Hive uses refresh-token auth and honest freshness gating; strict production smoke green on commit `707850d`)
- [x] **Phase 2 Batch 14** — dynamic weekly restructuring shipped: deterministic permutation engine keeps VO2 and Sweet-Spot off the same/adjacent days and defers hard sessions on a fatigue signal (readiness/HRV/verdict-trend); restructures version `planned_workouts`, audit in `analyses` (`weekly_restructure`), and reach Zwift only on approval via `GET/POST /api/v1/restructure/*` (human-triggered, not a scheduler job); VO2 progression incl. Rønnestad 30/15 centralized in `services/vo2_progression.py` (DECISIONS #63-65). No new migration
- [x] **Phase 2 Batch 15** — holiday pause/resume shipped: holidays treated as recovery-week equivalents; in-window workouts versioned as `status='skipped'`, `source='holiday_pause'`; on return, 2121 block continuation: Build1→Build2 (week S+1), Build2→repeat Build1 (week S-1); windows stored as JSONB in `knowledge_base` at `section='holiday_windows'`; frontend Holiday tab + `HolidayPage.tsx` with pause/resume UI (DECISIONS #66-68). No new migration
- [x] **Phase 2 Batch 16** — app-generated 13-week blocks shipped: deterministic generator (`services/block_generator.py`) emits a structured 13-week 2121 block from profile/FTP, reusing the shared block templates + Batch 14 VO2 toolkit (generated VO2 days carry 30/15); refine-then-lock workflow stored as JSONB in `knowledge_base` at `section='generated_block'` (versioned per generate/refine/lock); `lock` versions `plan_blocks` + active `planned_workouts` so the block feeds the daily loop and the Zwift rail on approval; `GET/POST /api/v1/block-generator/*` + `/builder` PWA tab (DECISIONS #69). No new migration
- [x] **Phase 2 Batch 17** — monitoring + insight shipped: deterministic FTP-drift detection (ride efficiency trend + evidence window), early-warning drift alerts (HRV/sleep/readiness slope, fires on ≥2 degrading trends before a Red), and driver/correlation analysis (Pearson movers of sleep/recovery over 84-night+ history) in `services/insights.py`, surfaced read-only via `GET /api/v1/insights/*` and audited to `analyses` on `POST /api/v1/insights/run`; experiment tracker (`services/experiment_tracker.py`) manages the standing hypotheses (collagen, recovery-week disruption, 04:00 waking) in the existing `experiments` table with a validated lifecycle + `analyses` audit, via `GET/POST /api/v1/experiments/*` (DECISIONS #71-72). No new migration
- [x] **Post-v2 review remediation** — v1+v2 code/security/functional review (`docs/reviews/v1-v2-review.md`); fixes shipped: Red-never-VO2 delivery gate (P1-2 — PR #14, #75); web CSP/headers + `react-router-dom` bump + CI dependency-audit gate (P2-1/2/3 — PR #16, #76); prod API docs disabled + stricter JWT-secret validator + backup `PGPASSWORD` (P3-5/6/7 — PR #17, #78). Open + optional: P3-4 (scheduler per-profile isolation), P3-9 (hygiene)
- [x] **Auth simplification Phases 1-2** — passwordless device-token activation live (migration `008`; dual-path `get_current_user`; `POST /api/v1/auth/activate`; `python -m src.activate` CLI; `/activate` PWA route — #73-74/#77), and the PWA cut over to device-token-first with the PIN form demoted to a "Use a PIN instead" fallback toggle (PR #19, #79). Phase 3 (delete PIN/JWT/lockout + endpoints, drop the dead columns — closes P1-1/P1-3/P3-1/2/3, retires the `1234` PIN) pending after a soak
- [x] **v3 Batch 19** — strength watching-brief shipped (PR #21, #80): advisory-only `GET /api/v1/strength-brief` + `strengthBrief` in the daily-loop envelope; `is_strength_activity` delegates to `exclude_from_recovery` (Batch 8/Decision #49); `compute_strength_rollup` is a pure function computing 4w/12w `WindowStats` (session count, duration, load proxy, sessions/week) and trend from first-vs-second-half session rates; `StrengthBriefService.brief` is read-only; recovery-isolation invariant (#49) explicitly tested (no verdict/recovery fields in result, flag never mutated). No migration, no LLM, no new cron
- [x] **v3 Batch 20** — weekly & monthly deep reviews shipped (PR #23, #81): deterministic `compute_review_rollup` (pure, DB-free) aggregates a period's sleep/recovery/load+adherence/morning-verdicts/thermal into reproducible averages, counts, by-type load and first-vs-second-half trends; `ReviewService` reuses the Batch 19 strength brief + Batch 17 insights and generates the narrative through the thin Anthropic Messages boundary (#47, fakeable), stored in `analyses` as `weekly_review` / `monthly_review`; calendar-aligned windows (ISO week / calendar month) make `run` idempotent per period; `GET /api/v1/reviews/{period}` previews and never writes (#71), `POST /…/run` generates + stores; `/reviews` PWA tab. No migration, no new cron
- [x] **v3 Batch 21** — year-on-year & seasonal trends shipped (PR #24, #82): deterministic `compute_trend_windows` (pure, DB-free) buckets daily history into comparable month/season windows (meteorological seasons; Dec → next year's winter) with per-metric count/mean/median/min/max over 9 metrics, honouring the SpO2/HRV reliability cutoff (#45) *in the aggregation* with an explicit `excludedCount` (#44 provenance); `compute_year_on_year` computes same-period-vs-prior-year deltas requiring ≥5 samples both sides, else degrades to `insufficient_history` (true YoY ~Mar 2027); `TrendsService` reads the rows; the optional narrative reuses the Batch 20 Anthropic boundary (`AnthropicReviewClient` gained a backward-compatible `system_prompt` override) and stores to `analyses` as `seasonal_trend`, idempotent per window, reporting insufficient history deterministically without calling the model; `GET /api/v1/trends/seasonal|year-on-year|narrative` preview and never write (#71), `POST /…/narrative/run` generates + stores; `/trends` PWA tab. No migration, no new cron
- [x] **v3 Batch 23** — auto-generated handover-doc export shipped (#84, the #13 capstone): deterministic `build_handover_packet` (pure, DB-free) composes the full retained state — KB (the six known sections in hand-doc order), current plan/block + upcoming workouts, `metric_baselines`, recent weekly/monthly reviews (Batch 20), seasonal year-on-year (Batch 21, reused), experiments + their latest deterministic evaluation (Batch 22, reused), strength brief (Batch 19) — with the data-quality rules echoed under `dataQualityGuardrails`; `render_handover_markdown` (pure, no model) renders the portable markdown handover doc so the export always works and faithfully reflects current state (the round-trip guarantee), surfacing L/R balance only as a rule; `HandoverService.run` polishes it through the Batch 20 Anthropic boundary (handover-specific system prompt), stored in `analyses` as `handover_export`, idempotent per day, fakeable without `ANTHROPIC_API_KEY`; `GET /api/v1/handover` previews + never writes (experiments listed with `seed=False`), `POST /…/run` generates + stores, `GET /…/export` downloads the deterministic markdown as a `text/markdown` attachment; `/handover` PWA tab with deterministic preview + client-side download + generate-narrative. No migration, no new cron
- [x] **v3 Batch 22** — hypothesis evaluation shipped (PR #25, #83): deterministic, advisory per-experiment evaluator (`services/experiment_evaluation.py`) reusing the Batch 17 slope/Pearson math; dispatches on the experiment `slug` to three pure DB-free evaluators — **gate** (collagen: consecutive age-adjusted-74+ night streak → gate met = `supported`), **correlation** (early_waking_0400: Pearson-rank overnight low °C / sleep-stress vs an `awake_sleep_sec` disruption proxy → strong = `supported`, none = `refuted`; alcohol/late-snack surfaced as an unmeasured-coverage gap), **group_compare** (recovery_week_disruption: recovery- vs build-week mean age-adjusted sleep from `plan_blocks.block_type` → recovery worse = `supported`) — each skipping below its #71 sample gate; maps to a `supported`/`refuted`/`inconclusive` **recommendation only** that never changes status (concluding stays the human-gated terminal `POST /…/status` action, #72); `GET /api/v1/experiments/{id}/evaluate` previews and never writes, `POST /…/evaluate/run` records an `experiment_evaluation` audit row in `analyses` idempotent per (experiment, subject date); new `/experiments` PWA tab evaluates each hypothesis and accepts a recommendation through the existing conclude path. No migration, no LLM, no new cron
