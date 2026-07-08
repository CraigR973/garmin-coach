# Status

> The cross-tool handoff doc. **Read the "Now" block at the start of a session;
> update it (and prepend to the Log) at the end.** See `AGENTS.md` for the
> handoff protocol, `DECISIONS.md` for why, `ARCHITECTURE.md` for the spec.

## Now

**Batch 66 - Swap-first recovery guidance - SHIPPED (PR #90, squash `73c2edf`), prod-verified.** 🔴 High, Decision #139, spec `docs/designs/workout-scheduling-feedback.md` — the second of the two workout-scheduling batches from Mark's 2026-07-07 feedback (65 split the sessions; 66 recommends *moving* them). **What it does:** the morning verdict used to only ever offer to *soften* a hard session on a cautious day; now, on an **Amber/Red** morning with a hard bike session (VO2/Sweet-Spot/Threshold) scheduled, it **leads** with a concrete week swap — "move it to <weekday> and bring <easier session> forward to today" — and that lead is **one-tap actionable** from Home's Today card, with softening kept as the explicit fallback. **How:** (66.1) new `coaching_protocol` KB section records the swap-first preference (`lowReadinessResponse.preference="swap_first"`), auto-seeded via `ensure_seeded`'s missing-section path. (66.2) new pure `plan_swap_first(items, subject_date)` in `weekly_restructure.py` reuses the engine's spacing primitives (`HARD_CATEGORIES`/`_conflicts`/`MIN_GAP_DAYS`) to find the soonest later bike day carrying an easier session the hard one can trade with while keeping the ≥2-day no-stack rule (returns `None` → soften when there's no hard session today or no sound swap); `assemble_context_packet` calls it on Amber/Red, prepends the swap lead to `planAdjustments`, and attaches `verdict.swapSuggestion`. `SYSTEM_PROMPT` gained a swap-first instruction; `PROMPT_VERSION`→`morning-analysis-v6-2026-07-08`. (66.3) daily-loop `AnalysisOut` + shared `dailyLoopAnalysisSchema` carry an optional `swapSuggestion`; the new `SwapSuggestionCard` on the Today card fires the **existing** category-scoped `swap_day` in one tap — no new endpoint. **Scope call (documented in #139):** the spec's *preferred* "restructure preview → apply" surface was **not** wired — `WeeklyRestructureService.apply_for_week` re-versions a whole date (`_version_workout`), so after Batch 65's split Saturdays it would silently drop the day's strength row. The batch takes the spec's sanctioned fallback (read-only suggestion + the Batch 65-safe `swap_day`) and does **not** make `apply_for_week` newly reachable, so that latent data-loss stays contained. **Boundaries:** no migration; the Green/Amber/Red rules, #133 soft-sleep, #134 completion/check-in, #135 Poor-readiness, and Red-never-VO2 are all untouched (`adjust_ir_for_verdict` + `blocks_red_vo2` unchanged; a swapped VO2 satisfies no-stack by construction). **Gates:** backend pytest **511 passed / 167 skipped** locally (7 new pure `plan_swap_first` tests; 2 new DB-backed morning-analysis integration tests — swap leads + softening fallback, Green no-suggestion — run in CI), ruff check + format clean, mypy 98 files clean; shared typecheck + **13** tests; web `tsc` clean, lint 0 errors (6 pre-existing Fast-Refresh warnings), vitest **181 passed / 30 files**, build clean under Node 20. **Closeout:** PR #90 CI went green in both push and PR contexts across all 7 jobs (pytest incl. the DB-backed swap tests, mypy, ruff, Alembic migration check, web build, web+shared vitest, security audit) plus a successful Vercel preview deploy; squash-merged to `main` as `73c2edf`. (A one-line CI fix `9cef61b` on the branch corrected a case-sensitive test assertion — `adjustments[0].lower()` searched for a capital-S substring — surfaced only in CI because that DB test skips locally.) **Production verified on the merge SHA:** Railway and Vercel same-origin `/api/v1/health` via `garmin-coach-one.vercel.app` both returned `73c2edf706aeb31d85f7d6408d07f1e252c52c82`, web `/` returned 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via the Vercel rewrite (the batch adds `swapSuggestion` to that auth-gated payload; no new endpoint). The Vercel `/api/*` proxy is healthy on the canonical `garmin-coach-one` alias (the Batch 64-flagged whole-surface 404 is not present here). **Next step:** `docs/phase-batches.md` has no remaining unshipped batch — both 2026-07-07 workout-scheduling batches (65/66) are now shipped; pick the next priority with Craig. **Flagged follow-up (out of scope, spawned as a background task):** fix `weekly_restructure._version_workout` to preserve non-bike sessions on a changed date before any restructure preview→apply UI is built. **Open (carried):** (a) `garmin-coach.vercel.app` stale alias `/api/*` 404 — use `garmin-coach-one.vercel.app` for same-origin smoke; (b) RLS disabled on 16 `coach.*` tables; (c) genuine POOR-readiness days remain a coaching/data question; (d) runtime coaching model still `claude-sonnet-4-6`.

---

**Prior — Batch 65 - Separate cycling & strength + correct Mon/Sat mapping - SHIPPED (PR #89, squash `cc445ac`), prod data + Zwift delivery verified.** High, Decision **#138** (spec `docs/designs/workout-scheduling-feedback.md`), first of the two workout-scheduling batches from Mark's 2026-07-07 feedback; Batch 66 - swap-first recovery guidance - remains `Planned`. **What shipped:** Plan No. 2 now has Dumbbells on every Monday and, on build-week Saturdays, a separate `bike_endurance` "Z2 + Neuromuscular" v1 row plus a Bodyweight `strength_maintenance` v2 row; recovery/consolidation/taper Saturdays stay ride-only. `import_plan` assigns per-date versions so same-day rows do not collide, and `swap_day` now scopes target detection to the source workout category so moving a ride never drags a same-day strength/flexibility row. **Boundaries:** no migration, no plan-editor UI, no bike prescription rewrite, and verdict / #133 / #134 / #135 / Red-never-VO2 invariants untouched. **Closeout evidence:** PR #89 CI was fully green in both branch-push and PR contexts (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest), plus Vercel preview; squash-merged to `main` as `cc445acd0f90d1fc30b9d81142b1f29f632542bb`. Production smoke on the merge SHA passed: Railway `/api/v1/health` and Vercel same-origin health via `garmin-coach-one.vercel.app` both returned `cc445ac...`, web `/` returned 200, and unauthenticated `GET /api/v1/plan-actions/schedule` returned 401 direct against Railway. **65.4 prod data step completed:** dry-run and apply both replaced the prior forward import from **2026-07-13** (13 blocks / 78 workouts) with 13 blocks / **87** workouts; a production shape query confirmed **65 bike + 22 strength** active forward rows through 2026-10-11, Mondays are Dumbbells, build Saturdays have ride v1 + Bodyweight v2, and non-build Saturdays remain ride-only. `reconcile_deliveries` then pushed/re-synced **65** bike sessions to Zwift with Intervals.icu event IDs. **Next step:** `/batch-start 66` when ready. **Open (carried):** (a) `garmin-coach.vercel.app` still appears to be an old/stale alias with `/api/*` 404; use the fresh production alias `garmin-coach-one.vercel.app` for same-origin smoke unless Craig rewires the canonical domain; (b) RLS disabled on 16 `coach.*` tables; (c) genuine POOR-readiness days remain a coaching/data question; (d) runtime coaching model still `claude-sonnet-4-6`.

---

**Prior — Batch 64 — Rate & correct any summary (feedback primitive) — SHIPPED (PR #88, squash `c6ebfec`); production HTTP smoke pending manual confirmation.** 🔴 High, part of Decision **#137** (spec `docs/designs/summary-feedback.md`), the second of the two batches from Mark's 2026-07-07 feedback-primitive ask (63 lightened the check-in; 64 adds rate-&-correct). **What it does:** every AI summary is one `analyses` row, so a single primitive keyed to `analysis_id` covers the whole app. **(64.1)** new `feedback` table + migration **`013`** — `id`/`user_id`→profiles CASCADE/`analysis_id`→analyses CASCADE/`kind` (`summary`|`suggestion`)/`rating`/`correction_text` nullable/`created_utc`, **unique `(user_id, analysis_id)`** for upsert + index. **(64.2)** `PUT /api/v1/analyses/{analysis_id}/feedback` (new `routers/feedback.py` + `services/feedback.py`) in the `{data,meta,errors}` envelope, **user-scoped**: 404 if the analysis doesn't exist, 403 if it's another profile's, 422 if the rating doesn't match the kind; `feedbackInputSchema`/`feedbackSchema` added to `packages/shared`; the daily-loop serializers + `/reviews` `StoredReview` now surface each analysis's existing `feedback` (one batched `feedback_for_analyses` query on the snapshot) so the widget shows current state. **(64.3)** reusable `FeedbackControl` — one-tap axis buttons (**accuracy** for summaries: spot on/a bit off/way off; **agreement** for suggested edits: agree/not for me/already doing), negative tap reveals an optional "what did we get wrong?" textarea (the correction is the real payload) — mounted on the Home verdict (kind = `suggestion` when the verdict carries a plan adjustment, else `summary`, since one row per analysis), the post-session read cards (ride/flexibility/strength/walk), and the `/reviews` written review. **(64.4)** the morning **and** post-workout context-packet assemblers now carry the 5 most-recent free-text corrections (`recentCorrections`); both system prompts weigh them as ground truth **without** overriding the Red floor / #133 soft-sleep / #135 Poor-readiness / Red-never-VO2; `PROMPT_VERSION` bumped (`morning-analysis-v5-2026-07-08`, `post-workout-analysis-v3-2026-07-08` — the post-workout bump also re-generates older reads via `_analysis_is_current`). **Boundaries:** no rating dashboard/aggregation (n=1 — the correction is the value); corrections **feed the next read**, no auto-regenerate; `/sleep` client-side review has no control in v1 (not an `analyses` row — piggybacks on the morning analysis); no separate suggestion entity. **Verification (all local, green):** migration `013` up→012→up verified against a local Postgres 16 and the table matches the model, single alembic head `013`; backend **665 passed** (incl. new `test_feedback.py`: endpoint upsert/one-row, 404, 403, 422, recent-corrections newest-first-text-only, scoped surfacing, morning-packet-includes-corrections), ruff + `ruff format --check` clean, mypy **98 files** clean; shared typecheck + **12** tests; web `tsc` clean, lint 0 errors (6 pre-existing Fast-Refresh warnings), full web vitest **179 passed** (new `FeedbackControl.test.tsx`), build clean under Node 22. **Closeout status:** PR #88 CI went **fully green** across all 7 jobs (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest) in **both** push and PR contexts, plus a successful Vercel preview deploy; squash-merged to `main` as `c6ebfec`. **Production verified on the Railway backend (egress reached the hosts this time):** after the merge + the docs redeploy, Railway `/api/v1/health` returns `{"status":"ok","sha":"c86d574…"}` (the latest `main`), which means **migration `013` applied cleanly on container startup** (the healthcheck gates cutover, so a failed migration would have kept the old container serving) — and it held across both the feature deploy (`c6ebfec`) and the docs redeploy (`c86d574`); the batch-specific non-mutating check — unauthenticated `PUT /api/v1/analyses/{uuid}/feedback` — returns **401** direct against Railway. `013` was also verified up→down→up locally. **One anomaly flagged for Craig (NOT this batch):** the Vercel `/api/*` → Railway rewrite is returning **404 for every endpoint** (health, daily-loop, feedback identically) while the web root serves **200** and direct Railway is correct — the `vercel.json` rewrite is unchanged by this batch, so this is a pre-existing/infra condition on the whole API proxy surface, not a feedback regression; it needs a look at the Vercel production deployment independent of Batch 64. **Next step:** Craig checks the Vercel `/api/*` proxy (it 404s the whole API surface, including endpoints that predate this batch); then the workout-scheduling batches **65/66** (both `Planned`, spec `docs/designs/workout-scheduling-feedback.md`) are the open frontier. **Open (carried):** (a) 🔒 RLS disabled on 16 `coach.*` tables; (b) genuine POOR-readiness days remain a separate coaching/data question; (c) runtime coaching model still `claude-sonnet-4-6`.

---

**Prior — Batch 63 — Lighten the morning check-in (fast path) — SHIPPED (PR #87, squash `bc17f59`); production HTTP smoke pending manual confirmation.** 🟢 Mid, Decision **#137** (spec `docs/designs/summary-feedback.md`). Cuts `/check-in` from a multi-card form to a quick tap: an "Overall" 5-button group (Rough/Meh/OK/Good/Great → `subjective_score` 2/4/6/8/10) plus three one-tap chips (Slept well / Low energy → `feel`; Niggle → `notes`, folded in as a comma-joined token via `toggleToken`/`hasToken`) are the whole default surface; BP, the free-text "in a few words"/notes inputs, supplements/food, and per-workout adherence all move behind a reused `CollapsibleSection` "More" (collapsed by default, reachable, never required). **Reuses the existing engine end to end** — same `manualEntryInputSchema` + `PUT /api/v1/daily-loop/{date}/manual-entry`, same single "Save check-in" action, and the endpoint's existing `regenerate_after_morning_checkin` call (unconditional on subject_date, unchanged) still fires on a quick save — so **no backend change, no new endpoint, no migration, no shared-schema change**. `homeActions.ts` was not touched: the morning check-in was already optional (revises #127 via #134) with no blocking `!manualEntry` rung, and the existing "Morning check-in" links (Home Today footer, `/sleep` foot) now point at the quick form by default, satisfying 63.3 with zero Home-side edits. **Verification:** `CheckInPage.test.tsx` rewritten (quick-save-with-no-typing, chip→column toggle mapping, BP/adherence still saves behind "More", error state stays usable) — full web gates green: `tsc --noEmit` clean, lint 0 errors (6 pre-existing Fast-Refresh warnings), full vitest **174 passed** (was 169), build clean under Node 20; shared package unchanged (**12** tests, typecheck clean). **Closeout status:** PR #87 CI went **fully green** across all 7 jobs (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest) in **both** push and PR contexts, plus a successful Vercel preview deploy; squash-merged to `main` as `bc17f59`. **Production HTTP smoke NOT run from this environment** — the agent egress policy denies CONNECT (403) to `api-production-e2bc7.up.railway.app` and `garmin-coach.vercel.app` (confirmed via `$HTTPS_PROXY/__agentproxy/status`'s `recentRelayFailures`, not transient), so the standard merge-SHA smoke (Railway + Vercel same-origin `/api/v1/health` returns `bc17f59…`, web `/check-in` 200, unauthenticated `GET /api/v1/daily-loop` 401 direct + via Vercel) must be run by Craig from a permitted network. **Deploy risk is low:** no migration (schema unchanged at `012`), no backend/shared file touched, and the Vercel preview already built the frontend clean. **Next step:** Craig confirms the prod smoke; then either scope Batch 64 (rate & correct any summary, 🔴 High, `feedback` table + migration `013`) or the workout-scheduling batches 65/66 (both `Planned`, spec `docs/designs/workout-scheduling-feedback.md`). **Open (carried):** (a) 🔒 RLS disabled on 16 `coach.*` tables; (b) genuine POOR-readiness days remain a separate coaching/data question; (c) runtime coaching model still `claude-sonnet-4-6`.

---

**Prior — Batch 62 — First-open latency: persist cache & thin daily-loop — SHIPPED (PR #86, squash `8a60a76`); production HTTP smoke pending manual confirmation.** 🔴 High, Decision **#136** (spec `docs/designs/first-open-performance.md`). Fixes "data is slow to load when I first open the app" — measured first: warm prod `/api/v1/health` is ~0.10 s, so it is **not** a container cold-start; the real causes are an empty client cache on a fresh PWA launch + `GET /api/v1/daily-loop` being the fattest endpoint. **What it does:** **(62.1)** `App.tsx` swaps to `PersistQueryClientProvider` (new `lib/queryClient.ts` centralises client + persister + `clearPersistedCache()`), persisting **only** a successful `daily-loop` query to `localStorage` with `maxAge` 24 h + `buster`=build SHA (vite `define __APP_BUSTER__` ← `VERCEL_GIT_COMMIT_SHA`); `useDailyLoop` gets `staleTime` 60 s; login/activate/unlock/logout clear the persisted cache alongside `queryClient.clear()`. All three `@tanstack` packages pinned to `5.101.2` to dedupe `query-core`. **(62.2)** `run_morning_weather_sync` precomputes the 120-day driver correlation once via new `InsightsService.record_drivers` (stored in the existing `analyses` `driver_correlation` audit row, **no migration**); `_envelope` reads it back via `cached_drivers`, falling back to live compute when absent — payload identical, only *when* it's computed moves. **(62.3)** the four post-`{workout,flexibility,strength,walk}` analysis SELECTs collapse into one `analysis_type IN (...)` query partitioned in Python, order-preserving. **(62.4)** new `run_connection_warmup` job runs `SELECT 1` every 10 min inside the 30-min `pool_recycle`. **(62.5)** the daily-loop GET handler logs `snapshot_ms`/`envelope_ms`/`total_ms`. **Scope deviation (documented in #136):** the spec's brief-parallelization half of 62.3 was **built then reverted** — separate `AsyncSessionLocal()` sessions break read-your-writes within the request transaction (the identical-payload snapshot test caught it) and the win is marginal for 1–2 users; only the safe SELECT collapse ships (the spec sanctions this staging). **Boundaries:** no verdict/analysis/sleep-scoring/#133/#134/#135/Red-never-VO2 change — *when*/*how fast*, never *what*. No migration. New health data at rest in `localStorage` (bounded by `maxAge` + daily-loop-only dehydrate + logout clear). **Verification (all local, green):** backend full pytest **658 passed** against a local UTF8 Postgres (incl. new identical-payload/read-through/collapse tests; earlier `SQL_ASCII` local runs mismatched CI encoding — recreating the DB as UTF8 matched CI and went green), ruff + `ruff format --check` clean, mypy **96 files** clean; shared typecheck + **12** tests; web `tsc` clean, lint **0 errors** (6 known Fast-Refresh warnings), full web vitest **172 passed** (new `lib/queryClient.test.ts`), web build clean under Node 22. **Closeout status:** PR #86 CI went **fully green** across all 7 jobs (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest) in **both** push and PR contexts, plus a successful Vercel preview deploy; squash-merged to `main` as `8a60a76`. **Production HTTP smoke NOT run from this environment** — the agent egress policy denies CONNECT (403) to `api-production-e2bc7.up.railway.app` and `garmin-coach.vercel.app`, so the standard merge-SHA smoke (Railway + Vercel same-origin `/api/v1/health` returns `8a60a76…`, web `/` 200, unauthenticated `GET /api/v1/daily-loop` 401 direct + via Vercel) and the before/after `railway run` daily-loop timing + Railway↔Supabase colocation check must be run by Craig from a permitted network. **Deploy risk is low:** no migration (schema unchanged at `012`), and the Vercel preview already built the frontend clean. **Next step:** Craig confirms the prod smoke + captures the daily-loop timing; then the daily-flow/summary-feedback/scheduling plans (Batches 63–66, all `Planned`) are the open frontier. **Open (carried, Craig's call):** (a) 🔒 RLS disabled on 16 `coach.*` tables; (b) genuine POOR-readiness days are a separate coaching/data question; (c) runtime coaching model still `claude-sonnet-4-6`.

---

**Prior — Batch 61 — Age-adjusted sleep norms & real age-adjusted score — SHIPPED (PR #84, squash `7936fcb`), prod-verified.** Decision **#135** replaces the flat Garmin `+4` with a pure `services/sleep_scoring.py` recompute from stored `sleepScores` factors + stage seconds + profile age/sex, using age-band credit with calibration and raw-score downgrade guards. `garmin_sync` no longer writes the old `+4`; morning analysis recomputes live, writes the row forward-only, bumps `PROMPT_VERSION` to `morning-analysis-v4-2026-07-06`, and treats Garmin **Poor** readiness as a hard cautious gate (the live safety probe found this mattered). `age_norms.py` now emits healthy sleep-stage bands (`bandLow`/`bandHigh`) plus nullable Garmin young-adult targets for REM/Deep/Light; Restless is descriptive-only. Chronic patterns, DB-history baselines, and reviews use the central scorer when profile context exists and fall back to stored history otherwise. Shared schemas accept the widened row shape, and `/sleep` now shows **Healthy range (50–59)** with a quiet Garmin-target contrast disclosure while Home's compact table stays unchanged. **Read-only prod safety probe via `railway run`:** Mark has 375 scored sleep rows, all with stage factors; 21 rows cross from old stored `<74` to new `>=74`, and the 4 Poor-readiness threshold-crossing days (2026-04-08, 2026-05-24, 2026-05-30, 2026-06-01) now resolve **Amber**, not Green. **Verification:** local backend full pytest **502 passed / 152 skipped** (3 existing warnings), repo-wide ruff format/check clean, backend mypy **96 files** clean; shared typecheck + **12** tests; web typecheck/lint clean (6 known Fast-Refresh warnings), full web vitest **163**, web build clean under Node 20. PR #84 CI went green across both push and PR contexts after DB-backed morning-analysis expectations were aligned with the new recompute. **Production verified on the merge SHA:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=7936fcbb0cb7e48e7ff03f6eeadd81f81c2e3523`, web `/` and `/sleep` returned 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via Vercel. **Next step:** no unshipped batch is queued; pick the next priority from the open items. **Open (unchanged from #133):** (a) 🔒 RLS disabled on 16 `coach.*` tables; (b) genuine POOR-readiness days remain a separate coaching/data question; (c) runtime model still `claude-sonnet-4-6`.

---

**Prior — Batch 60 — Completed-workout consolidation — SHIPPED (PR #83, squash `23de7e7`), prod-verified.** From Mark's 2026-07-06 feedback (three snags: a done ride's Today row still showed approve/upload/ignore with its read in a separate section; no check-in from Sleep; completed workouts were still movable). **Verified before scoping:** `PlannedWorkout.status` never became `completed` (dead enum) and there was no stored workout↔analysis link — so completion is now *persisted*, not derived (Craig's `/batch-start` call), and the Home display is *compact + link* (his other call). **What it does:** (1) migration `012` adds `analyses.planned_workout_id`; new `services/workout_completion.py` `complete_matched_planned_workout` matches an activity to the day's planned session by local date + `cycle` category (spreads two same-day rides, idempotent); `PostWorkoutAnalysisService.generate_and_store` links the analysis + flips the matched bike workout to `status='completed'`; the daily-loop ride analysis carries `plannedWorkoutId`. (2) `DashboardPage` `WorkoutRow` on `status==='completed'` drops the approve/upload/edit/swap/skip controls and shows a compact ✓ Completed state — tomorrow-impact + ride check-in + full read/interval table behind a "View analysis" disclosure; the standalone "After your ride" section is kept **only for unplanned rides** (`plannedWorkoutId==null`); `homeActions` points a matched unlogged ride at the Today card. (3) `swap_day` 409s a completed source *or* target; the Plan view hides Move + shows a "Done" badge (both off `status`). (4) the morning check-in is made **optional** and folded into the sleep review as one step (revises #127): the blocking `!manualEntry` rung is removed from `homeActions` (both ladders; the `check-in` action key retired), so reviewing last night is the one required morning step and a pending eased ride surfaces right after it; `/sleep` frames the check-in as an optional card, still one tap from the Today footer. **Scope boundary:** ride-scoped (strength/flexibility/walk completion is a fast-follow on the same helper); no historical backfill (today's rides flip on the next hourly poll). **Verification:** CI green across all 7 jobs (backend pytest incl. the DB flip/link + swap-409 tests against CI Postgres, Alembic `012` up/down, ruff, mypy, web build, web+shared vitest, security audit) + Vercel preview; squash-merged to `main` as `23de7e7`. **Production verified on the merge SHA:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=23de7e7944a034490d4514cc9ef52013e31a23d7` (the backend healthcheck passed → migration 012 ran cleanly on startup), web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Local gates: pytest **486/152**, shared **11**, web **162**, all lint/type/build clean under Node 20. Decision **#134** (the check-in-optional follow-up revises **#127**). **First-live-use:** the completed-row state + move-lock only take effect once Mark completes a ride post-deploy (the hourly poll flips `status='completed'`); nothing to backfill.

---

**Prior — Decision #133 — personal-readiness soft-sleep override — SHIPPED (PR #82, squash `5551aa6`), prod-verified; and batches 56–59 prod-validated against Mark's real data.** Follow-up to #129, found by running `scripts/diagnose_coaching_data.sql` against prod via the Supabase MCP (data lives in the **`coach` schema**, single user, 377 *contiguous* days 2025-06-24→now). **Validation outcome:** every complaint was real, and the data is healthy — so B1 "last year missing" was a calc/narration problem, not a data gap; but every stored output **and** the baselines predated the deploy, so the shipped fixes were un-exercised. **Three regenerations run (via `railway run`, real services — no faked rows):** (1) **`metric_baselines` rebuilt** → created the missing `readiness_score` band; (2) **monthly+weekly reviews + month+season trends** force-regenerated to `*-v3` — the monthly review now reads *"76.0 sits above your personal median of 53.5… a watch-and-monitor signal, not an alarm"* (was *"Recovery is drifting downward… decreasing"*) and the trends show real **July-2026-vs-July-2025 YoY**; (3) the **2026-07-05 morning verdict** force-regenerated → **Amber→Green**. **#133 itself:** `_soft_sleep_recovery_override` now gates readiness on his **baseline median (53.5)** not a generic `≥70` — his readiness genuinely runs Moderate, so the flat 70 rejected normal-for-him mornings (07-05 = readiness 66, RHR 43, balanced HRV, sleep 72). A per-metric check confirmed `readiness_level` maps cleanly to score (POOR ≤16 … HIGH 76–86) so the lows are **genuine** (no data cleaning); Red floor + downgrade-only + Red-never-VO2 intact. `PROMPT_VERSION`→`morning-analysis-v3-2026-07-05`. Backend **486 passed / 149 skipped**, ruff/mypy clean; PR #82 CI green; prod on `5551aa6`; the 07-05 verdict verified **Green** (v3, `softOverride=true`) as the latest row in `coach.analyses`. **Open items (Craig's call):** (a) 🔒 Supabase advisor flags **RLS disabled** on 16 `coach.*` tables — surfaced, not fixed (real exposure depends on whether the Data API exposes the `coach` schema; the app uses FastAPI+asyncpg, not the anon key); (b) Mark has frequent *genuine* **POOR readiness** days (17/85 nights ≤16) worth a look; (c) the runtime coaching model is still `claude-sonnet-4-6` (`config.py:53`). **Next step:** Mark's 2026-07-05 punch-list is fully addressed and live — pick the next priority with Craig. Full writeup: `docs/designs/coaching-calibration-and-data-truth.md`.

---

**Prior — Batch 59 — Chronic-pattern suggestions — SHIPPED (PR #81, squash `fb90e3e`), prod-verified.** 🔴 High, additive daily-loop/read-surface work with no migration, no new endpoint, and no verdict/delivery-rule change (DECISIONS #132; spec `docs/designs/coaching-calibration-and-data-truth.md`). New pure `services/chronic_patterns.py` looks across the last 4 weeks of sleep, requires at least 21 observed nights, and flags repeated misses against age norms (REM, Deep, Duration, Awake, Restless; Light is deliberately not suggestion-driving) plus personal-baseline bands where they exist (sleep score, age-adjusted sleep, readiness, HRV, resting HR). Suggestions are deterministic and evidence-windowed, with explicit `insufficient_history` / `clear` / `active` states; action mapping is grounded in the sleep protocol and prioritises the strongest measured sleep driver from `InsightsService.drivers()` (reusing the same driver report already needed for `sleepProjection`, so the daily-loop read avoids duplicate correlation work). `/api/v1/daily-loop` now carries optional `chronicSuggestions`; shared schemas parse it; `ChronicSuggestionsCard` renders inside `SleepSnapshotBody`, so both Home's "Last night's sleep" section and `/sleep` surface the same suggestions. **Verification:** backend `test_chronic_patterns.py` + `test_age_norms.py` **12 passed**; touched backend ruff/format/mypy clean; shared schema vitest **10 passed** and typecheck clean; focused `SleepPage.test.tsx` **5 passed**; web typecheck clean; web lint 0 errors (6 known Fast-Refresh warnings); web build clean under Node 20. PR #81 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and web/shared vitest, plus the Vercel preview; squash-merged to `main` as `fb90e3e`. **Production verified on merge SHA `fb90e3e`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=fb90e3e16ec4936143d52aeff9d2debd09c40c73`, web `/` and `/sleep` both returned 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via the Vercel rewrite. **Next step:** `docs/phase-batches.md` has no remaining unshipped batch — pick the next priority from Mark's 2026-07-05 feedback punch-list (see the dated entry below) or scope a new one with Craig.

---

**Prior — Batch 58 — Sleep-stage age-comparison table — SHIPPED (PR #80, squash `9c96bb6`), prod-verified.** 🟢 Mid, additive backend/shared/frontend work with no migration and no new endpoint (DECISIONS #131; spec `docs/designs/coaching-calibration-and-data-truth.md`). Extended the existing morning-analysis `ageComparison` packet instead of adding a parallel route: `services/age_norms.py` keeps the compact `rows` for Home's headline table and adds a sibling `sleepRows` group for the deeper Sleep-page read. The new sleep rows compare **Duration, Deep, Light, REM, Awake, and Restless** against coarse age-band norms, using **sleep-stage percentages** (not raw minutes) for Deep/Light/REM/Awake so the comparison tracks stage mix rather than just time in bed. `morning_analysis._age_comparison` threads sleep duration/stages/restless count from the synced `Sleep` row, shared Zod schemas parse the widened payload, and `/sleep` renders a dedicated "Sleep stages vs your age" table while Home's compact `MetricComparisonTable` stays unchanged. **Verification:** backend `test_age_norms.py` **9 passed**, touched backend mypy clean, shared schema vitest **10 passed**, focused web vitest **14 passed**, web lint 0 errors (6 known Fast-Refresh warnings), and web build clean under Node 20. PR #80 was squash-merged as `9c96bb6`; a narrow follow-up `chore: format batch 58 age norms` (`080e763`) fixed the repo-wide `ruff format --check` gate on `main`, after which the full main CI wave went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and web/shared tests. **Production verified on final shipped SHA `080e763`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=080e7634cd03c47ee6d42124e853b22fabf39595`, web `/` and `/sleep` returned 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via Vercel. **Next step:** Batch 59 — Chronic-pattern suggestions.

---

**Prior — Batch 55 — Screen polish & states — SHIPPED (PR #76, squash `aa2c7e0`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #125; spec `docs/designs/screen-polish-states.md`). Last of the four front-end premium batches — finishes the calm-premium pass across Sleep/Check-in/Week and adds a shared empty/error/offline pattern; **the front-end premium plan (Batches 52–55) is now fully shipped.** **Three open calls settled at `/batch-start`:** the "vs your age" column folds into a per-row descriptor (not kept as a column); the shared pattern is say-what-happened + a single recovery CTA; Check-in moves to one unified save action (not per-section). **What it does:** new `components/EmptyState.tsx` exports `ErrorState` (always a retry CTA), `EmptyState` (action optional), and `OfflineNotice` (a quiet status row) sharing one dashed-border shell, now used on Home/Sleep/Week/Check-in's loading-failed branches (Check-in previously had none at all); `MetricComparisonTable` drops the mostly-empty "vs your age" column and folds it into a tinted sub-line under each row's value, only where an age norm exists; `CheckInPage`'s five save buttons (one per card/workout) collapse into a single "Save check-in" that fires the manual-entry PUT then every workout's adherence PUT in sequence, same endpoints; `SleepPrepBody`'s evidence disclosure is lightened from a bordered pill to a quiet muted-text toggle; `WeekAheadPage`'s instructional card drops to plain text (reduced nesting). **Verification:** full web vitest **147 passed / 27 files**; `tsc --noEmit` clean; web lint 0 errors (6 pre-existing Fast-Refresh warnings); web build clean under Node 20; backend/shared untouched. **Live-verified** in a headless preview against a temporary local mock `/api` (reverted before commit): logged in and walked Home, Check-in (unified save confirmed via network log — both PUTs fired from one click), Sleep (folded age descriptors, lightened evidence disclosure), and Week, dark mode, no console errors. PR #76 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and the Vercel preview; squash-merged to `main` as `aa2c7e0`. **Production verified on merge SHA `aa2c7e0`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=aa2c7e0f5355497af1b047b8d8339e9014cda111`, web `/` and `/login` both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. **Next step:** the front-end premium plan (Batches 52–55) is complete; no batch is currently queued — pick the next priority from `docs/phase-batches.md` or scope a new one with Craig.

---

**Prior — Batch 54 — Home hierarchy & calm density — SHIPPED (PR #75, squash `8fb90a2`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #124; spec `docs/designs/home-hierarchy-calm-density.md`). Third of the four front-end premium batches — turns Home from a wall of equal accordions into a curated brief. **What it does:** a new pure `splitPrimaryDetail` in `lib/homeSections.ts` splits the one lead/primary section (unchanged prominence) from the rest, which now render under a quiet "More detail" label with a new `CollapsibleSection` `variant="secondary"` (lighter title, borderless card) — collapse-not-remove, the one-expanded model, the evening float, and the Batch 51 desktop lanes are all unchanged. The session card's five-button cluster (`WorkoutRowActions`, new) collapses to one primary + one secondary + a "More options" `DropdownMenu` overflow. The greeting/date lockup is now a compact line instead of the full `PageHeader` h1, so `VerdictHero` sits higher on load. A new `lib/truncate.ts` (`truncateWords`) truncates collapsed summaries on a word boundary instead of a mid-word CSS ellipsis. `CollapsibleSection`'s body now animates in with `framer-motion` (fade + settle, honouring `prefers-reduced-motion` via the same `useReducedMotionConfig` hook `score-input.tsx` already uses). **Verification:** local rerun green (`pnpm --dir apps/web test` → **137 passed / 28 files**; `pnpm --dir apps/web lint` → 0 errors / 6 known Fast-Refresh warnings; `pnpm --dir apps/web build` clean under Node 20). PR #75 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and the Vercel preview; the preview deploy loaded on the public auth shell and the merge went through as `8fb90a2`. **Production verified on merge SHA `8fb90a2`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=8fb90a2f293f16b480c6ba6900d7aac9955b5725`, web `/` and `/login` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. **Next step:** continue the front-end premium plan with **Batch 55 — Screen polish & states**.

---

**Prior — Batch 53 — Branded verdict, hero & login — SHIPPED (PR #74, squash `c84945e`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #123; spec `docs/designs/branded-verdict-hero-login.md`). The second front-end premium batch brings the generated CheckMark mark into the running app and keeps the Batch 52 calm-premium base. **What it does:** `Brand.tsx` now exports a reusable `Logomark` that renders the generated `public/brand/checkmark-icon-primary.svg` asset (no hand-edited SVG); compact/splash wordmarks can include the mark, and the splash wordmark uses the existing `--wordmark-gradient`. `VerdictHero` is rebuilt as the most crafted object on Home: elevated surface, branded mark ring, Green/Amber/Red/pending semantics and `verdictCopy` unchanged. Login is mark-led with tighter vertical rhythm and the invitation/PIN fallback flow unchanged. `TopBar` mobile and desktop lockups now include the mark. Home's `NextActionStrip` is promoted from a small outline strip to a full-width primary action band under the verdict, using brass as the one secondary accent while warning states stay warning-coloured; the all-clear state remains a quiet status row. **Boundaries kept:** presentation only; no verdict logic, daily-loop payload, endpoint, auth flow, migration, or rebrand change. **Verification:** local focused vitest `VerdictHero.test.tsx LoginPage.test.tsx Nav.test.tsx DashboardPage.test.tsx` (36 passed); full web vitest **123 passed / 24 files**; `pnpm --dir apps/web typecheck` clean; `pnpm --dir apps/web lint` 0 errors / 6 known Fast-Refresh warnings; `pnpm --dir apps/web build` clean; local browser visual pass confirmed login, mobile Home, and desktop Home render the mark/verdict ring/action band with no horizontal overflow. PR #74 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and Vercel preview; squash-merged to `main` as `c84945e`. **Production verified on merge SHA `c84945e`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=c84945ef6fed1d514730de6376fa60e395b87778`, web `/` and `/login` both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. **Next step:** continue the front-end premium plan with **Batch 55 — Screen polish & states** after Batch 54.

**Batch 52 — Design foundations (token + primitive tier) — SHIPPED (PR #72, squash `41f6734`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #122; spec `docs/designs/design-foundations.md`). The **first** of the four front-end premium batches (52–55) and the load-bearing one 53–55 inherit — it lifts the shipped design system from "developer-dark" to "calm premium" at the **token + primitive layer only**, with no per-screen layout change. **What it does:** (1) **re-spaces the dark surface/border ramp** into a clear value ramp — `bg #0A1112→#0A1314`, `surface #111E1F→#152628`, `elevated #192A2B→#1F383A`, `overlay #213436→#294648`, `border #253A3C→#2E4C4E`, `border-strong #345355→#3D5F61` (each surface step ~+8 CIELab L\* vs the old ~+5, chosen by a throwaway CIELab/WCAG evaluator not eyeballing), keeping the teal-graphite hue; **shadows softened** (value carries depth, not glossy drop-shadows) and the focus `--shadow-glow` strengthened 0.25→0.35; (2) **redesigns the input/control tier** — new `--control`/`--control-border` fill (`#223C3E`/`#436769` dark, `#FFFFFF`/`#CBD2D9` light) so inputs are raised, legible fields (was dark-on-dark `bg-bg`), applied to `Input`, a **new shared `Textarea` primitive** (replacing the two ad-hoc `textareaClassName` copies in `DashboardPage`/`CheckInPage`), and `Select` (trigger on control fill; dropdown → elevated, item-hover → overlay); **text AA held in both palettes** — dark muted `#7B859B→#98A2B4` + secondary `#94A3B8→#A6B4C4` (clears AA ≥4.6:1 even on the control fill, ordering preserved), and **light muted `#8A93A1→#6B7280` fixes a real pre-existing AA failure** (~2.8:1 on white); (3) **pulls mono-uppercase back to eyebrows** — the `Label` primitive is now sentence-case at `text-sm`, with a documented type scale added to `index.css`. `theme/tokens.ts` mirrors every value (and its stale teal `shadow.glow` was synced to the emerald CSS var); `tailwind.config.ts` exposes the `control` utilities; the PWA/status-bar `theme-color` (index.html meta + pre-mount script, `ThemeContext`, manifest) synced to `#0A1314`. **`Card`/`Button` were left unedited on purpose** — they consume the changed tokens (`bg-surface`/`border-*`/`shadow-sm`) so the wider ramp + stronger borders flow in without class churn. **Verification (local, all green under Node 20):** new `components/ui/controls.test.tsx` (4 cases: control-fill on Input/Textarea, prop/min-h forwarding, sentence-case Label); `tsc --noEmit` clean; web lint **0 errors** (6 Fast-Refresh warnings — the 5 pre-existing + one for `input.tsx`'s new exported const, same benign class as `buttonVariants`); full web vitest **118 passed / 23 files** (114 prior + 4 new); web build clean under Node 20; backend/shared untouched. **Live-verified** in a headless preview against a temporary prod-free mock `/api` (reverted before commit): Home, Check-in, Sleep at 375×812 in **dark + light** — dark surfaces now visibly separate (hero, section cards, nested wells, table header), Check-in inputs are legible raised fields with readable placeholders, labels render sentence-case, and the light palette's separation is intact. **Drive-by fix (test-only, documented in #122):** `DashboardPage.test.tsx` was flaky-by-clock — `isEveningNow()` reads `getHours() >= 20` and the daytime tests never mocked the clock, so **11 of them fail on `main` whenever the local `pnpm test` runs after 20:00 local**. **CI does not run web vitest** (web CI = lint + typecheck + vite build only), so this never blocked CI — Batch 51 shipped green because its *local* run happened earlier in the day, not from CI coverage. Fixed with a `beforeEach` freezing the wall-clock to a daytime instant (the one evening test keeps its 21:30 override) so the local gate is deterministic. (That CI gap is **now closed** — PR #73 / `e41c81c` added a `test-web` CI job running `pnpm -r test` across web + shared, so web/shared vitest regressions now fail CI.) **PR #72 CI went green** across backend pytest/ruff/mypy, Alembic migration check, security audit, the web build (lint + typecheck + vite), and the Vercel preview; squash-merged to `main` as `41f6734`. **Production verified on merge SHA `41f6734`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=41f6734758bac1d6b8bc6ed0f8a2cde46ea005ef`, web `/` and the restyled `/check-in` route both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke; this batch adds no new endpoint — it is frontend-render only, so the live proof is the served web deploy on the merge SHA). **Current follow-up:** Batch 53 is now shipped; the remaining front-end premium batches are **Batch 54 — Home hierarchy & calm density** and **Batch 55 — Screen polish & states**, in that order.

**Prior — Batch 51 — Desktop two-column dashboard — SHIPPED (PR #71, squash `5ebecdc`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #121; spec `docs/designs/desktop-dashboard-layout.md`). The third and last of the Home & navigation UX batches (49–51) — Craig confirmed at `/batch-start` to build it despite Mark being phone-only, so **the Home & navigation UX plan (49–51) is now fully shipped.** **What it does:** on `md+` viewports, Home's six sections split into an **act lane** (Today, After your ride, Tomorrow) and a **context lane** (Last night, Tonight, Bedroom); mobile is unchanged. New pure `sectionLane(key)` in `lib/homeSections.ts` maps each `HomeSectionKey` to its lane; `DashboardPage` wraps the existing `order.map(...)` in one `grid grid-cols-1 gap-5 md:grid-cols-2 md:items-start` container and gives each `CollapsibleSection` a `className` of `md:col-start-1`/`md:col-start-2` (a new passthrough prop on `CollapsibleSection`'s outer `Card`). CSS Grid's own auto-placement then stacks each lane in `orderedSections`' existing order with no extra logic, and the current primary (Batch 50 action or Batch 48 phase) stays first in its lane because it's already first in the flat `order` array. **One DOM tree, no duplicate render** — mobile's `grid-cols-1` collapses to the exact pre-batch single stacked column, so section open/collapsed state can never diverge across a resize. **Same-PR follow-on (a copy fix, not a design decision — no new decision number):** the Next-strip/Today-footer "Check in" label was ambiguous against the per-ride "How did it feel?" check-in already on the After-your-ride card, so `lib/homeActions.ts`'s rung 3 now labels `'Morning check-in'` (was the bare `'Check in'`) and rung 2 names the specific ride — `` `Log how ${activityName} felt` `` (falls back to `'your ride'` when the analysed activity has no name) instead of the generic `'Log how your ride felt'`; the same-route static fallback link in `DashboardPage.tsx`'s Today footer picked up the `'Morning check-in'` wording too. **Verification (local, all green):** new `sectionLane` tests in `homeSections.test.ts`; new `homeActions.test.ts` cases for the named-ride label and no-name fallback; a new `DashboardPage.test.tsx` case asserting the `md:col-start-1`/`md:col-start-2` classes + the shared `grid-cols-1` parent, and the Next-strip mount test updated for the new copy; `tsc --noEmit` clean; web lint 0 errors (5 pre-existing Fast-Refresh warnings); full web vitest **114 passed / 22 files**; web build clean under Node 20; backend suite untouched. **Visually confirmed** pre-merge in a headless preview by injecting the emitted Tailwind classes into the running dev server DOM and screenshotting desktop (1280×800 — two columns, act left/context right) and mobile (375×812 — single stacked column) — a lighter check than the full mock-`/api` walkthrough used for 49/50 since this is a pure CSS Grid placement change with no auth/data surface to exercise. PR #71 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `5ebecdc`. **Production verified on merge SHA `5ebecdc`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=5ebecdc2954fcebecb3cd194c24faab9e348c10f`, web `/` and `/sleep` both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke; this batch adds no new endpoint). **Next step:** a **front-end premium UX plan (Batches 52–55)** is now specced (design docs + ledger, not started) — see the dated entry below. Start with `/batch-start 52` (design foundations — the load-bearing token/primitive tier the others inherit).

**Also 2026-07-03: front-end premium review → Batches 52–55 specced (design docs + ledger, not started).** A world-class UI/UX pass over the shipped app with Craig — north-star **calm, premium health companion** (quiet confidence, one clear action per screen, data on demand), brand latitude **keep CheckMark, integrate it better**. Review-first: walked the **live** screens (headless preview against mock `/api`, mobile, dark + light), not just the code. **Finding:** the architecture is strong — real token system, 3-tab IA, verdict-first Home, collapse-not-remove — and is **kept**; the gap is **execution polish + brand presence**. On the live app the dark surface tiers sit in one narrow near-black band so cards don't separate and Home reads as a flat monotone wall (**P0**); form inputs are dark-on-dark and barely legible — an accessibility problem for a 57-year-old daily user (**P0**); the verdict heartbeat is an uncrafted faint box (**P0**); and there is **no logomark anywhere in-app** even though a strong mark (a checkmark-as-heartbeat on a teal→green tile with a verdict-gauge arc) already exists only as the PWA/favicon icon (**P1**). Net: competent developer-dark, not premium calm companion. **Four frontend-only, no-migration batches close it:** **52 — Design foundations** (🔴 High, ships first: re-space the dark surface/elevation ramp + redesign the input/control tier + pull mono-uppercase back to eyebrows, all at the token+primitive layer so 53–55 inherit it; `docs/designs/design-foundations.md`); **53 — Branded verdict, hero & login** (🔴 High: bring the existing mark in-app, a crafted `VerdictHero`, a mark-led login splash, a top-bar mark, and the "Next" strip promoted to a full-width action band; `docs/designs/branded-verdict-hero-login.md`); **54 — Home hierarchy & calm density** (🟢 Mid: recede the secondary sections, collapse the session-card button cluster to one primary + overflow, tighten the first screen, word-boundary truncation, expand motion; `docs/designs/home-hierarchy-calm-density.md`); **55 — Screen polish & states** (🟢 Mid, last: apply the system across Sleep/Check-in/Week + on-brand empty/error states; `docs/designs/screen-polish-states.md`). Sequence 52 → 53 → 54 → 55 (52 is load-bearing). Decision numbers **#122–#125** assigned at `/batch-start`; ledger: `docs/phase-batches.md` → "Post-roadmap — Front-end premium UX batch plan"; overview + the annotated live walk-through: `docs/designs/frontend-premium-review.md`. **This supersedes the Batch 51 block's "no batch is currently queued"** — the frontier is now the front-end premium plan. **Batch 52 is now implemented on `feat/batch-52-design-foundations` (see the Now block above — verified locally, not yet shipped); 53 is next.**

---

**Prior — Batch 50 — Action-first Home — SHIPPED (PR #70, squash `8542e4a`), prod-verified.** Frontend-only, no backend/payload change, no migration (DECISIONS #120; spec `docs/designs/action-first-home.md`). The second of the Home & navigation UX batches (49–51) — catches the **Home page** up to being push-first (Batch 45). **What it does:** a new pure, payload-only `lib/homeActions.ts` (`nextAction(data, {isEvening})` → `{key,label,to?,sectionKey?,tone}` + `actionSection`) resolves the single "what needs Mark next" action from a deterministic ladder — **pending coach change** (`delivery.changed && isBike`, → expand `today`) > **unlogged ride check-in** (`postWorkoutAnalyses` item with `postRideCheckIn==null`, → expand `afterRide`) > **no daily check-in** (`!manualEntry`, → `/check-in`) > **evening & `sleepProjection.tone==='protect'`** (→ `/sleep`) > **all-clear** ("You're all set"). It drives (a) a new **"Next" strip** under `VerdictHero` (a labelled region; the all-clear state is a quiet button-less status line) that replaces the lone Check-in button, and (b) an **override of the Batch 37/48 phase→primary selection** — `orderedSections` gained an optional `primary` param so `actionSection(nextAction) ?? primarySection(phase,{hasRide})` both **leads** the order and is the one `defaultOpen`, so the pending-action section is expanded regardless of time of day (rungs 1–3 are clock-independent; only protect-sleep is evening-gated). `CollapsibleSection` gained a `tone` prop (a `bg-warning` "needs a tap" dot while collapsed) + an `id` (so the strip scrolls to a section-target action); `todaySummary`/`afterRideSummary` now return `{text,tone}` (Today→warning on a pending change, After-your-ride→warning on an unlogged check-in); the **duplicated Today verdict badge is dropped** (VerdictHero canonical); Home's evening `tonight`/`bedroom` become compact cards deep-linking into the Batch 49 Sleep hub (Bedroom's link shipped in 49; Tonight gains a `DetailLinkCard` at the Home section level so the shared `SleepPrepBody` doesn't self-link on `/sleep`); and Check-in stays reachable via a fallback link in the Today footer. **Decisions settled at `/batch-start` (per spec):** action-over-phase *always* (not morning-only); the ladder order above; one primary action (Check-in demoted); revises-not-replaces Batch 37/48 (phase stays the fallback). **Boundaries kept:** every signal already rides `/api/v1/daily-loop` — no new endpoint/payload/migration; exactly one section expanded (need first, time second); no push logic (that's Batch 45 — this only *surfaces* the action). **The `ignored` note:** the resolver keys the pending-change rung on the payload's `delivery.changed && isBike` only — the client-only Ignore dismiss (#99) isn't persisted and the change is still pending until approved, so the strip honestly reflects the payload. **Verification (local, all green):** `tsc --noEmit` clean; web lint 0 errors (the same 5 pre-existing Fast-Refresh warnings); full web vitest **109 passed / 22 files** (new `homeActions.test.ts` = 11 pure cases; `homeSections.test.ts` +3 override cases; `DashboardPage.test.tsx` verdict-once fix + 3 new: check-in strip default, action-override-expands-Today + collapsed warning dot, all-clear strip); web build clean under **Node 20** (local Node 18 trips the pre-existing `vite-plugin-pwa`/`workbox` issue); backend + shared suites untouched (only `apps/web/src/**` changed). **Shipped:** PR #70 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `8542e4a`. **Production verified on merge SHA `8542e4a`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=8542e4a0d382f3052ed5c440187c4465b686fbea`, web `/` and the Batch 49 `/sleep` route both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke; this batch adds no new endpoint — the change is Home-render only). **Visual review** was covered by the deterministic vitest mount tests (they assert the Next strip per state, the action-over-phase expansion, the collapsed warning dot, and the dropped verdict badge) plus the green Vercel preview build, rather than a separate mock-`/api` headless session; Mark also sees the live Home directly. **Next step:** the Home & navigation UX plan (49–51) has one remaining batch — **Batch 51 — Desktop two-column dashboard** (🟢 Mid, layout-only, **optional/deferrable**; `docs/designs/desktop-dashboard-layout.md`). Run `/batch-start 51` if pursuing it; otherwise the daily-flow, passive-first, and Home/nav plans are all complete.

**Prior — Batch 49 — Navigation & IA refactor + Sleep hub — SHIPPED (PR #69, squash `1b306c1`), prod-verified.** Frontend-only, no migration (DECISIONS #119; spec `docs/designs/navigation-sleep-hub.md`). The first of the Home & navigation UX batches (49–51) — gives the sleep half of the daily loop a nav front door. **Primary tabs are now Home / Week / Sleep** (`Week` renamed from `Plan`, `Trends` demoted to More); "More" is re-tiered into **For you** (Reviews, Trends, Holiday) / **Coaching** (New training block, Experiments) / **Setup** (Coach memory, Handover, Settings) with de-jargoned labels (Tests→Experiments, Plan builder→New training block, Coach state→Coach memory; "Handover" kept as Mark's word). New `pages/SleepPage.tsx` (`/sleep`) is a **Last night | Tonight** segmented view composed entirely from existing pieces — the metrics-vs-baselines table + overnight glance + the overnight chart-and-pager (last night, retrospective) and the sleep projection + live Auto/manual fan controls (tonight, prospective) — no new data, same `/api/v1/daily-loop` + `/api/v1/bedroom/overnight` queries Home already used. `/bedroom` now redirects to `/sleep`; `BedroomPage.tsx` is deleted. The sleep/bedroom body pieces that used to be private functions inside `DashboardPage.tsx` (`SleepSnapshotBody`, `SleepPrepBody`, `BedroomBody`, `OvernightGlance`) are now standalone components under `apps/web/src/components/`, plus a new `DetailLinkCard` and `OvernightChartCard`, so Home and `/sleep` render the identical pieces (`BedroomBody` gained a `compact`/`full` variant prop; `SleepSnapshotBody` gained a `showOvernightGlance` flag so `/sleep` doesn't show a glance linking to itself). `navConfig.ts`'s `PRIMARY_TABS`/`MORE_GROUPS` changed only in data — `TabBar`/`MoreMenu`/`TopBar` render off it generically, no structural change to any of the three. **Verification:** `tsc --noEmit` clean; web lint 0 errors (5 pre-existing Fast-Refresh warnings + 1 pre-existing `tailwind.config.ts` error, both untouched by this diff); full web vitest **92 passed / 21 files** (new `Nav.test.tsx` + `SleepPage.test.tsx`; `DailyDetailPages.test.tsx` split into `MorningBriefPage.test.tsx` with its Bedroom cases removed); web build clean under Node 20; backend suite untouched (no backend files touched). **Live-verified** pre-merge in a headless preview against a temporary mock `/api` (reverted before commit): bottom bar shows Home/Week/Sleep, `/sleep` renders both tabs correctly (single room-verdict badge, working fan toggle/speed buttons), `/bedroom` redirects to `/sleep`, and the More sheet matches the specced groups/labels exactly. PR #69 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `1b306c1`. **Production verified on merge SHA `1b306c1`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=1b306c1be5849f8945d4c716ea29961cb13bae9c`, web `/` returned 200, `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite, and both the new `/sleep` route and the `/bedroom` redirect route served the SPA shell (200; client-side routing) (non-mutating auth-gated smoke). **Next step:** **Batch 50** (action-first Home) is next — `docs/designs/action-first-home.md`; **Batch 51** (desktop two-column) is optional/last. Run `/batch-start 50`.

**Prior — Batch 48 — Explicit daily/block loop model — SHIPPED (PR #68, squash `d9060a1`), prod-verified.** The optional consolidating refactor that closes the passive-first plan (DECISIONS #118; spec `docs/designs/explicit-loop-model.md`). **Scope settled with Craig at `/batch-start`:** Batch 48 is explicitly optional/deferrable and Batches 45–47 had shipped cleanly + prod-verified, so of the ledger's options Craig chose **"model + frontend, no rewire"** — build the loop-state model + orchestration seam and ship the user-visible generalisation, but **leave the prod-verified 45–47 push/projection/block wiring untouched** (it can adopt the seam later). **What it adds:** a pure DB-free `services/daily_loop_state.py` — `DayPhase = rest_day | pre_training | post_training | wind_down` (precedence: evening `wind_down` → `post_training` off *any* ride/strength/flexibility/walk read → `rest_day` → `pre_training`), `BlockPhase` classified from the active block (`consolidation` = the explicit end-of-block boundary, the Batch 47 trigger), and `describe_loop_state(...)` as the "where is Mark + what's next" seam. It generalises the cycling-shaped `post_ride` (a strength/walk-only day now advances instead of being stuck `pre_ride`) and makes evening a first-class `wind_down` phase instead of the 20:00 clock-reorder hack. The daily-loop payload gains a read-only `loopState { dayPhase, blockPhase, nextAction, atBlockBoundary }` (derived in `DailyLoopService` from post-session counts + planned workouts + the profile-local clock + a cheap new `_active_block` query); the generalised `useDailyPhase` **prefers** the server data stage with a local fallback and applies the live-clock `wind_down` overlay itself; `homeSections` swaps its phase→section map for a `hasRide`-aware `primarySection` (non-ride `post_training` leads with the Today card where those reads render; `wind_down` leads with Tonight); `DashboardPage` threads **one** `isEveningNow()` read through both phase and ordering. **Intended behaviour changes (the point, not regressions):** non-ride post-session days advance to `post_training`, and evening leads with Tonight as a real phase — the pinned section/evening tests were updated to document this; per-section renders are unchanged. **Boundaries kept:** no verdict/fan/analysis-engine change, no new coaching logic, **no migration**, 45–47 wiring untouched, and `loopState` is optional in the shared schema so pre-48 cached payloads still parse. **Verification (local, all green):** backend ruff + `ruff format --check` clean, mypy **92 files** clean; 34 pure `test_daily_loop_state.py` cases pass; touched `test_daily_loop.py` (incl. a new DB-backed consolidation block-boundary test + a non-flaky `loopState`-shape assertion) runs 34 passed / 7 skipped locally (DB cases skip without Postgres, run in CI); shared typecheck + 10 tests; web lint 0 errors (5 pre-existing Fast-Refresh warnings), full web vitest **89 passed / 19 files** (new `useDailyPhase.test.ts` + rewritten `homeSections.test.ts`), `tsc` clean, and the web build is clean **under Node 20** — local Node 18 trips a **pre-existing** `vite-plugin-pwa`/`workbox-build` dynamic-require failure (reproduced with the batch stashed), unrelated to this change. PR #68 CI then went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `d9060a1`. **Production verified on merge SHA `d9060a1`:** Railway and Vercel same-origin `/api/v1/health` both returned `sha=d9060a1ecefd1efb829d5174d36565a8343238b5`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke; the app booted cleanly with the new `loopState` serializer). **Next step:** the passive-first plan (Batches 45–48) is **complete** — `docs/phase-batches.md` has no remaining unshipped batch, and the daily-flow redesign + v1–v3 roadmaps are all shipped. **Deferred follow-up (no ticket):** the orchestration seam is available but the scheduler doesn't consume it yet — Batches 45–47's push/projection/block wiring can adopt `describe_loop_state` opportunistically when next touched (the scope call at `/batch-start`, DECISIONS #118).

**Also 2026-07-03: Home & navigation UX read → Batches 49–51 specced (design docs + ledger, not started).** A world-class UI/UX pass over the shipped app with Craig, against the two-loop intent (sleep→training daily, block→block per block) on "effortless, not empty", now that the app is push-first (Batch 45). **Finding:** the bones are strong — three-tabs-plus-More, verdict-first Home, and collapse-not-remove (Batch 37) are all kept — but two structural gaps remain: (1) the layout is training-forward, so the *sleep* half of the daily loop (last night, tonight's projection, the Batch 27 bedroom-fan autopilot) has **no nav presence** (reachable only via Home detail-links) while `Trends` holds a primary slot; and (2) Home hasn't caught up to push-first — the one expanded section is chosen by *time/phase*, so an actionable item (a pending coach adjustment, an unlogged ride check-in) can sit collapsed and invisible in a non-primary section, and collapsed summaries don't signal that they need a tap. Plus minor "More"-menu jargon for a non-technical daily user. **Three frontend-only, no-migration batches close them:** **49 — Navigation & IA refactor + Sleep hub** (🟢 Mid, ships first: primary tabs → Home / Week / Sleep, a `/sleep` hub composing the existing sleep/bedroom surfaces with `/bedroom` absorbed, `Trends` demoted, "More" re-tiered + de-jargoned; `docs/designs/navigation-sleep-hub.md`); **50 — Action-first Home** (🔴 High: a deterministic `nextAction` resolver drives a "Next" strip + overrides the phase→primary expansion so actions surface regardless of time, with state-signalling collapsed summaries and the duplicated verdict badge dropped; `docs/designs/action-first-home.md`); **51 — Desktop two-column dashboard** (🟢 Mid, **optional/last**: layout-only polish; `docs/designs/desktop-dashboard-layout.md`). Sequence 49 → 50 → 51 (51 deferrable). Decision numbers assigned at `/batch-start` (next free **#119**); ledger: `docs/phase-batches.md` → "Post-roadmap — Home & navigation UX batch plan". **This supersedes the Batch 48 block's "passive-first plan complete / no remaining unshipped batch"** — the frontier is now the Home/nav UX plan. Nothing built yet — start with `/batch-start 49`.

---

**Batch 47 — Block-to-block progression — SHIPPED (PR #67, squash `0241bf5`), prod-verified.** Backend + frontend, no migration, no LLM (DECISIONS #117; spec `docs/designs/block-to-block-progression.md`). Adds a deterministic `services/block_progression.py` core plus DB wrapper that reads the last completed 13-week block, existing adherence entries, activity load/duration, Batch 44 interval execution grades, Batch 17 FTP-drift, and morning verdict trend, then maps them to an advisory next-block proposal. `BlockGeneratorService.generate()` now uses that proposal only as the default seed when the user has not manually supplied FTP; the draft stores `progressionProposal` inside the existing `knowledge_base section='generated_block'` payload and the `/builder` page shows the recommended FTP/focus/evidence while keeping the existing generate → refine → lock workflow. Manual FTP override still wins, generation still refuses to clobber an unlocked draft, and only `lock` mutates `plan_blocks`/`planned_workouts` and triggers push-on-plan-set delivery. Insufficient history falls back to the current profile/default FTP. **Verification:** backend ruff + format-check clean for touched Python; backend mypy clean (**91 files**); focused API pytest `test_block_generator.py` **10 passed / 12 skipped** (DB-backed cases skip locally without `DATABASE_URL`); shared tests **10 passed** + typecheck clean; web `BlockGeneratorPage.test.tsx` **6 passed**; web lint 0 errors with the existing 5 Fast Refresh warnings only; web build clean. PR #67 CI green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `0241bf5`: Railway and Vercel same-origin `/api/v1/health` both returned `sha=0241bf5ceea194c5ec49ffa98c3af22bec7776cc`, web `/` returned 200, and `POST /api/v1/block-generator/generate` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke). **Next step:** Batch 48 (explicit daily/block loop model) is the only remaining batch — optional consolidating refactor, last. Run `/batch-start 48` if pursuing it, otherwise the passive-first plan (Batches 45-47) is complete.

---

**Batch 46 — Evening sleep projection — SHIPPED (PR #66, squash `5bf9940`), prod-verified.** Backend + frontend, no migration (DECISIONS #116; spec `docs/designs/evening-sleep-projection.md`). Adds a pure DB-free `services/sleep_projection.py` core that turns today's synced training signals (late/high-intensity/big-load timing), Mark's measured sleep drivers from the existing Batch 17/34 `InsightsService.drivers()` seam, bedroom temperature, overnight weather, the KB `sleep_protocol`, and `fan_auto_enabled` into a qualitative Tonight read plus 1-2 prep actions. It deliberately produces no numeric sleep-score prediction, never changes Green/Amber/Red, never tunes fan thresholds, and falls back to the static protocol when there is no training or not enough driver history. `/api/v1/daily-loop` now carries `sleepProjection`; shared schemas parse it; Home's Tonight section shows the projection headline/actions with evidence tucked behind a details disclosure, while older cached payloads still render the old static copy. The optional Batch 45 evening push/audit row and post-workout "impact tonight" line remain deferred so this batch closes the visible loop first. **Verification:** local gates were green before merge (backend ruff + format-check, backend mypy **90 files**, full API pytest from `apps/api` **435 passed / 144 skipped**, shared tests **10 passed** + typecheck, web lint 0 errors with existing Fast Refresh warnings only, full web vitest **77 passed**, web build clean). PR #66 CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `5bf9940`: Railway and Vercel same-origin `/api/v1/health` both returned `sha=5bf9940f11b9b261e404990a4b3d35127f4bc7ed`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. **Next step:** Batch 47 (block-to-block progression) remains the next unshipped passive-first batch; Batch 48 is optional/last.

---

**Batch 45 — Proactive push + fan-reconciled nudges — SHIPPED (PR #65, squash `0d6ad9f`), prod-verified.** Backend-only, no migration (DECISIONS #115; spec `docs/designs/proactive-push-fan-reconciled.md`). First batch of the passive-first plan — turns the app **push-first** and stops the evening thermal nudges contradicting the Batch 27 fan autopilot. **45.1/45.2 proactive push:** the two highest-value outputs were generated silently — `run_morning_weather_sync` stored the Green/Amber/Red verdict and the hourly `run_garmin_activity_poll` stored each per-session read, but neither pushed; only the static 20:00 nudge + thermal/stale alerts reached Mark. Now `NudgeAlertService` gains `push_morning_verdict` (title `Today: {Green|Amber|Red}` + the verdict's first reason, deep-links `/`) and `push_workout_analysis` (per ride/strength/flexibility/walk, deep-links `/`), both reusing the existing `_send_once` → `send_notification` boundary + the `analyses`-tag idempotency so a verdict pushes **once per (profile, day)** (tag `verdict-{date}`, 09:30-backstop + regeneration safe) and an analysis pushes **once per activity** (tag `analysis-{activity_id}`, so a newer check-in / `PROMPT_VERSION` bump never re-pushes). Breathwork has no per-session analysis (#112) so nothing to push. New audit `analysis_type`s `verdict_push`/`analysis_push` follow the `evening_nudge` audit precedent — **never surfaced** on `/api/v1/daily-loop` or in reviews/handover (every `Analysis` reader filters by type). Each push is wrapped so a failure never blocks the generating pass; the verdict push self-commits, the post-workout pushes land in the poll's trailing commit (helper `_push_new_analyses`). **45.3 fan-reconciled thermal nudges:** `evaluate_thermal_alert` now takes a `FanReconcileState` (from `Profile.fan_auto_enabled` + the latest `fan_state_readings` tick); when the autopilot is armed the manual pre-cool/seal nudges are **suppressed** (the fan manages the room overnight) and a single **"check the fan"** push (deep-links `/bedroom`) is escalated **only** while the room is warm (≥ `ON_THRESHOLD_C` 19.5 °C) **and** the fan can't cope — latest action `unreachable`/`no_data`, or ≥ 20 °C while the fan is at `MAX_SPEED`; a comfortable room is silent even if the fan is unreachable (nothing to physically act on). Autopilot **off** keeps the pre-Batch-45 manual protocol nudges unchanged. **Quiet-hours honesty:** a quiet-hours-suppressed push still records its `_send_once` audit row (send returns 0 but the row is written), so it is not retried next poll. **Boundaries kept:** no migration, no coaching-logic change — the `fan_control.py` decision logic/thresholds, the Green/Amber/Red verdict, and recovery isolation (#49/#80) are untouched; no frontend/shared change (pushes ride the existing web-push path; a per-category Settings toggle is a deferred nice-to-have). **Verification (local):** backend ruff + `ruff format --check` clean, mypy **89 files** clean, full pytest **431 passed / 144 skipped** (the 3 DB-backed push/fan-read tests run in CI — no local Postgres on this Mac; +11 pure nudge-plan/fan tests + 2 scheduler push-wiring tests pass locally). **CI fix (PR #65):** the first CI run hit a **real** (non-local) failure — `test_workout_analysis_pushes_once_per_activity` inserted an `Analysis` with a fabricated `activity_id`, which a real Postgres rejects on `analyses_activity_id_fkey` (the test skips locally without `DATABASE_URL`, so it only surfaced in CI); fixed by seeding a real `Activity` row and keying the analyses off its id (mirroring `test_post_strength_analysis.py`), pushed as a follow-up commit, then CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview. **Production verified on merge SHA `0d6ad9f`:** Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=0d6ad9fb…`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating auth-gated smoke; the batch adds no new endpoint — the push logic runs in the scheduler). **First-live-use:** pushes only land on devices with an active `PushSubscription` + VAPID configured in Railway; confirm Mark's device is subscribed so the verdict/analysis pushes actually arrive. **Next step:** Batches **46** (evening sleep projection) + **47** (block-to-block progression) are the next unshipped batches and can proceed in parallel — 46 closes the daily loop back to sleep, 47 builds the per-block coupling; **48** (explicit loop model) is the optional consolidating refactor, last. Start with `/batch-start 46` or `/batch-start 47`.

---

**Batch 44 — Interval-resolved ride analysis — SHIPPED (PR #63, squash `432e6b4`), prod-verified.** Backend-focused + optional frontend interval table, no migration (DECISIONS #114; spec `docs/designs/interval-resolved-ride-analysis.md`). Fixes the accuracy bug Mark named — the post-ride read judged a structured ride by its **blended whole-ride average power** (or its name), so warm-up + recovery valleys + cool-down dragged the average below the work band and mis-rated a clean session. Now the executed per-second trace (`ActivityTimeSeries`, #93) is segmented on the **planned IR's** interval boundaries (`build_structured_workout_ir`, Batch 12.1 — no new Garmin call) and each **work** interval is graded on its own %FTP target; warm-up/recovery/cool-down power is described, never graded. New pure `services/ride_intervals.py` (`segment_ride_intervals` + `classify_roles` + `summarize_execution` + a shared `power_zone` now reused by the zone histogram) computes per-interval NP (30 s rolling, mean below the window) / %FTP / zone / `adherence` (`on`/`over`/`under`, ±5%-FTP tolerance) / `fade` (first-third vs last-third power) / `hrDriftPct`. `assemble_context_packet` now carries `plannedWorkoutIr` + `intervals` + an `execution` summary, **keeps** `activity.avgPowerWatts` + `timeSeriesSummary` but relabels them as context; the `SYSTEM_PROMPT` + `outputRules` grade on the work intervals and forbid treating the whole-ride average as under-performance; `PROMPT_VERSION` bumped to `post-workout-analysis-v2-2026-07-03`, and a new `_analysis_is_current` makes the hourly poll + backfill regenerate any analysis predating the live prompt. **Free/outdoor rides** (no planned IR) degrade to the current whole-ride + zone-histogram read (no regression). Optional 44.6 frontend: the daily-loop serializer surfaces `intervals`/`execution`, a typed `rideIntervalSchema` parses them, and a compact "Interval execution" table under the post-ride card grades the work intervals only (renders nothing for a free ride). **Recovery isolation preserved (#49/#80):** narrative + grading only — the recovery decision and Green/Amber/Red are untouched; idempotent; boundary fakeable. **Five `/batch-start` calls settled (DECISIONS #114):** IR-alignment over the trace (not Garmin splits); free-ride fallback; fade = power-fade **plus** a descriptive HR-drift signal (richer option); no numeric rating; backfill recent structured rides only via `python -m src.ride_analysis_backfill --since YYYY-MM-DD [--commit]`. **Verification (local):** backend ruff + `ruff format --check` + mypy (89 files) clean, full pytest **421 passed / 141 skipped** (the new DB-backed packet cases run in CI — no local Postgres on this Mac; pure `test_ride_intervals` has 11 cases + the pure `_planned_ride_ir` selector test); shared 10 tests; web lint 0 errors + **76 vitest** (incl. 2 new interval-table tests) + vite build clean. PR #63 CI green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `432e6b4`: Railway + Vercel same-origin `/api/v1/health` both returned `sha=432e6b4…`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated direct and via Vercel. **First-live-use:** the interval-resolved read only applies to structured rides that have both a planned IR and a per-second trace; run `python -m src.ride_analysis_backfill --since 2026-06-01` (dry-run) then `--commit` to regenerate recent structured rides through the new packet — the `PROMPT_VERSION` bump also means the next hourly poll auto-regenerates recent rides. **Next step:** `docs/phase-batches.md` has no remaining unshipped batch (the daily-flow redesign ledger through Batch 44 is complete); deferred follow-ups from the spec — Garmin ground-truth splits (would also unlock interval structure for free/outdoor rides), a concision/density pass on the read, and a VO2max trend surface — are tracked in `docs/designs/interval-resolved-ride-analysis.md` for a future batch.

**Also 2026-07-03: passive-first loop reassessment → Batches 45–48 specced (design docs + ledger, not started).** Re-read the app with Craig against Mark's refined user story — two nested feedback loops (**last night's sleep → today's training**, daily; a **completed multi-week block → the next block**, per block) on an **"effortless, not empty"** principle: the app does the work and reaches out, while the rich data stays browsable (Mark enjoys it). **Finding:** the structure is sound and most of the loop is already built — the wake-triggered morning verdict → sleep-adjusted plan (`executable_coaching`), per-session reads for all five modalities (ride/strength/flexibility/walk + breathwork brief), and the real-world actuation Mark wants (the **Batch 27 Dreo fan autopilot already drives the bedroom overnight**) — so these are **connective tweaks, not a rebuild.** **Four batches close the gaps:** **45 — Proactive push + fan-reconciled nudges** (🔴 High, smallest/highest-impact: the morning verdict + every post-workout read are generated but **never pushed** — only the static 20:00 nudge + thermal/stale alerts push — and the evening thermal nudges still tell Mark to hand-cool a room the fan is managing; `docs/designs/proactive-push-fan-reconciled.md`); **46 — Evening sleep projection** (🔴 High, close the daily loop back to sleep — project how today's training affects tonight's sleep and personalise the wind-down; today the "Tonight" section is only the static protocol; `docs/designs/evening-sleep-projection.md`); **47 — Block-to-block progression** (🔴 High, the second coupling — `generate_block_plan` is profile/FTP-only and never reads how the last block went, though the Batch 17/20/44 signals exist; `docs/designs/block-to-block-progression.md`); **48 — Explicit daily/block loop model** (🔴 High, **optional consolidating refactor** — `DailyPhase` is ride-shaped with no evening phase, which is why the pushes are piecemeal; deferrable, last; `docs/designs/explicit-loop-model.md`). **Sequencing:** 45 first, 46/47 in parallel, 48 optional/last. Decisions assigned at `/batch-start` (next free **#115**); tiers all 🔴 High. Ledger: `docs/phase-batches.md` → "Post-roadmap — passive-first loop batch plan". **This supersedes the Batch 44 block's "no remaining unshipped batch" above** — the frontier is now the passive-first plan. **Batch 45 is now SHIPPED (PR #65, `0d6ad9f`) — see the Now block above;** 46/47 are next (parallel), 48 optional/last.

---

**Batch 43 — Post-strength analysis — SHIPPED (PR #61, squash `29e9d49`), prod-verified.** Backend + frontend, no migration (DECISIONS #113; spec `docs/designs/post-strength-analysis.md`). The direct counterpart to Batch 40 (post-flexibility) for the strength sessions Mark tracks on his watch, added in the 2026-07-02 replan (DECISIONS #108) after the in-app strength *player* (old Batch 38) was withdrawn. Same Batch 8 machinery, higher-reuse than Batch 40: reuses the **existing** `is_strength_activity` selector (Batch 19, via `exclude_from_recovery`, #49/#80 — no new classification code) and Batch 19's pure `compute_strength_rollup` for the consistency block. New `services/post_strength_analysis.py` (`PostStrengthAnalysisService` with `pending_strength_activities` → `assemble_strength_packet` → fakeable Anthropic boundary → idempotent `generate_and_store` keyed on `activity_id`, regenerated on a newer activity-linked check-in) stores `analyses.analysis_type='post_strength'` / `verdict='advisory'`; the lean packet carries duration, avg/max HR vs resting HR, the reused consistency rollup, planned session, and check-in, and **deliberately omits** power/FTP/cadence/stamina/Performance Condition/Training Effect/zones/time-series. The hourly Garmin poll runs the strength pass after the ride + flexibility passes (own try/except); `_post_strength_analyses` + `postStrengthAnalyses` surface on `/api/v1/daily-loop` (reusing the shared per-activity check-in map); `dailyLoopPostStrengthAnalysisSchema` parses it; Home renders a "Strength read" advisory card on Today. `python -m src.strength_analysis_backfill --since YYYY-MM-DD [--commit]` handles the historical strength backlog. **Recovery isolation preserved (#49/#80):** advisory only, never feeds verdict/recovery; the Batch 19 rollup brief is unchanged and complementary. **Verification:** local — backend ruff + `ruff format --check` + mypy (87 files) clean, full backend pytest **547 passed** against a real local Postgres 16 (`alembic upgrade head` → 011; DB-backed strength + daily-loop cases exercised, not skipped), shared typecheck + 9 tests, web lint 0 errors + **74 vitest** (incl. the new Home "Strength read" test) + vite build clean. PR #61 CI green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `29e9d49`: Railway + Vercel same-origin `/api/v1/health` both returned `sha=29e9d49…`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated direct and via Vercel. **First-live-use item:** the `post_strength` series is empty until the hourly poll (or the backfill) runs against Mark's real strength activities — run `python -m src.strength_analysis_backfill --since 2026-06-01 --commit` (dry-run first) to populate the historical strength reads, mirroring the Batch 40 mobility backfill. **Next step:** all four non-cycling analysis batches (40 mobility, 41 walking, 42 breathwork, 43 strength) are now shipped; `docs/phase-batches.md` has no remaining unshipped batch.

---

**Batch 42 — Breathwork integration — SHIPPED (PR #60, squash `743770f`), prod-verified.** Backend + frontend, no migration (DECISIONS #112; spec `docs/designs/breathwork-integration.md`). Added the Batch 19/41-style deterministic breathwork consistency brief: `services/breathwork_brief.py` with pure `compute_breathwork_rollup`, read-only `BreathworkBriefService`, `GET /api/v1/breathwork-brief`, `breathworkBrief` on `/api/v1/daily-loop`, and shared Zod schema support. Morning analysis now includes an advisory `breathworkBrief` packet and appends a breathwork recommendation to `planAdjustments` only when `should_recommend_breathwork` sees Red, recovery-low readiness, or unbalanced/low HRV; Green/high-readiness and load-driven Low readiness do not get the lever. Green/Amber/Red classification is unchanged by the lever, and breathwork never feeds recovery/verdict math. Home renders a compact "Breathwork rhythm" line in Today beside the existing walking base panel; the recommendation itself flows through the existing plan-adjustments UI. PR #60 CI green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `743770f`: Railway + Vercel same-origin `/api/v1/health` both returned `sha=743770f…`, web `/` returned 200, and `GET /api/v1/breathwork-brief` returned 401 unauthenticated direct and via Vercel. **Next step:** Batch 43 post-strength is the next unshipped batch — `/batch-start 43`.

---

**Batch 41 — Walking integration — SHIPPED (PR #59, squash `d9b5a69`), prod-verified.** Backend + frontend, no migration (DECISIONS #111; spec `docs/designs/walking-integration.md`). New `services/walking_brief.py` mirrors the Batch 19 brief pattern with pure `compute_walking_rollup`, `WalkingBriefService`, `GET /api/v1/walking-brief`, and `walkingBrief` on `/api/v1/daily-loop`. Morning analysis now carries advisory `activeRecovery.deliberateWalkVolume` with `classificationImpact="none"` so Green/Amber/Red classification is unchanged. New `services/post_walk_analysis.py` gates LLM generation to deliberate walks (30 min OR 3 km), assembles a lean HR/pace packet (pace, HR review, HR-zone distribution from per-second HR, active-recovery context, planned session, check-in), stores `analyses.analysis_type='post_walk'` idempotently by `activity_id`, and deliberately omits power/FTP/cadence/stamina/Performance Condition/Training Effect; elevation is reported unavailable when not stored. Scheduler runs the walk pass after ride + flexibility analyses; `python -m src.walk_analysis_backfill --since YYYY-MM-DD [--commit]` handles historical qualifying walks. Home renders a "Walking base" panel and advisory "Walk read" cards inside Today. A CI-only DB fixture collision with the default seeded plan was fixed before merge. PR #59 CI green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview; production verified on merge SHA `d9b5a69` with Railway + Vercel same-origin `/api/v1/health`, web `/` 200, and `GET /api/v1/walking-brief` 401 unauthenticated direct and via Vercel. **Next step:** Batch 42 breathwork and Batch 43 post-strength remain unshipped.

---

**Prior — Batch 40 — Post-flexibility/mobility analysis — SHIPPED (PR #58, squash `9a05176`), prod-verified.** Backend + frontend, no migration (DECISIONS #110; spec `docs/designs/post-flexibility-analysis.md`). New `services/post_flexibility_analysis.py` mirrors the Batch 8 post-workout machinery with a lean mobility packet: pure name-based `is_flexibility_activity` (`"mobility"` in activity name, never `typeKey=="other"` so the 153 old misclassified rides cannot leak in; yoga excluded), pure `compute_flexibility_consistency`, `assemble_flexibility_packet` (duration, HR vs resting, consistency, planned mobility, activity-linked check-in, guardrails), mobility-coach prompt, Anthropic Messages boundary, and idempotent `generate_for_pending_flexibility` storing `analyses.analysis_type='post_flexibility'` with `activity_id`. `/api/v1/daily-loop` serializes `postFlexibilityAnalyses`; shared Zod schemas parse it; Home renders an advisory "Flexibility read" markdown card inside Today on mobility days. Scheduler `run_garmin_activity_poll` runs the flexibility pass after ride analysis, and `python -m src.flexibility_analysis_backfill --since 2026-06-01 [--commit]` handles the historical mobility backlog. Recovery isolation is preserved: advisory only, never feeds Green/Amber/Red or ride recovery, and the packet omits power/FTP/zones/cadence/stamina/Performance Condition/Training Effect/time-series. CI green on PR #58; production verified on merge SHA `9a05176` (Railway + Vercel same-origin `/api/v1/health`, web `/` 200, `GET /api/v1/daily-loop` 401 unauthenticated direct and via Vercel).

---

**Prior — Batch 37 — Collapse-not-remove Home sections — SHIPPED (PR #57, squash `f9da1ba`), prod-verified.** Frontend-only Home rearchitecture (DECISIONS #109; spec `docs/designs/home-collapse-not-remove.md`). Home now renders the full six-section superset every load, with one section expanded per data state and the rest collapsed-but-present with one-line summaries; off-phase sections no longer disappear. `CollapsibleSection.tsx` keeps bodies lazy while closed; `lib/homeSections.ts` centralises state-driven ordering and the evening reorder nudge; `DashboardPage` renders one ordered section list instead of three phase branches. Presence is data-gated (only `afterRide`/`tomorrow` can be absent when no ride was analysed), never phase-gated; after 20:00 local, `tonight` + `bedroom` only float up in order. No backend/payload/migration change. Production on merge SHA `f9da1ba` verified (Railway + Vercel same-origin `/api/v1/health` = `f9da1ba…`, web `/` 200, `GET /api/v1/daily-loop` 401 unauthenticated direct and via Vercel).

---

**Prior — Batch 36 — Unified Today card — SHIPPED (PR #56, squash `3087d7a`), prod-verified.** Frontend-only Home recomposition (DECISIONS #107; spec `docs/designs/unified-today-card.md`). `DayPlanCard` (`apps/web/src/pages/DashboardPage.tsx`) became a single `Card`: header `"{label} day"` + the verdict `Badge` **once**; body renders each planned workout as an internal `WorkoutRow` (the former standalone `TodayCard`, stripped of its own `Card`/title/duplicate badge), divided by a top border between sessions, each keeping its **own** local `panel`/`ignored`/duration-intensity state so a mixed day's sessions expand and mutate independently; footer holds `AddWorkoutButtons` + "View week" + "Skip whole day" + `ActualWorkoutForm` ("I did something else"). Rest day renders the same single card with the empty state in the body. **No mutation/endpoint/payload change.** (Batch 37 has since folded this Today card into a `CollapsibleSection` alongside the other Home sections — see the Now block; the `WorkoutRow` scoping is unchanged.) PR #56 CI green; production on merge SHA `3087d7a` verified (Railway + Vercel same-origin `/api/v1/health` = `3087d7a…`, web `/` 200, `GET /api/v1/daily-loop` 401 unauthenticated).

---

**Prior — Batch 35 — Last night as the single morning hub — SHIPPED (PR #54, squash `a93644b`), prod-verified.** Frontend-only Home refinement (DECISIONS #106; spec `docs/designs/last-night-morning-hub.md`). `MetricComparisonTable` now folds the baseline **range** in as a muted sub-line under last night's value and **tints the value** by its in/out-of-band tone (direction-aware, so an out-of-band value in the good direction stays green), dropping the separate "vs your normal" column (back to 3 columns). The standalone **`/baselines` page is retired** — `pages/BaselinesPage.tsx`, its `App.tsx` route + lazy import, and `components/MetricsBaselineTable.tsx` are deleted, with `MetricBaselineRow` + `formatBaseline` moved into `MetricComparisonTable.tsx` (its sole consumer); the sleep card keeps only the `/brief` link. The retrospective **`OvernightGlance`** (room verdict badge + indoor "19→21 °C" glance) moves **into** `SleepSnapshotCard` under the table; the evening `BedroomSummaryCard` keeps tonight's live fan/bedroom read. **Judgment call settled:** the outdoor "Overnight low" weather stat stays in the bedroom card (the glance already carries the indoor overnight range; the outdoor low pairs with Wind). **No backend change, no migration.** **Verification:** full web vitest **60 passed / 17 files**, lint 0 errors, build (`tsc` + Vite) clean; PR #54 CI green (backend pytest/ruff/mypy + Alembic + security audit + web build + Vercel). Production on merge SHA `a93644b`: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=a93644b…`, web `/` returned 200.

**Prior — Batch 34 — Bedroom temperature × sleep correlation — SHIPPED (PR #50, squash `43cdf3a`), prod-verified.** The existing Batch 31 bedroom series now feeds the existing correlation surfaces without tuning the fan: `services/insights.py` adds bedroom driver keys (`bedroom_warning_minutes`, `bedroom_critical_minutes`, `bedroom_fan_ran_minutes`, `bedroom_peak_fan_speed`) to `DRIVER_KEYS`, derives them from `temperature_readings` + `fan_state_readings` keyed by wake-morning date, and adds a deterministic grouped-mean `summary` sentence to bedroom driver correlations; `GET /api/v1/insights/drivers` carries that nullable `summary`; `services/experiment_evaluation.py` adds the same keys to `early_waking_0400`'s measured candidates and includes the top bedroom summary in the existing experiment `reasons`. Missing bedroom data stays `None`, not zero. **No migration, no new endpoint, no cron/cloud call, no `fan_control.py` threshold or speed-ladder change.** **Verification:** targeted backend pytest for `test_insights.py` + `test_experiment_evaluation.py` passed (`27 passed / 12 skipped` locally; DB-backed cases skip without local Postgres); full backend pytest passed (`372 passed / 132 skipped`); full backend ruff passed; touched service/router mypy passed; PR #50 CI green across ruff, mypy, pytest, Alembic migration check, security audit, web build, and the Vercel preview. Production verified on merge SHA `43cdf3a`: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=43cdf3a…`; web `/` returned 200; unauthenticated `GET /api/v1/insights/drivers` returned 401 both direct and via the Vercel rewrite (non-mutating auth-gated smoke). **Durable docs updated:** DECISIONS #105 already recorded the advisory correlation boundary at batch start; `ARCHITECTURE.md` and `docs/phase-batches.md` reconciled to shipped state. **Next step (queued 2026-07-01):** three Home-refinement batches are specced + laddered in `docs/phase-batches.md`, to build in order — **Batch 35** (Last night as the single morning hub: fold the baseline range into the Home table + tint the number + retire `/baselines`, and pull the retrospective overnight-room read into the sleep card; 🟢 Mid, spec `docs/designs/last-night-morning-hub.md`), **Batch 36** (Unified Today card: one card with the verdict shown once + scoped per-session rows + a day footer; 🟢 Mid, spec `docs/designs/unified-today-card.md`), and **Batch 37** (Collapse-not-remove Home sections: keep off-phase sections present-but-collapsed, state-driven with the clock only reordering, superseding the Batch 24 remove-model; 🔴 High, spec `docs/designs/home-collapse-not-remove.md`). All frontend-only, no migration. Decision numbers #106/#107/#108 assigned at `/batch-start`. Nothing built yet — start with `/batch-start 35`.

**Also 2026-07-02: REPLAN — in-app guided-session batches (38/39) withdrawn; post-strength analysis (Batch 43) added (DECISIONS #108).** Mark clarified he tracks his strength and flexibility workouts on his watch and wants only the *post-workout analysis* in the app, not an in-app player to run the session. So **Batch 38** (in-app strength interval player) and **Batch 39** (in-app flexibility video) are withdrawn — with them go the `guided_sessions` table + migration and the completion/reconciliation machinery. Their specs are kept but banner-marked WITHDRAWN (`docs/designs/strength-guided-player.md`, `docs/designs/flexibility-video-player.md`). This surfaced a gap: Mark wanted the analysis for **both** strength and flexibility, but only flexibility had a per-session read planned (Batch 40) — strength had only the Batch 19 *rollup* brief. Filled by new **Batch 43 (post-strength analysis)**, a sibling of Batch 40 (same Batch 8 machinery, lean HR/consistency packet, strength-coach prompt, `analysis_type='post_strength'`, keyed on the Garmin strength activity; reuses the existing `is_strength_activity` selector + `compute_strength_rollup`; `docs/designs/post-strength-analysis.md`). **Impact review (Craig's ask): nothing beyond 38/39 breaks** — Batch 37 is before them and frontend-only; Batches 40/41/42 key on the Garmin activity, never on `guided_sessions` (Batch 40's only trace was an *optional* guided-session enrichment, now removed). **Decision-number shift** (append-only log, no gaps): replan = #108, so Batch 37 → #109, Batch 40 → #110, Batch 41 → #111, Batch 42 → #112, Batch 43 → #113.

**Also 2026-07-02: three non-cycling activity batches (40–42) specced (design docs + ledger, not started); Batch 43 added in the replan above.** A live census of Mark's full Garmin history (4,280 activities, Dec 2014 → Jul 2026, 10 `activityType.typeKey`s) surfaced three near-daily habits the coach is blind to — **mobility, walking, breathwork** — all currently synced into `activities` and then dropped (not `_is_ride`, not `is_strength_activity`). Specced as **Batch 40** (post-flexibility/mobility per-session analysis mirroring Batch 8 with a lean HR/consistency packet, name-based selector, yoga excluded; `docs/designs/post-flexibility-analysis.md`), **Batch 41** (walking brief + morning active-recovery context + threshold-gated deliberate-walk analysis on an HR/pace packet; `docs/designs/walking-integration.md`), **Batch 42** (breathwork consistency brief + a morning-verdict recommendation lever; `docs/designs/breathwork-integration.md`), and now **Batch 43** (post-strength per-session analysis; `docs/designs/post-strength-analysis.md`). All 🔴 High, backend + frontend, no migration; buildable 40 → 41 → 42 with 43 alongside 40, independent of the Home-refinement batches 35–37. Decision numbers #110/#111/#112/#113 assigned at `/batch-start`. **Landmine recorded in every spec:** Garmin's `other` bucket = 47 recent "…Mobility Workout" sessions (distance 0) **+** 153 old 2016–2020 misclassified road rides (distance > 0, already matched as rides by name), so the flexibility selector keys on the activity **name**, never `typeKey=="other"`. **Queue now:** Batches 35/36 shipped; next is **37** (Home collapse-not-remove), then the non-cycling analyses — **40 (mobility) + 43 (strength) as the pair Mark asked for**, then **41 (walking) → 42 (breathwork)**. Start with `/batch-start 37` unless reprioritised. Throwaway census scripts live at `~/garmin-spike/activity_types_probe.py` + `other_inspect.py` (outside the repo, like the other spikes).

**Also 2026-07-01: Operational — today's Garmin ride synced + post-ride analysis gate bug fixed (PR #51, squash `4e77f4c`), prod-verified.** Synced Mark's 1 Jul activities into the app via the normal `run_garmin_activity_poll` path (outdoor **road_biking** "East Ayrshire – 45m Z2" + a walk + a breathwork session; 16 activities over the 3-day poll window, ~11k timeseries samples). Found a latent bug: `_is_ride` (`services/post_workout_analysis.py`) matched only the tokens `cycling`/`bike`, so Garmin's `road_biking` (contains "biking", not "bike"), `mountain_biking`, and `virtual_ride` typeKeys were silently skipped — **all 20 of Mark's outdoor rides had never received a post-workout analysis** (indoor_cycling worked). Fixed to match the cycling family + `*_ride` with a parametrized regression test; CI green; prod-verified (`/api/v1/health` sha=`4e77f4c`, web `/` 200). Generated today's post-ride analysis via the fixed path (verdict `ready_for_review`, reconciled to the planned Z2 — 57 vs 70 min). The fix auto-analyses *future* rides via the hourly poll; the **19 historical outdoor rides were then backfilled** (18 freshly generated + 1 already covered, 0 failures, all `ready_for_review`), so all 20 `road_biking` rides (Aug 2025 → Jul 2026) now carry a post-ride analysis. (The separate pre-feature `indoor_cycling` backlog was left alone — not bug-related.)

**Prior (2026-07-01): Operational — Mark's out-of-sync training plan fixed + a real-plan importer added (DECISIONS #102).** The app had been showing the Batch 5 *generic* 2121 seed anchored to the setup week (Week 01 = Mon 15 Jun), so it sat **~10 weeks behind** Mark's real progression — it called today (Wed 1 Jul) Week 3 Recovery while he's finishing **Week 13 Consolidation** — with the wrong weekly shape (seed rides Tue/Thu/Sat, no Wed; Mark rides Tue/Wed/Thu/Sat/Sun) and placeholder content. His real plan was never imported. **Fixed in prod data** (each dry-run-previewed then applied; snapshot backup taken first): today (1 Jul) deduped to his real Week-13 Wed **"Outdoor Zone 2"**; the rest of this week set to his Plan No. 1 Week-13 sessions (Fri rest); and his **"Plan No. 2" (Scheduled Start 06.07.26)** loaded as the owned plan (**13 blocks + 78 workouts, 6 Jul → 4 Oct**), replacing the forward seed and keeping 1–5 Jul intact. The three leftover seed blocks (15 Jun–5 Jul) were **relabelled to his real weeks 11 Build / 12 Taper / 13 Consolidation**, so the current week reads "Week 13 Consolidation". **New capability SHIPPED (PR #47, squash `59655db`), prod-verified** (`/api/v1/health` sha=`59655db`, web `/` 200, plan read-back intact): `services/plan_import.py` (pure `build_plan_rows` + idempotent `import_plan`) + `src/plan_import.py` runner + reviewed `apps/api/data/plans/plan_no2.json`; 6 pure tests, ruff/mypy clean, CI green; no migration, no cron. **Follow-up:** the Batch 5 auto-seed still fires for a stateless user and anchors a fictional plan to the setup week — replace it with a real "no plan yet" empty state / onboarding import so this can't recur.

**Prior (2026-07-01): Batch 31 — Overnight temperature × fan × sleep chart — SHIPPED (PR #46, squash `d13d05c`), prod-verified.** (DECISIONS #101; spec `docs/designs/bedroom-overnight-chart.md`.)
Makes the Batch 27 fan autopilot legible without touching its decision logic — it only adds a write + a read:
- **31.0 de-risk (settled):** the per-interval hypnogram is in `sleep.raw_payload['sleepLevels']` (`{startGMT,endGMT,activityLevel}` 0=deep/1=light/2=rem/3=awake; survives the sync) → rendered as a faint band. Hive poll (+2 min) and `run_fan_control` (+4 min) fire at different 15-min offsets → nearest-time join, not exact-timestamp.
- **31.1 persist:** new `fan_state_readings` table (migration `011`, mirrors `temperature_readings`). `_apply_fan_control` now **returns** a `FanControlResult`; `run_fan_control` reorders the pure `loop_phase` check before the `fan_auto_enabled` gate and writes one idempotent tick per within-window fire — incl. `auto_off`/`no_data`/`unreachable`/`winddown` so gaps are explained, `idle` writes nothing. Timestamp floored to `INTERVAL_MIN` + `ON CONFLICT DO NOTHING` = coalesce-safe. Fan decision/thresholds/degradation unchanged; failure `reason` is a fixed secret-safe string.
- **31.2 read:** new `routers/bedroom.py` `GET /api/v1/bedroom/overnight` — pure DB read, night-windows `[21:30→09:00]` local (reuses `fan_control` constants), joins temp + fan + the night's sleep (`night+1`), defaults to last completed night, `nights[]` pager. Pure logic in `services/bedroom_overnight.py`. Kept off `/api/v1/daily-loop`. Shared `bedroomOvernightEnvelopeSchema`.
- **31.3/31.4 frontend:** recharts dual-axis `BedroomOvernightChart` (temp line + fan-speed step, 19.5/20.0 °C `ReferenceLine`s, hypnogram/sleep `ReferenceArea`s, muted spans, night pager, empty state) below the `/bedroom` fan card; one-line Home glance on evening/post-ride (`overnightGlanceText`) linking through.
- **Verification (local):** backend ruff + `ruff format --check` + mypy(75 files) clean, full suite **362 passed / 129 skipped** (the 11 new DB-backed tests run in CI — no local Postgres/Docker on this Mac), Alembic single head `011`; web build + lint (0 err) + **63 vitest**; shared typecheck + 7 tests.
- **CI fix (PR #46):** the first CI run hit a **real** (non-local) failure — `test_bedroom.py`'s `_seed_night` added the `Profile` and its FK-dependent `fan_state_readings`/`temperature_readings`/`sleep` rows to the same session without an intermediate flush, so real Postgres enforced the FK before the profile insert landed (`ForeignKeyViolationError`); this only surfaces against a real DB, so it passed locally (skipped, no Postgres) and failed in CI. Fixed with `await session.flush()` after the `Profile` add (the same pattern as the Batch 29 closeout fix) — pushed as a follow-up commit, CI went green.
- **Closeout (2026-07-01):** opened PR #46, fixed the CI-only FK-ordering test bug above, watched all 6 checks + the Vercel preview go green, squash-merged to `main` (`d13d05c`). Production verified: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=d13d05c…`; web `/` returned 200; `GET /api/v1/bedroom/overnight` returned unauthenticated 401 both direct and via the Vercel rewrite (non-mutating auth-gated smoke).
- **Next step:** no planned next batch is currently queued. **First-live-use items:** (1) the `fan_state_readings` series starts empty at the `011` deploy — early nights show temp+sleep with an empty fan track (expected; the empty state says so, will fill in as the overnight loop runs); (2) confirm the chart renders correctly against real prod data on first use (couldn't preview pre-deploy — the table wasn't in prod and the dev preview proxies `/api` to prod; verified instead via build + vitest mount tests pre-merge).

---

**Prior prod state (2026-06-30): Batch 30 — Home day controls + rearrangeable week plan — SHIPPED (PR #45, squash `263460f`), prod-verified.**
The Batch 29 Today-card action surface now has practical day controls, and Plan/Week-ahead is backed by the real mutable schedule:
- **Day model:** rest is still "no active workout", while cycle, weights, flexibility, and mixed days are derived from the active `planned_workouts` list. `mobility` maps to flexibility, and mixed days remain supported even though the live inspected plan had one workout per workout day.
- **Plan-action API:** new `/api/v1/plan-actions/schedule` groups the active plan into day cards including rest days; `POST /days/{date}/workouts`, `/swap-in`, `/skip`, and `/actual` add a workout, move an existing workout into a day, skip the whole day, or record "I did something else".
- **Home:** today's section now renders every same-day workout as an actionable Today card, with day-level Add Cycle / Weights / Flexibility, Skip whole day, and "I did something else" controls. Non-bike additions are local plan rows; added bike workouts reconcile through the Batch 29 delivery rail.
- **Plan page:** `/delivery` now shows the live grouped schedule, rest-day swap-in targets, per-day add/skip actions, and per-workout move controls instead of a hard-coded weekly shape.
- **Mixed-day delivery safety:** delivery and daily-loop lookups now prefer `planned_workout_id` before falling back to date-only rows, and reslotting no longer deactivates every workout already on the target date.
- **Verification (2026-06-30):** PR #45 checks green across ruff, mypy, pytest, Alembic migration check, security audit, web build, and Vercel preview after a formatting-only follow-up commit (`02ccaf4`). Production on implementation SHA `263460f`: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=263460f…`, web `/` returned 200, and the new `GET /api/v1/plan-actions/schedule` route returned 401 unauthenticated direct and through the Vercel rewrite (non-mutating auth-gated smoke); a direct unauthenticated `POST /plan-actions/days/{date}/workouts` also returned 401 before body parsing.
- **Next step:** no planned next batch is currently queued. Optional open follow-ups remain: observe a real Zwift replace/move propagation on first live use, and the smaller red/green "vs your own normal" sleep-tile tinting polish.

---

**Prior prod state (2026-06-29): Batch 29 — Today-card actions + push-on-plan-set delivery — SHIPPED (PR #44, squash `8b5a71e`), prod-verified.**
The Home Today card is now the one action surface for Mark's day, and delivery has moved to push-on-plan-set:
- **Delivery timing:** block generation and weekly restructure deliver the as-planned baseline to Zwift when the plan is set, without per-workout approval (DECISIONS #99). Morning approval now gates only a sleep/recovery adjustment.
- **Rail operations:** intervals.icu delivery supports create, replace, move, and delete (`create_event`, `replace_event`, `move_event`, `delete_event`) using true update-in-place for replace/move and honest failure handling (#97).
- **Today card:** `/api/v1/daily-loop` exposes per-workout delivery state (`changed`, live event id/status/origin, pending adjustment). No-changes state shows Edit / Swap day / Skip; coach-changed state adds Approve & upload / Ignore / Manual edit; non-bike sessions lead the card with no Zwift upload; rest day only means no planned workout.
- **Action routes:** `POST /api/v1/workout-delivery/planned-workouts/{id}/edit`, `/approve-adjustment`, `/swap`, `/skip`. Edit/Approve replace the live event; Swap is unified move-or-swap; Skip is mark-only local status after Zwift delete; Ignore is client-only dismiss.
- **Verification (2026-06-29):** PR #44 and `main` CI green across ruff, mypy, pytest, Alembic migration check, security audit, and web build. Production on implementation SHA `8b5a71e`: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=8b5a71e…`, web `/` returned 200, and the new action routes returned 401 unauthenticated (non-mutating auth-gated smoke; direct Railway + Vercel rewrite).
- **Next step:** optional open follow-ups remain: observe a real Zwift replace/move propagation on first live use, and the smaller red/green "vs your own normal" sleep-tile tinting polish.

---

**Earlier prod state (2026-06-28): Batch 27 — bedroom fan control — SHIPPED (PR #41, squash `9f09e52`), prod-verified.**
The whole batch (27.0 spike → 27.1 Dreo client → 27.2 overnight loop → 27.3 manual override + evening Home surface) is
merged to `main` and live. CI was green across ruff, mypy, pytest (incl. the DB-backed fan/daily-loop tests + Alembic
`010` up/down that skip locally), security audit, and web lint/typecheck/build. DECISIONS #95-97.
- **27.0 spike** (done, DECISIONS #95): proved direct-cloud control via `pydreo_community` against Mark's real fan; the
  device is a **`DR-HPF008S` "Air Circulator" (`speed_range=(1,9)`), not the 508S the plan named**, confirmed as the
  bedroom fan. Key rule: **mode-before-speed** (set `preset_mode='normal'` before `fan_speed`).
- **27.1** `services/dreo_fan.py`: `DreoFanClient` mirroring the `HiveClient` boundary — env creds + cached-token path
  with password fallback, secret-safe, never frontend-exposed; on/off + preset + speed + oscillate + state-read.
- **27.2** `services/fan_control.py` (pure decision core) + `scheduler.run_fan_control` (15-min interval job + a
  `fan-control` `run_scheduled` entry, DECISIONS #96): maps live indoor temp → bounded fan target against the Batch 9
  thresholds (on 19.5 / off 19.0 hysteresis; speed ladder 19.5→3 / 20→5 / 21→7, capped 7), overnight 21:30–08:30 with a
  08:30–09:00 wind-down off, idle (no cloud) by day; idempotent; degrades gracefully (no creds / unreachable / stale temp).
- **27.3** (DECISIONS #97): master switch `Profile.fan_auto_enabled` (migration `010`, default true) gates
  `run_fan_control` (early-return when off, before any cloud call). `routers/fan.py` — `PUT /api/v1/fan/auto`
  (preference) + `POST /api/v1/fan/command` (`{power?, speed?}`, drives the Dreo cloud; takes manual control =
  auto-off **only on success**, so a 502 leaves the autopilot intact; 400 if neither given). Read path: a pure
  `describe_fan_intent` surfaces the loop's *computed* intent on `thermalState.fan` (`{autoEnabled, mode, isOn, speed,
  respondingToC}`) — no cloud read per `GET /daily-loop`. Frontend: `/bedroom` fan card (Auto toggle + manual
  Off/Low/Med/High = 3/5/7) and an evening-Home fan status line (`fanStatusText`).
Batch 26 (post-ride check-in) stays closed out beneath this on `main`; prod now serves the **Batch 27 SHA `9f09e52`**
through Railway + the Vercel same-origin API rewrite.

**Prod verification (Batch 27, 2026-06-28):** Railway `/api/v1/health` → `{"status":"ok","sha":"9f09e52…"}`, so
migration `010` applied (the container only passes its healthcheck after `alembic upgrade head` runs at startup);
web `/` → 200; the new `PUT /api/v1/fan/auto` and `POST /api/v1/fan/command` both return **401 unauthenticated** —
direct on Railway *and* through the Vercel same-origin rewrite — so the routes are live + auth-gated and the smoke
never drove the fan (non-mutating). `DREO_USERNAME`/`DREO_PASSWORD` are now set in Railway, so the overnight loop can
actuate and `fan_auto_enabled` defaults true (armed) — the fan will run itself tonight within 21:30–08:30 as the room
crosses the thresholds.

**Also 2026-06-28 (operational, not a batch): detailed per-ride/walk time-series backfilled to prod + storage bounded (DECISIONS #93).** Loaded the per-second `activity_timeseries` (power/HR/cadence/PC/stamina) the #85 year-backfill had skipped, scoped to **cycling + walking** via a new committed `--detail-types` filter on `garmin_history_backfill.py` (run via `railway run`, 2025-06-24 → 2026-06-27, all months, no 429s): **203 rides + 387 walks** now have per-second data. The load overshot the Supabase **free-tier 500 MB cap** (→625 MB, disk full, `VACUUM FULL` blocked), so the redundant `raw_metrics` JSONB (a copy of the typed channels; nothing reads it) was emptied for indoor_cycling+walking via `UPDATE`+**dump→`TRUNCATE`→reload** (508,293 rows, zero loss) → **DB now 248 MB, under cap**. Outdoor rides keep `raw_metrics` (GPS/elevation). **Live-sync fix merged + deployed:** `STRIP_RAW_METRICS_TYPES` in `GarminSyncService.sync_activities` drops `raw_metrics` on write for those types so the table stays bounded — merged via PR #39 (squash `bf6d743`, all CI green) and **live in prod** (Railway `/api/v1/health` sha=`bf6d743`), so new rides/walks no longer re-bloat the DB.

**Next step:** Batch 27 is shipped + live; the roadmap (`docs/phase-batches.md`) has no remaining planned batch.
**Physical end-to-end CONFIRMED (2026-06-28):** an authenticated `POST /api/v1/fan/command` against prod drove Mark's
real fan on (speed 3 → `isOn:true`) then off (`isOn:false`), `PUT /fan/auto` re-armed the autopilot, and the one-off
device token was revoked (now 401) — so the full auth → router → `DreoFanClient` → Dreo cloud → fan path and the prod
**password login work** (final state: fan off, autopilot armed). One first-live-use item remains: (1) watch the first
overnight run actually drive the fan — confirm via Railway logs that `run_fan_control` reconciles the Dreo to the live
temp (`fired`, `action=apply/hold`) and that the 08:30–09:00 wind-down leaves it off. Optional: cache a `DREO_TOKEN` to
prove token-resume (still the unproven auth path, DECISIONS #95). If Mark wants the fan off overnight, the `/bedroom`
Auto toggle turns the autopilot off.

**Gotchas:** the saved subjective check-in is visible immediately, but the Claude markdown reflects it on the
next post-workout analysis generation; the service deliberately marks stale analyses pending so the next run
does not ignore the new input. Batch 25's same-day Zwift appearance timing observation remains a separate
first-live-use note from DECISIONS #91. Batch 27's throwaway Dreo spike (27.0) is complete — see DECISIONS #95 for the proven direct-cloud path, the
mode-before-speed rule, and the token-resume + temperature-sensor follow-ups.
**Free-tier storage gotcha (DECISIONS #93):** the Supabase DB is on the **free 500 MB cap, shared with the movie
app** (#34). Per-second `activity_timeseries` is now the dominant table — only **cycling + walking** carry details
and `raw_metrics` is stripped for indoor_cycling/walking. Before any large data load, size-project per-type from a
real sample first; and note that once the **physical disk fills, `VACUUM FULL` can't run** (no room for its copy) —
the escape is dump→`TRUNCATE`→reload. DB headroom after this work: ~248/500 MB.

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
  **already-approved** proposals due today; with `INTERVALS_API_KEY` unset
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
- **2026-07-08** — **Closed out Batch 66 — swap-first recovery guidance (PR #90, squash `73c2edf`); production verified.** Opened PR #90 from `feat/batch-66-swap-first-recovery`. The first branch-push CI run failed one job (pytest) on a **test-only** bug — the new DB-backed integration test lowercased `planAdjustments[0]` but searched for the capital-S substring `"move it to Saturday"`, which only runs in CI (the test skips locally without Postgres); fixed in `9cef61b` (behaviour was correct). CI then went **fully green** in both push and PR contexts across all 7 jobs (backend pytest incl. the DB-backed swap tests, mypy, ruff, Alembic migration check, web build, web+shared vitest, security audit), plus a successful Vercel preview deploy. Squash-merged to `main` as `73c2edf706aeb31d85f7d6408d07f1e252c52c82`. **Production smoke passed on the merge SHA:** Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` via `garmin-coach-one.vercel.app` both returned `73c2edf...`, web `/` returned 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct against Railway and via the Vercel rewrite (the batch adds `swapSuggestion` to that auth-gated payload; no new endpoint, no migration). Struck the Batch 66 ledger row to `Shipped`. Both 2026-07-07 workout-scheduling batches (65/66) are now shipped. A background task was spawned to fix `weekly_restructure._version_workout` (whole-date re-versioning would drop a split day's strength row) before any restructure preview→apply UI.
- **2026-07-08** — **Implemented Batch 66 — swap-first recovery guidance — on `feat/batch-66-swap-first-recovery`; not shipped.** Recorded DECISIONS **#139**. The morning verdict used to only ever offer to *soften* a hard session on a cautious day; now, on an **Amber/Red** morning with a hard bike session scheduled, it **leads** with a concrete week swap ("move it to <weekday>, bring <easier session> forward") that is **one-tap actionable** from Home's Today card, softening kept as the fallback. New pure `plan_swap_first(items, subject_date)` in `weekly_restructure.py` reuses the engine's spacing primitives (`HARD_CATEGORIES`/`_conflicts`/`MIN_GAP_DAYS`) to find the soonest later bike day with an easier session to trade with while keeping the ≥2-day no-stack rule (→ `None`/soften when there's no hard session today or no sound swap). `assemble_context_packet` calls it on Amber/Red, prepends the swap lead to `planAdjustments` + attaches `verdict.swapSuggestion`; `SYSTEM_PROMPT` gained a swap-first line; `PROMPT_VERSION`→`morning-analysis-v6-2026-07-08`. New `coaching_protocol` KB section records the preference (auto-seeded). Daily-loop `AnalysisOut` + shared `dailyLoopAnalysisSchema` carry an optional `swapSuggestion`; the new `SwapSuggestionCard` on the Today card fires the **existing** category-scoped `swap_day` in one tap — no new endpoint, no migration. **Scope call (#139):** the spec's preferred "restructure preview→apply" surface was **not** wired — `apply_for_week` re-versions a whole date (`_version_workout`), so after Batch 65's split Saturdays it would silently drop the day's strength row; the batch takes the sanctioned fallback (read-only suggestion + Batch 65-safe `swap_day`) and does not make `apply_for_week` newly reachable. Verdict / #133 / #134 / #135 / Red-never-VO2 invariants untouched. Gates (local, green): backend pytest **511 passed / 167 skipped** (7 new pure `plan_swap_first` tests; 2 new DB-backed morning-analysis tests skip without local Postgres → CI), ruff + format + mypy (98 files) clean; shared typecheck + **13** tests; web vitest **181 passed / 30 files**, `tsc`/lint (0 errors, 6 known warnings)/build clean under Node 20. Ready for review; stop before promotion. **`/closeout` owes only the standard merge-SHA prod smoke (no migration, no re-import).** Flagged follow-up: fix `_version_workout` for multi-workout days before any restructure-apply UI.
- **2026-07-08** - **Closed out Batch 65 - separate cycling & strength + correct Mon/Sat mapping (PR #89, squash `cc445ac`); production import + Zwift delivery verified.** Opened PR #89 from `feat/batch-65-separate-cycling-strength`; CI went fully green in both branch-push and PR contexts across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and web+shared vitest, plus a successful Vercel preview. Squash-merged to `main` as `cc445acd0f90d1fc30b9d81142b1f29f632542bb`. Production smoke passed on the merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` via `garmin-coach-one.vercel.app` both returned `cc445ac...`, web `/` returned 200, and unauthenticated `GET /api/v1/plan-actions/schedule` returned 401 direct against Railway. Ran the required 65.4 prod data step forward from Monday 2026-07-13: dry-run and apply both replaced 13 imported blocks / 78 workouts with 13 blocks / 87 workouts; production verification showed 65 bike rows + 22 `strength_maintenance` rows, Monday Dumbbells, build-Saturday ride v1 + Bodyweight v2, and ride-only recovery/taper Saturdays. Ran `reconcile_deliveries` for 2026-07-13..2026-10-11; 65 bike sessions were pushed/re-synced to Zwift with Intervals.icu event IDs. Struck the Batch 65 ledger row; Batch 66 remains next.
- **2026-07-08** — **Implemented Batch 65 — separate cycling & strength + correct Mon/Sat mapping — on `feat/batch-65-separate-cycling-strength`; not shipped.** Recorded DECISIONS **#138**. Rewrote `apps/api/data/plans/plan_no2.json` (a throwaway transformer, verified with a semantic old-vs-new diff — only the 13 Mondays and the 9 build-week Saturdays changed, every other cell byte-identical): every Monday is now the **Dumbbell** full-body circuit (`strength_maintenance`, 22 min, exercises from `Dumbbell & Bodyweight 19.06.26.docx`); each build-week Saturday splits into a `bike_endurance` "Z2 + Neuromuscular" (welded "Then: 20min dumbbells" tail dropped) + a **Bodyweight** `strength_maintenance` row; rows go 78 → 87. `import_plan` now assigns incrementing **versions per date** (cycle v1, strength v2) so same-day rows satisfy the unique constraint. `_active_workout_on` gained a `category` filter and `swap_day` passes the source's category (`category_for_workout_type`), so swap-target detection is category-scoped — a moved ride never drags a same-day strength row, and swapping two ride days leaves both days' strength put; the Batch 60 completed-session 409 guards are unchanged. Updated `test_plan_actions.py`'s cross-category swap to the new move semantics; added importer per-date-versioning + two category-scoped multi-workout swap tests + a plan-JSON shape test + a `WeekAheadPage.test.tsx` split-day render guard. No migration; verdict / #133 / #134 / #135 / Red-never-VO2 invariants untouched. Gates (local, green): backend pytest **504 passed / 165 skipped** (new DB tests skip without local Postgres → CI), ruff + format + mypy (98 files) clean; shared typecheck + **12** tests; web vitest **180 passed / 30 files**, `tsc`/lint (0 errors, 6 known warnings)/build clean under Node 20 (had to `pnpm install` first — local node_modules predated Batch 62's `@tanstack/*-persist-client` deps). Ready for review; stop before promotion. **`/closeout` must run the 65.4 prod re-import forward from next Monday (`--start-date`) then `reconcile_deliveries`, plus the merge-SHA prod smoke.**
- **2026-07-08** — **Closed out Batch 64 — rate & correct any summary (feedback primitive) (PR #88, squash `c6ebfec`); Railway backend prod-verified, Vercel `/api/*` proxy anomaly flagged for Craig.** Opened PR #88 from `claude/batch-start-64-7fg0zg`; CI went **fully green** in both push and PR contexts across all 7 jobs (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest), plus a successful Vercel preview deploy. Squash-merged to `main` as `c6ebfec`, struck the Batch 64 row to `Shipped`, then pushed the closeout docs (`c86d574`). **Production (egress reached the hosts this time, unlike recent batches):** Railway `/api/v1/health` returns `{"status":"ok","sha":"c86d574…"}` = latest `main`, so **migration `013` applied cleanly on startup** (healthcheck-gated) and held across the feature deploy (`c6ebfec`) and the docs redeploy (`c86d574`); unauthenticated `PUT /api/v1/analyses/{uuid}/feedback` returns **401** direct against Railway; `013` also verified up→down→up locally. Web root via Vercel returns **200**. **Anomaly (independent of this batch):** the Vercel `/api/*`→Railway rewrite 404s for **every** endpoint (health, daily-loop, feedback alike) — `vercel.json` is unchanged by Batch 64, so this is a pre-existing/infra condition on the whole API proxy surface for Craig to inspect on the Vercel production deployment, not a feedback regression. DECISIONS #137 (cont.) recorded at implementation time; batches 65/66 (workout-scheduling) remain the open `Planned` frontier.
- **2026-07-08** — **Implemented Batch 64 — rate & correct any summary (feedback primitive) — on `claude/batch-start-64-7fg0zg`; not shipped.** Recorded DECISIONS #137 (cont.) — the second half of the feedback-primitive plan. New `feedback` table + migration **`013`** (`id`/`user_id`/`analysis_id` both CASCADE/`kind`/`rating`/`correction_text`/`created_utc`, unique `(user_id, analysis_id)` for upsert); new `PUT /api/v1/analyses/{analysis_id}/feedback` (`routers/feedback.py` + `services/feedback.py`, envelope, user-scoped 404/403, 422 on rating↔kind mismatch); `feedbackInputSchema`/`feedbackSchema` in `packages/shared`; daily-loop serializers + `/reviews` `StoredReview` surface existing feedback via one batched `feedback_for_analyses` query on the snapshot. Reusable `FeedbackControl` (accuracy axis for summaries, agreement axis for suggested edits, negative-tap correction textarea) mounted on the Home verdict, the ride/flexibility/strength/walk read cards, and the `/reviews` written review. Morning + post-workout packet assemblers now carry the 5 most-recent free-text corrections (`recentCorrections`) with both system prompts told to weigh-not-obey them; `PROMPT_VERSION` bumped to `morning-analysis-v5-2026-07-08` / `post-workout-analysis-v3-2026-07-08`. Verification: migration `013` up→012→up verified on a local Postgres 16 (table matches model, single head `013`); backend **665 passed** (new `test_feedback.py` — endpoint upsert/one-row, 404, 403, 422, recent-corrections newest-first-text-only, scoped surfacing, morning-packet-includes-corrections), ruff/format/mypy (98 files) clean; shared typecheck + 12 tests; web `FeedbackControl.test.tsx` + full vitest **179 passed**, `tsc`/lint (0 errors, 6 known warnings)/build clean under Node 22. Ready for review; stop before promotion until explicit `/closeout 64` (opens the PR + runs the prod smoke — this env's egress denies the Railway/Vercel hosts).
- **2026-07-07** — **Closed out Batch 63 — lighten the morning check-in (fast path) (PR #87, squash `bc17f59`); production HTTP smoke deferred to Craig.** Opened PR #87 from `claude/batch-start-63-9cdavo`; CI went **fully green** in both push and PR contexts across all 7 jobs (backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web+shared vitest), plus a successful Vercel preview deploy. Squash-merged to `main` as `bc17f59`, struck the Batch 63 row to `Shipped` in `docs/phase-batches.md`. **Production HTTP verification could not run from this remote environment:** the agent egress policy denies CONNECT (403) to `api-production-e2bc7.up.railway.app` and `garmin-coach.vercel.app` (confirmed via `$HTTPS_PROXY/__agentproxy/status`'s `recentRelayFailures` — policy denial, not retryable), so the merge-SHA smoke (Railway + Vercel same-origin `/api/v1/health`=`bc17f59…`, web `/check-in` 200, unauthenticated `GET /api/v1/daily-loop` 401 direct + via Vercel) is handed to Craig to run from a permitted network. Deploy risk low: no migration (schema stays at `012`), no backend/shared file touched, and the Vercel preview built clean. DECISIONS #137 already recorded at implementation time; batch 64 (rate-&-correct feedback primitive) remains a separate, unstarted build.
- **2026-07-07** — **Implemented Batch 63 — lighten the morning check-in (fast path) — on `claude/batch-start-63-9cdavo`; not shipped.** Added DECISIONS #137 (batch 64, the rate-&-correct feedback primitive, remains a separate future build). `CheckInPage.tsx`'s default surface is now a 5-button "Overall" tap group (Rough/Meh/OK/Good/Great → `subjectiveScore` 2/4/6/8/10) plus three one-tap chips (Slept well / Low energy → `feel`; Niggle → `notes`) that toggle a comma-joined token; BP, the free-text feel/notes inputs, supplements/food, and per-workout adherence move behind a reused `CollapsibleSection` "More" (collapsed by default). No backend/shared change — reuses `manualEntryInputSchema` + the existing `PUT /manual-entry` endpoint verbatim, so `regenerate_after_morning_checkin` still fires unconditionally on save; `homeActions.ts`'s ladder was already check-in-optional (#134) so no Home change was needed for 63.3. Verification: `CheckInPage.test.tsx` rewritten (quick save with no typing, chip→column mapping incl. toggle-off, BP/adherence still save behind "More", error state stays usable); `tsc --noEmit` clean, lint 0 errors (6 pre-existing warnings), full web vitest **174 passed** (was 169), build clean under Node 20; shared package untouched (12 tests, typecheck clean). Backend suite not re-run in this sandbox (no `apps/api/.venv`) — justified since no backend/shared file changed. Ready for review; stop before promotion until explicit `/closeout 63`.
- **2026-07-07** — **Closed out Batch 62 — first-open latency (PR #86, squash `8a60a76`); production HTTP smoke deferred to Craig.** Opened PR #86, CI went **fully green** in both push and PR contexts across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and web+shared vitest, plus a successful Vercel preview deploy. Squash-merged to `main` as `8a60a76`, struck the Batch 62 row to `Shipped` in `docs/phase-batches.md`. **Production HTTP verification could not run from this remote environment:** the agent egress policy denies CONNECT (403) to `api-production-e2bc7.up.railway.app` and `garmin-coach.vercel.app` (policy denial, not retryable), so the merge-SHA smoke (Railway + Vercel same-origin `/api/v1/health`=`8a60a76…`, web `/` 200, unauthenticated `GET /api/v1/daily-loop` 401 direct + via Vercel), the before/after `railway run` daily-loop timing, and the Railway↔Supabase colocation check are handed to Craig to run from a permitted network. Deploy risk low: no migration (schema stays at `012`) and the Vercel preview built clean. DECISIONS #136 already recorded at implementation time.
- **2026-07-07** — **Implemented Batch 62 — first-open latency (persist cache + thin daily-loop) — on `claude/next-batch-model-82pgjw`; not shipped.** Added DECISIONS #136. Measured warm prod first (~0.10 s health → not a cold start), then: persisted the daily-loop React Query cache to `localStorage` (daily-loop-only dehydrate, `maxAge` 24 h, build-SHA buster, `staleTime` 60 s, cleared on every auth transition; all `@tanstack` packages pinned to `5.101.2`); precomputed the 120-day driver correlation once in `run_morning_weather_sync` into the existing `driver_correlation` audit row with a `cached_drivers` read-through + live fallback (no migration); collapsed the four post-activity analysis SELECTs into one order-preserving `IN (...)` query; added a 10-min `SELECT 1` connection warm-ping; and instrumented the daily-loop handler with `snapshot_ms`/`envelope_ms`/`total_ms`. **Deviation (in #136):** the spec's brief-parallelization was built then reverted — separate sessions break read-your-writes in the request transaction (caught by the identical-payload test) for a marginal 1–2-user win; only the safe SELECT collapse ships. No decision output changes (identical-payload DB test is the guard). Verification: backend **658 passed** on a local UTF8 Postgres (matching CI encoding), ruff/format/mypy (96 files) clean; shared typecheck + 12 tests; web `tsc`/lint (0 errors, 6 known warnings)/**172** vitest/build clean. Ready for review; stop before promotion until explicit `/closeout 62` (which also captures before/after daily-loop timing and verifies Railway↔Supabase colocation).
- **2026-07-06** — **Closed out Batch 61 — age-adjusted sleep norms & real age-adjusted score (PR #84, squash `7936fcb`).** Pushed `feat/batch-61-age-adjusted-sleep-norms`, opened PR #84, and repaired the CI-only DB-backed morning-analysis assertions that still expected the retired flat-`+4` score/Green verdict/baseline delta. Final PR CI was green in both push and PR contexts across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared tests, and Vercel preview. Squash-merged to `main`, deleted the branch, and production-verified the merge SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=7936fcbb0cb7e48e7ff03f6eeadd81f81c2e3523`, web `/` and `/sleep` served 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via Vercel. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `docs/phase-batches.md`, and `docs/designs/age-adjusted-sleep-norms.md` to shipped state. Decision #135 stands; no historical score backfill was run.
- **2026-07-06** — **Implemented Batch 61 — age-adjusted sleep norms & real age-adjusted score — on `feat/batch-61-age-adjusted-sleep-norms`; not shipped.** Added DECISIONS #135. Replaced the flat Garmin `+4` with a central `sleep_scoring.py` recompute from stored Garmin sub-scores/stage seconds/profile age, changed sleep-stage age rows from point averages to healthy bands with nullable Garmin target contrast, demoted Restless to descriptive-only, bumped the morning prompt to v4, and fixed the Poor-readiness guard found by a read-only prod safety probe. Verification: backend full pytest **502 passed / 152 skipped**, repo-wide ruff format/check and backend mypy **96 files** clean; shared typecheck + 12 tests; web typecheck/lint + 163 tests + build clean under Node 20. Prod read-only probe: 4 Poor-readiness days that crossed the sleep `>=74` threshold now stay Amber. Ready for review; stop before promotion until explicit `/closeout 61`.
- **2026-07-05** — **Shipped #133 (PR #82, squash `5551aa6`) and ran all three regenerations; Mark's 07-05 verdict flipped Amber→Green in prod.** Supersedes the "3 regenerations needed" note below. Via `railway run` against prod: rebuilt `metric_baselines` (added the `readiness_score` band), force-regenerated monthly+weekly reviews and month+season trends to `*-v3` (the "76 eroding" line is gone → now "above your personal median 53.5, not an alarm"; trends show real July-2026-vs-July-2025 YoY), shipped the personal-readiness override (#133: gate readiness on his baseline median vs the generic ≥70; `readiness_level` maps cleanly to score so the lows are genuine — no cleaning; Red floor intact; PROMPT_VERSION→v3; backend 486 passed / 149 skipped; CI green; prod `5551aa6`), then force-regenerated the 2026-07-05 morning verdict → **Green** (v3, `softOverride=true`), confirmed latest in `coach.analyses`. Open: RLS-disabled security decision; Mark's frequent genuine POOR-readiness days; runtime model still `claude-sonnet-4-6`. DECISIONS #133; writeup in `docs/designs/coaching-calibration-and-data-truth.md`.
- **2026-07-05** — **Prod-validated batches 56-59 (#129-#132) against Mark's real data via the Supabase MCP (read-only; data is in the `coach` schema, single user).** Every complaint confirmed real; data is healthy (377 contiguous days 2025-06-24→now, plan loaded, strength classified, 7 baselines) so B1 "last year missing" is calc/narration not a data gap; A3 `training_schedule` KB seeded with Mon/Fri rest days; C1 post-workout analyses ARE generated+pushed (visibility issue). **Key finding: everything Mark currently sees is STALE** — `softSleepRecoveryOverride` null on all 142 analyses, verdicts still `morning-analysis-v1`, review `reviews-v1`, trends 06-01, and `metric_baselines` has no `readiness_score` row. **3 regenerations needed** (auth-gated, Craig triggers): rebuild `metric_baselines`; regenerate morning verdict; re-run weekly/monthly review + trends (`…/run?force=true`). **Residual gap → #133 (proposed):** the soft-sleep override's generic `readiness_score >= 70` rejects Mark's normal-for-him readiness (84d median 54 / q3 65; 66 on 07-05) despite RHR 43 + balanced HRV → today stays Amber; fix = gate on his personal readiness baseline (clean junk `<10` values first). **Security:** Supabase advisor flags RLS disabled on 16 `coach.*` tables — surfaced to Craig, not fixed. Fixed `scripts/diagnose_coaching_data.sql` (was hitting empty `public.*`; now `coach.`-qualified). Full writeup: `docs/designs/coaching-calibration-and-data-truth.md`.
- **2026-07-05** — **Implemented Batch 59 — chronic-pattern suggestions — on `feat/batch-59-chronic-pattern-suggestions`; not shipped.** Added DECISIONS #132. New pure detector `services/chronic_patterns.py` reads the last 4 weeks of sleep/recovery history, requires 21 observed nights before calling a chronic pattern, compares sleep-stage metrics against age norms and available recovery markers against personal baseline bands, and maps repeated misses to concrete sleep-protocol actions prioritised by measured sleep drivers from `InsightsService.drivers()`. `/api/v1/daily-loop` now includes optional `chronicSuggestions`, reusing the already-needed driver report for `sleepProjection`; shared schemas parse the contract; `ChronicSuggestionsCard` renders inside `SleepSnapshotBody`, so Home and `/sleep` share the same evidence-windowed surface. No migration, no new endpoint, no verdict/delivery-rule change. Verification: backend `test_chronic_patterns.py` + `test_age_norms.py` 12 passed; touched backend ruff/format/mypy clean; shared schema vitest 10 passed + typecheck clean; focused `SleepPage.test.tsx` 5 passed; web typecheck clean; web lint 0 errors / 6 known Fast-Refresh warnings; web build clean. Ready for review; stop before promotion until explicit `/closeout 59`.
- **2026-07-05** — **Closed out Batch 58 — sleep-stage age-comparison table (PR #80, squash `9c96bb6`; final shipped SHA `080e763`).** Opened PR #80 from `feat/batch-58-sleep-stage-age-comparison`; the batch merged to `main` as `9c96bb6`, then a narrow follow-up `chore: format batch 58 age norms` (`080e763`) fixed the repo-wide `ruff format --check` gate that the initial branch had missed. Main CI then went fully green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and web/shared tests. Production verified on the final SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=080e7634cd03c47ee6d42124e853b22fabf39595`, web `/` and `/sleep` served 200, and unauthenticated `GET /api/v1/daily-loop` returned 401 both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, and `docs/phase-batches.md` to shipped state; DECISIONS #131 already stood from build time. Next: Batch 59 — Chronic-pattern suggestions.
- **2026-07-05** — **Implemented Batch 58 — sleep-stage age-comparison table — on `feat/batch-58-sleep-stage-age-comparison`.** Added DECISIONS #131. `services/age_norms.py` now emits a sibling `sleepRows` group on the existing `ageComparison` payload so Home keeps the compact Batch 55 folded age descriptors while `/sleep` gets the fuller table Mark asked for. The new age-norm rows cover Duration plus Deep/Light/REM/Awake stage percentages and Restless count; `morning_analysis._age_comparison` threads the synced sleep fields through; `packages/shared` accepts `sleepRows`; and the Sleep hub renders a new `SleepStageAgeTable` card with no endpoint or migration change. Verification: backend `test_age_norms.py` 9 passed, touched backend mypy clean, touched backend ruff clean; shared schema vitest 10 passed; focused web vitest 14 passed; web lint 0 errors / 6 known Fast-Refresh warnings; web build clean. Ready for review; stop before promotion until explicit closeout.
- **2026-07-05** — **Closed out Batch 57 — data truth in reviews/trends (PR #79, squash `4e0497a`).** PR CI and Vercel preview went green, the branch squash-merged to `main`, production Railway + Vercel same-origin health matched the merge SHA, `/` and `/reviews` served 200, and the new read paths stayed auth-gated with 401 unauthenticated direct and via Vercel. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `docs/phase-batches.md`, and `docs/designs/coaching-calibration-and-data-truth.md` to shipped state. Next: Batch 58 — Sleep-stage age-comparison table.

- **2026-07-05** — **Implemented Batch 57 — data truth in reviews/trends — on `feat/batch-57-data-truth`.** Review packets now expose coverage/sample counts, first-half → second-half trend evidence, and source-state/zero-interpretation fields for absent plan rows or untracked strength, so narratives cannot turn missing inputs into "stopped" or "zero sessions" claims. Trends prompt versions now require from→to numbers and sample counts while keeping insufficient-history behaviour deterministic. Reviews API/shared schemas and `/reviews` show the coverage/trend-basis/source caveats. No migration, no new endpoint, no prod backfill run; Step 0 coverage remains the evidence basis and `garmin_history_backfill.py` is still the operational path if gaps are later found. Verification: backend ruff + format-check clean on touched API files; touched-service/router mypy clean; focused API reviews/trends pytest 23 passed / 7 skipped; focused Reviews/Trends web vitest 4 passed; web typecheck clean; web lint 0 errors / 6 known Fast-Refresh warnings; web build clean; shared schema vitest 10 passed and shared typecheck clean. Ready for review; stop before promotion until explicit `/closeout 57`.

- **2026-07-05** — **Closed out Batch 56 — verdict calibration & personal baselines (PR #78, squash `20437e8`).** Opened PR #78 from `feat/batch-56-verdict-calibration`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and the Vercel preview; squash-merged to `main` as `20437e8` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=20437e82119aac1ad6e0c5bc7d7f6e46c01a099b`, web `/` and `/login` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `DECISIONS.md`, `docs/phase-batches.md`, and `docs/designs/coaching-calibration-and-data-truth.md` to shipped state; DECISIONS #129 remains the safety boundary. Next unshipped: Batch 57 — Data truth in reviews/trends.
- **2026-07-05** — **Implemented Batch 56 — verdict calibration & personal baselines on `feat/batch-56-verdict-calibration`; not shipped.** Ran Step 0 prod diagnosis first via Railway/read-only SQL: daily metrics/sleep/activities cover 2025-06-24 → 2026-07-05, strength is classified, post-workout analyses exist, and the active plan exists, so the first build focused on calibration/schedule truth rather than broad backfill. Added DECISIONS #129. `morning_analysis` now has a soft-sleep recovery override: age-adjusted sleep 60-73 can stay Green when HRV is clean, RHR is inside Mark's personal baseline band, readiness is not low/poor, and subjective is absent or >=5; Red floor and Red-never-VO2 remain unchanged. Morning packets now carry `personalBaselines`, `trainingSchedule`, and `yesterdayLoad`; reviews/trends carry baseline bands; readiness review trends now need both >5% and >4 absolute points before becoming a trend; DB-history baselines include `readiness_score`; `training_schedule` is a seeded KB section and missing default sections are added for existing users. Verification: full backend pytest **480 passed / 149 skipped** (3 existing warnings), backend ruff clean, format-check clean, touched-service mypy clean; full `mypy apps/api/src` still hits the known local `pydreo` missing-stub issue outside this batch. Next: commit + push branch, then wait for `/closeout 56`.
- **2026-07-05** — **Captured Mark's app feedback as a tracked punch-list + fix spec (`docs/designs/coaching-calibration-and-data-truth.md`); no code changed.** Nine points grouped into four themes with root cause (file:line) + fix per item: **(A) calibration** — the morning verdict gates hard on age-adjusted sleep (`morning_analysis._morning_verdict`, `<74`→Amber/`<60`→Red) and good HRV/RHR can't override it, so two soft-sleep nights force the 25–30% eased ride (`executable_coaching.AMBER_DURATION_SCALE=0.75`) even when Claude/Copilot greenlight; "76 readiness eroding" is `reviews._half_trend`'s 5% flag + a packet with no personal-baseline band; midweek recovery-day conflict because no structured rest-day schedule (Mon/Fri) is fed in. **(B) data truth** — "strength stopped"/"zero planned"/last-year-missing are truthful reads of empty inputs (no plan in `planned_workouts`, history starts ~Mar 2026 so YoY is genuinely `insufficient_history`, strength maybe unclassified) narrated as fact. **(C)** no post-workout feed-forward into the next verdict. **(D)** additive: sleep-stage age-comparison table (`age_norms` has no sleep norms yet) + chronic-pattern suggestions. **Sequencing:** Step 0 = on-screen diagnosis with Craig (checked vs Mark) before any build; A1/C1 change safety behaviour → decision #129. Updated the Now-block Next step to point here.
- **2026-07-05** — **Shipped the pre-ship thermal + morning-flow fixes (PR #77, squash `e0ee083`).** CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and the Vercel preview; squash-merged to `main` and deleted the branch. **The new DB-backed cases that skip locally (no Postgres) — `regenerate_after_morning_checkin` + the Hive future-clock clamp — passed in CI.** Production verified on that SHA: Railway direct and Vercel same-origin (`garmin-coach-one.vercel.app`) `/api/v1/health` both returned `sha=e0ee083f73c0411358d1c24dab1548f101708bea`, web `/` and `/login` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. DECISIONS #126–#128 stood from the PR. No batch is currently queued next.
- **2026-07-05** — **Implemented pre-ship thermal + morning-flow fixes on `fix/pre-ship-thermal-and-morning-flow` (DECISIONS #126–#128); shipping via PR.** (1) `ExecutableCoachingService.regenerate_after_morning_checkin` re-runs the verdict + eased ride when a late morning check-in worsens it — only while the ride is still `proposed` (never an approved/pushed ride, #29), only on a genuine deterministic Amber/Red drop (no LLM call otherwise), best-effort — wired into `PUT /manual-entry` for the profile-local today (#126). (2) Home's morning `nextAction` ladder re-orders to sleep → check-in → eased ride, with a new per-day `lib/sleepReview.ts` completion flag set on opening `/sleep` so the sleep rung steps down instead of nagging (#127). (3) `_hive_captured_at` clamps a future-dated Hive device clock back to poll time and `is_hive_temperature_fresh` uses an absolute delta — killing a "2068"-reading-reads-as-perpetually-fresh bug that shadowed the real latest temperature (#128). Local gates green: backend ruff + `ruff format --check` + mypy clean, full pytest **475 passed / 149 skipped** (new DB-backed cases run in CI — no local Postgres); shared typecheck + 10 tests; full web vitest **156 passed / 27 files**, web typecheck clean, lint 0 errors (6 known Fast-Refresh warnings), build clean under Node 20. Next: open the PR, get CI green, squash-merge to `main`, production-verify, then append the closeout line + merge SHA here.
- **2026-07-04** — **Closed out Batch 54 — Home hierarchy & calm density (PR #75, squash `8fb90a2`).** Opened PR #75 from `feat/batch-54-home-hierarchy-calm-density`; local rerun green (`pnpm --dir apps/web test` → 137 passed / 28 files, `lint` → 0 errors / 6 known Fast-Refresh warnings, `build` clean under Node 20). PR CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and the Vercel preview. Squash-merged to `main` as `8fb90a2` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=8fb90a2f293f16b480c6ba6900d7aac9955b5725`, web `/` and `/login` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and the Batch 54 design note to shipped state; DECISIONS #124 already stood from build time. **This ships the third front-end premium batch; next unshipped is Batch 55 (Screen polish & states).**
- **2026-07-04** — **Closed out Batch 53 — branded verdict, hero & login (PR #74, squash `c84945e`).** Opened PR #74 from `feat/batch-53-branded-verdict`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, web/shared vitest, and Vercel preview; squash-merged to `main` as `c84945e` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=c84945ef6fed1d514730de6376fa60e395b87778`, web `/` and `/login` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and the Batch 53 design note to shipped state; DECISIONS #123 already stood from build time. **This ships the second front-end premium batch; next unshipped is Batch 54 (Home hierarchy & calm density).**
- **2026-07-04** — **Implemented Batch 53 — branded verdict, hero & login on `feat/batch-53-branded-verdict`.** Added the generated CheckMark mark in-product via `Logomark`, rebuilt `VerdictHero` as the branded daily heartbeat, elevated the login splash, added the mark to the top bar, and promoted Home's Next strip into a primary action band. Frontend presentation only; no backend, payload, endpoint, auth, or migration change. Verification: focused web vitest 36 passed; full web vitest 123 passed / 24 files; web typecheck clean; web lint 0 errors / 6 known Fast-Refresh warnings; web build clean; local browser pass against a mock API confirmed login/mobile Home/desktop Home with no horizontal overflow. Updated DECISIONS #123, the Batch 53 design note, this STATUS handoff, and the phase ledger status to "Implemented on branch". Stop here until explicit `/closeout 53`.
- **2026-07-04** — **CI now runs the web + shared vitest suites (PR #73, squash `e41c81c`).** Closed the gap found during Batch 52: the CI `build-web` job only lint/typecheck/builds, so the web (118) and shared (10) vitest suites were never run anywhere in CI and web unit-test regressions could merge green. Added a `test-web` job (`pnpm -r test`, Node 20). Verified locally green and that it exits non-zero on a broken test (`ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL`), and confirmed it **ran green in real CI** (46s) on PR #73 before merge. Squash-merged to `main` as `e41c81c`; prod healthy on that SHA (Railway `/api/v1/health` = `e41c81c…`, web `/` 200). CI-workflow-only change, no app code.
- **2026-07-04** — **Closed out Batch 52 — design foundations (token + primitive tier) (PR #72, squash `41f6734`).** Opened PR #72 from `feat/batch-52-design-foundations`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, the web build (lint + typecheck + vite), and the Vercel preview; squash-merged to `main` as `41f6734` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=41f6734758bac1d6b8bc6ed0f8a2cde46ea005ef`, web `/` and the restyled `/check-in` route both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md` and `docs/phase-batches.md` (row struck, Shipped) to shipped state; DECISIONS #122 already stood from build time; `ARCHITECTURE.md` untouched (no spec/roadmap/data-model item is touched by a token/primitive visual change — consistent with how Batches 49–51 were closed). **This is the first of the front-end premium plan (52–55); next unshipped is Batch 53 (branded verdict, hero & login).** Flagged a separate follow-up task: **CI does not run the web vitest suite** (web CI = lint + typecheck + vite build only), so web test regressions can merge green — worth adding.
- **2026-07-04** — **Built Batch 52 — design foundations (token + primitive tier) — on `feat/batch-52-design-foundations`.** Lifted the design system from developer-dark to calm premium at the **token + primitive layer only** (no per-screen layout change, no backend/payload/migration): re-spaced the dark surface/border ramp into a clear value ramp (each surface step ~+8 CIELab L\* vs the old ~+5, chosen with a throwaway CIELab/WCAG contrast evaluator), softened the shadows (value carries depth) and strengthened the focus ring; redesigned the input/control tier with a new `--control`/`--control-border` raised fill so inputs are legible (was dark-on-dark), a **new shared `Textarea` primitive** replacing the two ad-hoc `textareaClassName` copies, and `Select`; held text AA in **both** palettes (dark muted/secondary lifted; **light muted darkened to fix a real pre-existing AA failure** ~2.8:1 on white); pulled mono-uppercase back to eyebrows so the `Label` primitive is sentence-case, with a documented type scale. `tokens.ts` mirrors every value (+ synced its stale teal `shadow.glow` to emerald), `tailwind.config.ts` exposes the control utilities, and the PWA/status-bar `theme-color` synced to `#0A1314`; `Card`/`Button` left unedited (they inherit via tokens). Decisions #122. Verified: new `controls.test.tsx` (4 cases), `tsc` clean, web lint 0 errors (6 Fast-Refresh warnings — 5 pre-existing + 1 for the new `input.tsx` exported const, same class as `buttonVariants`), full web vitest **118 passed / 23 files**, web build clean under Node 20, backend/shared untouched; live-verified in a headless preview against a temporary prod-free mock `/api` (reverted before commit) — Home/Check-in/Sleep at 375×812 in **dark + light**. Also fixed a latent clock-flake in `DashboardPage.test.tsx` (froze the wall-clock in a `beforeEach`; 11 daytime tests failed after 20:00 local). Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-03** — **Closed out Batch 51 — desktop two-column dashboard (PR #71, squash `5ebecdc`).** Opened PR #71 from `feat/batch-51-desktop-dashboard`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `5ebecdc` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=5ebecdc2954fcebecb3cd194c24faab9e348c10f`, web `/` and `/sleep` both returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md` and `docs/phase-batches.md` (row struck, Shipped) to shipped state; DECISIONS #121 already stood from build time. **This closes the Home & navigation UX plan (Batches 49–51) — no remaining unshipped batch.**
- **2026-07-03** — **Built Batch 51 — desktop two-column dashboard — on `feat/batch-51-desktop-dashboard`.** On `md+` viewports Home's sections split into an act lane (Today, After your ride, Tomorrow) and a context lane (Last night, Tonight, Bedroom) via a single CSS grid (`grid grid-cols-1 md:grid-cols-2`) with each `CollapsibleSection` placed by a `md:col-start-1`/`md:col-start-2` className (new passthrough prop) and lane membership from a new pure `sectionLane(key)` in `lib/homeSections.ts`; CSS Grid's own auto-placement stacks each lane in the existing `orderedSections` order with no extra logic, and mobile's `grid-cols-1` collapses to the exact pre-batch single stacked column from the same DOM tree (no duplicate render, no state divergence across a resize). Same-PR follow-on: renamed the ambiguous "Check in" action/button — `'Morning check-in'` for the daily entry, `` `Log how ${activityName} felt` `` (named ride, with a `'your ride'` fallback) for the per-ride check-in — so the two are never confused. No backend/payload change, no migration. Verified: `tsc --noEmit` clean, web lint 0 errors (5 pre-existing Fast-Refresh warnings), full web vitest 114 passed/22 files (new `sectionLane` + `homeActions` cases, updated `DashboardPage` mount tests), web build clean under Node 20, backend suite untouched; visually confirmed pre-merge in a headless preview (desktop 1280×800 two columns, mobile 375×812 single column) by injecting the emitted Tailwind classes into the running dev server DOM. Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-03** — **Closed out Batch 49 — navigation & IA refactor + Sleep hub (PR #69, squash `1b306c1`).** Opened PR #69 from `feat/batch-49-nav-sleep-hub`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `1b306c1` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=1b306c1be5849f8945d4c716ea29961cb13bae9c`, web `/` returned 200, `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite, and both the new `/sleep` route and the `/bedroom` redirect served the SPA shell (200). Reconciled `STATUS.md` and `docs/phase-batches.md` (row struck, Shipped) to shipped state; DECISIONS #119 already stood from build time. **Next unshipped: Batch 50 (action-first Home); Batch 51 (desktop two-column) is optional/last.**
- **2026-07-03** — **Built Batch 49 — navigation & IA refactor + Sleep hub — on `feat/batch-49-nav-sleep-hub`.** Primary tabs became Home/Week/Sleep (Trends demoted); "More" re-tiered into For you/Coaching/Setup with de-jargoned labels. New `pages/SleepPage.tsx` (`/sleep`, Last night \| Tonight) composed from the sleep/bedroom pieces extracted out of `DashboardPage.tsx` into standalone components (`SleepSnapshotBody`, `SleepPrepBody`, `BedroomBody` with a `compact`/`full` variant, `OvernightGlance`, plus new `DetailLinkCard`/`OvernightChartCard`) so Home and `/sleep` share the same rendering; `/bedroom` now redirects to `/sleep` and `BedroomPage.tsx` was deleted. No backend/payload change, no migration. Verified: `tsc --noEmit` clean, web lint 0 errors (5 pre-existing Fast-Refresh warnings + 1 pre-existing `tailwind.config.ts` error), full web vitest 92 passed/21 files (new `Nav.test.tsx` + `SleepPage.test.tsx`), web build clean under Node 20, backend suite untouched; live-verified in a headless preview against a temporary mock `/api` (reverted before commit). Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-03** — **Closed out Batch 48 — explicit daily/block loop model (PR #68, squash `d9060a1`).** Opened PR #68 from `feat/batch-48-explicit-loop-model`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `d9060a1` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=d9060a1ecefd1efb829d5174d36565a8343238b5`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite (the app booted cleanly with the new `loopState` serializer). Reconciled `STATUS.md`, `ARCHITECTURE.md` (shipped-batch checklist), and `docs/phase-batches.md` (row struck, Shipped) to shipped state; DECISIONS #118 already stood from build time. **This closes the passive-first plan (Batches 45–48) and leaves `docs/phase-batches.md` with no remaining unshipped batch.** Deferred follow-up (no ticket): the scheduler can adopt the `describe_loop_state` seam opportunistically (the DECISIONS #118 "no rewire" scope call).
- **2026-07-03** — **Built Batch 48 — explicit daily/block loop model — on `feat/batch-48-explicit-loop-model`.** Scope settled with Craig at `/batch-start` (**"model + frontend, no rewire"** — the optional refactor is behaviour-preserving and 45–47 shipped cleanly, so build the model + seam and the visible generalisation but do not touch the prod-verified 45–47 wiring). Added pure DB-free `services/daily_loop_state.py` (generalised `DayPhase` with a real evening `wind_down`, `post_ride`→`post_training` off any modality, `BlockPhase` + `consolidation` boundary, `describe_loop_state` seam) mirrored by a generalised `useDailyPhase`; exposed a read-only `loopState` on `/api/v1/daily-loop` (new `_active_block` query + profile-local clock) with an optional shared schema; replaced `homeSections`' phase→section map with a `hasRide`-aware `primarySection` and threaded one `isEveningNow()` read through `DashboardPage`. Non-ride days now advance to `post_training` and evening leads with Tonight as a first-class phase (pinned tests updated to document this; per-section renders unchanged). No verdict/fan/analysis-engine change, no new coaching logic, no migration, 45–47 wiring untouched. Verified: backend ruff + format-check clean, mypy 92 files clean, 34 pure loop-state tests + `test_daily_loop.py` 34 passed/7 skipped locally (DB cases skip without Postgres, incl. a new consolidation block-boundary test); shared typecheck + 10 tests; web lint 0 errors (5 pre-existing warnings), full vitest 89 passed/19 files, `tsc` clean, web build clean under Node 20 (local Node 18 hits a pre-existing `vite-plugin-pwa`/`workbox-build` failure, reproduced with the batch stashed). Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-03** — **Built Batch 47 — block-to-block progression — on `feat/batch-47-block-progression`.** Added deterministic `services/block_progression.py` with pure outcome → proposal mapping plus a thin DB wrapper that aggregates the last completed 13-week block from existing plan blocks/workouts, manual adherence, activity load/duration, Batch 44 interval execution packets, Batch 17 FTP-drift, and morning verdict trend. Wired `BlockGeneratorService.generate()` to use the proposal's FTP/focus as the default seed only when the caller has not supplied FTP, storing `progressionProposal` in the existing generated-block KB draft. `/builder` now shows the recommended FTP, focus, structural nudge, and evidence; manual FTP override, generate conflict on unlocked drafts, refine, discard, lock, and push-on-plan-set semantics are unchanged. Insufficient history falls back to the current profile/default FTP. Verified: backend ruff + format-check clean, backend mypy 91 files clean, focused API pytest `10 passed / 12 skipped` (DB-backed skipped locally without `DATABASE_URL`), shared tests `10 passed` + typecheck, web `BlockGeneratorPage.test.tsx` `6 passed`, web lint 0 errors with existing Fast Refresh warnings, and web build clean. Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-03** — **Closed out Batch 46 — evening sleep projection (PR #66, squash `5bf9940`).** Opened PR #66 from `feat/batch-46-evening-sleep-projection`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `5bf9940` and deleted the remote branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=5bf9940f11b9b261e404990a4b3d35127f4bc7ed`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/evening-sleep-projection.md` to shipped state; DECISIONS #116 already stood from build time and now points at the shipped PR. The optional evening push/audit row and post-workout "impact tonight" line stay deferred. Next unshipped: Batch 47 block-to-block progression; Batch 48 remains optional/last.
- **2026-07-03** — **Built Batch 46 — evening sleep projection — on `feat/batch-46-evening-sleep-projection`.** Added pure deterministic `services/sleep_projection.py` with qualitative routine/watch/protect reads, no numeric sleep-score prediction, no verdict/fan-threshold mutation, and static-protocol fallback when there is no training or insufficient driver history. Wired today's synced activities + KB `sleep_protocol` through `DailyLoopService`, reused `InsightsService.drivers()` for Mark's measured sleep movers, added `sleepProjection` to `/api/v1/daily-loop` + shared schemas, and rendered the Tonight projection/actions/evidence on Home while tolerating older cached payloads. Deferred the optional evening push/audit row; this branch ships the read surface first. Verified: backend ruff + format-check clean, backend mypy 90 files, focused pytest 4 passed/6 skipped, full API pytest from `apps/api` 435 passed/144 skipped, shared tests 10 passed + typecheck, web lint 0 errors (existing warnings), full web vitest 77 passed, web build clean. Batch row left unstruck/not shipped; ready for review, not closed out.
- **2026-07-03** — **Closed out Batch 44 — interval-resolved ride analysis (PR #63, squash `432e6b4`).** Opened PR #63 from `feat/batch-44-interval-resolved-ride-analysis`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `432e6b4` and deleted the branch. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=432e6b4…`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md` (§4 Post-workout spec bullet + shipped-batch checklist), `docs/phase-batches.md` (row struck, Shipped), and `docs/designs/interval-resolved-ride-analysis.md` to shipped state; DECISIONS #114 already stood from build time. The daily-flow redesign ledger through Batch 44 is complete — no remaining unshipped batch. **First-live-use:** run `python -m src.ride_analysis_backfill --since 2026-06-01` (dry-run then `--commit`) to regenerate recent structured rides through the interval-resolved packet; the prompt-version bump also self-heals recent rides via the hourly poll.
- **2026-07-03** — **Built Batch 44 — interval-resolved ride analysis — on `feat/batch-44-interval-resolved-ride-analysis`.** Fixed the accuracy bug Mark named: the post-ride packet judged a structured ride by its whole-ride average power, so warm-up + recovery + cool-down dragged it below the work band. New pure `services/ride_intervals.py` segments the per-second trace (`ActivityTimeSeries`, #93) on the planned IR's interval boundaries (`build_structured_workout_ir`, Batch 12.1 — no new Garmin call) and grades each **work** interval on its own %FTP target (NP/%FTP/zone/adherence/fade/HR-drift), describing but never grading warm-up/recovery/cool-down. Wired `plannedWorkoutIr` + `intervals` + an `execution` summary into `assemble_context_packet` (whole-ride average kept but relabelled context), extended `SYSTEM_PROMPT` + `outputRules`, bumped `PROMPT_VERSION` → `post-workout-analysis-v2-2026-07-03` with a prompt-version-aware `_analysis_is_current` regeneration, added a free-ride fallback, a `ride_analysis_backfill.py` runner, and an optional Home "Interval execution" table (serializer + `rideIntervalSchema` + component). Settled the five `/batch-start` calls in DECISIONS #114 (IR-first, free-ride fallback, power-fade + HR-drift, no numeric rating, recent-rides backfill). Recovery isolation preserved (#49/#80): narrative + grading only, Green/Amber/Red untouched. Verified locally: backend ruff + `ruff format --check` + mypy (89 files) clean, full pytest **421 passed / 141 skipped** (new DB-backed packet cases run in CI — no local Postgres on this Mac; 11 pure `test_ride_intervals` + pure `_planned_ride_ir` selector test); shared 10 tests; web lint 0 errors + **76 vitest** (2 new interval-table tests) + build clean. Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-02** — **Closed out Batch 43 — post-strength analysis (PR #61, squash `29e9d49`).** Opened PR #61 from `claude/batch-start-43-h33k5y`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `29e9d49`. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=29e9d49…`, web `/` returned 200, and `GET /api/v1/daily-loop` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/post-strength-analysis.md` to shipped state; DECISIONS #113 already stood from build time. All four non-cycling analysis batches (40–43) are now shipped; no remaining unshipped batch in the ledger. **First-live-use:** run the `strength_analysis_backfill` (dry-run then `--commit`) to populate historical strength reads.
- **2026-07-02** — **Built Batch 43 — post-strength analysis — on `claude/batch-start-43-h33k5y`.** Cloned the Batch 40 post-flexibility machinery for strength: new `services/post_strength_analysis.py` reusing the **existing** `is_strength_activity` selector (Batch 19, via `exclude_from_recovery`, #49/#80) and Batch 19's pure `compute_strength_rollup` for the consistency block, a strength-coach `SYSTEM_PROMPT`, the fakeable Anthropic boundary, and idempotent `generate_and_store` keyed on `activity_id` (regenerated on a newer check-in) storing `analyses.analysis_type='post_strength'` / `verdict='advisory'`. Wired the hourly Garmin poll to run the strength pass after ride + flexibility (own try/except); added `_post_strength_analyses` + `postStrengthAnalyses` to `/api/v1/daily-loop`, `dailyLoopPostStrengthAnalysisSchema`, a Home "Strength read" card, and `strength_analysis_backfill.py`. Lean packet omits power/FTP/cadence/stamina/PC/TE/zones/time-series; recovery isolation preserved and tested; the Batch 19 rollup brief is untouched. Settled the `/batch-start` calls in DECISIONS #113. Verified against a real local Postgres 16 (`alembic upgrade head` → 011): backend pytest **547 passed**, ruff + `ruff format --check` + mypy (87 files) clean; shared typecheck + 9 tests; web lint 0 errors + 74 vitest + build clean. Batch row left unstruck/Planned; ready for review, not closed out.
- **2026-07-02** — **Closed out Batch 42 — breathwork integration (PR #60, squash `743770f`).** Opened PR #60 from `feat/batch-42-breathwork-integration`; CI went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and the Vercel preview; squash-merged to `main` as `743770f`. Production verified on that SHA: Railway and Vercel same-origin `/api/v1/health` both returned `sha=743770f…`, web `/` returned 200, and `GET /api/v1/breathwork-brief` returned 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/breathwork-integration.md` to shipped state; DECISIONS #112 already stood from build time. Next unshipped: Batch 43 post-strength analysis.
- **2026-07-02** — **Built Batch 42 — breathwork integration — on `feat/batch-42-breathwork-integration`.** Added deterministic breathwork rollups (`services/breathwork_brief.py`, `GET /api/v1/breathwork-brief`, `breathworkBrief` daily-loop field), threaded the brief into the morning-analysis packet, and added the pure `should_recommend_breathwork` lever so low-recovery mornings append a breathwork recommendation to existing `planAdjustments` without changing Green/Amber/Red classification. Home renders "Breathwork rhythm" in the Today section; shared schemas parse the new field. Settled the `/batch-start` calls in DECISIONS #112: trigger on Red / recovery-low readiness / unbalanced or low HRV, keep copy in plan adjustments, ship brief + lever together, and include last-7-day count context when the brief is available. Verified: full backend pytest 404 passed/136 skipped, backend ruff + format-check clean, touched-source mypy clean (full `mypy src` still blocked by the existing local `pydreo` missing-stub issue in `services/dreo_fan.py`), shared tests/typecheck green, full web vitest 73 passed, web lint 0 errors (existing warnings), web build clean. Batch row left unstruck/not shipped; ready for review, not closed out.
- **2026-07-02** — **Closed out Batch 41 — walking integration (PR #59, squash `d9b5a69`).** Opened PR #59 from `feat/batch-41-walking-integration`; the initial branch CI surfaced a real DB-backed test collision where the walking test inserted a same-date planned workout before `ensure_seeded` inserted the default plan. Fixed the fixture to use a non-seed walk date, then watched both push and PR CI runs go green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview. Squash-merged to `main` as `d9b5a69`; production verified on that SHA with Railway and Vercel same-origin `/api/v1/health`, web `/` 200, and `GET /api/v1/walking-brief` returning 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/walking-integration.md` to shipped state. Next unshipped: Batch 42 breathwork and Batch 43 post-strength.
- **2026-07-02** — **Built Batch 41 — walking integration — on `feat/batch-41-walking-integration`.** Added deterministic walking rollups (`services/walking_brief.py`, `GET /api/v1/walking-brief`, `walkingBrief` daily-loop field), advisory active-recovery walk volume in the morning packet (`classificationImpact="none"`), and a threshold-gated post-walk analysis path (`analysis_type='post_walk'`) for deliberate walks only (30 min OR 3 km). The walk packet is HR/pace-based with HR-zone distribution from per-second HR and no power/FTP/cadence/stamina/PC/TE; elevation is left unavailable when not stored. Scheduler now runs walk generation after ride + flexibility analysis; `src.walk_analysis_backfill` dry-runs or commits historical qualifying walks; shared schemas parse `postWalkAnalyses`; Home renders a "Walking base" panel and advisory "Walk read" cards. DECISIONS #111 records the settled open calls. Verified: backend walking+daily-loop pytest `6 passed / 7 skipped` (DB-backed skipped locally), backend ruff + format-check clean, targeted mypy clean, shared schema tests green, targeted web vitest 24 passed, web lint 0 errors (existing warnings), web build clean. Batch row left unstruck/not shipped; ready for review, not closed out.
- **2026-07-02** — **Closed out Batch 40 — post-flexibility/mobility analysis (PR #58, squash `9a05176`).** Rebased the branch onto Batch 37's shipped `main` and dropped unrelated planning-doc history so PR #58 contained only Batch 40. The first CI run exposed a real DB-backed test collision: the new flexibility test used the same date as the default seeded plan; fixed the test fixture by adding a tiny explicit `PlanBlock` so `ensure_seeded` no longer created the default plan. Local full backend pytest then passed (`389 passed / 134 skipped`), and PR #58 checks went green across backend pytest/ruff/mypy, Alembic migration check, security audit, web build, and Vercel preview. Squash-merged to `main` as `9a05176`; production verified on that SHA with Railway and Vercel same-origin `/api/v1/health`, web `/` 200, and `GET /api/v1/daily-loop` returning 401 unauthenticated both direct and via the Vercel rewrite. Reconciled `STATUS.md`, `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/post-flexibility-analysis.md` to shipped state. Next unshipped: Batch 43 post-strength analysis, then 41 walking and 42 breathwork.
- **2026-07-02** — **Built Batch 40 — post-flexibility/mobility analysis — on `feat/batch-40-post-flexibility-analysis`.** Added the mobility sibling of Batch 8: name-based `is_flexibility_activity` (matches "mobility" in activity name, never Garmin's broad `other` type; yoga excluded), pure `compute_flexibility_consistency`, lean `assemble_flexibility_packet` (duration + HR vs resting + consistency + planned mobility + activity-linked check-in + guardrails; no power/zones/cadence/stamina/PC/TE/time-series), mobility-coach Anthropic boundary, idempotent pending/generate/store path using `analyses.analysis_type='post_flexibility'`, and scheduler wiring after ride analysis. `/api/v1/daily-loop` now carries `postFlexibilityAnalyses`, shared schemas parse it, and Home renders the advisory markdown read in the Today section on mobility days. Added `src.flexibility_analysis_backfill` for the ~47 historical mobility sessions; dry-run counts pending and `--commit` generates. Settled the `/batch-start` calls in DECISIONS #110: analyse 3-minute sessions too, sibling service for now, dedicated daily-loop list, backfill full routine history. Verified backend targeted tests 7 passed/8 skipped; full backend pytest 389 passed/134 skipped; backend ruff + format-check clean; touched-source mypy clean (full `mypy src` still blocked by existing local `pydreo` import-stub issue in `services/dreo_fan.py`); shared test/typecheck green; web vitest 72 passed/18 files, lint 0 errors (existing warnings), build clean. Batch row left unstruck/not shipped; ready for review, not closed out.
- **2026-07-02** — **Closed out Batch 37 — Collapse-not-remove Home sections (PR #57, squash `f9da1ba`).** Opened PR #57 from `feat/batch-37-collapse-home-sections`; CI green across backend pytest/ruff/mypy + Alembic + security audit + web build + Vercel preview; squash-merged to `main` as `f9da1ba`. Production verified on the merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=f9da1ba…`, web `/` returned 200, and the touched `GET /api/v1/daily-loop` route returned 401 unauthenticated both direct and via the Vercel rewrite (non-mutating smoke). Reconciled STATUS.md, `docs/phase-batches.md`, and `docs/designs/home-collapse-not-remove.md` to shipped state; DECISIONS #109 already stood from build time. Next unshipped: Batch 40 (paired closely with Batch 43), then 41 → 42.
- **2026-07-02** — **Closed out Batch 36 — Unified Today card (PR #56, squash `3087d7a`).** Opened PR #56 from `feat/batch-36-unified-today-card`; CI green across backend pytest/ruff/mypy + Alembic + security audit + web build + the Vercel preview; squash-merged to `main` as `3087d7a`. Production verified on the merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=3087d7a…`, web `/` returned 200, and the touched `GET /api/v1/daily-loop` route returned 401 unauthenticated (non-mutating smoke). Reconciled STATUS.md and `docs/phase-batches.md` to shipped state; DECISIONS #107 recorded at build. Next unshipped: Batch 37.
- **2026-07-02** — **Built Batch 36 — Unified Today card — on `feat/batch-36-unified-today-card`.** Reworked `DayPlanCard` (`apps/web/src/pages/DashboardPage.tsx`) into a single `Card` — header `"{label} day"` + one verdict `Badge`, body rendering each planned workout as an internal `WorkoutRow` (the former `TodayCard`, its own `Card`/title/duplicate badge removed, divided by a top border between sessions), footer holding `AddWorkoutButtons` + "View week" + "Skip whole day" + `ActualWorkoutForm`. Each `WorkoutRow` keeps its own local `panel`/`ignored`/duration-intensity state so multiple sessions on a mixed day expand and mutate independently. No mutation/endpoint/`/api/v1/daily-loop` payload change. DECISIONS #107; `docs/phase-batches.md` Batch 36 row left unstruck (not shipped). Updated `DashboardPage.test.tsx`: dropped the removed "Today's session" text assertions in favour of the day-header text, added a verdict-shown-once assertion, and added a mixed-day test proving each row's Swap panel mutates only its own `workoutId`. Verified: full web vitest 61 passed/17 files, lint 0 errors, build (`tsc` + Vite) clean; backend untouched. Ready for review; not closed out.
- **2026-07-02** — **Closed out Batch 35 — Last night as the single morning hub (PR #54, squash `a93644b`).** Opened PR #54 from `feat/batch-35-last-night-hub`; CI green across backend pytest/ruff/mypy + Alembic + security audit + web build + the Vercel preview; squash-merged to `main` as `a93644b`. Production verified on the merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned `sha=a93644b…`, web `/` returned 200. Reconciled STATUS.md, ARCHITECTURE.md, `docs/phase-batches.md`, and the design doc to shipped state; DECISIONS #106 recorded at build. Next unshipped: Batch 36.
- **2026-07-02** — **Built Batch 35 — Last night as the single morning hub — on `feat/batch-35-last-night-hub`.** Reworked `MetricComparisonTable` to fold the baseline range in as a muted sub-line under last night's value and tint the value by its (direction-aware) in/out-of-band tone, dropping the "vs your normal" column (3 columns again). Retired the standalone `/baselines` page: deleted `BaselinesPage.tsx`, its `App.tsx` route + lazy import, and `MetricsBaselineTable.tsx`, moving `MetricBaselineRow` + `formatBaseline` into `MetricComparisonTable.tsx`; removed the sleep card's Baselines detail link (kept `/brief`). Moved the retrospective `OvernightGlance` (verdict + indoor range) into `SleepSnapshotCard`; left the outdoor overnight-low stat + live controls in the evening `BedroomSummaryCard` (the settled judgment call). DECISIONS #106; ARCHITECTURE Batch 28 line corrected. Frontend-only, no backend/migration. Verified: full web vitest 60 passed/17 files, lint 0 errors, build (`tsc` + Vite) clean; backend untouched. Ready for review; not closed out.
- **2026-07-01** — **Queued three Home-refinement batches (35–37) from Craig's four Home-page thoughts — specced, not built.** Reviewed the current `DashboardPage`, the two metrics tables, `BaselinesPage`, and `useDailyPhase`, then decomposed the four ideas into three laddered frontend-only batches (each shrinks the surface the next organises): **35** Last night as the single morning hub (fold the baseline range into the Home `MetricComparisonTable` + tint the number + retire the `/baselines` page, and pull the retrospective overnight-room read into the sleep card — combines the "add baselines to the sleep table" and "temperature into last night's sleep" ideas since both restructure the one card; 🟢 Mid); **36** Unified Today card (one card, verdict shown once, scoped per-session rows + day footer, replacing the summary-card-plus-N-session-cards; 🟢 Mid); **37** Collapse-not-remove Home sections (keep off-phase sections present-but-collapsed instead of absent, state-driven with the clock only reordering — my answer to "does time-of-day make sense? maybe collapse rather than remove"; supersedes the Batch 24 remove-model; 🔴 High). Wrote `docs/designs/{last-night-morning-hub,unified-today-card,home-collapse-not-remove}.md`, added the three spec paragraphs + `Planned` rows to `docs/phase-batches.md`, and updated the "Now" block. No code, no branch — decision numbers #106/#107/#108 assigned at `/batch-start`.
- **2026-07-01** — **Synced today's Garmin ride for Mark + fixed the post-ride analysis gate for outdoor rides (PR #51, squash `4e77f4c`).**
  Read today's activity from Garmin and synced the 1 Jul activities via `run_garmin_activity_poll` (outdoor `road_biking` Z2 +
  walk + breathwork; 16 over the 3-day window, ~11k timeseries). Post-ride analysis didn't fire → traced to `_is_ride` matching
  only `cycling`/`bike`, missing Garmin's `road_biking`/`mountain_biking`/`virtual_ride`; a prod audit showed all 20 outdoor rides
  un-analysed (indoor_cycling fine). Fixed `_is_ride` to cover the cycling family + `*_ride` with a parametrized regression test;
  ruff/format/mypy + CI green; squash-merged, prod verified (health sha=`4e77f4c`, web 200). Generated today's post-ride analysis
  via the fixed path (verdict `ready_for_review`, reconciled to the planned Z2). Then backfilled the 19 historical outdoor rides
  (18 generated + 1 already covered, 0 failures) → all 20 `road_biking` rides now analysed; separate indoor_cycling backlog left alone.
- **2026-07-01** — **Closed out Batch 34 — bedroom temperature × sleep correlation (PR #50, squash `43cdf3a`).**
  Opened PR #50 from `feat/batch-34-bedroom-sleep-correlation`; watched CI go green across ruff, mypy, pytest,
  Alembic migration check, security audit, web build, and the Vercel preview; then squash-merged to `main` as
  `43cdf3a`. Production verified on that merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health`
  both returned `sha=43cdf3a…`; web `/` returned `200`; unauthenticated `GET /api/v1/insights/drivers` returned `401`
  both direct and through the Vercel rewrite (non-mutating auth-gated smoke). Reconciled `STATUS.md`,
  `ARCHITECTURE.md`, and `docs/phase-batches.md` to shipped state; DECISIONS #105 was already recorded at batch
  start. No planned next batch is currently queued.
- **2026-07-01** — **Built Batch 34 — bedroom temperature × sleep correlation — on `feat/batch-34-bedroom-sleep-correlation`.**
  Added bedroom-derived driver values to the existing Batch 17 correlation engine and Batch 22 `early_waking_0400`
  evaluator: warning minutes, critical minutes, fan-run minutes, and peak fan speed are derived from the Batch 31
  bedroom series by wake-morning date, with missing bedroom data represented as `None`. Added a deterministic
  grouped-mean summary sentence to bedroom driver correlations and exposed it through `/api/v1/insights/drivers` plus
  the experiment evaluation `reasons`; no new endpoint, migration, cron/cloud call, or fan-threshold/speed-ladder
  change. DECISIONS #105 records the advisory-only boundary. Verified targeted backend pytest
  (`test_insights.py` + `test_experiment_evaluation.py`: 27 passed / 12 skipped locally), full backend pytest
  (372 passed / 132 skipped), full backend ruff, and mypy on touched services/router. Ready for review; not closed out.
- **2026-07-01** — **Closed out Batch 33 — bedroom overnight temperature verdict (PR #49, squash `8389985`).**
  Opened PR #49 from `feat/batch-33-bedroom-verdict`; watched CI go green across ruff, mypy, pytest, Alembic
  migration check, security audit, web build, and the Vercel preview; then squash-merged to `main` as `8389985`.
  Production verified on that merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both
  returned `sha=8389985…`; web `/` returned `200`; unauthenticated `GET /api/v1/bedroom/overnight` returned `401`
  both direct and through the Vercel rewrite (non-mutating auth-gated smoke). Reconciled `STATUS.md`,
  `ARCHITECTURE.md`, `docs/phase-batches.md`, and `docs/designs/bedroom-temperature-verdict.md` to shipped state;
  DECISIONS #104 was already recorded at batch start. Next unshipped batch: Batch 34 — bedroom temperature × sleep
  correlation.
- **2026-07-01** — **Built Batch 33 — bedroom overnight temperature verdict — on `feat/batch-33-bedroom-verdict`.**
  Added a pure bedroom-night classifier over the existing Batch 31 summary path: `warning_minutes` (>=19.5 °C),
  `critical_minutes` (>=20.0 °C), and `room_verdict` with a single `RED_CRITICAL_MINUTES=60` threshold in
  `services/bedroom_overnight.py`; extended `GET /api/v1/bedroom/overnight` + `bedroomOvernightEnvelopeSchema`; and
  surfaced verdict badges on Home's overnight glance and the `/bedroom` chart header using the shared verdict colour
  mapping with room-specific labels. No migration, no new endpoint, no new cloud call, no fan-loop change. Verified:
  backend pytest (`test_bedroom_overnight.py` green; DB-backed bedroom endpoint tests still skip locally without
  Postgres), backend mypy + ruff on touched files green; frontend targeted vitest (`30 passed`), lint (existing Fast
  Refresh warnings only), and production build green. DECISIONS #104. Ready for review; not closed out.
- **2026-07-01** — **Closed out Batch 32 — Plan page tap-to-move day picker (PR #48, squash `5d7804f`).**
  Opened PR #48 from `feat/batch-32-plan-day-picker`; branch CI went green across ruff, mypy, pytest, Alembic
  migration check, security audit, web build, and the Vercel preview; then squash-merged to `main` as `5d7804f`.
  Production verified on that merge SHA: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both
  returned `sha=5d7804f…`; web `/` returned `200`; unauthenticated `POST
  /api/v1/workout-delivery/planned-workouts/{id}/swap` returned `401` both direct and via the Vercel rewrite
  (non-mutating auth-gated smoke). Ticked `ARCHITECTURE.md` for the shipped mobile-first Plan move UX, struck the
  Batch 32 row `Shipped` in `docs/phase-batches.md`, and updated the top-level `Now` block to shipped state.
- **2026-07-01** — **Fixed Mark's out-of-sync training plan + added a training-plan importer (DECISIONS #102).**
  Read-only prod probe found the active plan was the `batch_5_seed` generic 2121 anchored to Week 01 = Mon 15 Jun
  (the app's `next_cycle_start(date.today())` at first-run), so today (Wed 1 Jul) resolved to Week 3 Recovery vs
  Mark's real **Week 13 Consolidation** — a 70-day/10-week drift, plus the wrong weekly shape and placeholder
  content (his real plan was never imported). Corrected prod data (dry-run → apply, snapshot taken first):
  today → single **"Outdoor Zone 2"** (deduped 3 `plan_action_add` rows); this week's tail (2–5 Jul) → Plan No. 1
  Week-13 sessions with Fri rest; loaded **"Plan No. 2 (start 06.07.26)"** as the owned plan (13 blocks + 78
  workouts, 6 Jul → 4 Oct) replacing the forward seed, 1–5 Jul kept; relabelled the 3 leftover seed blocks
  to his real weeks 11/12/13 so the current week reads Week 13 Consolidation. Added `services/plan_import.py` (pure
  `build_plan_rows` + idempotent `import_plan`), the `src/plan_import.py` runner, and reviewed
  `apps/api/data/plans/plan_no2.json`; 6 pure tests + ruff/format/mypy clean. **Shipped via PR #47 (squash
  `59655db`)** — CI green (ruff/mypy/pytest/alembic/security/web build/Vercel), prod verified (health
  sha=`59655db`, web `/` 200, plan read-back intact). Follow-up: replace the stateless auto-seed with a real
  "no plan yet" empty state / onboarding import so this can't recur.
- **2026-07-01** — **Closed out Batch 31 — Overnight temperature × fan × sleep chart (PR #46, squash `d13d05c`).**
  Opened PR #46 from `feat/batch-31-overnight-bedroom-chart`; the first CI run hit a genuine (CI-only) bug —
  `test_bedroom.py`'s `_seed_night` inserted the `Profile` and its FK-dependent `fan_state_readings`/
  `temperature_readings`/`sleep` rows in the same session without flushing the profile first, so real Postgres
  raised `ForeignKeyViolationError` (the tests are skipped locally with no Postgres, so this only ever surfaces in
  CI). Fixed with `await session.flush()` after the `Profile` add — the same pattern as the Batch 29 closeout fix —
  pushed as a follow-up commit, watched all 6 checks + the Vercel preview go green, then squash-merged to `main`.
  Production verified on implementation SHA `d13d05c`: Railway `/api/v1/health` and Vercel same-origin
  `/api/v1/health` both returned that SHA; web `/` returned 200; `GET /api/v1/bedroom/overnight` returned
  unauthenticated 401 direct and via the Vercel rewrite (non-mutating auth-gated smoke). Ticked `ARCHITECTURE.md`
  §7 and struck the Batch 31 row `Shipped` in `docs/phase-batches.md`.
- **2026-06-30** — Implemented **Batch 31 — Overnight temperature × fan × sleep chart** on
  `feat/batch-31-overnight-bedroom-chart` (not closeout-shipped). 31.0 de-risk confirmed the hypnogram lives in
  `sleep.raw_payload['sleepLevels']` and that temp/fan fire at different 15-min offsets (→ nearest-time join). Added
  `fan_state_readings` (migration `011`) + a scheduler refactor where `_apply_fan_control` returns a `FanControlResult`
  and `run_fan_control` writes one idempotent (floored-timestamp + `ON CONFLICT DO NOTHING`) tick per within-window fire
  across all branches with the fan decision logic untouched; a pure `services/bedroom_overnight.py` + new
  `routers/bedroom.py` `GET /api/v1/bedroom/overnight` (temp×fan×sleep join, default last completed night, pager, kept
  off daily-loop); shared `bedroomOvernightEnvelopeSchema`; a recharts dual-axis `BedroomOvernightChart` + night pager +
  empty state on `/bedroom`, and a one-line Home glance. DECISIONS #101; ARCHITECTURE §5 data-model updated. Verification:
  backend ruff + `ruff format --check` + mypy(75) clean, full suite `362 passed, 129 skipped` (11 new DB-backed tests run
  in CI — no local Postgres/Docker), Alembic single head `011`; web build + lint (0 err) + `63 vitest`; shared 7. Live
  chart preview deferred to post-deploy (the new table isn't in prod and the dev preview proxies `/api` to prod).
- **2026-06-30** — **Closed out Batch 30 — Home day controls + rearrangeable week plan (PR #45, squash `263460f`).**
  Opened PR #45 from `feat/batch-30-home-day-controls`, fixed the CI-only `ruff format --check` failure with
  formatting commit `02ccaf4`, watched PR checks go green across ruff, mypy, pytest, Alembic migration check,
  security audit, web build, and Vercel preview, then squash-merged to `main`. Production verified on implementation
  SHA `263460f`: Railway `/api/v1/health` and Vercel same-origin `/api/v1/health` both returned that SHA; web `/`
  returned 200; `GET /api/v1/plan-actions/schedule` returned unauthenticated 401 direct and via the Vercel rewrite;
  direct unauthenticated `POST /api/v1/plan-actions/days/2026-06-30/workouts` also returned 401 without mutating data.
  Updated `ARCHITECTURE.md` §2/§7 and struck the Batch 30 row `Shipped` in `docs/phase-batches.md`.
- **2026-06-30** — Implemented **Batch 30 — Home day controls + rearrangeable week plan** on
  `feat/batch-30-home-day-controls` (not closeout-shipped). Added a plan-action API for grouped schedule reads,
  add-workout, rest-day swap-in, whole-day skip, and "did something else" actuals; taught Home to classify
  cycle/weights/flexibility/rest/mixed days and render every same-day workout as an actionable Today card; replaced
  the Plan page's hard-coded week with the live mutable schedule; and tightened delivery lookup/reslotting so
  mixed days prefer `planned_workout_id` and preserve secondary same-day workouts. Verification: backend full suite
  `348 passed, 118 skipped`; ruff clean; mypy clean; shared tests `7 passed`; targeted web tests `12 passed`; web
  lint 0 errors with existing Fast Refresh warnings; web build clean; full web vitest passed with
  `--testTimeout=10000` after the default 5s timeout was too tight under local whole-suite load.
- **2026-06-29** — **Closed out Batch 29 — Today-card actions + push-on-plan-set delivery (PR #44, squash `8b5a71e`).**
  Pushed `feat/batch-29-today-card-actions`, opened PR #44, fixed the CI-only FK-ordering failure in the new
  daily-loop delivery-state test (`await session.flush()` after `Profile`), watched PR checks go green, then
  squash-merged to `main`. `main` CI run `28397005091` passed ruff, mypy, pytest, Alembic migration check,
  security audit, and web build. Production verified on implementation SHA `8b5a71e`: Railway `/api/v1/health`
  and Vercel same-origin `/api/v1/health` both returned that SHA; web `/` returned 200; new action routes
  `/edit`, `/approve-adjustment`, `/swap`, and `/skip` returned unauthenticated 401 without mutating data.
  Updated `ARCHITECTURE.md` §2/§7 and struck the Batch 29 row `Shipped` in `docs/phase-batches.md`.
- **2026-06-29** — Continued **Batch 29 — Today-card actions + push-on-plan-set delivery** on
  `feat/batch-29-today-card-actions` after 29.1/29.2 were already committed. Completed the Today-card action layer:
  daily-loop delivery state, API action routes for Edit / Approve adjustment / Swap / Skip, universal Home card
  across bike and non-bike days, client-only Ignore, and dashboard/shared schema tests. Updated the handoff docs to
  mark the batch implemented on branch but **not closeout-shipped**. Verification: backend ruff clean; backend mypy
  clean with API config; full backend pytest `347 passed, 113 skipped` (existing notification async-mock warnings);
  shared typecheck + 7 tests; web lint 0 errors / 5 pre-existing fast-refresh warnings; web tests `51 passed`; web
  build (`tsc && vite build`) green.
- **2026-06-29** — **Closed out Batch 28 — age-comparison axis + merged last-night table (PR #42, squash `0738c2a`).** Pushed `feat/age-comparison` (initial backend batch commit + table-consolidation refactor + ruff format fix), watched CI go green across all 6 jobs (ruff, mypy, pytest, alembic, security-audit, web build), squash-merged to `main`. Railway + Vercel auto-deployed; **prod verified**: `/api/v1/health` → `sha=0738c2a`, web `/` → 200, `/api/v1/daily-loop` → 401 (auth-gated, non-mutating). Ticked `ARCHITECTURE.md` §7 and struck the Batch 28 row `Shipped` in `docs/phase-batches.md`. DECISIONS #98.
- **2026-06-28** — **Merged the age-comparison and own-baseline reads into one Home table** (DECISIONS #98 refinement,
  on `feat/age-comparison`). New bare `MetricComparisonTable` (4-col Metric / Last night / vs your normal / vs your age —
  **difference-forward**: comparison columns state the verdict + numeric difference) joins `metricsVsBaselines` ⋈ `ageComparison`
  (RHR exact key, HRV bridged `hrv_7_day_avg_ms`⟷`hrv_overnight_ms`, VO₂max appended) with `—` where a frame is absent (only
  RHR + HRV have both). It renders **inside the 'Last night's sleep' card** (replacing the REM/Deep/SpO₂ stat grid; duration·quality
  headline + /brief + /baselines links kept); `AgeComparisonCard` + the fitness-age banner are gone (fitness age still computed, not
  surfaced). Frontend-only — backend untouched; `/baselines` detail route keeps `MetricsBaselineTable`. Web lint 0 errors, build
  (tsc+vite) + **47 vitest** green. Awaiting review + `/phase-closeout`.
- **2026-06-28** — **Built the "compared to the average for your age" Home surface** on branch `feat/age-comparison`
  (DECISIONS #98), not yet merged. Garmin fitness age (derived from the already-synced VO₂max payload — no migration) as
  the headline + VO₂max/RHR/HRV vs static sex×age-band population norms (`services/age_norms.py`), threaded through the
  morning context packet → daily-loop → new `AgeComparisonCard` on the pre-ride/rest-day Home, direction-aware tone
  (low RHR = green). ruff+mypy green, backend 347 passed, web build + 18 vitest green. Awaiting `/phase-closeout`.
- **2026-06-28** — **Physical end-to-end of the fan confirmed in prod** (post-closeout). Minted a one-off device
  token for Mark (`railway run python -m src.activate --profile Mark` → `POST /auth/activate`), then drove the real
  fan via authenticated `POST /api/v1/fan/command`: on at speed 3 (`200 {isOn:true,speed:3}`, 4.8s — real Dreo cloud
  connect), off (`200 {isOn:false}`), re-armed the autopilot with `PUT /api/v1/fan/auto {enabled:true}`, then revoked
  the token (verified 401) and shredded the temp creds. Proves the whole auth → router → `DreoFanClient` → Dreo cloud
  → fan path and the prod **password login** (token-resume #95 still optional). Final prod state: fan off, autopilot
  armed (will run itself tonight 21:30–08:30). Only remaining first-live-use item: watch the first overnight loop run
  in Railway logs.
- **2026-06-28** — **Closed out Batch 27 — bedroom fan control (Dreo air-circulator)** (PR #41, squash `9f09e52`).
  Pushed `feat/batch-27-bedroom-fan` (all 3 fan commits + a `style:` ruff-format fixup — CI's `ruff format --check .`
  caught two cosmetic line-collapses in `scheduler.py` + `test_dreo_fan.py` from the never-pushed 27.1/27.2 commits),
  watched CI go green across ruff, mypy, **pytest incl. the DB-backed fan/daily-loop tests**, Alembic `010` up/down,
  security audit, and web build, then squash-merged to `main`. Railway + Vercel auto-deployed; **prod verified**:
  `/api/v1/health` → `sha=9f09e52` (migration `010` applied — healthcheck passes only after `alembic upgrade head`),
  web `/` → 200, and `PUT /api/v1/fan/auto` + `POST /api/v1/fan/command` → **401** unauthenticated (direct + via the
  Vercel rewrite, non-mutating — fan untouched). Did **not** drive the fan from the preview (proxies to prod). Ticked
  `ARCHITECTURE.md` (§2 sync jobs + §7 checklist) and struck the Batch 27 row `Shipped` in `docs/phase-batches.md`.
  Open first-live-use items: confirm the first overnight loop run from Railway logs, and a one-off authenticated
  `POST /command` against the real fan (also tests token-resume #95). `DREO_USERNAME`/`DREO_PASSWORD` now set in Railway.
- **2026-06-28** — **Batch 27.3 built (uncommitted): manual override + preferences + evening "Bedroom — Auto" surface
  (DECISIONS #97).** Master switch `Profile.fan_auto_enabled` (migration `010`, default true) gates `run_fan_control`
  (early-return when off, before any cloud call). New `routers/fan.py`: `PUT /api/v1/fan/auto` (preference) +
  `POST /api/v1/fan/command` (`{power?, speed?}`; drives the Dreo cloud off-thread, takes manual control = auto-off
  **only on success** so a 502 leaves the autopilot intact; 400 if neither given) — registered in `main.py`. Read path:
  a pure `describe_fan_intent(now, temp, *, auto_enabled)` (reusing `loop_phase`+`decide_fan_action`) surfaces the
  loop's *computed intent* on the existing daily-loop payload as `thermalState.fan` `{autoEnabled, mode, isOn, speed,
  respondingToC}`, so `GET /daily-loop` stays a pure DB read (no per-request cloud connect). Shared:
  `dailyLoopThermalStateSchema.fan` + fan input/envelope schemas. Frontend: `BedroomPage` fan card (Auto `Toggle` +
  manual `Off/Low/Med/High` = speeds 3/5/7) and an evening-Home `BedroomSummaryCard` status line via a new
  `fanStatusText` helper. Also improved the command ordering (drive-then-disable) over the initial draft so a transient
  cloud failure can't silently strand the autopilot. Tests: +8 pure (`describe_fan_intent`, `run_fan_control` auto-off
  gate) + 5 DB-backed (router ×4, daily-loop fan intent — skip locally, run in CI). Verified: ruff + strict mypy clean,
  backend **338 passed / 93 skipped**; shared typecheck + 7 tests; web **41 vitest**, lint 0 errors, build incl. tsc.
  No live preview run (previews proxy to prod → would move Mark's real fan). Awaiting commit + `/phase-closeout 27`.
- **2026-06-28** — **Batch 27.1 + 27.2 built (uncommitted): Dreo client wrapper + overnight airflow loop.**
  27.1 `services/dreo_fan.py` (`DreoFanClient`, mirrors `HiveClient`: env creds + cached-token-with-password-fallback,
  secret-safe; on/off + preset + speed + oscillate + state-read; the #95 mode-before-speed rule baked into `set_speed`).
  27.2 `services/fan_control.py` pure decision core (`loop_phase` + `decide_fan_action`: Batch 9 thresholds, hysteresis,
  bounded speed ladder, idempotent) + `scheduler.run_fan_control` integrator (15-min interval, `fan-control` cron entry),
  overnight-only with a morning wind-down off, graceful degradation. `pydreo-community` added to `requirements.txt`.
  52 new tests (18 client + 34 loop); ruff + strict mypy + full suite green (330 passed). DECISIONS #96. Uncommitted.
- **2026-06-28** — **Batch 27.0 — throwaway Dreo fan spike: direct-cloud control proven (DECISIONS #95).**
  Drove Mark's real bedroom fan end-to-end via `pydreo_community` (no HA fallback): login → discover →
  `start_transport()` → power / preset-mode / speed / oscillate / state-read, all physically confirmed. **Device is a
  `DR-HPF008S` "Air Circulator" (`speed_range=(1,9)`), not the 508S the plan named** — Mark confirmed it is the bedroom
  fan. Two spike-script bugs found + fixed (outside the repo): the missing `start_transport()` (control commands
  hard-fail until the WebSocket is open) and the **mode-before-speed** rule (set `preset_mode='normal'` before
  `fan_speed`, or the windlevel is ignored under a preset). Region auto-detects to EU. Open: token-resume not yet
  tested (password fallback needed); the fan reports a `temperature` attr (~°F) as a possible bonus indoor-temp source.
  Next: **27.1** — `DreoClient` wrapper mirroring `HiveClient`, plus `pydreo_community` in `requirements.txt`.
- **2026-06-28** — **Surfaced already-captured Garmin load/activity context into the morning packet (DECISIONS
  #94).** Audit (validated samples in `~/garmin-spike/out/`) confirmed the high-value signals are *already*
  fetched daily and stored in `daily_metrics.raw_payload` — just not promoted. `_training_and_activity_fields`
  now reads **chronic training load → ACWR (acute:chronic)**, **training-load balance**, **steps**, and
  **intensity minutes** from `raw_payload` into `_daily_metric_packet`, and `SYSTEM_PROMPT` tells Claude to use
  them as supporting context. **Additive read — no Garmin fetch, no migration, no storage**; the deterministic
  Green/Amber/Red verdict is unchanged (it never read the packet dict). Concluded **no new Garmin retrieval is
  warranted** (all-day HR/SpO2 = intraday volume trap; `user_summary` dupes `stats`; `body_composition` empty for
  Mark; activity zones/laps derivable from #93's per-second data). +4 pure tests; backend **278 passed / 88
  skipped**, ruff+format+mypy clean. Branch `feat/surface-garmin-load-context` → PR.
- **2026-06-28** — **Detailed per-ride/walk time-series backfill (operational, not a batch; DECISIONS #93).**
  Loaded the per-second `activity_timeseries` the #85 year-backfill deliberately skipped, scoped to **cycling +
  walking** via a now-committed `--detail-types` filter on `garmin_history_backfill.py`
  (`fetch_activity_payloads` skips `get_activity_details` for non-listed types; summaries still load for all).
  Chose cycling+walking over all-types because of the Supabase **free-tier 500 MB cap** (shared with the movie
  app). Ran via `railway run` 2025-06-24→2026-06-27, 13/13 month-chunks, no 429s → **203 rides + 387 walks**
  with per-second power/HR/cadence/PC/stamina (verified; outdoor GPS intact). **Cap incident + recovery:** the
  re-sync pulled in ~260 summaries the original run had missed + higher-than-estimated sample density → DB hit
  ~625 MB and the **physical disk filled** (so `VACUUM FULL` couldn't run). Fixed by emptying the redundant
  `raw_metrics` JSONB (nothing reads it; typed columns hold every analysed channel) for indoor_cycling+walking
  via `UPDATE`+**dump→`TRUNCATE`→reload** (508,293 rows round-tripped, **zero loss**) → **DB 248 MB, under cap,
  writes confirmed working**. Outdoor rides keep `raw_metrics` for GPS/elevation. **Durable fix (this commit):**
  `STRIP_RAW_METRICS_TYPES` in `GarminSyncService.sync_activities` drops `raw_metrics` on write for those types
  so the table stays bounded; +1 DB-backed test. Backend **274 passed / 88 skipped**, ruff+format+mypy clean.
  **Merged via PR #39** (squash `bf6d743`, all 6 CI jobs + Vercel green) and **deployed** — prod
  `/api/v1/health` confirmed at `sha=bf6d743`, so the live-sync strip is now active (new rides/walks store
  `raw_metrics={}` for indoor_cycling/walking). Backfill data + reclaim were already applied directly to prod.
- **2026-06-28** — Closed out **Batch 26 — Post-ride check-in into the analysis**. Fast-forwarded `main` to
  `b6c92b9`, watched main CI green (`28304972699`), verified Railway + Vercel same-origin health at the Batch
  26 SHA, confirmed web `/` 200, and smoked the new post-ride check-in route unauthenticated through both hosts
  (401, no write). Marked Batch 26 shipped in `docs/phase-batches.md`; Batch 27 is now the next planned batch.
- **2026-06-27** — Built **Batch 26 — Post-ride check-in into the analysis** on
  `feat/batch-26-post-ride-check-in`. Added migration `009` for nullable
  `manual_entries.activity_id`, the authenticated post-ride check-in endpoint, daily-loop serialization as
  `postWorkoutAnalyses[*].postRideCheckIn`, and Home post-ride card capture for RPE / legs / feel / niggles.
  `PostWorkoutAnalysisService` now includes the check-in in the analysis packet and marks an existing analysis
  stale when it predates the latest activity-linked check-in; morning analysis filters to date-level manual
  entries only so later ride feedback cannot back-feed the morning verdict. Recorded DECISIONS #92 and updated
  `ARCHITECTURE.md` / `docs/phase-batches.md`. Verification: API pytest **274 passed / 87 skipped**; focused
  new coverage for persistence + stale-analysis regeneration; ruff + mypy clean; web vitest **37 passed**;
  web build OK; web lint 0 errors / 5 existing warnings; shared tests **7 passed** + typecheck OK. Local
  Alembic upgrade was attempted but Postgres was unreachable on `localhost:5432`, so migration execution is
  left to CI's `migration-check`.
- **2026-06-27** — **Closed out Batch 25 — Same-day delivery + manual override** (PR #38, squash merge
  `aaab0a0`, prod verified). Shipped Home **Send to Zwift** + **Override** controls and the authenticated
  `send-today` endpoint, with same-day approve→push, manual override IR, Red-never-VO2 gate, audit rows,
  and `DEFAULT_LEAD_DAYS=0` same-day catch-up behavior. PR checks were green twice; production health
  reported `sha=aaab0a0506b77796fe548ed66e40f4828187d256`; web `/` returned 200; same-origin and direct API
  `send-today` unauthenticated POSTs returned 401. Same-day Zwift appearance timing remains an explicit
  first-live-use observation item, documented in #91 and the Now block.
- **2026-06-27** — Started **Batch 25 — Same-day delivery + manual override** on
  `feat/batch-25-same-day-delivery`. Added the same-day Home delivery endpoint
  (`POST /api/v1/workout-delivery/planned-workouts/{id}/send-today`) and UI controls:
  **Send to Zwift** plus manual duration/intensity override dials. The endpoint reuses
  the existing delivery proposal table and intervals.icu rail, builds from the stored
  verdict-adjusted IR, audits proposal + push rows, and re-checks Red-never-VO2 before
  calling intervals.icu. Superseded the old two-day-ahead default by setting
  `DEFAULT_LEAD_DAYS=0`; updated `DECISIONS.md` #91 and `ARCHITECTURE.md`. Focused
  verification passed: API suite 273 passed / 85 skipped; ruff + mypy clean; web vitest
  36 passed; web build OK; web lint 0 errors / 5 existing warnings; shared tests 7 passed;
  browser smoke with local mock API confirmed the new Home send/override flow. Fresh same-day
  Zwift latency observation is still outstanding before closeout.
- **2026-06-27** — **Closed out Batch 24 — Time-aware home** (PR #37, squash merge `fa8a036`, prod verified).
  Shipped the phase-driven Home to production: pre-ride (sleep snapshot + ride card), post-ride (ride analysis
  + tomorrow + tonight + bedroom), and explicit strength/rest-day “nothing to ride today” handling, all derived
  from the existing `/api/v1/daily-loop` payload. Moved the dense reads onto detail routes
  `/brief`, `/baselines`, and `/bedroom`; added shared frontend helpers
  `apps/web/src/hooks/{useDailyLoop,useDailyPhase}.ts` and `apps/web/src/lib/dailyFlow.ts`;
  rewrote the dashboard/detail-page frontend coverage. CI green on PR #37; production verified with
  Railway `/api/v1/health` sha=`fa8a036…`, Vercel production `https://garmin-coach-one.vercel.app` serving
  the CheckMark shell, and unauthenticated `GET /api/v1/daily-loop` returning 401 as expected.
- **2026-06-27** — Built **Batch 24 — Time-aware home (daily-flow rebuild)** on
  `feat/batch-24-time-aware-home`. Replaced the kitchen-sink dashboard with a phase-driven Home based on the
  existing daily-loop payload: pre-ride (sleep snapshot + ride card), post-ride (ride analysis + tomorrow +
  tonight + bedroom), and strength/rest-day (“nothing to ride today”, with non-bike work still shown). Added
  shared frontend-only helpers `apps/web/src/hooks/{useDailyLoop,useDailyPhase}.ts` and
  `apps/web/src/lib/dailyFlow.ts`; moved dense reads onto detail routes
  `pages/{MorningBriefPage,BaselinesPage,BedroomPage}.tsx` wired at `/brief`, `/baselines`, and `/bedroom`;
  rewrote `DashboardPage.test.tsx` for pre-ride/post-ride/rest-day/offline coverage and added
  `DailyDetailPages.test.tsx`. Verified with `pnpm --dir apps/web test` → **34 passed** and
  `pnpm --dir apps/web build` OK; lint still reports the same 5 pre-existing `react-refresh/only-export-components`
  warnings in shared UI/context files and no new errors.
- **2026-06-27** — Merged the Garmin history backfill follow-up to `main`. Added
  `--detail-types` to `apps/api/src/garmin_history_backfill.py` so historical runs can still
  write activity summaries for every type while scoping the expensive per-second detail fetches
  to chosen `activityType.typeKey` values only; threaded the filter through
  `GarminConnectClient.fetch_activity_payloads`, preserving the old defaults (`None` = all
  details, `--no-activity-details` = none). Added focused tests for CSV parsing, runner plumbing,
  and Garmin-client filtering. Verified with
  `PYTHONPATH=apps/api apps/api/.venv/bin/python -m pytest apps/api/tests/test_garmin_sync.py apps/api/tests/test_garmin_history_backfill.py`
  → **17 passed, 5 skipped**.
- **2026-06-26** — **World-class UI/UX redesign SHIPPED (PR #35, squash merge `dea04da`, CI green, prod verified).**
  Acted as a UI/UX designer reviewing the finished app against Mark's *original* requirement docs
  (`~/Downloads/Dad Fitness/`: App Optimisations = his feature wishlist, the Handover Document = profile/
  protocol/framework, the AI Daily Check-in = desired output format — now captured in memory
  `reference_dad_requirements_docs`). The diagnosis: strong design-token/craft layer, but the app read as a
  developer dashboard — AI output dumped as raw markdown (his "bold each headline" ask showed literal `**`),
  the Metrics-vs-Baselines table he wanted was computed then hidden, a 10-tab mobile bar (3-tab desktop with
  7 unreachable routes), and a 774-line kitchen-sink Home. Full redesign in 7 phases: (1) `Markdown.tsx`
  renderer + surface `metricsVsBaselines` (additive `daily_loop.py`/shared schema, no migration) +
  `MetricsBaselineTable`/`VerdictHero` primitives; (2) nav → Home/Plan/Trends/More (`navConfig.ts`,
  `MoreMenu.tsx`, TabBar/TopBar); (3) Home rebuilt read-first + check-in split to `CheckInPage.tsx`;
  (4) Plan = whole week incl. strength, de-jargoned Zwift; (5) Trends recharts charts + Reviews polish;
  (6) admin screens consistency/de-jargon; (7) live headless verification (mock-data middleware, prod-free —
  Home/baselines/Plan/Trends screenshotted; fixed table mobile-clip + invisible chart lines). **Verified:** web
  typecheck+lint(0 err)+28 vitest(6 new)+build; shared 7; backend ruff+mypy; CI all green on the PR;
  prod `/api/v1/health` sha=`dea04da`, web 200, daily-loop 401. DECISIONS #90.
- **2026-06-24** — **`metric_baselines` seeded for Mark from DB history (built, working tree, not yet committed).**
  The #85 year backfill left `metric_baselines` empty, so the morning "Metrics vs Baselines" read (ARCHITECTURE
  §4) was falling back to static KB profile bands. Rather than belatedly run the never-applied 84-night xlsx,
  derived the baselines from the real DB history: extracted the xlsx importer's per-metric stats into a pure,
  source-parametrized core `services/sleep_history.py::compute_metric_baselines(samples, *, source)` (xlsx
  `build_metric_baselines` now a thin wrapper → identical output, existing tests unchanged); added
  `services/metric_baselines.py::MetricBaselineBackfillService.rebuild` (reads `sleep`+`daily_metrics`, joins per
  day with the *exact* column mapping of `morning_analysis._metrics_vs_baselines` so baseline ⟷ current are
  apples-to-apples, configurable trailing window, idempotent upsert, dry-run, `source=db_history`) + CLI
  `src/metric_baselines_backfill.py`. #45 SpO2/HRV cutoff honoured by reusing the existing reliability specs.
  Tests: 5 pure + 5 DB-backed in `tests/test_metric_baselines.py` (create+cutoff, idempotent, dry-run, window,
  xlsx-source coexistence) plus the morning-fallback invariant (empty → KB-band fallback; populated → surfaced).
  **Verified against prod via `railway run`:** dry-run then write → 7 baselines under `db_history` (84-night
  window 2026-04-02 → 2026-06-24); a read-only check confirmed `_metrics_vs_baselines` now returns 7 populated
  rows (was 0) with the #45 cutoff applied (SpO2 n=11/excl=69, HRV n=14/excl=70, reliFrom=2026-06-11). Local
  ruff + mypy(src) clean; pure tests pass (DB tests skip — no local Postgres, run in CI). Recorded DECISIONS #88,
  ticked ARCHITECTURE §5. **No prod deploy required** (morning read path already live). Next: commit on a branch
  + PR if wanted.
- **2026-06-24** — **Wake-triggered morning verdict (built, branch `feat/wake-triggered-morning`, PR pending).**
  Replaced the fixed 06:30 morning cron with a wake-detection trigger so the verdict reads Mark's finalized
  overnight metrics whatever time he surfaces (his median wake is 08:22 / 98.6% after 06:30, so 06:30 was
  almost always ~2 h too early). Added a pure decision core `services/wake_detection.py::is_morning_ready`
  (fire/wait/nap_ignored + the sleepEnd to persist) implementing the back-to-sleep **stability guard** —
  fire only once today's Garmin `sleepEnd` matches the previous poll's value, sits ≥20 min in the past, and
  clears a 180-min duration floor (excludes naps); a later `sleepEnd` ⇒ keep waiting. `scheduler.run_wake_check()`
  drives it per active profile within a 03:30–10:00 Europe/London window: short-circuits when today's morning
  analysis already exists (cheap `analyses` read, no Garmin call), else a **light sleep-only** poll (new
  `GarminConnectClient.fetch_sleep` = one `get_sleep_data`, not the ~10-call `fetch_daily_payloads`), persists
  the last-seen `sleepEnd` as a migration-free `wake_check` audit row, and runs the **unchanged**
  `run_morning_weather_sync` once ready. Backstop is belt-and-suspenders: a dedicated `morning_backstop` 09:30
  cron **and** `is_morning_ready`'s `now ≥ backstop` branch both guarantee a verdict. Wiring: replaced the
  06:30 cron in `create_scheduler()` with the `wake_check` 15-min interval (seeded +3 min) + `morning_backstop`
  cron; added `wake-check` to `run_scheduled.JOBS`. Tests: 18 pure matrix + 6 mock-orchestration (run locally)
  + 3 DB-backed (persist→compare→fire, backstop, short-circuit — CI-only, skip without `DATABASE_URL`); updated
  the existing `create_scheduler`/lifespan/`run_scheduled` job-set assertions. **Backend 262 passed / 76
  DB-skipped, ruff + mypy(src) clean.** Precondition met upstream: PR #28 merged + App Sleeping off (always-on
  container, in-process APScheduler reliable + DST-correct) — DECISIONS #86. Recorded DECISIONS #87; ticked
  `ARCHITECTURE.md` §2/§4; marked `docs/designs/wake-triggered-morning.md` Implemented. **Merged** (PR #30,
  squash `f605b26`, CI green all 6 jobs) + STATUS follow-ups (PR #31 `c7838b1`). **Prod deploy confirmed** from
  Railway logs: scheduler registered `run_wake_check` and it fired live at 17:46 UTC (`fired=0` — correctly
  idle out of the morning window, no Garmin call, no error); behavioural fire + `wake_check` audit row pending
  tomorrow's 03:30–10:00 BST window.
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
