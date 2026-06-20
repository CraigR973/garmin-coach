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
| **Hive** | `pyhiveapi` (sync) | email+pw, **no 2FA on his account** → headless re-login | Live indoor temp via `API(token).getAll()` → `parsed[i].props.temperature`. Refresh-token path bugged + device-tracked; just re-login (no 2FA) |
| **Weather** | Open-Meteo | none (keyless) | KA1 2SD = Kilmarnock, **lat 55.6045, long -4.5249**. `past_days` + `wind_speed_unit=mph` gives daily high/low + overnight low/wind |

Spikes live in `~/garmin-spike/` (outside this repo). Raw sample JSON in `~/garmin-spike/out/` (Garmin) and `out_hive/` (Hive) — **canonical reference for real field shapes**.

**Sync jobs (APScheduler):** Hive temp poll every ~15 min; morning Garmin+weather sync ~06:30 local → triggers morning analysis; hourly activity poll → on new ride triggers post-workout analysis. NB Training Readiness is time-of-day live → morning analysis must read in the morning. `recoveryTime` is in MINUTES.

### Workout delivery — OUTPUT (validated 19 Jun 26)

Push direction only — *not* a data source (ingestion stays direct-from-Garmin). The app emits a structured workout → POST to his **intervals.icu** calendar (free API; athlete `i618709`) → intervals.icu's approved Zwift Training-Connections integration delivers it into Zwift's Custom Workouts automatically. **Power + timing proven exact** end-to-end. intervals.icu is a **delivery rail, NOT the system-of-record** (our DB owns the plan). Deterministic **`.ZWO` export** is the no-dependency fallback. Any write to his trainer is **propose → approve → push**, never silent. Cadence nuance: Zwift overrides cadence on repeated-interval blocks with defaults (100/90) — emit cadence-critical reps as individual steps (confirm on PC). Spike: `~/garmin-spike/intervals_spike.py`.

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
