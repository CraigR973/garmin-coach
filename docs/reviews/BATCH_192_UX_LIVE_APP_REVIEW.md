# Batch 192 full-app UX / live-app review

**Date:** 2026-08-06

**Branch:** `chore/batch-192-ux-live-app-review`

**Mode:** diagnose-only — documentation and captured evidence only; no product
code, styling, plan, coaching memory, chat message, or runtime configuration
changed

**Dataset decision (Craig, at `/batch-start`):** current production data,
rendered through the current local web bundle with `/api/*` forwarded to the
production Railway API — the Batch 156 method. For the two surfaces production
provably does not contain (a Batch 187 state-change turn and a Batch 185
scheduled weekly-review turn), browser-only response fixtures were used, exactly
as Batch 156 covered its rare states. Both absences were verified against the
database before being simulated: `coach.brief_messages` holds **zero**
`state_change` and **zero** `weekly_review` rows, ever.

## Executive summary

Every route works. All 15 routes rendered real production content at 390 px in
both themes, no route had page-level horizontal overflow, no page threw a script
error, no API call returned 4xx/5xx, and Batch 156's lead finding is closed —
Coach memory now loads and renders. The per-screen work of Batches 157–187 shows.

The whole-app property this batch exists to judge does not hold. **The coach —
the surface Batch 179 made "reachable from anywhere" and Batches 185 and 187
then chose as their delivery channel — is effectively unreachable, and has been
since Batch 185 shipped on 2026-08-05.** Three independent defects compound on
that one surface: the launcher is not actually pinned to the screen, the thread
opens 28,000 px away from the newest message, and a failed thread fetch is
rendered as "Nothing here yet." Each is individually fixable; together they mean
that if the Sunday review had fired on 2026-08-09 as designed, Mark would most
likely never have seen it.

The review found **ten material issues: three High, five Medium, and two Low.**

1. `cn()` silently drops `fixed` in favour of `relative` on the coach launcher,
   so the button sits at the bottom of page content, 16 px off the left edge,
   and is not in the viewport on load — confirmed in the **deployed production
   bundle**, not just locally.
2. The coach sheet opens scrolled to the top of a 60-message thread — the
   newest turn, which is where every proactive message lands, is 27,992 px
   below the fold.
3. A failed `GET /api/v1/coach/messages` renders as an empty conversation
   inviting Mark to start over, making 82 real messages look deleted.
4. A Batch 187 state-change turn lights nothing on the launcher; only
   `weekly_review` does.
5. 75 text nodes across 13 of 15 light-mode routes fail WCAG AA, including the
   active tab-bar label; Batch 163's contrast guard passes anyway because it
   tests tokens rather than pages.
6. While the coach is thinking, nothing says so — the question disappears and
   the composer greys out.
7. Two conversations coexist on one page with asymmetric membership and two
   different empty-state vocabularies.
8. Seven interactive controls sit under the app's own 44 px floor.
9. Cold time-to-content is dominated by one 275 KB, 5.4 s endpoint.
10. Batch 186's week-ahead guidance has no surface of its own and its only
    delivery channel has never fired.

Each finding has a provisional remediation-batch stub. These identifiers are
review-local placeholders; they do not allocate ledger batch numbers.

## Acceptance result

| Batch 192 acceptance item | Result |
|---|---|
| Every route captured at 390×844 in light and dark | **Pass.** 15 routes × 2 themes = 30 route captures, all rendering real production data, plus 14 focused captures. |
| The six post-156 surfaces exercised, incl. honest absent/generating/failed states | **Partial.** `CoachLauncher`/`CoachConversation` (179) and local dates + per-message times (183) exercised on real data and behaving. The 185 unseen marker and a 187 turn were exercised by fixture because production contains none. **Fail on honest states:** the thread's failure state is indistinguishable from its empty state (UX192-03), and its pending state is indistinguishable from idle (UX192-06). |
| Cross-screen consistency assessed and drift named | **Pass, with drift found.** One global toaster, one shared skeleton primitive, one shared conversation component; drift named in UX192-05 (semantic colour), UX192-07 (two chat views), UX192-08 (touch floor). |
| App-wide thread vs the three inline per-read chats judged explicitly | **Pass — see UX192-07.** They are one thread with two views and asymmetric membership: an inline question appears in both, a launcher question asked from the same page appears only in the launcher. |
| Findings ranked with screenshots as evidence + remediation stubs | **Pass.** UX192-01…10, R192-A…J. |
| Diagnose-only | **Pass.** Fixtures and the one simulated `POST` were fulfilled inside the browser and never reached the production write path or the model provider. The only production writes were the walkthrough's own credentials, revoked afterwards. |

## Method and evidence

- Ran the current Vite bundle at `http://localhost:5173`, with `/api/*`
  forwarded to `https://api-production-e2bc7.up.railway.app`.
- Authenticated through the real `/activate` flow with a single minted
  activation link. All device credentials created for this review were revoked
  after the walkthrough (see *Cleanup*).
- Captured at **390 × 844**, `isMobile`, both `colorScheme` values, with the
  app's own theme selection (`sss_theme`) set to match. Each route was loaded in
  a **fresh browser context**, so every measurement is a cold-cache load.
- Capture waited for the app's own busy affordances (`[aria-busy="true"]`,
  `.animate-shimmer`, `.animate-spin`) to clear before screenshotting, so a
  route that never settles is itself recorded rather than silently photographed
  mid-load.
- Production data for 2026-08-06: a Green morning verdict, a completed sweet-spot
  ride, a 6-session week 4 done / 2 to do, an active holiday window, 9 coach
  memory sections, 118 active planned workouts, 3 active experiments.
- Read-only SQL against the `coach` schema established the thread's true size
  and the absence of proactive turns. No row was written or modified.
- Machine-readable records: [`batch-192/audit.json`](batch-192/audit.json) (30
  route captures with DOM measurements, contrast analysis, touch-target
  geometry, console/network diagnostics), [`batch-192/focus.json`](batch-192/focus.json)
  and [`batch-192/focus2.json`](batch-192/focus2.json) (14 focused states).
- **Not assessed:** the push-notification permission control on Settings renders
  `Enabling…` indefinitely under headless Chromium because the permission prompt
  cannot be answered. This is an environment artifact, not a finding.

### Cross-route measurements

| Property | Result |
|---|---|
| Page-level horizontal overflow | **0 of 30** captures — `scrollWidth == clientWidth == 390` everywhere |
| Script errors / console errors | **0 of 30** |
| API responses ≥ 400 | **0** across all captures |
| Blank routes | **0** — all 15 rendered substantive content |
| Busy affordance still present at capture | **0 of 30** |
| Light-mode AA text failures | **75 nodes across 13 of 15 routes** |
| Dark-mode AA text failures | **0 across all 15 routes** |
| Cold time-to-content, median / worst | **7.4 s / 34.2 s** (`/brief`, dark) |

## Ranked findings

### UX192-01 — High — the coach launcher is not fixed to the screen; `cn()` drops `fixed` in favour of `relative`

**Evidence**

- `CoachLauncher.tsx:126` passes `'fixed right-4 z-tabbar tap-target relative'`
  to `cn()`. `cn` is `twMerge(clsx(...))` (`lib/utils.ts:4-6`), and `fixed` and
  `relative` are both Tailwind *position* utilities — so tailwind-merge keeps the
  last one and **discards `fixed`**.
- Live computed style on `/` against production data:
  `position: "relative"`, `left: "-16px"`, `rect.x: -16`, `rect.y: 2176` in an
  844 px viewport on a 2300 px page, `inViewport: false`
  ([`focus2.json`](batch-192/focus2.json) `F09`, both themes).
- The button therefore renders **in normal flow at the very end of the layout**,
  after `<main>` and before the tab bar (`Layout.tsx:27-28`), and `right-4`
  resolves against a static box as `left: -16px`, clipping 16 px of the 48 px
  button off the left edge:
  [`F09-dark-launcher-at-page-bottom.png`](batch-192/screenshots/F09-dark-launcher-at-page-bottom.png),
  [`F09-light-…`](batch-192/screenshots/F09-light-launcher-at-page-bottom.png).
- **This is live in production, not a local-dev artifact.** The deployed chunk
  `Layout-DNS4CIE5.js` on `garmin-coach-one.vercel.app` contains the same call:
  `g("fixed right-4 z-tabbar tap-target relative", …)`.
- **Introduced by Batch 185.** `git show 368ef69 -- apps/web/src/components/CoachLauncher.tsx`:
  `-'fixed right-4 z-tabbar tap-target'` → `+'fixed right-4 z-tabbar tap-target relative'`,
  added in the same commit as the unread dot's `absolute right-0 top-0`, which
  needed a positioned ancestor. The fix for the dot broke the button.
- Reproduced identically at desktop width 1280 ([`focus.json`](batch-192/focus.json) `F08`),
  so no breakpoint escapes it.

**Impact**

Batch 179's premise is "the coach, reachable from anywhere". Since 2026-08-05 it
has been reachable from the bottom of each page's scroll, partially off-screen,
and not visible at all in the initial viewport of any route. Everything routed
through the launcher inherits this: Batch 185's weekly review, Batch 187's
state-change turns, and the unread dot that is supposed to announce them are all
attached to a control Mark has to scroll to the end of a page to find. On Home
that is 2300 px of scrolling to reach a button that is then clipped.

**Proposed remediation batch R192-A — pin the launcher and stop the class from silently losing**

- Separate the positioning from the dot anchor: keep `fixed` on the launcher and
  give the badge its own positioned wrapper, or drop the redundant `relative`
  (a `fixed` element is already a containing block for `absolute` children).
- Add a rendered-DOM assertion — `getComputedStyle(button).position === 'fixed'`
  and the button inside the viewport on a long page — so the class list is
  tested by behaviour rather than by string.
- Audit the rest of the app for the same `cn()` collision class: any call site
  where two utilities from one tailwind-merge group appear in the same string.

### UX192-02 — High — the coach thread opens at the oldest message, 27,992 px from the newest

**Evidence**

- Opening the launcher on `/` with real data: 60 messages and 11 day separators,
  `scrollTop: 0`, `scrollHeight: 28380`, `clientHeight: 388`, so
  **`pxBelowFold: 27992`** — about 72 screenfuls ([`focus.json`](batch-192/focus.json) `F01`,
  identical in both themes).
- The first thing shown is a user message from **Thursday, 23 July 2026** — 14 days
  old: [`F01-dark-coach-thread-opens-at-oldest.png`](batch-192/screenshots/F01-dark-coach-thread-opens-at-oldest.png).
- `CoachConversation.tsx:152-158` renders the scroll pane
  (`max-h-[46vh] overflow-y-auto`) with **no scroll anchoring** — there is no
  effect that scrolls to the newest turn on open or after a reply.
- Desktop is the same shape: `pxBelowFold: 11906` ([`focus.json`](batch-192/focus.json) `F08`).
- The window is already truncating. `coach.brief_messages` holds **82** messages
  (41 user / 41 assistant) from 2026-07-18; `THREAD_PAGE_LIMIT = 60`
  (`services/brief_chat.py:107`) and the endpoint returned exactly 60, oldest
  2026-07-23. The **22 messages before that date are unreachable in the UI** —
  there is no "load older" affordance.
- The fixture runs show the same behaviour with a proactive turn present: even
  with only 7 messages, the injected weekly review sits `3264 px` below the fold
  ([`focus.json`](batch-192/focus.json) `F03`).

**Impact**

A chat that opens at the oldest message is not a chat; it is an archive. For
ordinary questions this is friction. For Batches 185 and 187 it is the failure of
the delivery mechanism itself: those messages are appended at the end, which is
the one part of the pane that is never on screen when it opens. Combined with
UX192-01, the Sunday review scheduled for 2026-08-09 would arrive on a button
Mark cannot see, in a position he would have to scroll 28,000 px to reach.

**Proposed remediation batch R192-B — open the conversation where the conversation is**

- Scroll the pane to the newest turn on open, and after each reply lands.
- Decide what the 60-message ceiling means to a reader: either page older turns
  in on demand, or state plainly at the top of the pane that earlier messages
  exist and are not shown. Silently truncating a coaching history is the wrong
  default for a record Mark is invited to reply to.
- If a proactive turn is unread, open on that turn rather than merely at the end.

### UX192-03 — High — a failed thread fetch renders as "Nothing here yet"

**Evidence**

- With `GET /api/v1/coach/messages` returning 503, the sheet reads in full:
  *"Your coach / Ask about today / Nothing here yet. Ask whatever's on your mind."*
  ([`focus.json`](batch-192/focus.json) `F05`,
  [`F05-dark-coach-thread-503.png`](batch-192/screenshots/F05-dark-coach-thread-503.png)).
- `CoachLauncher.tsx:78` collapses every non-success state to an empty list
  (`threadQuery.data?.data ?? []`), and `:149-153` chooses the hint on
  `isLoading` alone — there is **no error branch**, so failure and emptiness are
  the same screen.
- The inline per-read view is worse: `BriefFollowUpChat` passes no `emptyHint` at
  all (`BriefFollowUpChat.tsx:50-60`), so a loading, failed, or genuinely empty
  read chat all render as a heading and a composer with nothing between them
  ([`focus2.json`](batch-192/focus2.json) `F11`, observed live on `/brief`).
- Neither surface surfaces a retry. The launcher's `toast.error` path
  (`:111-113`) covers only the ask mutation, not the thread read.

**Impact**

Mark has 82 messages of coaching history. On any transient API failure — and
Batch 190 records that the API is sleep-enabled and its scheduled work has
failed silently before — that history renders as "Nothing here yet. Ask
whatever's on your mind.": a confident statement that the conversation does not
exist, plus an invitation to start it again. This is the exact failure mode
Batch 144 removed from the brief (orphaned spinner) reappearing in the newest
surface, inverted: not a state that never resolves, but a false state that
resolves immediately and reads as fact.

**Proposed remediation batch R192-C — make absent, loading and failed three different screens**

- Give `CoachConversation` an explicit status input and three distinct
  presentations, with a retry action on the failure one.
- Never render "Nothing here yet" for anything but a confirmed empty thread.
- Apply it to both views — the inline read chat currently has no non-success
  copy of any kind.
- Cover with tests that assert the *rendered copy* per status, not just that the
  component mounts.

### UX192-04 — Medium — a state-change turn lights nothing on the launcher

**Evidence**

- Fixture with an assistant turn at `originKind: "weekly_review"`: dot present,
  label becomes `"Ask about today — new coach message"`
  ([`F03-dark-launcher-weekly_review.png`](batch-192/screenshots/F03-dark-launcher-weekly_review.png)).
- Identical fixture at `originKind: "state_change"`: **`dot: false`**, label
  unchanged
  ([`F03-dark-launcher-state_change.png`](batch-192/screenshots/F03-dark-launcher-state_change.png)).
- `CoachLauncher.tsx:80-82` hard-codes `newestAssistant?.originKind === 'weekly_review'`.
- The vocabulary is split three ways: the backend's `ORIGIN_KINDS`
  (`services/chat_context.py:119-135`) has 15 kinds including `state_change`;
  the shared `coachOriginKindSchema` (`packages/shared/src/schemas.ts:811-826`)
  has 14 and omits it; the client's `ORIGIN_PROMPTS`
  (`lib/coachOrigin.ts:30-45`) has the same 14. Nothing fails loudly, because
  `briefMessageSchema.originKind` is a plain nullable string.
- This is the UX-layer confirmation of Batch 189's `CR189-01`, which reached the
  same conclusion by reading the code. Zero `state_change` rows exist in
  production, so no user has hit it yet.

**Impact**

Decision #268 justified adding no new push type for Batch 187 on the grounds
that "Batch 185's unseen coach launcher is the visibility rail". That rail does
not carry `state_change`. An unprompted turn — the batch's entire product — is
written to the database and announced nowhere.

**Proposed remediation batch R192-D — one origin vocabulary, one unread rule**

- Decide the unread rule by *role and recency* (any assistant turn newer than
  last-seen) rather than by an origin allowlist, or make the allowlist explicit
  and complete.
- Bring `coachOriginKindSchema` and `ORIGIN_PROMPTS` up to `ORIGIN_KINDS` and add
  a test that fails when the backend gains a kind the client does not know.

### UX192-05 — Medium — 75 light-mode text nodes fail AA on 13 of 15 routes, and the contrast guard passes anyway

**Evidence**

- Measured on rendered pages, resolving each text node's effective background:
  **75 failures across 13 of 15 light routes**; dark mode is **clean on all 15**.
  Per route: sleep 23, brief 18, week-ahead 16, trends 5, home 3, settings 3,
  and 1 each on environment, holiday, builder, reviews, experiments, handover,
  coach-state.
- Three combinations account for 73 of them:

  | Foreground | Background | Ratio | Needs | Count |
  |---|---|---|---|---|
  | `#059669` (`--primary` / `--success`) | `#FFFFFF` (`--surface`) | **3.77** | 4.5 | 42 |
  | `#6B7280` (`--text-muted`) | `#F1F3F5` (`--surface-elevated`) | **4.35** | 4.5 | 17 |
  | `#059669` | `#F7F8FA` (`--bg`) | **3.55** | 4.5 | 14 |

  plus `#D97706` (`--warning`) on white at 3.19 and a recharts legend at 3.78.
- Affected text includes the **active bottom-tab label** — `TabBar.tsx:73-74`
  renders the current tab's 10 px label as `text-primary`, measured at
  **3.55:1** — the workout-type chips on Home (`VO2`), the sleep table's
  "Below the healthy range for your age" warning, and the trends chart legend.
- Batch 163 (Decision #244) shipped the right tokens: `--primary-text: #047857`,
  `--success-text: #047857`, `--warning-text: #92400E` all pass. They are simply
  not used at these sites, which still reference the decorative fill tokens.
- The guard cannot see this. `lib/semanticTextContrast.test.ts:46-66` reads
  `index.css` and checks nine `*-text` tokens against `--surface` only. It never
  checks whether those tokens are *used*, never checks `--text-muted`, and never
  renders a page — so it is green while 75 live nodes fail.

**Impact**

This is Batch 156's `UX156-03` still open after the batch that was meant to close
it. The scope was read as "define AA tokens and adopt them in `Badge`", and the
test was written to match that scope, so the app's own primary navigation label
still fails AA in light mode. Mark is 60-plus and reads this on a phone outdoors.

**Proposed remediation batch R192-E — enforce contrast where it is rendered, not where it is declared**

- Replace decorative-fill tokens used as text with the `*-text` tokens at the 75
  measured sites; start with the tab bar, the Home chips and the sleep table.
- Fix `--text-muted` in light, or stop using it on `--surface-elevated`.
- Replace the token test with a rendered-DOM contrast assertion over a
  representative page set in both themes, so drift is caught at usage.

### UX192-06 — Medium — nothing indicates that the coach is thinking

**Evidence**

- With `POST /api/v1/coach/messages` held open, 2.5 s after submitting:
  `textareaDisabled: true`, `textareaValue: ""`, `submitDisabled: true`,
  **`busyCount: 0`**, and the visible tail of the sheet is unchanged — the last
  turn is still yesterday's ([`focus.json`](batch-192/focus.json) `F06`,
  [`F06-dark-coach-pending.png`](batch-192/screenshots/F06-dark-coach-pending.png)).
- `CoachConversation.tsx:136-142` clears the composer on submit;
  `:221-236` disables the textarea and button while `pending`. There is no
  optimistic user turn, no typing indicator, no spinner.
- Both views share this, since both render the same component.

**Impact**

Mark types a question, it vanishes, and the sheet looks exactly as it did
before — greyed out. The answer is an Anthropic call; a multi-second wait with no
acknowledgement reads as "it didn't send". Every other async surface in the app
does better: `BriefGeneratingCta` says "Writing your brief", the check-in and
Coach-memory controls spin. The newest surface is the least honest one.

**Proposed remediation batch R192-F — show the question and show the wait**

- Append the user's turn optimistically so it stays visible, and show a thinking
  affordance in the assistant slot until the reply lands.
- Keep the typed text recoverable if the request fails.

### UX192-07 — Medium — two conversations on one page, with asymmetric membership and two empty states

**Evidence**

- `/brief` renders the inline read chat (`MorningBriefPage.tsx:108`) headed
  **"Ask about this read"**, while the launcher on the same page is headed
  **"Ask about this morning's brief"** (`lib/coachOrigin.ts:33`). Two chat
  affordances, two names, same page
  ([`F11-dark-brief-inline-chat.png`](batch-192/screenshots/F11-dark-brief-inline-chat.png)).
- They are one thread with two views, but membership is one-way. The inline chat
  lists `GET /api/v1/briefs/{analysisId}/messages`; the launcher posts with
  `analysisId` set **only** when replying to a weekly review
  (`CoachLauncher.tsx:93-101`), and `BriefChatService.ask` resolves an anchor
  only from an explicit `analysis_id` — origin never infers one
  (`services/brief_chat.py:381-397`). So a question asked from the launcher
  while standing on `/brief` is stored with `analysis_id = NULL` and can never
  appear in that brief's inline chat, though the inline one appears in both.
- The two views also disagree on empty: the launcher says "Nothing here yet. Ask
  whatever's on your mind."; the inline chat says nothing at all (UX192-03).
- The same split exists on Home (`DashboardPage.tsx:1866`) and in the Week
  workout sheet (`WorkoutDetailSheet.tsx:239`) — three inline views against one
  app-wide view.

**Impact**

Mark cannot tell whether he is in one conversation or several, and the answer
depends on which of two adjacent boxes he typed into. A question asked in the
"wrong" box disappears from the read it was obviously about.

**Proposed remediation batch R192-G — make the relationship visible or make membership symmetric**

- Either anchor a launcher question to the read the current route is showing, or
  state in the inline view that it shows only this read's turns and link to the
  full thread.
- Align the two headings so one page does not name the same coach two ways.

### UX192-08 — Medium — seven interactive controls sit under the app's own 44 px floor

**Evidence** (measured geometry, both themes)

| Control | Size | Routes |
|---|---|---|
| Feel-score range input (`input.accent-primary`) | 316 × **16** | check-in |
| Back link (`a.inline-flex`) | 58 × **16** | brief, check-in |
| "View analysis"-style link (`a.text-primary`) | 49 × **20** | home |
| Toggle switch (`button.h-7`) | 48 × **28** | environment, settings |
| Date input `#start-date` | 316 × **36** | builder |
| Number input `#ftp-watts` | 316 × **36** | builder |

- The app defines the floor itself: `.tap-target { min-height: 44px; min-width: 44px }`
  (`index.css:370-373`).
- Batch 163 (Decision #244) raised `Button size="sm"` to 44 px and made the
  account trigger a `tap-target`. Links, switches, range and text inputs were
  outside that scope and remain under the floor.

**Impact**

The 16 px range input is the primary control on Check-in — the one interaction
Mark performs every single day — and the 16 px back link is how he leaves the
brief. These are the two highest-frequency touch targets in the app.

**Proposed remediation batch R192-H — extend the 44 px floor past buttons**

- Give the feel slider a 44 px hit area, raise inline nav links and switches, and
  set form inputs to the same floor.
- Assert the floor in a rendered test across the primary daily path rather than
  per component.

### UX192-09 — Low — cold time-to-content is dominated by one endpoint

**Evidence**

- `GET /api/v1/daily-loop` measured directly against production: **5.4 s,
  275,530 bytes**. By comparison `/api/v1/coach-memory` is 1.2 s / 113 KB.
- Cold time-to-content across 30 captures: median **7.4 s**, worst **34.2 s**
  (`/brief`, dark — the only capture that did not settle inside the 25 s budget;
  the same route in light settled in 10.0 s, so the outlier is variance in that
  one request, not a stuck state).
- Routes that do not depend on the daily loop are markedly faster: `/delivery`
  2.1 s, `/holiday` 2.7 s, `/experiments` 3.7 s.
- Batch 62 already persists the daily-loop query to `localStorage`, so this
  affects first open after a cache bust or install, not every launch.

**Impact**

The morning path — Home and the brief — is the slowest part of the app, on the
one endpoint the morning path cannot avoid, and the skeleton is honest but long.

**Proposed remediation batch R192-I — split or slim the daily loop**

- Measure what dominates the 275 KB payload and whether the brief needs all of
  it; consider splitting the hero verdict from the long tail so the first screen
  paints before the rest arrives.

### UX192-10 — Low — Batch 186's week-ahead guidance has no surface, and its only channel has never fired

**Evidence**

- Batch 186 (Decision #267) is backend-only by design: the week-ahead packet is
  narrated inside the Sunday weekly review, deliberately avoiding a second
  notification. There is no `weekAhead` reference anywhere in `apps/web/src`.
- Its only delivery channel is the Batch 185 coach turn, and
  `coach.brief_messages` contains **zero** `weekly_review` rows — the scheduled
  review has never produced one. The first scheduled Sunday is 2026-08-09.
- `/delivery` presents *this* week ("This week at a glance… 6 sessions, 4 done,
  2 to do") and offers no view of the week about to start.

**Impact**

None yet, and the design is deliberate. It is recorded because 192.2 required
exercising this surface and it cannot be exercised: a feature whose only outlet
is a message type that has never been produced is untested in front of a user,
and the three findings above all sit between it and Mark.

**Proposed remediation batch R192-J — verify the Sunday path end to end before it ships to Mark**

- After R192-A/B/C land, force one weekly review into a disposable context and
  confirm the whole chain: turn written → dot lit → launcher visible → sheet
  opens on the new turn → week-ahead prose present and readable.

## What is healthy

- **Every route works on real data.** 15 of 15 rendered substantive production
  content in both themes, with no blank sheet, no infinite spinner, no script
  error and no failing request.
- **Batch 156's High is closed.** `/coach-state` loads (3,926 px of content,
  "9 active memory sections · 118 active planned workouts") — the raw Zod error
  `UX156-01` is gone, and Batch 157's public contract holds against live data.
- **Responsive layout is solid.** Zero page-level horizontal overflow on 30
  captures, including the interval editor's route and the widest tables. Batch
  163's responsive work holds.
- **Dark mode is contrast-clean** on all 15 routes — the failures are entirely a
  light-theme token-usage problem.
- **Batch 183's local dates and per-message times work** exactly as specified:
  11 day separators across the thread, labelled `Thursday, 23 July 2026`, with
  `h23` times on every turn, in the profile's `Europe/London` zone.
- **Batch 185's unseen marker works** for the origin it knows about — the dot
  appears and the launcher's accessible name changes to "— new coach message".
- **The completed-read sheet remains the app's best surface.** It opens with the
  stored strength read, its structure and its own chat, honestly labelled.
- **One toaster, one skeleton primitive, one conversation component.** The
  shared-primitive discipline Batch 156 praised is intact; the drift found here
  is in usage, not in the system.
- **Batch 156's `UX156-02` is closed.** The activation that authenticated this
  review produced exactly **one** `purpose="device"` row, not the two the
  concurrency race produced every time in 2026-07; Batch 161's idempotency
  holds against a real double-mounting client.

## Cleanup

- The single activation link minted for this review was exchanged once and
  produced exactly one `purpose="device"` credential. It was revoked through
  `POST /api/v1/auth/revoke` (204), the same credential then returned 401 on a
  protected route, and a follow-up query confirmed **zero live credentials**
  created on 2026-08-06 — the activation row is used and expired, the device row
  is revoked.
- The local `vite.config.ts` proxy override and `apps/web/.env.local` used to
  point the dev bundle at production were reverted; neither is part of this
  branch's diff.
- No production row was written or modified. The fixtures, the 503 and the held
  `POST` were all fulfilled inside the browser.
