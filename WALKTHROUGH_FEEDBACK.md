# Walkthrough Feedback — 2026-07-12

Captured during a live "just woke up" walkthrough of the PWA **on prod**, driven
as Mark on Craig's iPhone. The check-in mirrored Mark's real morning entry (feel
*"A bit more tired this morning"*, score 6, BP 105/67, note *"Later in bed."*).

Prod was reset to the pre-check-in state with only Craig's handset armed for
notifications; the real data + device state are held in
`~/garmin-coach-snapshots/snapshot_2026-07-12/` for restore.

**Type legend:** 🔴 correctness · 🟡 UX/flow · 🟢 feature · 🔵 design-decided (recommendation on record)

---

## Reconciliation summary

All 13 reconciled against the code. Headlines:

- **One root drives four Home points (2, 3, 9, 12).** Since Batch 85 the pre-brief
  Home shows a "Say good morning" hero, but the *action resolver*
  (`homeActions.ts`) and *section model* (`homeSections.ts`) have **no "brief not
  generated yet" concept**. So the action strip falls through to **"You're all
  set"** (contradicting the hero → #3), the section model leads with an
  auto-expanded **Last night's sleep** on a rest day (#2, #12), and nothing claims
  the top slot for the check-in / unread brief (#9). A single "pre-brief" state
  resolves all four coherently.
- **#7 (correctness) is confirmed and structural** — the morning packet has no
  rest-day/holiday flag, and the deterministic plan-adjustment says "proceed with
  the planned workout" even when today's ride is `skipped`.
- **#10 is a real gap** — the Dreo client hard-codes `fans[0]`; the app can only
  ever see/-control one fan, and exposes only on/off + speed.

**Batched as 95–102** in [`docs/phase-batches.md`](docs/phase-batches.md)
("2026-07-12 walkthrough UX batch plan"): **95** pre-check-in Home state + check-in
discoverability (pts 2, 3, 4, 12) · **96** brief lifecycle — unviewed surfacing +
button state (pts 8, 9) · **97** passive generation — notify-when-ready + staged
loader (pt 6) · **98** rest-day/holiday-aware verdict (pt 7, 🔴 High) · **99** iOS
notification deep-link (pt 1) · **100** multi-fan support + telemetry (pt 10) ·
**101** dedicated Environment/Climate tab (pt 11) · **102** presentation polish —
personal status + "Tonight" transparency (pts 5, 13). **All shipped** as of
2026-07-13 (PRs #118–#123, Decisions #168–#175) — see the 2026-07-13 follow-up below
for the gaps found testing them.

---

## 🏠 Home screen

### 1. Notification deep-link 🟡
Tapping the good-morning notification just reopens whatever you last had open; it
should deep-link to the check-in / today's view.

**Confirmed — [sw.ts:107-123](apps/web/src/sw.ts:107).** The `notificationclick`
handler focuses an existing window and calls `client.navigate(url)` — but on
**iOS PWAs `WindowClient.navigate()` is a no-op**, so a running app stays on its
last view. Fallback `openWindow(url)` only runs when no window is open.
**Fix:** on a focused client, `postMessage` the target URL and have the SPA router
navigate (works on iOS); also confirm the nudge push sets `data.url` to
`/check-in` (else it defaults to `/` — [sw.ts:109](apps/web/src/sw.ts:109)).

### 2. Sleep shown too early 🟡
Last night's sleep is visible/expanded on Home before you've said good morning.

**Confirmed — [homeSections.ts:39-44](apps/web/src/lib/homeSections.ts:39) +
[DashboardPage.tsx:532-537](apps/web/src/pages/DashboardPage.tsx:532).** On a
`rest_day` `primarySection` returns `lastNight`, and `splitPrimaryDetail` makes it
the expanded `lead` — regardless of whether a brief exists yet. Same root as #12.

### 3. Contradictory status copy 🟡
"Say good morning" (hero) sits directly above "You're all set" (action strip).

**Confirmed — [DashboardPage.tsx:662](apps/web/src/pages/DashboardPage.tsx:662)
(hero) + [:686](apps/web/src/pages/DashboardPage.tsx:686) (`NextActionStrip`
renders unconditionally) + [homeActions.ts:91-118](apps/web/src/lib/homeActions.ts:91).**
The morning ladder's first rung requires `morningAnalysis != null`; pre-brief it's
`null`, so every rung is skipped and it falls to the **"You're all set"** default.
**Fix:** add a pre-brief rung returning a "Say good morning / check in" action so
the strip agrees with the hero (and can own the top slot — see #9/#12).

### 9. Unviewed brief placement 🟡
An unviewed brief should be at the top; instead the top card is "pre-cool the
bedroom".

**Confirmed — [DashboardPage.tsx:659-686](apps/web/src/pages/DashboardPage.tsx:659).**
Render order after generation: `VerdictHero` (just the verdict word) → feel recap →
feedback → **`TodayActions`** (whose thermal entry is *"Pre-cool the bedroom
tonight"* — [morning_analysis.py:1159](apps/api/src/services/morning_analysis.py:1159)).
The **full brief lives at `/brief`**, linked only from *inside* the Last-night
section ([DashboardPage.tsx:560](apps/web/src/pages/DashboardPage.tsx:560)) — there
is no prominent "brief ready — read it" element up top. **Fix:** an unviewed-brief
CTA above `TodayActions`, gated on a per-day "brief viewed" flag (mirror
`hasReviewedSleep`, [sleepReview.ts](apps/web/src/lib/sleepReview.ts)).

### 12. Don't auto-expand last night's sleep 🔵
**Recommendation:** collapse to a one-line headline; give the top slot to the
check-in CTA + unviewed brief; full breakdown only after the brief is viewed / on
Sleep.

**Locus — [homeSections.ts:30-44](apps/web/src/lib/homeSections.ts:30) +
[DashboardPage.tsx:532](apps/web/src/pages/DashboardPage.tsx:532).** Implement the
pre-brief state from #3 so `primary` leads with the check-in CTA, not `lastNight`.
Same fix resolves #2.

### 13. More personal top status 🟢
A Jarvis-style line ("You're good to go today") instead of a flat status.

**Locus — [copy.ts:41-46](apps/web/src/lib/copy.ts:41) (`greetingForNow`, rendered
at [DashboardPage.tsx:650](apps/web/src/pages/DashboardPage.tsx:650)) +
[VerdictHero.tsx](apps/web/src/components/VerdictHero.tsx).** Today the greeting is
a bare "Good morning/afternoon/evening" and the verdict is a two-word label
("Good to go"). Compose a personable one-liner from verdict + name/time.

---

## ✅ Check-in & brief flow

### 4. Empty-state check-in prompt 🟢
When no check-in exists, the Sleep page should show an "enter the morning check-in"
entry point at the top.

**Locus — the `/sleep` hub.** No check-in CTA there today; the pattern already
exists as [GoodMorningCta.tsx](apps/web/src/components/GoodMorningCta.tsx) (links
`/check-in`). **Fix:** render it at the top of `/sleep` when
`daily.manualEntry == null`.

### 6. Passive brief generation 🟢
Make generation passive — "I'll notify you when I'm ready", let the user leave,
fire a **second notification** when ready; polished staged loader (Domino's-style).

**Confirmed blocking — [CheckInPage.tsx:319-330](apps/web/src/pages/CheckInPage.tsx:319).**
The button blocks on the LLM call behind a *"Reading your morning…"* spinner.
Backend `regenerate_after_morning_checkin` generates **inline and does not push**
(matches our walkthrough finding — the verdict push is a separate step). **Fix:**
generate async server-side + push a "brief ready" notification on completion; swap
the blocking spinner for a staged progress UI that the user can walk away from.

### 8. Button state after generation 🟡
After the brief is generated the button should switch to "View brief"; it still
says "Get today's brief".

**Confirmed — [CheckInPage.tsx:319-350](apps/web/src/pages/CheckInPage.tsx:319).**
Once `brief` is set it renders below, but the primary button stays
*"Get today's brief"* (a re-generate affordance). **Fix:** when `brief` exists,
switch it to "View brief" (→ `/brief` or Home).

---

## 📄 Brief content

### 5. "Tonight" data transparency 🟢
The "Tonight" section should show what data it's basing itself on so far (early:
just temperature), getting more detailed as the day progresses.

**Locus — [SleepPrepBody.tsx](apps/web/src/components/SleepPrepBody.tsx) +
`sleepProjection`.** The component already carries an "evidence disclosure"; extend
it to state data-completeness explicitly and grow it through the day.

### 7. Workout verdict wrong on a rest day 🔴
The workout verdict discusses an endurance ride when today is a **rest day**.

**Confirmed — structural, backend.** No rest-day/holiday flag is assembled into the
morning packet ([morning_analysis.py:332-398](apps/api/src/services/morning_analysis.py:332)).
`_planned_workouts` filters only `is_active`
([:510-530](apps/api/src/services/morning_analysis.py:510)) so a **`skipped`
holiday ride is still passed to the model**, and `_plan_adjustments`
([:1501-1519](apps/api/src/services/morning_analysis.py:1501)) ignores
`workout.status` → on a Green day it emits *"Proceed with the planned workout"*
even when that workout is skipped. The `SYSTEM_PROMPT`
([:76-137](apps/api/src/services/morning_analysis.py:76)) has no "when today is a
rest/holiday day, don't frame a training verdict around the skipped session" rule.
(The `todayActions` approve-ride path already guards on `skipped` at
[:1128-1134](apps/api/src/services/morning_analysis.py:1128) — the verdict/prose
path does not.) **Fix:** assemble a deterministic rest-day/holiday flag; gate
`_plan_adjustments` on `workout.status`; add a prompt rule to frame the day as rest
and not narrate the paused session as a live decision.

---

## 🌬️ Fans / environment

### 10. Much more fan detail (+ multiple fans) 🟢
Current setting, next-on time, position/mode, anything useful — and handle multiple
fans (Mark now has >1).

**Confirmed gap — single-fan hard-code.**
[dreo_fan.py:265-268](apps/api/src/services/dreo_fan.py:265) picks
`fans[0]` and drops the rest, so the app can only ever see/control one fan.
`DreoFanState` already exposes `oscillating` (≈ position/mode) alongside
`is_on`/`fan_speed`, but the API surface
([fan.py:39-43](apps/api/src/routers/fan.py:39)) only returns
`autoEnabled/isOn/speed` — no oscillation, no next-on time, no per-fan identity.
Frontend `FanState`/`fanStatusText`
([dailyFlow.ts:53-94](apps/web/src/lib/dailyFlow.ts:53)) and
[BedroomBody.tsx](apps/web/src/components/BedroomBody.tsx) are likewise single-fan,
one-liner. **Fix spans the stack:** multi-device in the Dreo client + fan-control
loop → richer `FanState[]` (identity, oscillation, computed next-on) in the payload
→ per-fan UI.

### 11. Fan/temperature control structure 🔵
**Recommendation:** hybrid — concise thermal summary stays in Sleep; full multi-fan
control moves to its own "Environment/Climate" tab.

**Touch-points — [navConfig.ts](apps/web/src/lib/navConfig.ts),
[TabBar.tsx](apps/web/src/components/TabBar.tsx), routes in
[App.tsx](apps/web/src/App.tsx).** Move `BedroomBody`'s controls to a new
`/environment` route; keep the compact bedroom summary in `/sleep`.

---

## Status
13 points — 1 correctness (#7), 2 design calls with recommendations on record
(#11, #12), the rest UX/feature. All reconciled against code 2026-07-12.

---

# Walkthrough Feedback — 2026-07-13 (follow-up)

Second live "just woke up" walkthrough on prod (13th reset to pre-check-in, driven
as Mark), this time against the **now-shipped Batches 95–102**. 8 points, all
reconciled against the *current* code. Most are follow-up gaps in the batches that
just landed — several in the exact code they touched.

**Type legend:** 🔴 correctness · 🟡 UX/flow · 🟢 feature · 🔵 design-decided

**Batched as 103–107** in [`docs/phase-batches.md`](docs/phase-batches.md)
("2026-07-13 walkthrough follow-up batch plan"): **103** pre-check-in gating, Home +
Sleep (Issues 1, 2, 3) · **104** right-surface placement — overnight graph + walking/
breathwork (Issues 4, 7) · **105** holiday-aware environment (Issue 8, 🔴 High) ·
**106** read-aloud brief (Issue 6) · **107** sleep/climate calendar (Issue 5).

## Pre-check-in Home & Sleep — follow-ups to Batch 95

### 1. Repetitive pre-brief CTA 🟡
Batch 95 fixed the "You're all set" contradiction by adding a `say-good-morning`
rung ([homeActions.ts:95-96](apps/web/src/lib/homeActions.ts:95)), but it now echoes
the `GoodMorningCta` hero's "Say good morning" + "Get today's brief"
([GoodMorningCta.tsx:38](apps/web/src/components/GoodMorningCta.tsx:38),
[:44](apps/web/src/components/GoodMorningCta.tsx:44)) — two prompts for one action.
**Fix:** suppress the strip rung while the hero renders.

### 2. Last-night sleep reachable pre-brief 🟡
Batch 95 stopped auto-expanding it; the `lastNight` section still renders collapsed
under "More detail" pre-brief. **Fix:** don't render it until a brief exists.

### 3. Sleep page ungated 🟡
Batch 95.3 added the check-in CTA ([SleepPage.tsx:88](apps/web/src/pages/SleepPage.tsx:88))
but the body (overnight chart, tonight, bedroom stats) still renders pre-check-in.
**Fix:** gate the page behind `manualEntry`/brief. ⚠️ Tension with the *optional*
check-in (Batch 60/#127) — product call at `/batch-start`.

## Content placement — follow-up to Batch 101

### 4. Overnight graph should be Sleep-only; Climate = current 🔵
`OvernightChartCard` renders on both [SleepPage.tsx:124](apps/web/src/pages/SleepPage.tsx:124)
and [EnvironmentPage.tsx:75](apps/web/src/pages/EnvironmentPage.tsx:75). **Fix:**
remove it from `EnvironmentPage` (Climate becomes live room + fan controls only).

### 7. Walking base + breathwork in the workout card 🟢
Both render inside `DayPlanBody` at
[DashboardPage.tsx:1044-1045](apps/web/src/pages/DashboardPage.tsx:1044). **Fix:**
breathwork → Sleep/wind-down; walking base → baseline/Trends. Keep crediting them,
just not in the today-workout card.

## Holiday-awareness — follow-up to Batch 98

### 8. Thermal subsystem ignores holiday 🔴
`run_evening_sleep_nudge` ([scheduler.py:180](apps/api/src/scheduler.py:180)),
`run_evening_monitoring_alerts` ([:200](apps/api/src/scheduler.py:200)) /
`evaluate_thermal_alert` ([nudge_alerts.py:264](apps/api/src/services/nudge_alerts.py:264)),
and `run_fan_control` ([scheduler.py:975](apps/api/src/scheduler.py:975)) never
consult `HolidayPauseService`. Evidence: the 12th (holiday) fired an evening_nudge
(19:00) + a **critical** thermal_alert (20:45), fan still running. Batch 98 only made
the *morning verdict* holiday-aware. **Fix:** gate those three jobs on the active
holiday window (holiday = Mark's away).

## New features

### 5. Full calendar view 🟢
The Sleep page is a `last-night`/`tonight` binary
([SleepPage.tsx:21-26](apps/web/src/pages/SleepPage.tsx:21)); no date browse. The
overnight chart already has a night pager (Batch 31) + `GET /api/v1/bedroom/overnight`
recent-nights to build on. **New.**

### 6. Speak the AI summary 🟢
No TTS anywhere. **New** — a "Listen" control on the brief via `SpeechSynthesis`.

## Status
8 points — 1 correctness (#8), 1 design-decided (#4), the rest UX/feature. Reconciled
against current code (post-95–102) 2026-07-13. Batched 103–107.

---

# Walkthrough Feedback — 2026-07-14 (follow-up)

The 13th walkthrough continued into the 14th (the reset-13th test rolled past BST
midnight). A further wave of points (Issues 9–17), reconciled against current code with
**Batches 95–107 all shipped**. Batched as **108–112**; two need no batch (12, 16).

**Type legend:** 🔴 correctness · 🟡 UX/flow · 🟢 feature · 🔵 design-decided

## Resolved / not a bug
- **16 — remove last-night from Climate → DONE.** Batch 104 removed `OvernightChartCard`
  from [EnvironmentPage.tsx](apps/web/src/pages/EnvironmentPage.tsx).
- **12 — "generated for the 14th" → not a bug.** The clock rolled past BST midnight;
  `_local_today` ([daily_loop.py:128](apps/api/src/services/daily_loop.py:128)) correctly
  returned the 14th. *(Operational: restore must now cover the 13th **and** the 14th.)*

## Open follow-ups → Batches 108–112

### 9. Home tonight/bedroom ignore holiday 🟡 → Batch 109
Batch 105 gated the backend ([scheduler.py:191-242](apps/api/src/scheduler.py:191)); the
frontend `homeSections`/`DashboardPage` sections have no holiday awareness. Hide them on
Home/Sleep when the payload flags holiday.

### 10. Gate isn't today-scoped 🔴 → Batch 108
Batch 103's `hasSleepAccess` ([SleepPage.tsx:105](apps/web/src/pages/SleepPage.tsx:105))
hides the whole page including Batch 107's `SleepDateCalendar`
([:128](apps/web/src/pages/SleepPage.tsx:128)) until today's check-in. Gate today's
detail only; let the calendar/past dates through. (Regression from the 103×107
interaction.)

### 11. Check-in flow leftovers 🟡 → Batch 110
Staged progress is a card below the form
([CheckInPage.tsx:405](apps/web/src/pages/CheckInPage.tsx:405)); the inline brief render
([:456-473](apps/web/src/pages/CheckInPage.tsx:456)) still duplicates Home's
`UnviewedBriefCta`. Move progress in-place; drop the inline brief.

### 13. Robotic read-aloud voice 🟢 → Batch 111
Batch 106 shipped the default `SpeechSynthesis` voice. Upgrade to a natural voice; weigh
on-device vs. hosted-TTS health-data privacy.

### 14. Home says the verdict twice 🟡 → Batch 110
Lockup `personalStatusLine`+date
([DashboardPage.tsx:684-691](apps/web/src/pages/DashboardPage.tsx:684)) duplicates
`VerdictHero`+`dateLabel` ([:697](apps/web/src/pages/DashboardPage.tsx:697)). De-dup.

### 15. Calendar polish 🟢 → Batch 108
`SleepDateCalendar` expanded by default; a past-date view shows sleep+room only
([SleepPage.tsx:133-168](apps/web/src/pages/SleepPage.tsx:133)) though `historyData` holds
the whole day. Collapse by default; whole-day view.

### 17. Notification audit 🟡 → Batch 112
Critical thermal alert → `/bedroom` (retired redirect route,
[nudge_alerts.py:388](apps/api/src/services/nudge_alerts.py:388) /
[App.tsx:115](apps/web/src/App.tsx:115)); `verdict_push` (→`/`) overlaps
`brief_ready_push` (→`/brief`). Fix routes; consolidate the brief push. (Holiday-gating
already done via Batch 105.)

## Status
9 points (Issues 9–17). 2 need no batch (12 not-a-bug, 16 done); 7 → Batches 108–112.
Reconciled against current code (post-95–107) 2026-07-14.

---

# Walkthrough Feedback — 2026-07-14 (wave 2)

A second 14th wave (the walkthrough continued through the morning). 13 points, reconciled
against current code with **Batches 95–112 all shipped**. Batched as **113–119**; Issue 1 is
already fixed (Batch 110).

**Type legend:** 🔴 correctness · 🟡 UX/flow · 🟢 feature · 🔵 design-decided

## Fixed / partial
- **1 — progress replaces the button in place → DONE** (Batch 110,
  [CheckInPage.tsx:378](apps/web/src/pages/CheckInPage.tsx:378)); the inline brief render is
  gone. *(Verify the check-in fields don't still render above the progress.)*
- **4 — greeting above verdict → partial.** Batch 110 dropped the duplicate date; but
  `personalStatusLine` still doubles the verdict above the hero
  ([DashboardPage.tsx:733](apps/web/src/pages/DashboardPage.tsx:733)). → Batch 115.

## Open → Batches 113–119

### Holiday-thermal completeness → Batch 113 (Issues 3, 6, 7, 12)
`_thermal_action`/`build_today_actions` ([morning_analysis.py:1202](apps/api/src/services/morning_analysis.py:1202))
still emit the pre-cool action + the prompt still includes the thermal review on a holiday
(3, 7); the pre-cool href is `/sleep` not `/environment`
([:1222](apps/api/src/services/morning_analysis.py:1222)) (12); Sleep's Last-night tab still
shows the fan chart on holiday ([SleepPage.tsx:194](apps/web/src/pages/SleepPage.tsx:194)) (6).
Batch 105/109 only reached the scheduler + Home/Sleep-Tonight.

### Check-in CTAs clear after check-in → Batch 114 (Issues 8, 11)
Home hero gates on `analysis` not `manualEntry`
([DashboardPage.tsx:739](apps/web/src/pages/DashboardPage.tsx:739)) — 8; Sleep's "Add today's
check-in" shows when `hasSleepAccess` (i.e. after check-in)
([SleepPage.tsx:286](apps/web/src/pages/SleepPage.tsx:286)) — 11.

### Home lockup + layout → Batch 115 (Issues 4, 5)
Status line doubles the verdict (4); "You're all set"
([DashboardPage.tsx:770](apps/web/src/pages/DashboardPage.tsx:770)) overlaps the Today section (5).

### Hosted read-aloud voice → Batch 116 (Issue 2)
Batch 111 shipped on-device `selectBestVoice`
([BriefListenControls.tsx:60](apps/web/src/components/BriefListenControls.tsx:60)); still
robotic → hosted/neural TTS (privacy call).

### Calendar day-stepping → Batch 117 (Issue 9)
Chevrons page by month ([SleepDateCalendar.tsx:40](apps/web/src/components/SleepDateCalendar.tsx:40)); want day-steps.

### More specific feedback → Batch 118 (Issue 13)
`FeedbackControl` is 3-way + free-text ([FeedbackControl.tsx](apps/web/src/components/FeedbackControl.tsx)); want granular options (vocabulary TBD).

### Follow-up chat on briefs → Batch 119 (Issue 10)
New feature — conversational follow-up on a brief, grounded in its context packet. The brief
answers only the one check-in question today.

## Status
13 points. 1 fixed (Batch 110), 1 partial → 115; 12 → Batches 113–119. Reconciled against
current code (post-95–112) 2026-07-14.
