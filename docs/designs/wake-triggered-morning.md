# Design: wake-triggered morning verdict

**Status:** **Implemented** (2026-06-24, DECISIONS #87). The scheduling model is
settled: App Sleeping is off (container always-on), so wake detection runs
in-process via APScheduler (which handles BST/GMT) and `run_scheduled wake-check`
is the external-cron fallback. Built as `apps/api/src/services/wake_detection.py`
(pure `is_morning_ready`) + `scheduler.run_wake_check()`; the 06:30 cron is
replaced by a `wake_check` interval job + a `morning_backstop` 09:30 cron.
**Depended on:** PR #28 (scheduler reliability + `apps/api/src/run_scheduled.py`),
DECISIONS #86.
**Related:** `ARCHITECTURE.md` §4 (morning analysis), §2 (sync jobs).

> **As-built note (settling the "Open decisions" below):** backstop **09:30**;
> window **03:30–10:00**, **15-min** cadence; `settle_min` **20**, duration floor
> **180 min**; revision handling = **lock** (reuses morning idempotency — once
> today's verdict exists the poll short-circuits, so a later `sleepEnd` does not
> regenerate); state home = **`analyses`** (`wake_check`); scheduling = **in-process
> always-on** with `run_scheduled wake-check` as the resilient fallback.

## Goal

Replace the rigid 06:30 morning run with one that fires when Mark *actually
wakes up*, detected from his Garmin sleep data, so the verdict is built from his
freshest finalized overnight metrics and is ready when he picks up his phone —
whatever time he surfaces.

## Why it's better (not just nicer)

- **Training Readiness is time-of-day-live** and only finalizes after wake
  (ARCHITECTURE §2/§4: "morning analysis must read in the morning"). Firing at
  wake reads the finalized value, not a pre-dawn placeholder.
- **Sleep score/stages finalize at sleep-end.** A fixed 06:30 can run before his
  watch has even synced the night.
- Personalised to his real schedule (early riser one day, lie-in the next).

## Calibration — Mark's actual wake distribution (363 backfilled nights, 2026-06-24)

Measured from the backfilled `sleep.sleep_end_utc` → Europe/London local:

| metric | value |
|---|---|
| median wake | **08:22** (mean 08:16) |
| range | 03:45 – 09:24 |
| p10 / p25 / p75 / p90 | 07:38 / 08:01 / 08:38 / 08:50 |
| wakes after 06:30 | **358/363 = 98.6%** |
| wakes after 08:00 | 273/363 = 75% |

**Implication:** the legacy fixed 06:30 cron fires ~2 h *before* Mark wakes on
98.6% of mornings — while he is still asleep and readiness/sleep are not
finalized — so for him a fixed morning time is essentially never right. This makes
the wake trigger **near-essential, not optional**, and it calibrates the window
and backstop below to *him* rather than generic defaults.

## Signal

Garmin's sleep record carries `sleepEndTimestampGMT` — already parsed as
`sleep_end_utc` by `parse_sleep_fields`. "Awake" = today's consolidated sleep
session has a finalized `sleepEnd` in the past.

## The back-to-sleep problem & the stability guard (the key correctness point)

- Garmin records **one consolidated overnight session**; brief awakenings are
  *awake epochs inside* it, so a quick wake-and-resleep does **not** move
  `sleepEnd`.
- A morning **nap is a separate record** and does not extend the main session.
- Residual risk: a genuine **two-block night** where Garmin closes the first
  session early.
- **Guard:** do not fire on first detection. Fire only once today's `sleepEnd`
  is **stable across two consecutive polls** (~15–30 min unchanged), is in the
  past, and the session clears a **duration floor** (excludes naps). If he drifts
  back to sleep, the next poll shows no finalized record or a *later* `sleepEnd`,
  so we wait until it settles at his true get-up. Cost: verdict lands ~15–20 min
  after wake rather than instantly — a fair trade for not building it on a
  half-night.

## Mechanism

A `wake-check` job polls `get_sleep_data(today)` every ~15 min within a morning
window (~04:30–10:00 local). One cheap Garmin call per poll. Per poll:

1. If today's morning analysis already exists → done; **skip** (cheap `analyses`
   check, no Garmin call needed — short-circuits the rest of the day).
2. Else fetch today's sleep; evaluate the stability guard against the
   **previously persisted** `sleepEnd` for today.
3. If finalized + stable + duration-floor met → run the full
   `run_morning_weather_sync` (sync + verdict + Amber regen), **once**.
4. Else persist the current `sleepEnd` as "last seen" for the next poll's
   comparison, and wait.

**Backstop:** if not run by a fallback time (default **~09:30 local**), run
`run_morning_weather_sync` anyway on whatever data exists, so a verdict is
**always** produced (watch not worn / never synced).

## State / persistence

- **Idempotency per day:** reuse the existing morning-analysis idempotency
  (`generate_and_store` is idempotent per `subject_date`); the `wake-check`
  short-circuits when today's morning-analysis row exists.
- **Stability tracking:** the "last seen `sleepEnd` for today" must persist
  between 15-min polls (the scheduler is stateless across runs). Prefer a
  lightweight audit row in `analyses` (`analysis_type='wake_check'`) keyed per
  (user, date) — migration-free, mirrors prior batches — over a new table.

## Pure-function core (testable, no I/O)

`is_morning_ready(today, sleep, *, prev_sleep_end, now, duration_floor_min,
settle_min) -> WakeDecision` returning `{fire | wait | nap_ignored}` plus the
current `sleepEnd` to persist. Unit-test matrix:

- finalized + stable (`sleepEnd == prev_sleep_end`, settled ≥ `settle_min`) → **fire**
- first sighting (`prev_sleep_end is None`) → **wait** (persist current)
- back-to-sleep (current `sleepEnd` later than prev) → **wait** (persist later value)
- nap (duration < floor) → **nap_ignored**
- unfinalized (no `sleepEnd`) → **wait**
- past backstop time → **fire** regardless

## Wiring (settle the scheduling model first)

- **If container always-on:** replace the 06:30 `morning_weather_sync` cron with
  an in-process interval `wake_check` job (every 15 min, gated to the window) + a
  ~09:30 backstop cron. In-process APScheduler handles DST correctly.
- **If external cron (PR #28):** add `wake-check` to `run_scheduled.JOBS`; a
  Railway Cron runs `python -m src.run_scheduled wake-check` every 15 min in the
  window; the job itself enforces the ~09:30 backstop by comparing London-local
  time. The DST caveat in the runbook applies to the window/backstop bounds.

## Open decisions (settle when implementing)

1. **Backstop time** — **~09:30 Europe/London** (data-backed: p90 wake 08:50,
   latest 09:24, so firing at 09:00 would sometimes precede his wake; 09:30 clears
   p90 with margin).
2. **Window + cadence** — **~03:30–10:00**, every 15 min (data-backed: earliest
   wake 03:45, median 08:22 — start before the earliest riser, end past the latest).
3. **Stability threshold** — `settle_min` ~20–30 min (≈2 polls); **duration
   floor** ~180 min (tune to Mark's real nights so naps never trigger).
4. **Revision handling** — if `sleepEnd` moves materially *after* we've fired
   (rare), **lock** the day's verdict vs. allow one regenerate. Leaning lock
   (avoids a 2nd LLM call; the change is usually minor).
5. **State home** — `analyses` (`wake_check` audit) vs. a small state table.
   Prefer `analyses`, migration-free.
6. **Scheduling model** — in-process always-on vs. external cron (gates the
   wiring above; tied to the Railway App-Sleeping decision).

## Reuses (thin integrator, no new sync/verdict logic)

- `run_morning_weather_sync` (unchanged) for the actual sync + verdict.
- `parse_sleep_fields` / `sleep_end_utc`, `GarminConnectClient` `get_sleep_data`.
- `run_scheduled` (PR #28) as the cron entry point.
- Existing morning-analysis idempotency.

## Testing

- Pure `is_morning_ready` decision matrix (above).
- DB-backed (injected fake Garmin client, no LLM): short-circuits when today's
  analysis exists; fires once on stable wake; respects the backstop;
  persists/compares last-seen `sleepEnd`. Mirrors the existing scheduler tests.

## Non-goals

- Real-time "instant he opens his eyes" — we depend on Garmin sync latency
  (minutes).
- Changing the verdict logic itself — only the **trigger** changes.
