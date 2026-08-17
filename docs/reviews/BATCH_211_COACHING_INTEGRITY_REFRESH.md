# Batch 211 — Coaching-integrity audit refresh

**Date:** 2026-08-17 · **Predecessors:** 2026-07-10 baseline, Batch 155
(2026-07-26), Batch 191 (2026-08-06) · **Auditor lens:** exercise physiologist +
cycling coach · **Diagnose-only** — no product code, prompt, threshold, verdict,
plan, proposal, migration, config or production row changed by this batch.

**Framework:** `COACHING_INTEGRITY_AUDIT.md`. Mark-safe scorecard:
`docs/reviews/BATCH_211_MARK_SCORECARD.md`.

---

## The question this refresh exists to answer

Batch 191 closed with: *"Closing CI191-01 and CI191-02 is what now moves this to
A−."* Batches 194 and 205 have since shipped, claiming exactly those two. This
refresh asks whether they are **closed on real data**, which is Batch 191's own
kickoff rule: a remediation counts as closed only when it is observed working on
real data, not when the code implementing it is present.

### Grade: **A− (up from B+)**, with one stated reservation

Both Highs are closed. CI191-02 is closed **and observed firing on a live
morning**. CI191-01 is closed and **proved against the exact real Red that
defeated the old rule**, but has not yet been exercised by a live Red, because
Mark has not had one since 2026-08-08 — which predates the fix. That reservation
is why this is A− rather than A, and the next refresh should confirm it on a real
morning.

### Observation window — read this before trusting any "in the wild" claim

This is a **narrow** window and materially narrower than Batch 191's:

| Fix | Shipped | Mornings since |
|---|---|---|
| Batch 194 (CI191-01) | 2026-08-15 | 2 |
| Batch 205 (CI191-02) | 2026-08-16 | **1** |

Batch 191 had twelve. Claims below are labelled **observed** (a live morning did
it), **proved** (the real function driven with real recorded inputs — no window
needed) or **implemented** (code read only, weakest).

---

## CI191-01 — a Red can no longer be talked away · **CLOSED (proved)**

### What the defect looked like on real data

The 2026-08-13 production packet is a textbook instance, recorded *after* Batch
191 named the problem and *before* Batch 194 fixed it:

```
08-07  checkInReasons=[alcohol]  classification=explained_by_check_in  counts=FALSE
       physiology: HRV 43 (floor 45, UNBALANCED), RHR 47 (ceiling 45), recovery 1 min
08-08  checkInReasons=[]         classification=systemic_markers_strained  counts=true
       physiology: HRV 44 (floor 45, UNBALANCED), RHR 45 (ceiling 45), recovery 291 min
```

On 08-07 **both** systemic markers were strained — HRV below its own floor, resting
HR above its own ceiling — and the single word *"alcohol"* removed the Red from
the cluster anyway. `redMorningCount` read 1 against
`redMorningObservedCount` 2 on every morning from 08-10 to 08-13.

### What the current code does with the same inputs

Prong A: the real `_qualify_red_morning` driven with that packet's physiology
copied verbatim. Probe script kept in the session scratchpad, not committed.

```
The real 08-07 Red, exactly as production recorded it
  alcohol, HRV 43<45 floor, RHR 47>45 ceiling      counts=TRUE   acute_cause_with_systemic_strain
  08-08 no check-in, HRV 44<45 floor               counts=TRUE   systemic_markers_strained

Which excuses still work at all (clean physiology, same day)
  alcohol                                          counts=false  explained_by_acute_check_in
  illness                                          counts=false  explained_by_acute_check_in
  travel                                           counts=false  explained_by_acute_check_in
  training_load                                    counts=TRUE   endogenous_training_signal
  deliberate_rest                                  counts=TRUE   endogenous_training_signal

Endogenous beats acute when both are present
  alcohol AND training_load                        counts=TRUE   endogenous_training_signal

Decay
  alcohol, 1 day old                               counts=false  explained_by_acute_check_in
  alcohol, 5 / 10 / 20 / 40 days old               counts=TRUE   acute_check_in_expired

Cap  (ACUTE_RED_EXCLUSION_LIMIT = 1)
  cap still available                              counts=false  explained_by_acute_check_in
  cap already spent                                counts=TRUE   acute_exclusion_cap_reached
```

All four bounds Batch 194.2 promised are real and independently demonstrable:
**physiology may contradict the excuse**, **endogenous tags never excuse at all**,
the exclusion **decays**, and it is **capped at one**. The sharpest edge the
original finding named — `training_load` excusing a Red *because* Mark named
cumulative load, which is the signature the deload path exists to catch — is
gone outright.

**Reservation.** No Red has occurred since 2026-08-08, so the live path has not
run. This is *proved*, not *observed*.

---

## CI191-02 — the day's record means one thing · **CLOSED (observed)**

Batch 205 shipped 2026-08-16 15:25 UTC. Exactly one wake sync has run since, on
2026-08-17 — and it did the right thing.

```
date    phase    readiness  level     recovery   Garmin timestamp
08-17   morning     67      MODERATE     590     09:01     <- today, day not yet closed
08-16   morning     38      LOW         2000     07:42     <- wake row, INTACT
08-16   settled     44      LOW         1520     18:15     <- written by today's D-1 re-sync
08-15   morning     69      MODERATE       1     08:16
08-15   settled     26      LOW         2849     17:32
08-14   morning     62      MODERATE      40     06:38
08-14   settled     62      MODERATE       1     21:16
08-13   morning     50      MODERATE      23     08:26
08-13   settled     42      LOW           666    20:12
```

The 08-17 morning run wrote today's `morning` row and re-synced the closed days
into `settled` rows **without touching the wake rows**. That is the defect closed,
observed on production data rather than asserted by a test.

**08-15 is the case worth keeping.** Mark was told **69 / MODERATE with a
1-minute recovery clock**. Before Batch 205 every retrospective consumer — the Red
qualification's `recovery_time_min`, the 84-day baselines the floors key off, the
trend alarm, the chronic misses — would by now be reading **26 / LOW with 2,849
minutes** for that same morning. A 43-point readiness gap and a 2,848-minute
recovery gap, on a day the coaching called moderate.

Today's row carries only a `morning` phase, correctly: the day has not closed, so
there is no settled observation to record yet.

**Backfill integrity.** 56 historical `morning` rows were reconstructed from the
stored packets; all four dates above show a genuine wake timestamp and a non-empty
`raw_payload`. The reconstructed rows are identifiable by an `updated_at` of
`2026-08-16 14:26:09` — the migration's own timestamp.

---

## CI191-08 — the deterministic protections reached the shared floors · **CLOSED**

Batch 191 found that none of the five deterministic protections added since Batch
155 was in `coach_policy.FLOORS`, so their non-softening rules were hand-written
into one prompt, unprotected by the drift test and not inherited by chat. All
five are now there, and `FLOORS` carries **10** entries each with a recognizer
*and* an inverted negative control (Batch 199):

`never_vo2_on_red` · `no_power_balance` · `local_clock_times` ·
`no_skipped_as_live` · `recorded_data_honesty` · **`training_load_cap`** ·
**`sleep_credit_ceiling`** · **`cumulative_escalation`** ·
**`readiness_baseline_trend`** · **`chronic_action`**

---

## The spoken layer has started speaking

Batch 191's mitigating observation was that the spoken layer had not undermined
the deterministic one "largely because it has barely spoken". That is no longer
the excuse:

| | Batch 191 (08-06) | Now (08-17) |
|---|---|---|
| `state_change` coach turns | **0 ever** | 1 |
| Newest `weekly_review` turn | 2026-06-29 | **2026-08-16** |
| User turns in the thread | 41 | 92 |

The rails are live. With `FLOORS` now covering the five protections and every
floor carrying a failing negative control, the spoken layer is speaking into a
materially better-guarded prompt surface than when it was silent.

---

## Verdict distribution — the ladder got stricter, as intended

Last 30 days: **32 morning reads — 19 Green (59%), 5 Amber, 8 Red.**

Across the four audit windows: 48% → 71% → 75% → **59% Green**. The direction
reversed after a run of batches (194, 199, 201) whose every mechanism only ever
hardens. Eight Reds in thirty days on an athlete the July window called 75% Green
is the ladder doing its job, not a regression.

---

## New finding

### CI211-01 — Low — a proposal for a date that has passed is never retired

**Where:** `coach.workout_delivery_proposals`; no expiry path exists in
`services/workout_delivery.py`.

**Evidence.** Sixteen rows sit at `status='proposed'`, and **every one of them is
for a workout date already in the past** — earliest 2026-06-27, latest 2026-08-13,
against today's 2026-08-17. None was ever pushed (`intervals_event_id` null on all
16). By comparison 89 rows reached `pushed` and 6 were explicitly `deleted`. They
have accumulated at roughly two a week for seven weeks and nothing will ever clear
them.

**Impact, honestly bounded.** This is hygiene, not a live defect. The daily loop
looks proposals up by `planned_workout_id`, so a stale row surfaces only if Mark
navigates back to that specific past day; it cannot appear against today's
session. The risk is drift: a growing set of undecided rows makes "is there an
open proposal?" a progressively less meaningful question, and it is the same
shape as CI191-03 (a withdrawn escalation leaving its proposals standing), which
Batch 194.3 addressed only for the withdrawal path, not for natural expiry.

**Remediation stub.** Retire a `proposed` row once its `workout_date` is past —
either a terminal `expired` status written by an existing scheduled job, or a
read-time derivation so no writer is needed. Prefer the read-time derivation: it
needs no migration and no new job, matching how Batch 144 handled the orphaned
`generating` brief state.

---

## What did not change

- `_morning_verdict` remains deterministic Python; the model is nowhere near it.
- `readinessEffectiveFloor` resolved to the absolute **60.0** on every morning
  examined (08-10 → 08-17), so F1's anchor is still load-bearing and Mark's
  personal centre is still below it.
- No narrative softening was found on any non-Green morning.

---

## Carried forward for the next refresh

1. **Confirm CI191-01 on a live Red.** The single outstanding item behind a full
   A. It needs a Red to occur, which cannot be forced honestly.
2. **Re-run this refresh on a wider window.** One morning of CI191-02 evidence is
   enough to show the mechanism works and not enough to characterise it.
3. **`updated_at` is insert time, not update time.** `UpdatedAtMixin` sets a
   `server_default` with no `onupdate`, so a row updated in place keeps its
   original timestamp. This misled the reading of `daily_metrics` twice during
   this audit and misled Batch 191 once. Do not use it to date a change.
