# Design: Proactive push + fan-reconciled nudges (Batch 45)

**Status:** Specced, not started. Backend-focused, no migration. Decision
assigned at `/batch-start` (next free **#115**).
First batch of the passive-first loop plan (2026-07-03 reassessment). The
smallest, highest-impact tweak: turn the app **push-first** and stop the evening
nudges contradicting the Batch 27 fan autopilot.

## Problem

The two highest-value outputs the app produces are **generated silently and
never pushed**:

- The **morning verdict** — `run_morning_weather_sync` calls
  `MorningAnalysisService.generate_and_store` (and the 09:30 backstop) and stores
  the Green/Amber/Red read, but sends no notification.
- Each **post-workout analysis** — the hourly `run_garmin_activity_poll` runs
  `generate_for_pending_rides` / `_flexibility` / `_strength` / `_walks` and
  stores the per-session read, but sends no notification.

The only things that push today are the static 20:00 `run_evening_nudge` and the
`run_monitoring_alerts` thermal / stale-source alerts. So Mark has to **open the
app** to discover his verdict or post-ride read is ready — the opposite of the
"push things to him so he doesn't have to think about it" principle.

Separately, the evening **thermal nudges** (`nudge_alerts.evaluate_thermal_alert`,
`PROMPT_VERSION = notification-rules:v1`) still tell Mark to *manually*
"Pre-cool now", "Seal it now", "Start pre-cooling toward 17C" — copy written
**before** the Batch 27 fan autopilot shipped. Now that `run_fan_control` drives
the room itself overnight, those nudges are redundant or contradictory (telling
Mark to do what the fan is already doing). The "notify only if he must physically
act" model Mark described is currently inverted.

## Builds on / reuses

- **`push_notification_service.send_notification`** — the existing web-push
  boundary (timezone + quiet-hours aware, records the send), already used by
  `NudgeAlertService`.
- **`NudgeAlertService._send_once`** — the idempotency pattern: dedupe by writing
  an `analyses` audit row keyed on `analysis_type` + `tag` + `subject_date`, and
  short-circuit if a matching `tag` already exists. Reused verbatim so a verdict
  or analysis pushes **exactly once**.
- **The two scheduler completion points** — `run_morning_weather_sync` (after
  `analysis_result.generated`) and `run_garmin_activity_poll` (after each
  `generate_*` returns freshly generated analyses). No new job, no new cron.
- **Batch 27 fan state** — `run_fan_control` writes `fan_state_readings.action`
  ∈ {`apply`, `hold`, `no_data`, `unreachable`, `winddown`}; `describe_fan_intent`
  surfaces the loop's computed intent on `thermalState.fan`; `Profile.fan_auto_enabled`
  is the master switch. Used to decide whether the room is "being handled".

## What the change adds

**Backend**

- **Morning-verdict push** — in `run_morning_weather_sync`, after
  `analysis_result.generated`, send one push (`analysis_type='verdict_push'`,
  tag `verdict-{subject_date}`): title e.g. "Today: Amber" + the verdict's
  one-line headline, `data.url='/'`. Idempotent per (profile, subject_date) via
  the `_send_once` tag, so the 09:30 backstop and any regeneration never
  double-push.
- **Post-workout push** — after each `generate_*` pass, send one push per
  **newly generated** analysis (`analysis_type='analysis_push'`, tag
  `analysis-{activity_id}`): "Ride analysis ready" / "Strength read" /
  "Mobility read" / "Walk read", `data.url='/'`. Idempotent per `activity_id`, so
  regeneration on a newer check-in or a `PROMPT_VERSION` bump does **not**
  re-push. Covers ride / strength / flexibility / walk; **breathwork has no
  per-session analysis** (brief only, DECISIONS #112) so there is nothing to push.
- **Fan-reconciled thermal nudges** — in `evaluate_thermal_alert` /
  `run_monitoring_alerts`, consult the latest `fan_state_readings` +
  `fan_auto_enabled`:
  - When the autopilot is **on and handling the room** (latest `action` ∈
    {`apply`, `hold`, `winddown`}), **suppress** the manual pre-cool / seal
    "you do it" nudges — the fan has it.
  - **Escalate a push only when the fan can't cope** — latest `action` ∈
    {`unreachable`, `no_data`}, or the room holds ≥ the critical threshold while
    the fan is already at max — framed as a genuine manual ask ("Bedroom still
    warm and the fan can't reach it — go check the bedroom fan").
  - When `fan_auto_enabled` is **false** (Mark is cooling by hand), keep the
    existing manual protocol nudges **unchanged**.
- **Quiet-hours honesty** — a push suppressed by `send_notification`'s quiet
  hours still records its `_send_once` audit row, so it is not retried on the
  next poll.

**Frontend / Shared**

- None required — pushes land via the existing web-push path and deep-link into
  Home via `data.url`. (A per-category Settings toggle — verdict / analysis /
  bedroom — is a deferred nice-to-have, not in scope unless asked.)

## Boundaries (kept)

- **No migration** — reuses the existing `analyses` audit and `fan_state_readings`
  series.
- **No coaching-logic change** — this only *notifies* about outputs already
  generated and *re-scopes which nudges fire*; the Green/Amber/Red verdict, the
  recovery isolation (#49/#80), and the `fan_control.py` decision logic /
  thresholds are all untouched.
- **Idempotent** — one push per verdict (per day) and per analysis (per
  activity); the backstop and regeneration never re-push (the whole point of the
  `_send_once` tag).
- **Secret-safe** — notification bodies carry no creds; no new cloud call on the
  push path.

## Tests

- Morning verdict pushes exactly once even when the 09:30 backstop reruns and
  when the analysis regenerates (tag dedupe).
- Each post-workout type pushes once per activity; regeneration on a newer
  check-in / prompt bump does not re-push; breathwork pushes nothing.
- Thermal nudge is suppressed when the autopilot is `apply`/`hold`/`winddown`;
  the "check the fan" escalation fires on `unreachable`/`no_data`/can't-reach-target;
  the manual protocol nudges are intact when `fan_auto_enabled` is false.
- A quiet-hours-suppressed push still records its audit row (no retry loop).
- No scheduler ERROR on the push path; each push is wrapped so a failure never
  blocks the analysis pass that triggered it.
