# Design: Interval-resolved ride analysis — "analyse the workout as a set" (Batch 44)

**Status:** **SHIPPED** — Batch 44, PR #63, squash `432e6b4`, DECISIONS #114 (2026-07-03).
Designed with Craig on 2026-07-02 after Mark reviewed the app's post-ride analysis
against the read Copilot gives him and named a real accuracy bug in plain English:

> *"we need to fix its analysis first — it's basing it on average power expecting
> the power for the full workout to be in sweet spot range, which isn't right. Only
> the sweet spot intervals will be in sweet spot power and it shouldn't be including
> power from other intervals eg warm up and cool down. It basically needs to analyse
> the workout as a set, not base it all on its name."*

Decision number assigned at `/batch-start` (next free **#114**).

This is the **first batch that goes *back into* the cycling `post_workout` packet**
to enrich it, rather than forking a lean packet away from it (Batches 40–43 did the
opposite — they gave *non-cycling* types their own packets *because* those types
have no power/time-series). Cycling is the one type that carries per-second power,
and today we flatten it to averages. This batch finally uses that trace
*structurally*.

## The bug, located in code

The post-ride context packet (`services/post_workout_analysis.py`
`assemble_context_packet`) hands Claude three things that dominate the "how hard did
he ride" signal — and all three blur or omit the interval structure:

1. **`activity.avgPowerWatts`** — [`_activity_packet`, line 469] — Garmin's whole-ride
   mean power.
2. **`timeSeriesSummary.power.avg`** — [`_time_series_summary` → `_series_stats`,
   line 522] — the mean of *every* power sample across the whole file.
3. **`timeSeriesSummary.powerZones`** — [`_power_zone_distribution`, line 532] — a
   time-in-zone histogram. This is a *partial* mitigation (a model can infer "~25 % of
   samples in Z4 ≈ a ~20-min sweet-spot block") but it is coarse: it can't isolate one
   clean block from scattered surges, can't see fade *within* a block, and can't match
   segments to each interval's own target.

The packet gives the model the **planned** structure (`plannedWorkouts[].structuredWorkout`,
[line 582]) but **never the executed effort segmented into intervals and graded against
each interval's target**. So the model is handed a misleading whole-ride average *plus*
the workout's name/plan — and with nothing between them, it either anchors on the
average (which on any structured session sits *below* the work-target band, because
warm-up + recovery + cool-down drag it down) or it pattern-matches the **name**. That
is exactly the failure Mark named: *"base it all on its name."*

## The fix — segment the executed trace, grade each work interval on its own target

The raw material already exists; only the **join** is missing:

- The **planned interval IR** — `services/workout_delivery.py::build_structured_workout_ir`
  ([line 139], Batch 12.1) — already emits ordered steps, each with `label`, `kind`
  (`steady`/`ramp`), `durationSec`, `powerStartPct`/`powerEndPct` (% FTP target band),
  and optional `cadenceRpm`. Cumulative `durationSec` gives the interval **boundaries**;
  the power-pct band gives each interval's **target**.
- The **executed per-second trace** — `ActivityTimeSeries` ([coaching.py:139], backfilled
  under DECISIONS #93) — carries `elapsed_sec`, `power_watts`, `heart_rate_bpm`,
  `cadence_rpm` per sample.

A pure, DB-free `segment_ride_intervals(timeseries, ir, ftp_watts)` walks the IR steps in
order, slices the per-second trace into each step's `[t_start, t_end)` elapsed-time
window, and emits one **interval object** per step:

| Field | From |
|---|---|
| `index`, `label`, `role` | IR step order + `label`/`kind` + target (see role rule) |
| `durationSec` | IR step duration (executed window) |
| `avgPowerWatts`, `normalizedPowerWatts` | trace slice (NP only when ≥ ~30 s, else avg) |
| `pctFtp` | interval avg power ÷ FTP |
| `powerZone` | zone of the interval's avg (reuse `_power_zone`) |
| `avgHeartRateBpm`, `maxHeartRateBpm`, `avgCadenceRpm` | trace slice |
| `targetPctFtpLow`/`High` | IR `powerStartPct`/`powerEndPct` |
| `adherence` | `on` / `over` / `under` vs the target band — **work intervals only** |
| `fade` | first-third vs last-third avg power drop within the interval (power fade) and HR drift — the signal that earns "no fade / no surges" |

**Role rule** (which intervals get graded): classify each step from the IR — a `ramp`
at the start = `warmup`, a `ramp` at the end = `cooldown`, a low-target steady step
between work = `recovery`, a higher-target steady step = `work`. Only `work` intervals
carry an `adherence`/`fade` grade; warm-up/recovery/cool-down power is described, never
graded against the work target. This is the literal expression of Mark's *"don't
include warm-up and cool-down power."*

The packet then also gains a small **`execution` summary** — e.g. *"1 × 20 min work,
target 88–94 % FTP; held 91 % avg / 250 W NP; on target; no fade"* — so the model leads
with the graded work, not the blended average.

## Packet, prompt, storage

- **Packet** (`assemble_context_packet`): add `intervals` (the list above) and
  `execution` (the summary). Include the **planned `structured_workout_ir`** (the packet
  currently carries only the raw `structuredWorkout`, [line 582], not the IR).
  **Keep** `activity.avgPowerWatts` and `timeSeriesSummary` but **relabel the whole-ride
  average as context** — it is no longer the execution verdict.
- **Prompt**: extend `SYSTEM_PROMPT` ([lines 34–41]) + `outputRules` ([lines 236–244])
  with an explicit rule — *grade execution on the **work intervals** against their %FTP
  targets; the whole-ride average power is expected to sit below target on a structured
  session and must never be treated as under-performance.* This bumps `PROMPT_VERSION`
  ([line 29]).
- **Storage**: **no migration** in the recommended v1 — intervals are derived in packet
  assembly from the already-stored per-second trace + planned IR; the enriched packet
  lands in the existing `analyses.context_packet` JSONB.
- **Backfill**: bump the prompt version and `generate_and_store(force=True)` for recent
  rides that have both a planned structured workout and a per-second trace — precedent:
  the #51 outdoor-ride backfill (20 rides) and Batch 40's 47-session backfill.

## Free / outdoor rides (no plan)

Mark's target rides are structured indoor Zwift sessions delivered by the app itself, so
their executed timeline tracks the planned IR closely (ERG holds each step for its
programmed duration). A **free or outdoor ride has no planned IR** to align to; for v1 it
**falls back to today's whole-ride + zone-histogram behaviour** (no regression). Getting
interval structure for free rides is the job of the Garmin-splits enhancement below.

## Phases

- **44.1** Pure `segment_ride_intervals(timeseries, ir, ftp_watts)` + the role classifier
  + per-interval NP / %FTP / zone / fade computation — fully unit-testable, no DB. Tests:
  a warm-up→2×SS→cool-down IR over a synthetic trace yields graded **work** intervals at
  the right %FTP with warm-up/cool-down **ungraded**; a fading block flags `fade`.
- **44.2** Wire `intervals` + `execution` + the planned IR into `assemble_context_packet`;
  relabel the whole-ride average as context.
- **44.3** Extend `SYSTEM_PROMPT` + `outputRules`; bump `PROMPT_VERSION`. The thin
  Anthropic boundary is unchanged and stays fakeable (no key in tests).
- **44.4** Free-ride fallback (no IR → current behaviour) + the guardrail test that a
  ride without a plan still produces a valid analysis.
- **44.5** One-off backfill of recent structured rides; regenerate through the new packet.
- **44.6** *(optional, small)* Frontend interval table under the post-ride card — the card
  already renders the analysis markdown, so this is additive, not required for the fix.
- Tests + green gates throughout.

## Testing

- **Pure:** segmentation slices the trace on IR boundaries; NP computed only for
  intervals ≥ ~30 s; work intervals graded `on`/`over`/`under` vs the band; warm-up/
  cool-down never graded; `fade` fires on a decaying block and not on a steady one.
- **Packet:** `intervals`, `execution`, and the planned IR are present; the whole-ride
  average is labelled context; a no-plan ride omits `intervals` and keeps the whole-ride
  summary.
- **Boundary:** generation is fakeable without `ANTHROPIC_API_KEY`; `PROMPT_VERSION`
  is bumped and stored.
- **Idempotency:** unchanged from Batch 8/26 — one analysis per activity, regenerated on
  a newer check-in or a prompt-version change.
- Backend pytest/ruff/mypy pass; web lint/test/build pass for any touched surface.

## Non-goals / out of scope

- **Concision / density pass.** Mark also asked whether the read should be *refined* vs.
  dense; he deflected to *"fix the analysis first."* This batch is **accuracy only** —
  keep Copilot's sectioned structure in mind, but tightening prose is a **separate,
  later** batch, deliberately not bundled here.
- **The "hard-baked" numeric score** (Copilot's 8.5 with 8.8/8.7/8.6 sub-scores). That
  decimal precision is false precision and won't reproduce run-to-run. If a rating is
  added it should be a **coarse band**, not decimals — flagged as a settling question,
  not built by default.
- **Algorithmic interval *detection*** from the raw power trace (changepoint detection)
  — v1 aligns to the known plan; auto-detection is only relevant for free rides and is
  deferred with the Garmin-splits enhancement.
- **No change to the recovery decision** (`_recovery_decision_packet`) — rides still feed
  recovery exactly as today; this batch enriches the *narrative + grading*, not the
  Green/Amber/Red or ride-recovery gate.
- **VO2max trend surface** — a genuinely good idea from the same conversation (Mark checks
  cycling VO2max after every block; it's already synced via `get_max_metrics`), but it's a
  *display* feature, not part of fixing the analysis. Tracked separately.

## Decisions settled at `/batch-start`

1. **Interval source.** Planned-IR alignment over the stored per-second trace
   (**recommended v1** — no new Garmin call, no migration, and accurate for Mark's ERG
   Zwift rides) **vs.** Garmin ground-truth splits via `get_activity_splits` (an extra
   sync call — [`garmin_sync.py:231`] fetches details but *not* splits — plus a small
   `activity_laps` store + migration). Recommendation: **IR-first for v1; laps as the
   documented follow-up** that also unlocks free/outdoor rides.
2. **Free-ride handling.** Fall back to today's whole-ride read (**recommended v1**) vs.
   infer intervals from the trace now.
3. **Fade signal.** Include both power-fade and HR-drift (decoupling) flags, or power-fade
   only, in v1.
4. **Rating.** Add a coarse execution band (Strong/Solid/Off-target) or leave the read
   qualitative (**recommended** — no numeric score).
5. **Backfill window.** Recent structured rides only (**recommended**) vs. the full ride
   history with a planned IR.

## Dependency & sequencing

- **Independent** of Batches 40–43 (those are non-cycling packets); this modifies the
  cycling `post_workout` path only. Reuses Batch 12.1's `build_structured_workout_ir` and
  the DECISIONS #93 per-second trace — both already shipped, so no upstream dependency.
- Naturally built **after** the 40–43 non-cycling set closes out (it touches the
  highest-traffic analysis path — the one Mark reads most — so it wants a clean tree).

## Safety / invariants preserved

- **Recovery isolation** unchanged — the recovery decision packet and Green/Amber/Red are
  untouched; this is narrative + grading only.
- **Idempotent** — one analysis per activity; regenerated only on a newer check-in or the
  prompt-version bump.
- **Reuses the thin Anthropic boundary** (#47) — fakeable, prompt/version stored.
- **Graceful degrade** — a ride with no planned IR or no per-second trace falls back to the
  current whole-ride analysis rather than erroring.
