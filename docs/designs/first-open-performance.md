# Design: First-open latency — persist the cache & thin the daily-loop request (Batch 62)

> Status: **shipped** — PR #86, squash `8a60a76` (production HTTP smoke pending Craig's confirmation; the agent egress policy blocked the prod hosts from the build environment). Decision **#136**.
> Tier: 🔴 High (concurrency + cache-correctness reasoning; 62.1 alone is Mid).
>
> **Build note (2026-07-07):** 62.1, 62.2, the 62.3 SELECT collapse, 62.4, and 62.5
> shipped as specced. The 62.3 **brief parallelization** was built then reverted —
> running the three briefs on separate `AsyncSessionLocal()` sessions breaks
> read-your-writes within the request transaction (the identical-payload snapshot
> test proved it: the parallel briefs read empty because the seed data lived in the
> request's uncommitted transaction), and the win is marginal for 1–2 users. Per
> this doc's own staging ("the SELECT collapse lands first; the brief
> parallelization second") only the safe collapse ships. See DECISIONS #136.

One-line: when Mark first opens the PWA the whole Home screen blocks on one fat
request behind an empty cache. Persist the client cache so the last brief paints
instantly, and move the heavy correlation maths off the hot request path so the
authenticated `GET /api/v1/daily-loop` returns faster.

## The complaint, and what's actually true

"Data is slow to load when I first open the app." Measured before scoping, so we
fix the real thing and not the assumed one.

### It is NOT the server cold-starting
Warm production timings (2026-07-07), unauthenticated:

| Path | total |
|---|---|
| Railway `/api/v1/health` direct | ~0.10 s |
| Vercel-proxied `/api/v1/health` | ~0.11 s |
| Vercel-proxied `/api/v1/daily-loop` (401, bails at auth) | ~0.10 s |

The container is warm — the in-process APScheduler (hive poll, fan control, wake
check every ~15 min) keeps it alive, so there is no Railway scale-to-zero wake.
The Vercel proxy hop is negligible. **Cold container start is not the cause; do
not "fix" it.**

### It IS cold client cache + the single heaviest request
Two things line up only on a fresh launch:

1. **No persisted client cache, `staleTime` default 0.** `QueryClient`
   (`apps/web/src/App.tsx:69`) sets no `staleTime`, and nothing persists React
   Query to storage (no `persistQueryClient`). So a fresh launch (PWA cold start
   / hard reload) starts with an **empty** in-memory cache: `DashboardPage`
   (`apps/web/src/pages/DashboardPage.tsx:284`) has nothing to render, shows the
   skeleton, and blocks on the full network round-trip. In-session navigation
   away-and-back is instant from cache — which is exactly why *only the first
   open* feels slow.

2. **That one blocking request is the fattest endpoint in the app.** The whole
   Home hangs on `GET /api/v1/daily-loop` (`useDailyLoop.ts`), whose handler
   (`routers/daily_loop.py:953` `_envelope`) does, all **sequentially** on one
   session:
   - `DailyLoopService.get_snapshot` — ~15+ awaited-one-after-another DB queries
     (`services/daily_loop.py:115`), including four separate post-`*`-analysis
     SELECTs and three activity-history briefs.
   - `InsightsService.drivers()` — pulls up to **120 days** of metrics / sleep /
     weather / activity rows and computes Pearson correlations, **on every load**
     (`services/insights.py:835`, `DRIVERS_LOOKBACK_DAYS = 120`).
   - `ChronicPatternSuggestionService.suggestions()` — another history scan.

   The ~0.10 s above is only the 401 that bails *before* any of this runs, so the
   authenticated cost is materially higher and unmeasured until 62.5.

Secondary: `apiFetch` calls `ensureFreshToken()` first (`lib/api.ts:36`), which
can fire `/auth/refresh` *before* daily-loop — but only for PIN/JWT sessions;
device-token sessions skip it (`lib/api.ts:37`).

## What we build

### 62.1 — Persist the client query cache (perceived-latency killer, frontend)
The biggest *felt* win, smallest change. React Query is `^5.45.1`, so use the v5
persist packages.

- Add `@tanstack/react-query-persist-client` + `@tanstack/query-sync-storage-persister`.
- In `App.tsx` swap `QueryClientProvider` → `PersistQueryClientProvider` with a
  `createSyncStoragePersister({ storage: window.localStorage, key: 'gc-rq-cache' })`,
  `persistOptions`: `maxAge` 24 h, `buster` = build SHA / app version (so a deploy
  invalidates stale shapes), and `dehydrateOptions` that persist **only** the
  `daily-loop` (and optionally `week-ahead`) query keys — not every query.
- Give `useDailyLoop` a small `staleTime` (≈60 s) so a hydrated brief renders
  immediately and the refetch is background, not blocking; keep
  `refetchOnWindowFocus` and `installResumeRefetch`.
- On login / activate / unlock / logout, `AuthContext` already calls
  `queryClient.clear()`; also **remove the persisted client** (clear the
  `gc-rq-cache` key) so one user's health data can't rehydrate into another
  session.
- `DashboardPage`'s `query.isLoading` gate then only trips on a true first-ever
  open (no cached brief); a returning open paints the last brief instantly and a
  quiet background refetch swaps in fresh data. Pairs with the existing
  `OfflineNotice` — a cold *offline* open now shows the last brief too.

### 62.2 — Precompute drivers + chronic suggestions in the morning sync (backend, biggest server-time win)
The 120-day correlation and the chronic-pattern scan are **deterministic** and,
by their inputs (`DRIVER_KEYS`: overnight temp/wind, bedroom minutes, prev-day
load, stress, RHR, sleep-stress — no manual-entry fields), only change when new
*synced* data lands, i.e. once a day. So compute them once, not on every open.

- Compute point: `run_morning_weather_sync` (`scheduler.py:248`) already runs the
  daily pipeline after the Garmin/weather sync + morning analysis. Compute
  `drivers()` + `suggestions()` there and store the serialized packet. There is
  precedent: `InsightsService.run()` already writes an `AUDIT_TYPE_DRIVERS`
  (`"driver_correlation"`) row into `analyses` with an `_already_recorded`
  idempotency guard — reuse that storage shape (keyed by `subject_date`), so
  **no migration**.
- Read-through in `_envelope`: look up today's stored packet; if present, hydrate
  it; if missing/stale (`subject_date != today`, or no row yet), fall back to the
  current live compute. Output is identical for the common (today, already-synced)
  path — we only move *when* it is computed.
- The backstop (`morning_backstop` 09:30) and the manual-regeneration paths that
  already re-run the morning pipeline refresh the packet naturally.

### 62.3 — Thin & parallelize the snapshot's DB round-trips (backend)
`get_snapshot` stacks ~15 sequential round-trips; if Railway↔Supabase RTT is even
20–40 ms (see 62.4) that is most of the budget. **Constraint:** one `AsyncSession`
= one asyncpg connection and *cannot* run concurrent queries — so we cut the count
and parallelize on separate sessions, not `gather` on the shared one.

- **Cut round-trips:** collapse the four post-`{workout,flexibility,strength,walk}`
  analysis SELECTs into a single `analysis_type IN (...)` query partitioned in
  Python; likewise fold where planned-workouts / adherence / deliveries can share
  a query.
- **Parallelize independent groups:** run the three briefs (strength / walking /
  breathwork) concurrently via `asyncio.gather`, each with its own short-lived
  `AsyncSessionLocal()` (pool is `size=10 + overflow=10`; 1–2 users leave ample
  headroom). Keep result rows and ordering byte-identical to the sequential path.
- Lowest-risk subset if we want to stage it: the post-analysis SELECT collapse
  (pure query change, easy to test) lands first; the brief parallelization second.

### 62.4 — Verify region colocation & connection warmth (investigation / config)
Potentially the single biggest factor and a **config-only** fix.

- Confirm the Railway service region matches the Supabase project region. If they
  differ, every one of the ~15 sequential queries pays a cross-region RTT —
  colocating them may beat all the code changes combined.
- Connection warmth: `pool_recycle=1800` (`database.py:8`) + idle means the first
  request after 30 min re-establishes a Supabase-pooler connection (TLS + auth).
  Add a tiny `SELECT 1` warm-ping to an existing ~15-min scheduler job so a
  pooled connection is usually hot when Mark opens the app.
- Measure-first: instrument authenticated `/daily-loop` server time to attribute
  the budget (network vs snapshot vs drivers) before/after 62.2–62.3.

### 62.5 — Measurement, tests, gates
- **Baseline + after:** lightweight structlog timing on the daily-loop handler
  (or a timing smoke) to capture authenticated p50 before and after, so the
  acceptance target is a real number, not a guess.
- **Web tests:** hydrated brief renders without a spinner; logout clears the
  persisted cache; `buster` change invalidates it.
- **Backend tests:** drivers/suggestions read-through returns the stored packet
  and falls back to live compute when absent; the parallelized + collapsed
  snapshot returns a payload identical to the sequential implementation for a
  fixed DB state.
- **Gates:** backend pytest / ruff / mypy; shared typecheck; web vitest / tsc /
  lint / build (Node 20).

## System interactions & safety (the real risk surface)
- **No change to any decision output.** Verdict logic, morning analysis, sleep
  scoring (#135), soft-sleep override (#133), completed-workout/check-in (#134),
  Red-never-VO2 — all untouched. This batch changes *when* and *how fast* data is
  computed and delivered, never *what* it says. The identical-payload test in 62.5
  is the guard.
- **Privacy — health data now at rest in `localStorage`.** The persisted cache
  stores the daily-loop payload (sleep, HRV, verdict) on the device. Accepted for
  a private single-user PWA that already keeps tokens + player there, but bounded:
  `maxAge` cap, scoped to the `daily-loop` key only, cleared on logout. Record as
  a Decision trade-off.
- **Session concurrency.** 62.3 must not `gather` on the shared request session;
  each concurrent task gets its own `AsyncSessionLocal()`. Getting this wrong
  surfaces as intermittent asyncpg "operation in progress" errors under load.
- **Stale precomputed packet.** If the morning packet is missing (new user, sync
  failed, viewing a past `subjectDate`), 62.2 must fall back to live compute — the
  cache is an optimization, never a correctness dependency.

## Boundaries (non-goals)
- Not a container cold-start fix (measured warm ~0.10 s — not the problem).
- No new user-facing feature; latency and perceived-latency only.
- No DB migration if the drivers cache reuses the `analyses` audit row (preferred).
  A dedicated cache table would be a migration — avoid unless 62.2 proves it needed.
- Not touching the auth/refresh preflight beyond noting it; a device-token session
  already skips it.

## Verification plan
Backend pytest/ruff/mypy, shared typecheck + tests, web vitest/tsc/lint/build under
Node 20; then the standard closeout production smoke on the merge SHA (Railway +
Vercel same-origin `/api/v1/health` returns the SHA, web `/` 200, unauthenticated
`GET /api/v1/daily-loop` 401 direct and via Vercel), plus a before/after
authenticated daily-loop timing captured via `railway run` / instrumented log.

## Resolved defaults (decided at spec time; `/batch-start` may still adjust)
1. **Ship as one batch.** The four phases share one goal (first-open latency) and
   one identical-payload safety test; 62.1 is the independently-valuable lead but
   stays in the batch rather than a separate fast-follow.
2. **`staleTime` = 60 s** on daily-loop — long enough to skip a redundant refetch
   on a quick reopen, short enough that a stale verdict never lingers. Tune during
   62.1 if the background swap feels visible.
3. **Drivers cache reuses the `analyses` `driver_correlation` row** (no migration).
   A dedicated cache table is only revisited if 62.2 proves the audit row can't
   carry both the drivers and the chronic-suggestions packet cleanly.
4. **Parallelization does both:** the post-analysis SELECT collapse (safe, lands
   first) and the brief `gather` (bigger win), the latter gated behind the
   identical-payload test in 62.5.
