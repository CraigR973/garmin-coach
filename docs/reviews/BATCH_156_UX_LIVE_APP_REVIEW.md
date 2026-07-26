# Batch 156 full-app UX / live-app review

**Date:** 2026-07-26

**Branch:** `chore/batch-156-ux-live-app-review`

**Mode:** diagnose-only — documentation and captured evidence only; no product
code, plan, coaching memory, chat message, or runtime configuration changed

**Dataset decision:** current production data, rendered through the current
local web bundle with `/api/*` requests forwarded to the production Railway API

## Executive summary

The core daily experience is coherent and the newest completed-workout flow is
good: all 15 routes rendered at 390 px in light and dark, no route had
page-level horizontal overflow, no sheet was blank, and no loading state became
an infinite spinner. The Week completed-read sheet presents the stored read,
feedback, chat, and planned structure cleanly; its loading, absent, and failed
states are honest. The conversation-memory proposal card also supports edit and
accept cleanly when given a valid pending proposal.

The review found **six material issues: one High, four Medium, and one Low**:

1. the production Coach-memory page is completely blocked by a live API/shared
   schema mismatch and prints the raw Zod error to Mark;
2. a single-use activation code can be redeemed twice concurrently;
3. semantic status colours fail normal-text contrast across 12 of 15 light-mode
   routes, with smaller dark-mode failures too;
4. the interval editor's editable column is pushed off-screen inside a
   34-rem-wide table at 390 px;
5. important mobile controls repeatedly miss the app's own 44 px touch-target
   floor; and
6. scrollable Markdown and handover regions are not keyboard-focusable.

Each finding has a provisional remediation-batch stub. These identifiers are
review-local placeholders; they do not allocate ledger batch numbers.

## Acceptance result

| Batch 156 acceptance item | Result |
|---|---|
| Walk and capture every route | **Pass.** 15 routes × 2 themes = 30 route captures. |
| Exercise the four new surfaces | **Partial.** Completed read, chat, interval editor, and valid proposal review were exercised. The real Coach-memory route is blocked by UX156-01, so the proposal lifecycle used browser-only response fixtures after preserving the live failure. |
| Honest loading, empty, and error states | **Pass for the completed-read flow.** Delayed, null, and 503 responses all produced bounded, truthful copy. **Fail for Coach memory:** it exposes a raw validation payload. |
| Mobile-first at 390 px and light + dark | **Fail.** No global overflow, but the interval editor hides the editable column and important touch targets are undersized. |
| Cross-screen toast, skeleton, save, empty/error consistency | **Mostly pass.** One global toaster, one shared skeleton treatment, no persistent skeleton, and Batch 137's deliberate Settings-only `SaveButton` boundary remain coherent. Coach memory is the material error-state outlier. |
| Ranked report + screenshots → remediation stubs | **Pass.** R156-A through R156-F below. |
| Diagnose-only | **Pass.** Rare-state fixtures were browser-only. The only production write was cleanup: all 10 disposable review device tokens were revoked after the walkthrough. |

## Method and evidence

- Ran the current Vite bundle at `http://127.0.0.1:5173` and forwarded local
  `/api/*` requests to
  `https://api-production-e2bc7.up.railway.app`.
- Authenticated through the real `/activate` flow. The five successful
  walkthrough activations unexpectedly produced 10 device-token rows; all 10
  were revoked by exact ID after the audit, and a follow-up query returned zero
  active targets.
- Used production data for 2026-07-26: a morning analysis, two today workouts,
  14 schedule days, four completed workouts, and zero pending learning
  proposals.
- Captured all routes at **390 × 844** in light and dark. Added desktop captures
  for the completed-read sheet and interval editor.
- Ran axe-core on every settled route and focused state. Browser-only response
  fixtures covered the completed-read loading/null/503 cases and a schema-valid
  pending learning proposal plus accepted response. The chat question was
  drafted but not submitted; no proposal was accepted in production.
- The complete machine-readable record is
  [`batch-156/audit.json`](batch-156/audit.json). It contains 30 route captures,
  11 focused captures, DOM measurements, accessibility results, and sanitized
  diagnostics. The two console errors are the deliberate mocked 503; the seven
  request aborts are navigation/context-close cancellations. There were no page
  exceptions and no unexpected real API error responses.

## Ranked findings

### UX156-01 — High — the live Coach-memory contract rejects an internal KB section and exposes the parser failure

**Evidence**

- The production `GET /api/v1/coach-memory` response includes a knowledge-base
  row with `section="holiday_windows"`.
- The shared `knowledgeBaseSectionSchema` accepts only the 10 public sections
  ending in `learned_context`
  (`packages/shared/src/schemas.ts:281-292`), so
  `coachingStateEnvelopeSchema.parse` rejects the whole response
  (`apps/web/src/pages/CoachStatePage.tsx:94-101`).
- `CoachingStateService.get_snapshot` selects every knowledge-base row for the
  user without a public-section filter
  (`apps/api/src/services/coaching_state.py:638-650`), and the read route
  serializes the list unchanged
  (`apps/api/src/routers/coaching_state.py:258-270`). The backend also stores
  another non-shared internal section, `generated_block`.
- The error card renders `readQuery.error.message` directly
  (`CoachStatePage.tsx:432-444`), producing a full raw Zod issue array on Mark's
  phone:
  [`36-dark-coach-memory-contract-error.png`](batch-156/screenshots/36-dark-coach-memory-contract-error.png).

**Impact**

Coach memory is unusable against current production data, including Batch 151's
proposal-review surface. This is a complete route failure rather than a minor
empty state, and the implementation detail shown to Mark is noisy and
unactionable.

**Proposed remediation batch R156-A — make Coach memory a stable public contract**

- Define an explicit public Coach-memory DTO and either filter internal
  `holiday_windows` / `generated_block` rows or intentionally add and render
  them; do not let arbitrary storage-section names leak into a closed client
  enum.
- Keep the admin editor contract separate if it genuinely needs every internal
  row.
- Replace raw schema/API messages with short user-safe copy and a retry action;
  retain structured detail only in diagnostics.
- Add backend/shared/frontend contract tests containing the live internal
  section set, plus a production-shaped route test that proves one unexpected
  row cannot blank the whole page.

### UX156-02 — Medium — the single-use activation exchange is concurrency-racy

**Evidence**

- Development React Strict Mode mounts the activation effect twice
  (`apps/web/src/main.tsx:7-10`); the effect calls `activateDevice(code)` without
  a once-per-code guard (`apps/web/src/pages/ActivatePage.tsx:19-65`).
- Each of the five successful review activations produced **two** live
  `purpose="device"` rows, 123–135 ms apart, with the same truncated
  HeadlessChrome device hint.
- The API first selects an unused activation row, then sets `used_at`, inserts a
  device row, and commits (`apps/api/src/routers/auth.py:278-324`). The read has
  neither `FOR UPDATE` nor an atomic compare-and-set, so two transactions can
  both observe `used_at IS NULL`.
- `refresh_tokens.token_hash` has a non-unique index and there is no database
  constraint that serializes consumption
  (`apps/api/src/models/refresh_token.py:11-26`). Tests cover one successful
  request and invalid/expired requests, not concurrent redemption.

**Impact**

The documented "exactly once" boundary is false under concurrency. Strict Mode
made the race deterministic in this audit and left an extra long-lived
credential row per activation. Production React does not double-run the effect,
but two clients, a retry, or a deliberately concurrent redemption can still
cross the same server-side race window.

**Proposed remediation batch R156-B — atomic one-time activation**

- Consume the activation row with a locking read or atomic conditional
  `UPDATE ... WHERE used_at IS NULL ... RETURNING`; mint the device credential
  only for the transaction that wins.
- Add a client ref/idempotency guard so development and remount behavior does
  not issue duplicate requests, while treating the API as the authoritative
  defence.
- Add a real DB-backed concurrent-redemption test proving exactly one 200, one
  401, and one device-token row.
- Include orphan-device-token cleanup/observability in the operational check.

### UX156-03 — Medium — semantic status colours systematically fail normal-text contrast

**Evidence**

- Axe reported serious colour-contrast failures on **12 of 15 light routes**:
  Home, Brief, Sleep, Climate, Week, Holiday, Builder, Reviews, Trends,
  Experiments, Coach memory, and Settings. Week alone produced 41 affected
  nodes; Brief 18 and Sleep 24.
- The light semantic foregrounds are `#059669` success/primary, `#A77C2A`
  accent, and `#D97706` warning (`apps/web/src/index.css:178-201`). Against
  white they are approximately 3.77:1, 3.78:1, and 3.19:1, below WCAG AA's
  4.5:1 requirement for the 10–12 px text in use.
- The shared Badge compounds the pattern by using the same semantic token as
  small foreground text on a 20%-alpha tint
  (`apps/web/src/components/ui/badge.tsx:5-20`).
- Dark mode is materially better, but error/status badges still failed on
  Sleep, Reviews, and Trends.

**Impact**

The weakest contrast is concentrated in the very information colour is meant
to convey: in-range/out-of-range metrics, completion state, trends, warnings,
and primary micro-labels. This is a shared-system issue, not 12 isolated page
bugs.

**Proposed remediation batch R156-C — separate semantic text and fill tokens**

- Introduce AA-verified semantic foreground tokens for small text in each
  theme, distinct from decorative fills, borders, chart marks, and button
  backgrounds.
- Fix the shared Badge/status primitives first, then remove page-local uses of
  decorative `text-primary`/`text-success` on light surfaces.
- Add automated contrast coverage for every badge variant and representative
  metric/status rows in both themes.

### UX156-04 — Medium — the 390 px interval editor hides the action column

**Evidence**

- The editor places Setting, Current, and Change to in a table with
  `min-w-[34rem]` inside an `overflow-x-auto` wrapper
  (`apps/web/src/components/IntervalWorkoutEditor.tsx:175-182`).
- At 390 px the page itself correctly reports no global overflow, but the
  viewport shows only `SETTING`, `CURRENT`, and a clipped `CHAN…`; every
  editable input begins off-screen:
  [`38-light-interval-editor.png`](batch-156/screenshots/38-light-interval-editor.png).
- The desktop capture is clear, confirming this is a mobile composition issue
  rather than missing data:
  [`40-light-interval-editor-desktop.png`](batch-156/screenshots/40-light-interval-editor-desktop.png).

**Impact**

Batch 147's primary task is changing interval values on a phone, but its action
controls initially look absent. Horizontal scrolling technically makes them
reachable, yet the cue is weak and row labels/current values disappear while
editing.

**Proposed remediation batch R156-D — responsive interval-edit rows**

- Use stacked per-setting cards or a two-row label/current/change layout below
  the small breakpoint; retain the compact comparison table on wider screens.
- Keep each label and editable control visible together, with unit/bounds
  messaging and a 44 px target.
- Add 390 px visual/interaction tests that reach every field without horizontal
  scrolling, plus light/dark and Z2 zero-rest cases.

### UX156-05 — Medium — key mobile controls miss the app's 44 px target floor

**Evidence**

- The design system declares `.tap-target` as a 44 × 44 px minimum
  (`apps/web/src/index.css:351-355`), but the account dropdown trigger omits it
  (`apps/web/src/components/TopBar.tsx:44-51`) and measured **32 × 20 px** on
  every route.
- Shared `Button size="sm"` is 36 px high
  (`apps/web/src/components/ui/button.tsx:26-31`). It is used by the post-read
  feedback controls and chat Ask button
  (`FeedbackControl.tsx:175-231`, `BriefFollowUpChat.tsx:120-135`).
- Week's activity-detail chips measured roughly **123 × 22 px**. Check-in
  anchors, brief audio controls, climate controls, and many secondary actions
  also measured 36 px high.

**Impact**

These are frequent phone interactions, including account access, checking a
completed activity, rating a read, and asking the coach a question. The visual
density is pleasant, but the hit areas are below the project's stated mobile
standard.

**Proposed remediation batch R156-E — enforce touch targets by interaction context**

- Give the account trigger, activity chips, feedback controls, and chat action
  a 44 px hit area, using invisible padding/pseudo-elements where the visual
  chip should stay compact.
- Define a mobile-safe small-button primitive or enforce `tap-target` on
  interactive chips; do not rely on each page remembering the utility.
- Add a 390 px DOM-size assertion for the primary navigation and completed-read
  interaction stack.

### UX156-06 — Low — scrollable document regions cannot receive keyboard focus

**Evidence**

- Axe raised serious `scrollable-region-focusable` findings for Markdown tables
  in Brief and Handover. The shared wrapper is an overflow container with no
  focus affordance (`apps/web/src/components/Markdown.tsx:65-68`).
- Both formatted and raw Handover document containers cap height at 480 px and
  scroll, also without keyboard focus
  (`apps/web/src/pages/HandoverPage.tsx:162-170`).

**Impact**

Mouse/touch users can scroll these regions, but keyboard users may be unable to
reach hidden content. The scope is narrow and no content is lost for the
primary phone user, so this is Low despite axe's rule impact label.

**Proposed remediation batch R156-F — keyboard-reachable scroll regions**

- Add an appropriate `tabIndex`, accessible label/description, and visible
  focus style to shared scroll containers only when they can overflow.
- Cover Markdown tables and both Handover modes with keyboard-scroll tests.

## What worked well

- **Completed Week read:** the sheet keeps plan context, verdict, long-form read,
  feedback, follow-up chat, and structure in one understandable flow. It scales
  cleanly from 390 px to desktop:
  [`31-dark-week-completed-read.png`](batch-156/screenshots/31-dark-week-completed-read.png).
- **Honest states:** the completed-read loading, absent, and failed messages are
  explicit and bounded; all three focused states had no axe violation. The chat
  draft also had no accessibility violation and was not submitted.
- **Proposal interaction design:** once supplied a schema-valid public payload,
  edit and accept are clear, preserve the confirmation boundary, and fit at
  390 px:
  [`36-dark-memory-proposal-edited.png`](batch-156/screenshots/36-dark-memory-proposal-edited.png).
- **Responsive shell:** all 30 route captures had document width equal to the
  390 px viewport. Navigation, safe areas, sheets, and cards did not create
  page-level overflow.
- **Loading consistency:** routes use the shared Skeleton primitive and no
  settled capture retained a skeleton. No blank sheet or runaway loading state
  was observed.
- **Mutation feedback consistency:** `App.tsx` mounts one `AppToaster`; write
  surfaces consistently use it. Settings remains the intentional
  `SaveButton`/saved-lifecycle surface from Batch 137; quick actions that
  collapse, navigate, or complete asynchronously continue to use the settled
  toast/disabled-state patterns instead of reintroducing per-screen save drift.

## Non-material observations

- Axe's best-practice `page-has-heading-one` rule fired on the settled light
  Home capture and browser-only interval fixtures. The visible hierarchy is
  understandable and this does not outrank the six findings above, but it can
  be folded into R156-D or a later semantic-heading pass.
- The real Coach-memory request took long enough that the initial numbered
  route captures show its loading card; the focused contract-error capture
  preserves the eventual settled failure.
- Production currently has zero pending learning proposals. The proposal
  screenshots are therefore explicitly browser-only state fixtures, not
  evidence that a live proposal was edited or accepted.

## Evidence inventory

- [`batch-156/audit.json`](batch-156/audit.json) — sanitized route/state audit.
- [`batch-156/screenshots/`](batch-156/screenshots/) — 42 screenshots:
  30 light/dark route captures and 12 focused/mobile/desktop captures.
- No authentication code or device token is stored in the evidence. The one
  forwarded-request diagnostic contains only `Bearer [REDACTED]`.
