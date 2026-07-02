# Design: Post-strength analysis (Batch 43)

**Status:** Implemented on branch `claude/batch-start-43-h33k5y`; backend +
frontend, no migration. Decision **#113**.
Designed as the direct counterpart to Batch 40 (post-flexibility) for the
strength sessions Mark tracks on his watch — added in the 2026-07-02 replan
(DECISIONS #108) after the in-app strength *player* (old Batch 38) was withdrawn.
Mark wanted only the post-workout *analysis* of his strength work, not an in-app
player to run the session. This is the per-session narrative that **complements**
(does not replace) the Batch 19 weekly rollup watching-brief.

Builds on / reuses:
- **Batch 8 post-workout analysis** as the architecture — `services/post_workout_analysis.py`:
  the `pending_* → assemble_packet → thin Anthropic Messages boundary → store in
  `analyses` with `analysis_type` + `activity_id`` shape, triggered by the hourly
  Garmin activity poll and surfaced on `/api/v1/daily-loop`. Same machinery as
  Batch 40, with a lean HR/consistency packet + a strength-coach prompt — *not* a
  reuse of the power-centric ride packet.
- **The existing strength selector** — `services/strength_brief.py`
  `is_strength_activity(activity)` (Batch 19), which delegates to the stored
  `exclude_from_recovery` flag set at Garmin ingestion for `strength_*` typeKeys
  (#49/#80). **No new classification code** — a test confirms it picks the
  strength sessions and rejects rides.
- **Batch 19's consistency rollup** — `compute_strength_rollup` +
  `StrengthSession`/`StrengthBriefResult`, reused as the packet's consistency
  read (4w / 12w frequency + trend) instead of a bespoke consistency function.
- **The recovery-isolation invariant (#49/#80)** — strength HR is wrist-based, so
  the session must never feed the Green/Amber/Red verdict or ride-recovery
  decisions. The analysis is advisory only.

## Why it is higher-reuse than Batch 40

Batch 40 had to add a name-based `is_flexibility_activity` selector and a bespoke
`compute_flexibility_consistency`. Batch 43 needs neither: the selector already
exists (`is_strength_activity` via `exclude_from_recovery`) and the consistency
read reuses `compute_strength_rollup`. The only genuinely new pieces are:

1. A **lean HR/consistency packet** (`assemble_strength_packet`) — duration,
   avg/max HR vs resting HR, the Batch 19 consistency rollup, planned session,
   and the activity-linked check-in. It **omits** power, FTP, cadence, stamina,
   Performance Condition, Training Effect, zones, and time-series — a strength
   session on a wrist HR monitor has no meaningful power/zone data and must not
   leak any into a recovery-adjacent read.
2. A **strength-coach `SYSTEM_PROMPT`** that acknowledges the session, reads
   frequency/consistency against the recent trend, flags an unusually high HR,
   and gives one light next step — with the wrist-HR / no-recovery-decision and
   no-power/zones guardrails.

## What the change adds

**Backend**
- `services/post_strength_analysis.py` — `PostStrengthAnalysisService` with
  `pending_strength_activities`, `assemble_strength_packet`,
  `generate_and_store` (idempotent per activity, regenerated on a newer
  activity-linked check-in), `generate_for_pending_strength`, and the
  `AnthropicStrengthAnalysisClient` boundary (fakeable without
  `ANTHROPIC_API_KEY`). `analysis_type='post_strength'`, `verdict='advisory'`.
- `scheduler.py` — the hourly Garmin activity poll runs the strength pass after
  the ride + flexibility passes, wrapped in its own try/except so a failure
  never blocks the other passes.
- `services/daily_loop.py` — `_post_strength_analyses` snapshot query +
  `ANALYSIS_TYPE_POST_STRENGTH`.
- `routers/daily_loop.py` — `PostStrengthAnalysisOut` + serializer +
  `postStrengthAnalyses` on the payload (the shared per-activity check-in map is
  reused, so a strength session's check-in is attached automatically).
- `strength_analysis_backfill.py` — `python -m src.strength_analysis_backfill
  --since YYYY-MM-DD [--commit]`, a dry-run/commit runner for the historical
  strength backlog (mirrors the flexibility/walk backfills).

**Shared**
- `dailyLoopPostStrengthAnalysisSchema` + `postStrengthAnalyses` on the daily
  loop schema.

**Frontend**
- `StrengthReadList` on the Home Today section (reuses the post-workout
  card + Markdown), rendered when `postStrengthAnalyses` is non-empty.

## Boundaries (kept)

- **No migration** — `analyses.analysis_type` is already `String(50)`.
- **Recovery isolation preserved** — advisory only; never feeds verdict/recovery,
  and the packet omits power/FTP/cadence/stamina/PC/TE/zones/time-series.
- **The Batch 19 rollup brief is unchanged** — this is the per-session read; the
  brief remains the weekly watching-brief. They are complementary.
- **No new cron, no new cloud call, no new ingestion** — strength activities are
  already synced into `activities`.

## Tests

- Pure: `is_strength_activity` selects strength / rejects rides (via
  `exclude_from_recovery`).
- DB-backed: lean packet (HR-vs-resting, reused consistency, no power/zone/
  time-series keys), idempotency, regenerate-on-newer-check-in, and daily-loop
  serialization of `postStrengthAnalyses`.
- Shared: the daily-loop post-strength schema shape parses.
- Web: the Home "Strength read" renders on the Today section.
