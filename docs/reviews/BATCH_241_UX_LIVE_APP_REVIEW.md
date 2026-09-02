# Batch 241 — full-app UX / live-app review

**Date:** 2026-09-01
**Pass:** 6 of 6 in the Batch 236–241 audit wave (product / UX lens)
**Mode:** diagnose-only. No product code, styling, plan, coaching memory, chat
message, check-in, feedback, generation or runtime configuration was changed.
**Deliverables:** this document and `BATCH_241_MARK_SCORECARD.md`.

---

## Method — and exactly what was observed vs read

**A live session was achieved.** Every screenshot in `batch-241/screenshots/` is
a real render of the current `main` frontend at **390 × 844**, `isMobile`,
`hasTouch`, `Europe/London`, in a **fresh browser context per route** (so every
timing is a cold load), driven headlessly with Playwright.

The one thing that is *not* production is the transport. The wave is read-only
and minting a device token is a production write, so instead of proxying to the
Railway API this pass ran a **local read-only mock API on port 8000** — the port
the dev server already proxies `/api` to, so **no repository file was modified**.
The mock **returns 405 on every non-GET**, which is the harness's own guarantee
that nothing could be written even by accident.

The mock is **seeded with Mark's real production data for 2026-09-01**, read
column-projected from the `coach` schema:

| Fed into the render | Source |
|---|---|
| The morning brief prose | `coach.analyses` `subject_date='2026-09-01'`, `analysis_type='morning'` (3,646 chars, `claude-sonnet-5`, `morning-analysis-v40-2026-08-28`) |
| Readiness / HRV / RHR / Body Battery | `coach.daily_metrics` 2026-09-01 |
| Sleep score, stages, SpO₂, restless | `coach.sleep` 2026-09-01 |
| His check-in words and sleep setup | `coach.manual_entries` 2026-09-01 |
| The week's sessions | `coach.planned_workouts` 2026-08-31 → 09-06 |
| Every baseline in the metrics table | `coach.metric_baselines` (all 10 rows) |
| Thread size | `coach.brief_messages` (268 rows) |

**The payloads are contract-checked, not hand-waved.** The app parses
`/api/v1/daily-loop` and `/api/v1/bedroom/overnight` through the real
`@coach/shared` Zod schemas; a fixture that did not match the shipped contract
failed to render and had to be corrected before any measurement was taken. That
is a stronger guarantee of fidelity than eyeballing.

**Labelling.** `observed` = seen rendered in this session. `proved` = established
against production data or the deployed artefact. `implemented` = read in the
code, not exercised.

**Not assessed, and why:**

- **`/trends`** — the trends envelope shape was not reconstructed, so the page
  rendered its error card. No trends finding is made. (What *is* recorded from
  that accident is how the error card behaves — see UX241-03.)
- **Anything that requires a write** — submitting a check-in, sending a chat
  turn, approving a ride, leaving feedback, triggering a generation. Those flows
  are assessed from code and from their rendered idle/failure states only, and
  are labelled `implemented`.
- **The push permission prompt** — headless Chromium cannot answer it, so the
  Settings button sits at `Enabling…`. That is an environment artefact, as it was
  in Batch 192. The *code path* behind it is a finding (UX241-07).
- **iOS-specific PWA behaviour** (standalone chrome, Dynamic Type, the
  `WindowClient.navigate()` no-op) — not reproducible in headless Chromium.
- **Routes not walked live:** `/reviews`, `/experiments`, `/handover`,
  `/holiday`, `/builder`, `/coach-state`, `/offline`. Batch 192 covered all 15;
  this pass concentrated the budget on the eight surfaces Mark touches daily.

---

## Executive summary

**The app Mark opens is in materially better shape than it was in August.** All
three of Batch 192's High findings are fixed and I can show it on a real render:
the coach launcher is genuinely `position: fixed` and in the viewport, the thread
opens at the newest message (`pxBelowFold: 0`), and a failed thread now has its
own error state. The 75 light-mode contrast failures are **zero** across the
eight routes walked. Six of Batch 192's seven remaining findings are closed. The
morning flow itself — verdict, feel, today's session, brief link, all above the
fold on a 390 px phone — is genuinely good design.

**And then the model changed underneath it, and the app did not notice.**

The single most important finding of this pass is not a layout bug. It is that
**on 1 September the brief Mark read was missing four of the sections that
shipped batches deliberately put there, and every part of the system reported
success.** The experiment loop ran — there are four `experiment_update` rows
timestamped `08:24:58`, twenty-one seconds before the brief was written — and
then the brief did not mention a single one of them. The Chronic REM Pattern
section and its two carried actions are gone. Respiration, SpO₂, VO₂max and
Body Battery charged are gone. The section where the app admits its own past
mistakes to Mark is gone. Home showed a green light, the push fired, and nothing
anywhere said "this brief is 43 % of yesterday's and is missing half its
content".

That is a product failure before it is an AI failure. The AI pass (AI238-01,
AI238-02) owns the mechanism and the missing guard; what this pass owns is what
Mark actually lost, which is **the two things in the brief that told him what to
do differently tonight, and the one thing that told him when the app had been
wrong.**

Second: **`/brief` is the page the "your brief is ready" push opens, and it is
the one page in the app that has not been taught the Batch 141 lesson.** Three of
its four failure states render **byte-for-byte identically**, and none of them
offers a retry.

**Fifteen findings: four High, seven Medium, four Low.**

---

## Where Batch 192's findings stand

| Batch 192 finding | Status now | Evidence |
|---|---|---|
| UX192-01 launcher not `fixed`, off-screen | **Fixed** | `observed`: `position: "fixed"`, rect `(326, 720, 48×48)`, `inViewport: true` on a 1,452 px page — `coach-probe.json` |
| UX192-02 thread opens 27,992 px from newest | **Fixed** | `observed`: `scrollTop 9920 / scrollHeight 10308 / pxBelowFold 0`. `CoachConversation.tsx:161-165` (Batch 193.2) |
| UX192-03 failed thread renders as "Nothing here yet" | **Fixed** | `implemented`: `CoachConversation.tsx:200-206` now has explicit `loading` / `error` states; `CoachLauncher.tsx:161` wires `threadQuery.isError` |
| UX192-04 state-change turn lights nothing | **Not assessed** | production still holds no `state_change` turn to render |
| UX192-05 75 light-mode AA failures | **Fixed on the routes walked** | `observed`: **0 failures** across 8 routes × light, 0 across 8 × dark (`audit-light.json`, `audit.json`) |
| UX192-06 nothing says the coach is thinking | **Fixed** | `implemented`: bouncing-dot pending row, `CoachConversation.tsx:285-293` |
| UX192-07 two conversations, two empty states | **Fixed** | `implemented`: `MorningBriefPage.tsx:30-35` — "no inline chat on this page any more" (Batch 207) |
| UX192-08 seven controls under 44 px | **Almost fixed** | `observed`: **one** left — see UX241-13 |
| UX192-09 cold time-to-content | **Open, unquantified here** | see UX241-15 |
| UX192-10 week-ahead guidance has no surface | **Not assessed** | |

The per-screen work of Batches 193–235 shows. This is a real improvement and it
should be said plainly before the findings.

---

## Ranked findings

### UX241-01 — High — the brief lost four sections on the model swap, and the two things in it that told Mark what to *do* went with them

**What is wrong.** The brief is the product. On 2026-08-31 it had eight
navigable headings; on 2026-09-01 it has four. The sections that vanished are
not decoration — three of the four were added by named batches to solve named
problems, and two of them carried **actions**.

**Where.** `coach.analyses`, `analysis_type='morning'`. Rendered through
`MorningBriefPage.tsx:110` → `Markdown.tsx`.

**Evidence — `proved` (database) and `observed` (rendered).**

| | 2026-08-31 (`claude-sonnet-4-6`) | 2026-09-01 (`claude-sonnet-5`) |
|---|---|---|
| `length(output_markdown)` | 8,482 | **3,646** |
| Markdown headings (`#`/`##`/`###`) | **8** | **4** |
| Horizontal rules | 8 | **0** |
| Sleep stages reported | deep, light, REM, awake, restless | **REM and deep only** |
| `## 🔬 Experiment Updates` | present, all four experiments | **absent** |
| `## 🔁 Chronic REM Pattern` | present, **two carried actions** | **absent** |
| Respiration / SpO₂ / VO₂max / BB charged | all present | **all absent** |
| Data-quality corrections acknowledgement | present, two corrections | **absent** |

The five 4.6 briefs before the swap ran 6,966–11,475 chars. 3,646 is not
day-to-day variation.

**The app did the work and did not tell him.** Four `experiment_update` rows
exist for `subject_date='2026-09-01'`, written at `08:24:58.374`; the brief was
written at `08:25:19.954`, twenty-one seconds later, and mentions none of them.
The experiment loop, the chronic-pattern detector and the correction ledger all
ran normally. Only the surface disappeared.

**The concrete consequence for Mark.** He lost, in one morning and with no
notice:

- **Both carried REM actions** — "protect the final 90-minute sleep cycle from
  early alarms" and "hold the room cool into the back half of the night". These
  are the only two behavioural instructions the chronic-REM work has ever
  produced. On 09-01 the brief still *diagnoses* low REM at length (7.0 %, below
  his own floor and below the age band) and then tells him nothing to do about
  it. A diagnosis with the action stripped off is worse than silence: it worries
  him and leaves him nowhere to go.
- **All four running experiments** — the REM intervention rotation, the collagen
  reintroduction gate, the 04:00 waking pattern, the recovery-week question. He
  is a participant in four experiments on his own body and the app stopped
  telling him where they stand.
- **The corrections channel.** The 08-31 brief ends by admitting two of the
  app's own past errors to him. The Batch 211 scorecard specifically promised him
  this behaviour. It is now silent — and a silent corrections channel is
  indistinguishable from an app that has stopped making mistakes.
- **Half his sleep detail.** He reads this to manage his bedroom. Light, awake
  and restless are gone; **Batch 230's explicit denominator sentence** — shipped
  to close a factual error — is reduced to a parenthetical `(deep+light+REM+awake)`.

**Also a comprehension regression, not only a content one.** The 09-01 brief
opens with `**Sleep summary:**` and `**Note on your check-in:**` as *bold
paragraph leads*, not headings. `Markdown.tsx` gives `h2` a real visual break
(`mt-5 mb-2 text-base font-semibold`) and gives `strong` nothing but weight, so
the top third of the brief is now an unbroken run of prose on a 390 px screen.
On a page that is **4.5 screenfuls tall**, losing four of eight section breaks
removes the only means of skimming it.

**Cross-reference.** AI238-01 (the output contract is a stale four-item list),
AI238-02 (nothing inspects generated output), HS240-19 (scope correction: SpO₂
survived, respiration and the experiment section did not).

**Fix shape.** Two parts, and the second matters more than the first.

1. Make the output directive enumerate every section the product owns.
   `morning_analysis.py:229` currently names four — "a sleep summary line, a
   metrics-vs-baselines read, a thermal/environment review, and a
   Green/Amber/Red workout verdict". Sonnet 5 produced exactly those four. The
   sections added after that sentence was written were never added *to* it.
2. **Assert on the rendered product, not on the call succeeding.** A brief that
   parses to fewer than N headings, or that omits a section whose upstream data
   exists (experiment rows written today, a chronic pattern active, carried
   actions pending), should raise before it reaches Mark — or at minimum
   surface a "some sections are missing" marker on `/brief`. Today the only
   thing standing between a hollow brief and Mark is that somebody happened to
   compare two rows by hand.

---

### UX241-02 — High — `/brief` is where the push lands, and it cannot tell "it failed" from "it hasn't started"

**What is wrong.** `MorningBriefPage.tsx:114-122` has exactly one empty state:

> **No morning brief yet**
> The coach read appears here once today's morning analysis has run.

It is rendered whenever `morningAnalysis == null`, and the page never reads
`briefGeneration` at all.

**Where.** `apps/web/src/pages/MorningBriefPage.tsx:114-122`. The push target is
`apps/api/src/services/nudge_alerts.py:218` — `data={"url": "/brief", ...}`.

**Evidence — `observed`.** Four scenarios were served to the real page and
captured:

| Scenario | `/brief` renders | Screenshot |
|---|---|---|
| `briefGeneration.status = 'failed'` | "No morning brief yet…" | `state-failed-brief.png` |
| `briefGeneration.status = 'generating'` | "No morning brief yet…" | `state-generating-brief.png` |
| No check-in yet today | "No morning brief yet…" | `state-precheckin-brief.png` |
| Overnight sync has not run | "No morning brief yet…" | `state-nosync-brief.png` |

The first three files are **byte-identical** (`md5 59285cd4a19211d2fa55d1a960d359b9`).
The fourth differs only in an unrelated pixel and reads the same.

Home, by contrast, gets all four right — `BriefFailedCta` ("Couldn't finish your
brief… Your check-in is saved. **Try again**"), `BriefGeneratingCta` ("Writing
your brief"), `GoodMorningCta` ("Say good morning… your overnight data's already
in") and the no-sync variant ("…I'll sync your overnight data before I read your
day"). `/check-in` gets it right too, with a staged progress list and a
**Refresh now** button. Only `/brief` was left behind.

**The concrete consequence for Mark.** The brief-ready push deep-links to
`/brief`. Any other route to that page — a bookmark, the "Read it" card, the
back button, an iOS PWA cold start restoring the last view — lands him there
too. On a morning when generation fails he is told, on the app's most important
page, to wait for something that is never coming, with no retry and no hint that
anything went wrong. That is precisely the 2026-07-21 credit-outage experience
Batch 141 existed to end; it was ended on one screen out of two.

**Cross-reference.** AI238-03, AI238-04 (failures that classify as neither
billing nor a retryable transport error still reach this state); DS237-01 (no
operator alert reaches anyone, so nobody else notices either).

**Fix shape.** `/brief` already has `data.briefGeneration` in the payload it
fetched. Render `BriefFailedCta` / `BriefGeneratingCta` from it, exactly as
`DashboardPage` does, and keep the "Try again" link to `/check-in`. This is a
small change with a large blast radius — it closes the failure path on the page
the notification actually opens.

---

### UX241-03 — High — a response the app cannot parse is shown to Mark as a wall of raw JSON

**What is wrong.** Eight page-level error cards render `query.error.message`
directly. When the failure is a **schema mismatch** rather than an HTTP error,
that message is a `ZodError` — whose `.message` is the serialised issue array.

**Where.** `SleepPage.tsx:116`, `DashboardPage.tsx:486`, `MorningBriefPage.tsx:54`,
`TrendsPage.tsx:120`, `ReviewsPage.tsx:123`, `ExperimentsPage.tsx:73-74`,
`EnvironmentPage.tsx:31`, `HandoverPage.tsx:78-79`, plus
`OvernightChartCard.tsx:87`.

**Evidence — `observed`, twice, on two different mechanisms.**

1. A `/api/v1/bedroom/overnight` payload that did not match
   `bedroomOvernightEnvelopeSchema` rendered **inside the "Overnight room & fan"
   card on `/sleep`** as roughly 900 characters of
   `[{"code":"invalid_type","expected":"string","received":"undefined","path":["data","night"],…}]`
   — `screenshots/sleep-light.png`, lower third.
2. A single wrong field type (`readinessScore: "seventy-two"`) produced, on both
   Home and `/sleep`:

   > **Today's brief couldn't load**
   > `[ { "code": "invalid_type", "expected": "number", "received": "string", "path": [ "data", "dailyMetrics", "readinessScore" ], "message": "Expected number, received string" } ]`
   > **Try again**

   `screenshots/state-schemadrift-home.png`, `state-schemadrift-sleep.png`.

For contrast, a plain HTTP 500 renders correctly and legibly — "Internal Server
Error" plus **Try again** (`state-serverdown-home.png`). The failure is specific
to contract drift.

**Is it reachable in production?** Yes. Any field the API adds, renames or
re-types before the Vercel bundle catches up produces it, and the app deploys API
and web independently (Railway and Vercel, both auto-deploying from `main`, with
no ordering guarantee). The persisted React Query cache and the service worker's
NetworkFirst fallback widen the window further. It is latent, not theoretical.

**The concrete consequence for Mark.** He is not technical. A page of JSON where
his sleep should be does not say "a mismatch between two deploys"; it says "this
thing is broken and I cannot trust it". Trust in a health app is the whole
asset, and this spends it for no benefit — the text is useless to him and the
developer detail is already in the console.

**Cross-reference.** DS237-16 (a 401 clears the token but not the persisted
brief) is the same family: a recovery path that leaves the user holding
something incoherent.

**Fix shape.** One helper between the error and the card: if the error is a
`ZodError` (or the message parses as JSON, or exceeds ~120 characters) show
"Something's out of date between the app and the server — pull to refresh, or
try again in a minute" and log the detail. Keep the raw message for the two
admin-only surfaces (`/coach-state`, `/handover`) if it is useful there.

---

### UX241-04 — High — on `/brief`, the verdict sits 3,080 px down a 3,809 px page

**What is wrong.** The brief page renders the coach's prose in generation order,
and the model writes its conclusion last. So does the page: the `Today` actions,
then a nine-row metrics table, then the full prose, and the verdict at the end
of the prose.

**Where.** `MorningBriefPage.tsx:81-112` (render order) — the heading positions
below are the model's, but the page does nothing to reorder them.

**Evidence — `observed`.** Heading offsets on the real 09-01 brief at 390 × 844
(`probe2.json`):

| Heading | y | screenful |
|---|---|---|
| `Morning brief` (h1) | 187 | 1 |
| `Today` | 254 | 1 |
| `Last night's metrics` | 496 | 1 |
| `Coach read` | 1,464 | 2 |
| `Tuesday 1 September 2026 — Morning Read` | 1,588 | 2 |
| `Metrics vs. Baselines` | 1,944 | 3 |
| `Thermal / Environment Review` | 2,740 | 4 |
| **`Today's Verdict: 🟢 Green`** | **3,080** | **4** |

Page height 3,809 px = **4.51 screenfuls**. The verdict is at **81 %** of the
scroll depth. The "Listen to brief" control is also below the fold, at y = 1,524.

**Mitigation, stated fairly.** Home gets this right and Home is the default
landing. `home-dark.png` shows, entirely above the 844 px fold: the date, the
verdict word ("Good to go"), a one-line personal read, what he said this
morning, a "Green verdict" chip, the "Your morning brief is ready — Read it"
card, and today's session with Edit / Swap. That is a genuinely good morning
screen and it deserves credit.

**The concrete consequence for Mark.** The reasoning is only in the prose. When
he wants to know *why* — which is the whole point of the paid model — he taps
"Read it" and gets four and a half screenfuls with the answer at the bottom.
This is why UX241-01 compounds: the section breaks that made that scroll
skimmable are the ones that disappeared.

**Fix shape.** The verdict is already structured data (`analysis.verdict`,
`analysis.reasons`, `analysis.planAdjustments`) — it does not need to be mined
from the prose. Lead `/brief` with a verdict card built from those fields, and
let the prose below it be the detail rather than the delivery. Optionally add a
sticky section jump built from the markdown's own `h2`s; that also degrades
gracefully when the model emits fewer of them.

---

### UX241-05 — Medium — the coach remembers 268 messages and shows 60, with no way to reach the other 208

**What is wrong.** `THREAD_PAGE_LIMIT = 60` and the UI has no "load older"
control, so the conversation is a fixed-size window over a growing history.

**Where.** `apps/api/src/services/brief_chat.py:117` and `:364`;
`CoachConversation.tsx` renders `messages` with no pagination affordance.

**Evidence.** `proved`: `select count(*) from coach.brief_messages` → **268**
(131 from Mark), oldest 2026-07-18, newest 2026-08-30. `observed`: no control
matching `/older|more|load/i` exists in the open sheet other than the nav's
"More" menu (`coach-probe.json`).

Batch 192 measured 82 stored and 22 unreachable. It is now **208 unreachable**,
growing at roughly four messages a day. The window will keep receding.

**The concrete consequence for Mark.** Everything he asked before roughly
mid-August is gone from his view. He cannot go back and find what the coach told
him about a session, or re-read an explanation. Worse, the app *does* still use
that history — it is his coaching record — so there is now a gap between what
the coach remembers and what Mark can see it remembering.

**Fix shape.** A "Load earlier messages" button at the top of the pane calling
the same endpoint with a `before` cursor. The scroll-to-bottom effect at
`CoachConversation.tsx:161-165` must be made not to fight it (only auto-scroll
when already near the bottom, or on a new message rather than on every length
change).

---

### UX241-06 — Medium — the coach thread is the one fetch with no schema guard, and a wrong-shaped 200 empties it silently

**What is wrong.** `CoachLauncher.tsx:76` fetches the thread as
`apiFetch<{ data: BriefMessage[] }>('/api/v1/coach/messages')` with **no Zod
parse** — unlike `useDailyLoop` and `useBedroomOvernight`, which both validate.
If the response is a 200 whose `data` is not an array, `messages.length` is
`undefined`, the falsy branch is taken, and the sheet renders the *empty* state.

**Where.** `apps/web/src/components/CoachLauncher.tsx:76, 81`;
`CoachConversation.tsx:295-298`.

**Evidence — `observed`.** A 200 response of `{data:{messages:[…60…]}}` instead
of `{data:[…60…]}` rendered as:

> Nothing here yet. Ask whatever's on your mind.

with `dialogOpen: true` and no error (`coach-probe.json`, first run). Correcting
the shape rendered all 60 messages, scrolled to the newest.

This is the shallower cousin of UX192-03, which Batch 193.2 fixed for *failed*
fetches. A **succeeding** fetch with a drifted shape still lands in the same
place, and the honest error state that now exists cannot fire because nothing
threw.

**The concrete consequence for Mark.** After an API change he opens the coach and
his 268-message history reads as deleted, with an invitation to start over. He
has no way to distinguish that from data loss.

**Fix shape.** Parse with `z.object({ data: z.array(briefMessageSchema) })` like
every other fetch in the app, so drift becomes the error state that already
exists rather than the empty state that lies.

---

### UX241-07 — Medium — turning notifications on can fail with no message, and a denied permission is a dead button

**What is wrong.** `usePushSubscription.subscribe()` wraps the whole flow —
`Notification.requestPermission()`, `pushManager.subscribe()`, and the
`POST /api/v1/push/subscribe` — in one `try`, and the `catch` is
`console.error(...)` only. `isLoading` resets in `finally`, so the button
returns to "Enable push notifications" and nothing is said.

Separately, the hook computes and returns `permission`, and `NotificationsSection`
destructures **only** `{ isSubscribed, isLoading, subscribe, unsubscribe }` —
`permission` is never rendered. A `denied` permission therefore looks exactly
like a `default` one, and browsers will not re-prompt after a denial, so the
button becomes inert.

**Where.** `apps/web/src/hooks/usePushSubscription.ts:66-92` (the swallowing
`catch` at `:88`); `apps/web/src/pages/SettingsPage.tsx:53, 83-92`.

**Evidence.** `implemented` — read, not exercised (headless Chromium cannot
answer the permission prompt; the button was `observed` sitting at `Enabling…`,
which is the expected environment artefact). `proved` that push currently works:
`coach.push_subscriptions` holds one active iPhone subscription created
2026-07-29, so this is a **recovery** gap, not a live outage.

**The concrete consequence for Mark.** Push is the entire delivery mechanism of
the daily loop — the good-morning nudge, the brief-ready push, the workout
check-in nudge, the weekly review. If he ever re-installs the PWA, changes phone,
or taps "Don't Allow" once, the repair path is a button that does nothing and
says nothing. He would conclude the app had stopped working and have no way to
find out why.

**Fix shape.** Show the permission state: when `permission === 'denied'`, replace
the button with "Notifications are blocked for CheckMark — turn them back on in
iPhone Settings › Notifications › CheckMark", and surface a toast on the `catch`
("Couldn't turn notifications on — try again"). Both are small; the second alone
removes the silence.

---

### UX241-08 — Medium — Home's sleep line leaks Garmin's raw grade and truncates mid-number

**What is wrong.** The collapsed "Last night's sleep" summary on Home reads:

> `7h 42m asleep · FAIR · REM below your 65–9…`

Three problems in eleven words. `FAIR` is Garmin's raw uppercase `qualifier`
string passed straight through — the app's own vocabulary everywhere else is
sentence case and plain English. It sits next to a sleep score of 78 and an
age-adjusted 82, both of which the brief describes as "squarely normal for you",
so the one word Mark sees on Home contradicts the read he gets everywhere else.
And the genuinely useful part — his personal REM range — is cut off mid-number,
so "65–9…" could be 90 or 95 or 900.

**Where.** `observed` on `home-dark.png` and `home-light.png`. The truncation is
the shared `truncate.ts` helper applied to a summary line that is too long for
390 px; the raw qualifier comes from `coach.sleep.qualifier` (`'FAIR'` for
2026-09-01, `proved`).

**The concrete consequence for Mark.** The first thing he sees about last night,
before he expands anything, is a shouted Garmin grade that disagrees with his
coach, followed by half a number. Home is where he spends the least attention and
it is carrying the least reliable sentence in the app.

**Fix shape.** Translate the qualifier through the app's own vocabulary (or drop
it — the age-adjusted score already carries the judgement), and shorten the REM
clause so the range survives the truncation ("REM 34 min, below your usual").

---

### UX241-09 — Medium — his own words are the input the coach quotes back, and they are behind a collapsed accordion

**What is wrong.** `/check-in` puts the feel score, the five feel chips and three
quick flags above the fold, then collapses everything else into two accordions:
"Last night's setup" and "More — In your own words, blood pressure, and
yesterday's supplements & food". Both are `aria-expanded="false"` by default.

**Where.** `apps/web/src/pages/CheckInPage.tsx:517` and `:607-609`.
`observed`: both accordions collapsed, at y = 629 and y = 745 on a 964 px page
(`probe2.json`).

**Evidence that it matters — `proved`.** Mark's actual 2026-09-01 check-in note
is 260 characters and is the single most informative thing he gave the app that
day:

> "…although had temp ok even small window openings did create drafts which felt
> impacted sleep. With cooler outside temps going to try for next few nights
> getting room to 17° then sealing."

The brief opens its second paragraph with it ("**Note on your check-in:** you
flagged that small window gaps created drafts…"). His 11:56 post-workout note
contains a direct question — whether to repeat the 30/30 session next week rather
than progress to 40/20 — and the post-workout read answers it under its own
heading, "**Answering Your Question**". Free text is not a nice-to-have on this
app; it is where his intent enters the system.

**The concrete consequence for Mark.** The most valuable field is two taps down
and described in a summary line that leads with "In your own words" but bundles
it with blood pressure and supplements, which he mostly leaves blank. On a
morning when he is half-awake, the path of least resistance is to tap a chip and
hit the button — and the coach then reads his day without the one thing only he
knows.

**Fix shape.** Promote the free-text box to the always-visible card (one
textarea, "Anything you want me to know?"), and leave BP / supplements / food in
the collapsed "More". This is a reordering, not new functionality.

---

### UX241-10 — Medium — nothing Mark reads says what the app cannot see

**What is wrong.** The app issues daily go/no-go training guidance, discusses
SpO₂ dips, REM deficits, resting heart rate and blood pressure, and runs
experiments on his sleep. The only caution anywhere in the UI is a single
sentence under two age-comparison tables.

**Where.** `observed` across every page walked; `implemented` by grep — the
strings "medical" / "not medical advice" appear in exactly two components:
`SleepStageAgeTable.tsx:124` and `MetricComparisonTable.tsx:412`, both reading
"— a rough guide, not medical advice."

Nowhere does the app state what it *cannot* see: that it has no knowledge of
illness, infection, medication, injury, chest pain or breathlessness; that a
Green verdict is a statement about training load and recovery signals, not about
whether he is well; and that certain symptoms mean stop and call a doctor
regardless of what the light says.

**The concrete consequence for Mark.** He is 61, he trusts this app, and on a
morning when he is coming down with something the app will confidently say "Good
to go" because his HRV and RHR have not moved yet. The verdict word is
unqualified and the boundary is unstated.

**Cross-reference.** This is the user-facing face of **HS240-04** (there is no
medical boundary anywhere Mark reads, and no statement of what the app cannot
see). That pass owns the clinical framing; this pass confirms the surface is
bare and specifies where it should not be.

**Fix shape.** One short, permanent line under the verdict on Home and on
`/brief` — not a modal, not a checkbox: "This reads your Garmin data and your
check-in. It can't see illness, medication or injury. If you feel unwell, that
outranks the light." Plus a fuller note on `/settings`.

---

### UX241-11 — Medium — the app detects a stale brief on Home only, and can only fix it there

**What is wrong.** `DashboardPage.tsx:261-263` computes `isStale` by comparing
`data.subjectDate` against local-today in the profile timezone, and offers a
cache-bypassing force-refetch (`StaleDataNotice`, `:746-747`). No other page does
either. `/brief`, `/sleep`, `/delivery` and `/environment` will render a
previous day's payload from the persisted React Query cache or the service
worker's NetworkFirst fallback with no notice and no route to a fresh read.

**Where.** `apps/web/src/pages/DashboardPage.tsx:261-263, 746-752`;
absent from `MorningBriefPage.tsx`, `SleepPage.tsx`, `WeekAheadPage.tsx`,
`EnvironmentPage.tsx`.

**Evidence.** `implemented`. Partially mitigated and this should be said: every
page walked *does* print the subject date as its eyebrow ("TUESDAY 1 SEPTEMBER"),
so a careful reader can tell — `observed` on all eight routes.

**The concrete consequence for Mark.** A cold open on a slow morning can paint
yesterday's brief on `/brief` with yesterday's date in small caps at the top and
no way to force a refresh short of killing the app. He is being asked to
notice a date to avoid acting on the wrong day's verdict.

**Fix shape.** Lift `isStale` + `StaleDataNotice` into the shared layout, or into
`useDailyLoop` itself so every consumer inherits it.

---

### UX241-12 — Low — twenty-five hard-coded sub-14 px type sizes, on an app read by a 61-year-old

**What is wrong.** Body text is `text-sm` (14 px, and `rem`-based so it scales),
but there are **25** occurrences of `text-[10px]`…`text-[13px]` — literal pixel
values that ignore the reader's text-size setting entirely.

**Where.** `PageHeader.tsx:59` (the date eyebrow on every page),
`TabBar.tsx:72` (**every tab label in the app**), `BriefFailedCta.tsx:27`,
`BriefGeneratingCta.tsx:30`, `GoodMorningCta.tsx:38`, and twenty more.

**Evidence — `observed`.** Measured text-node font sizes per route (`audit.json`):
Home 5 nodes at 10 px, 2 at 11 px, 5 at 12 px against 25 at 14 px; `/delivery`
has **32** nodes at 12 px. Combined with `tracking-[0.3em]` letter-spacing and
`text-text-muted`, the 10 px eyebrows are the least legible text in the app —
and one of them is the date, which is load-bearing for UX241-11.

**The concrete consequence for Mark.** If he raises his phone's text size —
which is exactly what a 61-year-old reading at 07:00 is likely to have done —
the body text grows and these do not, so the gap widens rather than closes.

**Fix shape.** Convert the `text-[Npx]` utilities to the `rem`-based scale
(`text-xs` / a new `text-2xs` token). Mechanical, and it makes the app's own
accessibility guard meaningful.

---

### UX241-13 — Low — one control still sits under the app's own 44 px floor

**What is wrong.** The "Change" link in the "How you feel today" card on Home
measures **49 × 20 px**. Everything else in the app now clears 44 px in both
dimensions.

**Where.** `observed` on `/` in both themes (`audit.json`, `audit-light.json`,
`smallTargets`).

Batch 192 found seven such controls; six are fixed. Worth recording only because
this one sits inside the verdict hero — the highest-traffic card in the app —
and it is the correction affordance, so it is reached precisely when he has
mis-tapped something already.

**Fix shape.** Add `tap-target` (the app's existing 44 px utility) to the link.

---

### UX241-14 — Low — "Generated 01/09/2026, 09:25:19"

**What is wrong.** `/brief` timestamps the coach read with a raw locale
date-time, to the second.

**Where.** `MorningBriefPage.tsx:105` — `formatDateTime(analysis.generatedAtUtc)`.
`observed` on `brief-dark.png`.

Seconds are meaningless to Mark and the numeric date duplicates the eyebrow
directly above it. The app is otherwise careful and warm about time ("Good
morning, Mark", "TUESDAY 1 SEPTEMBER", "Breathing at 20:00, snack by 21:30"),
which makes this line read like debug output that escaped.

**Fix shape.** "Written at 9:25 this morning" / "Written yesterday at 09:25".

---

### UX241-15 — Low — cold time-to-content, 4.9 s to 11.7 s

**Evidence — `observed`, with a large caveat.** Cold-context load to
busy-affordances-clear, 390 × 844, one fresh context per route:

| Route | ms | | Route | ms |
|---|---|---|---|---|
| `/settings` | 4,890 | | `/environment` | 6,131 |
| `/trends` | 5,230 | | `/delivery` | 6,720 |
| `/` | 5,462 | | `/check-in` | 8,432 |
| | | | `/brief` | 9,173 |
| | | | `/sleep` | **11,724** |

**The caveat is the finding's ceiling.** This is an unminified Vite dev build
transforming modules on demand against a local mock — it is *not* the production
bundle against Railway, and the numbers are not comparable to a real device.
What they do establish is the **shape**: `/sleep` and `/brief` are consistently
the slowest, both are dominated by the one 275 KB `daily-loop` payload Batch 192
identified, and nothing has been done about it since. Recorded as a shape, not a
measurement; a real number needs a production trace.

---

## What works well — and this is a long list

Said plainly, because the findings above are the exceptions:

- **The morning screen is right.** On a 390 px phone, above the fold, with no
  scrolling: the date, the verdict ("Good to go"), a warm one-line read, what he
  said this morning, a "Green verdict" chip, "Your morning brief is ready — Read
  it", today's session with its duration and target, and Edit / Swap day. The
  most important thing and the second-most-important thing are both visible on
  waking. `home-dark.png`.
- **The traffic light is never colour alone.** Green renders as a check icon +
  the words "Good to go" + a "Green verdict" chip; Red renders as "Rest or
  substitute" + "Recovery is the right call" + a "Red verdict" chip
  (`state-red-home.png`). A colour-blind or low-vision reader gets the verdict
  from text and shape. This is the single most important accessibility property
  in the app and it holds.
- **Zero contrast failures.** 0 AA failures across 8 routes × 2 themes, against
  75 light-mode failures at Batch 192. Whatever was done between 192 and now,
  it worked. (One false positive: the gradient-filled "CheckMark" wordmark has
  `color: transparent` by design.)
- **The failure states on Home and `/check-in` are genuinely honest.** "Couldn't
  finish your brief. Something went wrong while writing today's brief. **Your
  check-in is saved.** [Try again]" — it names what happened, reassures him
  about the thing he'd worry about, and gives him one button.
- **"No data" and "nothing wrong" are distinguishable.** Pre-check-in says "Say
  good morning — your overnight data's already in"; the same screen with no sync
  says "Check in and I'll sync your overnight data before I read your day"; the
  bedroom card says "**Indoor not synced**" rather than showing a stale
  temperature. That distinction is hard and the app makes it.
- **The check-in itself is well judged.** One screen, 1.14 screenfuls, every
  primary control 44 px or larger, a 0–10 slider *and* five word-chips (Rough /
  Meh / OK / Good / Great) *and* a numeric field — three ways to say the same
  thing, which is exactly right for a half-awake user. The word is shown next to
  the number, so "6" is never presented bare.
- **The staged generation progress works.** After submitting, the button is
  replaced in place by "I'll notify you when it's ready", a four-stage progress
  list, "No push? You can stay here or check back in a moment" and a **Refresh
  now** button. Batch 144's orphaned spinner has stayed fixed and then some.
- **Numbers are given meaning almost everywhere.** The metrics table shows the
  value, the personal range and an "in range" / "0.6 below" verdict per row; the
  sleep-stage table shows "Above the healthy band" / "Below the healthy band"
  in words with an icon, not just a colour. Very little is reported bare.
- **The coach is now reachable and correct.** Fixed launcher, in-viewport,
  48 × 48, context-labelled per page ("Ask about your week", "Ask about this
  morning's brief", "Ask about your check-in"), opening at the newest message.
- **Post-workout reads did not regress.** The 2026-09-01 post-workout analysis
  is 4,719 characters, fully sectioned, and answers the question Mark asked in
  his check-in note under its own heading. Whatever went wrong with the morning
  brief is specific to the morning brief.

---

## The three highest-value fixes

**1. Give the brief a contract and check the product against it (UX241-01).**
Not because the prose is shorter — because two behavioural actions and four
experiment updates disappeared from the only place Mark reads them, and nothing
noticed for a day. Enumerate every section the product owns in the output
directive, then assert on the rendered brief: if experiment rows were written
today and the brief has no experiment section, that is a defect, not a style
choice. This is the fix that stops the app from quietly becoming a different
product on the next model swap.

**2. Teach `/brief` the four states Home already knows (UX241-02).**
It is the page the notification opens and it is the only surface where a failed
generation still looks like patience. `data.briefGeneration` is already in the
payload; render `BriefFailedCta` and `BriefGeneratingCta` from it. Small change,
closes the last leg of the Batch 141 failure path.

**3. Stop showing Mark raw errors (UX241-03).**
One helper between the caught error and the card. A page of Zod JSON where his
sleep should be costs more trust than any layout bug in this document, and it is
reachable any time a Railway deploy lands before a Vercel one.

---

## Evidence index

All paths relative to `docs/reviews/batch-241/`.

| File | Contents |
|---|---|
| `audit.json` | 8 routes × dark: heights, contrast analysis, touch-target geometry, font-size census, above-fold inventory, cold TTC, console/network errors |
| `audit-light.json` | the same 8 routes × light |
| `probe2.json` | heading and control geometry for `/check-in`, `/delivery`, `/trends`, `/settings`, `/brief` |
| `coach-probe.json` | launcher computed position and rect; thread scroll state on open |
| `state-failed.json`, `state-generating.json`, `state-precheckin.json`, `state-nosync.json`, `state-schemadrift.json`, `state-serverdown.json`, `state-red.json`, `state-aug31.json` | rendered text of Home / `/brief` / `/sleep` under each scenario |
| `screenshots/*.png` | 33 full-page captures at 390 px |

Key screenshots: `home-dark.png` (the morning screen), `brief-dark.png` (the
4.5-screenful brief), `state-failed-brief.png` vs `state-generating-brief.png`
vs `state-precheckin-brief.png` (byte-identical — UX241-02),
`state-schemadrift-home.png` (UX241-03), `sleep-light.png` (UX241-03 in the
wild, and the sleep-stage table that works well), `state-red-home.png` (the
traffic light is not colour-only).

## Cleanup

The mock API process was stopped and the dev server left as found. **No
repository file was modified** — the harness used the dev server's existing
`/api → localhost:8000` proxy rather than editing `vite.config.ts`, and no
`.env.local` was created. No production write of any kind was made: no device
token was minted, no check-in submitted, no chat turn posted, no generation
triggered, no feedback left. Every production read was column-projected against
the `coach` schema and no JSONB payload column was selected.
