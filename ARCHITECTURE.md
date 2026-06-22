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
- **Auth:** name + PIN (bcrypt) + JWT access/refresh. Stripped of WC's leagues/groups/invites/email — **1–2 private users, no sign-up**.
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
- [ ] **Phase 2 Batch 16** — app-generated 13-week blocks (ready for closeout): deterministic generator (`services/block_generator.py`) emits a structured 13-week 2121 block from profile/FTP, reusing the shared block templates + Batch 14 VO2 toolkit (generated VO2 days carry 30/15); refine-then-lock workflow stored as JSONB in `knowledge_base` at `section='generated_block'` (versioned per generate/refine/lock); `lock` versions `plan_blocks` + active `planned_workouts` so the block feeds the daily loop and the Zwift rail on approval; `GET/POST /api/v1/block-generator/*` + `/builder` PWA tab (DECISIONS #69). No new migration
