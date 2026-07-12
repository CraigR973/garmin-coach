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
personal status + "Tonight" transparency (pts 5, 13).

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
