# Batch 333 — UX and the live app (audit wave #5, R7)

**Date:** 9–10 Oct 2026
**Pass:** R7 of the 327–333 wave (`docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`)
**Lens:** product designer — every surface Mark touches, every state, one morning as one story,
every Mark-facing line since 1 Sep, accessibility and speed, Mark's own words about the app.
**Mode:** read-only. Nothing written to production; no device token minted; no paid call ($0).
**Base:** `42a6a98` (production). Wave #4 base: `2178381` (`BATCH_241_UX_LIVE_APP_REVIEW.md`).
**Companion:** `BATCH_333_MARK_SCORECARD.md` (plain words, for Craig to read as Mark).


## Method

**A live render was achieved, on the production bundle.** Wave #4 rendered the Vite dev server;
this pass built the shipped front end (`vite build` of `apps/web` at `42a6a98`, Node 24.21, into
the gitignored scratch folder, never into the repo) and served the minified bundle, so bundle
sizes and load shape are the real artefact's. Headless Chromium (Playwright 1.60, the repo's own
install) drove it at **390 × 844**, `isMobile`, `hasTouch`, `en-GB`, `Europe/London`, in a
**fresh browser context per route and per state**, light and dark.

**The API was a local read-only mock** (`scratchpad/wave5/r7/mock_server.py`): it serves GETs from
fixture files and **returns 405 on every non-GET**; the browser driver also refuses every non-GET
and every request to any other host, and logs them. No auth endpoint is called (the bundle reads
its token from local storage; the driver seeds a dummy string there), so **no device token was
minted or read**.

**The fixtures are production responses, not reconstructions.** `dump_fixtures.py` ran the
shipped FastAPI app in-process under `railway run` with two dependency overrides (the current user
is Mark's profile; every request's session sits on a connection with
`default_transaction_read_only = on`, plus `SET TRANSACTION READ ONLY`, rolled back), every
outbound credential blanked and every non-database host refused at DNS. It saved the real
`{data, meta, errors}` envelopes for 39 GET routes (daily loop for 7, 8, 9, 10, 12 and 19 Oct;
coach thread; plan builder; schedule; week ahead; sleep; trends; reviews; experiments; holiday;
handover). A write probe on the same connection was refused, and one GET route that writes
(`/notifications/preferences`, which inserts a default row) failed on the read-only connection
and was not captured. Because the app parses its main payloads through the shipped `@coach/shared`
Zod schemas, a fixture that did not match the contract would have rendered an error card: none
did.

**States** (generating, failed, rest day, holiday, no plan, Zwift rail states, schema drift,
offline, server error) were produced by transforming those real envelopes in the driver, one
field at a time, from the shapes the API code produces. Each is labelled where it appears.

**Labels.** `observed` = seen rendered in this session (or in production data). `proved` = the
shipped code driven with crafted inputs (a transformed envelope through the real bundle).
`implemented` = read in the code. `computed` = derived from production data by a script.

**Where the evidence is.** `scratchpad/wave5/r7/out/` (per-render JSON audit, page text and a
full-page screenshot), gitignored. Nothing from it is committed.

## 1. Summary

**Verdict.** Screen by screen the app is the best it has been: 11 of wave #4's 15 findings are
fixed or dropped on evidence, the brief's failure states are right, Plan No. 3's ask is clear, the
Zwift rail says the truth about intervals.icu, push works, and Home loads in under a second on a
desktop-class CPU (about 2.7 s on a throttled phone profile). What fails is the story across
screens: **no screen says what is actually in Zwift**, and Home offers two fixes for one session
at once, so Mark took both on 8 Oct and the swap again on 10 Oct — Sunday's Zwift ride is now a
29-minute spin labelled Sweet Spot on every screen (UX333-01, live). **Grade: B−.**

| Question | In this lens |
|---|---|
| 1. Correct and safe? | Mostly. One live wrong ride (UX333-01 / CR327-01), reached through Home's own offers (UX333-02); raw error text and a whole-Home blank on a stale client (UX333-03). |
| 2. Honest with Mark? | The call: yes, on every surface. The ride: no — Home, Week and the brief name the planned session and say "Already in Zwift" whatever Zwift holds. From 19 Oct with no plan, the screens say "Rest is the plan today" (UX333-06). |
| 3. Helping him get fitter? | The builder lets him shape Plan No. 3, but it is 22 screens long and edits minutes as seconds (UX333-04); the one-tap plan-change card says nothing of cost (UX333-05, with AI329-02 and CI330-04). |
| 4. Would failure be noticed? | By Mark, only by reading the workout name in Zwift; by the app, not at all — its own "Something changed" alert fired on a stale packet and was retracted (UX333-02). No client error reporting. |
| 5. Cheap to run and change? | Yes. 476 KB of gzip JavaScript in all, 41 KB per day's payload, fixes here are hours to a day each. |

**Counts:** 1 High, 2 Med-High, 4 Medium, 3 Low. **Before 21 Oct?** one caution-only stopgap
(withhold the swap offer when the live event is not the planned ride, under UX333-01) and the
Decline confirm (UX333-04).

## 2. What optimal looks like

For one user on one phone, optimal is: **one morning, one story** — the call, the session card,
the week row, the brief and the Zwift event name the same ride, and when they cannot (a change
he approved, a swap, a failed push) the card says what Zwift holds and offers the one action that
reconciles it; **one choice per decision** — alternatives presented as alternatives, gone once
one is taken; **errors in words** — "Couldn't load, your data is safe, Try again", never JSON;
and **his words in his units** — minutes, his own phrasing for advice he has rewritten.

Already near-optimal, leave alone: the morning's first screen (call, his own words, the brief
link, today's session above the fold); the written-brief pending and failed states; the chest
follow-up; the Zwift rail words (326); the coach thread (opens at the newest, loads earlier);
dark-mode contrast (no misses); speed and bundle size; push delivery.

The smallest set of changes, in order:
1. Show the live Zwift event when it differs from the plan row (UX333-01), and until then withhold
   the swap offer on such a row (the "before 21 Oct?" stopgap). Ship with CR327-01.
2. One card for the two morning fixes; derive the swap offer, week mix and state-change alert from
   the live plan rows (UX333-02).
3. A `friendlyError()` helper and per-section parsing (UX333-03, open since 1 Sep).
4. "No plan loaded" as its own state from 19 Oct (UX333-06), and his own words for the REM line
   (UX333-07).
5. Builder: minutes, weeks folded, a confirm on Decline; a consequence line on the coach's plan
   card (UX333-04, -05).

## 3. Findings

Highs first. Every render cited is in `scratchpad/wave5/r7/out/` under the name given in brackets
(JSON audit, page text, screenshot in `shots/`).

### UX333-01 — High · No screen says what is actually in Zwift; after a change it names the planned ride and says "Already in Zwift"

**Evidence — observed, implemented, proved.**
- *Observed (the real 10 Oct state, `real-1010-*`):* the production envelope dumped at 09:05 BST
  on Sat 10 Oct, rendered through the shipped bundle. Home: "Sweet Spot (1 × 30 min @ 89%) ·
  Sweet spot · 58 min · Sweet Spot ~89% FTP · **Already in Zwift, ready to ride.**" Week: "Today's
  Sweet Spot session is eased, not lost: its hard intervals drop a zone and it keeps its full
  length." The brief: ride it "at its full planned length (58 minutes)". What Zwift holds is the
  8 Oct recovery substitution, 29 min, nothing above 60 % (R4 §3.0, R1 CR327-01). The envelope
  says so: today's row carries `delivery.liveOrigin = "red_substitution"`.
- *Implemented:* no file in `apps/web/src` reads `liveOrigin` (grep: zero hits). The Today card's
  status line (`DashboardPage` today-workout card) is chosen only from "has an intervals.icu
  event id" and the Zwift rail; title, minutes and target always come from the plan row. The API
  already loads the live proposal's whole structure (`DailyLoopService` delivery states read
  `structured_workout_ir`) but passes on only its `origin`.
- *Proved (8 Oct after approval, `m1008-after-approve-home`):* the 8 Oct row as the API returns
  it once an adjustment is approved (live, `changed: false`, no pending adjustment) renders
  "Sweet Spot … 58 min … Already in Zwift, ready to ride." with Edit and Swap day: no sign that
  the ride in Zwift is a 29-minute spin. The same holds for every approved adjustment, not just
  the swap case: approval replaces the intervals.icu event and leaves the plan row as it was.

- *Observed live, 10 Oct 12:48 UTC (read-only SQL on `workout_delivery_proposals` and
  `planned_workouts`):* at 10:08 UTC Mark took Home's "Move it to Sunday". The recovery
  substitution (event …345, `origin: red_substitution`) now sits on **Sun 11 Oct** under an active
  plan row titled "Sweet Spot (1 × 30 min @ 89%)"; Saturday holds the Easy Z2 (…352, as planned).
  It is CR327-01 a second time in three days, reached through the same Home offer (UX333-02), and
  Sunday's morning cannot replace the event (`_deliberately_acted`, R4 §3.0). Unless something
  changes, on Sunday Home will show a 58-minute Sweet Spot "Already in Zwift" and Zwift will serve
  a 29-minute spin at 60 %.

**What Mark experiences.** Every surface agrees on the *call*; none tells him the *ride*. The only
place the truth appears is the workout name in Zwift itself. On 10 Oct the week's only quality
session becomes a recovery spin unless he notices.

**Fix.** Carry the live event's title, minutes and top intensity in `delivery` (the API already
holds them) and, whenever the live event differs from the plan row, say so on Home and Week: "In
Zwift: Recovery substitution · 29 min · up to 60 % FTP", with the one action that reconciles it.
About half a day with tests. **Where:** with CR327-01's fix (R1); overlaps G8's 322.2 ("link each
ride to the version pushed"), which grades against it but does not display it. It adds
information rather than caution, so it waits for 21 Oct unless Craig bundles it with CR327-01.
**Before 21 Oct?** — one caution-only stopgap: withhold the swap offer (Home's "Move it to …" and
the brief's Apply) whenever the session's live event is not the planned ride (`liveOrigin` other
than `as_planned`). Every such swap reproduces CR327-01; withholding it removes an option and
adds none. A few lines and a test.

### UX333-02 — Med-High · On a hard morning Home offers two fixes for one session side by side, and both stay live after either is used

**Evidence — observed, implemented, proved.**
- *Observed (8 Oct envelope, `m1008-home-morning`, `state-generating-home`):* the stored
  morning's `todayActions` hold both `apply_swap` ("Move Sweet Spot … from Thursday to Saturday")
  and `approve_ride` ("Substitute recovery — no intervals, ~60% FTP for 29 min"), for the same
  planned workout. Home renders "Rearrange the week … Move it to Saturday" above the session card,
  and inside the card "Coach's suggested change: Move Sweet Spot … to Saturday … Substitute
  recovery, mobility, or rest … Approve & upload". The brief's Today list repeats "Move … Apply".
  Nothing says they are alternatives. Mark took both, nine seconds apart (10:07:01 approve,
  10:07:10 swap, R4 §3.0), which is how CR327-01 happened.
- *Observed (8 Oct end of day, `story-home-1008`):* after the swap, Home still offers "Move it to
  Saturday" and "Sweet Spot 0/1 → Sat" all day, because both come from the morning's stored
  analysis, frozen at 09:40.
- *Proved (`m1008-stale-swap-tap`):* a second tap on the stale button gets the API's 404 detail
  for an inactive row, shown raw at the top of the page: "Planned workout not found".
- *Observed + implemented:* the 10:45 coach message "**Something changed:** Sweet Spot has
  quietly gone at risk this week (1 still due, 0 still scheduled)" came from the same frozen
  morning: `StateChangeCoachService._candidates` compares the stored morning packets, so it
  announced, 38 minutes after he had fixed it, the shortfall the 09:40 packet carried. Home's
  launcher read "Ask about today — new coach message" (`chat-unread-1045`). Mark corrected it at
  13:10 ("already moved to … Saturday … showing there"); the coach retracted it. R3 asked for this
  cross-check: it is a false alarm, and its cause is the stale packet.
- *Observed (10 Oct):* the same pairing returns: "Move it to Sunday" beside a call to ride it
  eased; the brief offers both in one paragraph ("If you'd rather keep today's session where it
  is, the fallback is …").

**What Mark experiences.** Two buttons that look like steps, not choices; an offer that is still
there after he has done it; a "something changed" alert about a problem he has already fixed.

**Fix.** Present the two as one choice ("Either move it to Saturday, or ride an easy 29-min spin
today"); once one is applied, hide the other. Derive the swap offer, the week's mix and the
state-change check from the live plan rows, not the morning's stored packet. About a day.
**Where:** with CR327-01's fix; no G8 row covers it (316 is the load-ratio line, not the
week's offers). Not caution-only, so after 21 Oct.

### UX333-03 — Med-High · A response the app cannot parse, or any server failure, shows Mark raw machine text; one missing field blanks the whole of Home (UX241-03, still open)

**Evidence — proved, implemented.** Real envelopes, one field changed each (`drift-*`, `fail-*`):

| Change | What Mark sees |
|---|---|
| `thermalState` removed from the day | Home, the brief and Sleep each replaced by "Today's brief couldn't load" / "Sleep data couldn't load" and the Zod issue list as JSON (`"code": "invalid_type" … "path": ["data","thermalState"]`) |
| `briefGeneration.status` = a new value (`queued`) | the whole of Home replaced by the Zod enum error JSON |
| a field removed from the Week's schedule | "Plan couldn't load" + JSON |
| an unknown extra field | nothing: renders normally (the schemas strip unknown keys) |
| API 500 / 502 HTML / network down | "Internal Server Error" / "API error 502" / "Failed to fetch" |
| Accept the plan fails (503) | a toast reading "Service Unavailable" — no word on whether anything changed (`builder-accept-fails`) |
| tap a stale swap | "Planned workout not found" (UX333-02) |

*Implemented:* the pages still render `error.message`; `BlockGeneratorPage` toasts
`error.message` for make, change, accept and decline. No helper turns an error into words.

**What Mark experiences.** A stale phone (the PWA keeps an old bundle until reload; Railway and
Vercel deploy separately) meeting a newer API loses all of Home, not one card, and reads JSON.
**Fix.** One `friendlyError()` helper (three plain sentences: "Couldn't load — your data is
safe — Try again", plus "nothing was changed" on a failed write) and per-section `safeParse` so a
bad field drops one card. About half a day. **Where:** never placed in any batch since 1 Sep
(follow-through table); Craig to place it after G8.

### UX333-04 — Medium · The plan builder is 22 phone screens long and edits a 25-minute block in seconds

**Evidence — observed, implemented.** `/builder` on the real Plan No. 3 draft (`builder-*`):
18,836 px tall at 390 px wide (about 22 screens); every session of all 13 weeks is laid out with
three icon buttons (Change, Move, Remove), 273 controls 40 px wide against the app's 44 px floor.
Opening Change on "Sweet Spot (2 × 25 min @ 89%)" shows Reps 2, **Effort (seconds) 1500**, Effort
(% of FTP) 89, **Recovery (seconds) 180**, Recovery 60, under a free-text Name (the server
re-titles the session when the numbers change, `plan_changes.interval_workout_title`)
(`builder-change-open`). The coach button floats over the Save button. Decline is a
single tap with a bin icon and no confirm; it discards his changes (the draft row goes inactive;
"Make the plan" builds a fresh one). "Back to the plan as proposed", by contrast, confirms.
Mark writes sweet-spot blocks in minutes and VO₂ reps in seconds ("2 × 25" minutes; "35/25"
seconds, 8 Sep chat), as the plan's own titles do; the editor uses seconds for both.

**Fix.** Minutes for anything a minute or longer; show weeks 1–2 open and the rest folded ("Show
weeks 3–13"); a confirm on Decline ("This throws away your changes"); keep the floating button
clear of the open panel. About a day. These words were signed off under the 6 Oct delegation
(`docs/drafts/2026-10-07-batch-324-wording.md`); this is a fresh read, for Craig. CI330-01 (the
editor multiplies a VO₂ dose) and CI330-04 (protections removable one tap at a time) are R4's and
not repeated. **Where:** after G8; the Decline confirm is caution-only and small — **before 21
Oct?** (the ask is live on Home from Mon 12 Oct).

### UX333-05 — Medium · The coach's plan-change card states the change and nothing of its cost

**Evidence — proved (crafted offer through the shipped card, no model call), implemented.**
`chat-plan-offer`: the card reads "CHANGE TO YOUR NEXT PLAN · Tue 20 Oct, FTP Ramp Test: removed.
· Apply this change". One tap applies it; the applied line says "Nothing goes to Zwift until you
accept the plan". Nothing on the card says what goes with it (every target stays a percentage of
an FTP untested since 27 Jan) or how to undo it (only the builder's all-or-nothing "Back to the
plan as proposed"). R3 proved the coach makes this offer on the first ask (AI329-02); R4 owns the
coaching consequence (CI330-04). My lens adds that the card gives the one-tap path no friction and
no consequence line. **Fix:** a consequence line from the server for the protected sessions (test,
VO₂, recovery week) and a per-change undo in "Your changes". Fold into CI330-04's fix.
**Where:** with CI330-04.


### UX333-06 — Medium · From 19 Oct with no plan loaded, Home and Week say "Rest is the plan today"

**Evidence — proved (the real API's 19 Oct envelope, dumped read-only; and the shipped "no session
planned" call crafted onto a checked-in morning).** Before his check-in (`state-noplan-home-1019`)
Home reads "Rest day · Rest is the plan today. Add something light, swap a workout in…"; Week
(`state-noplan-week-1019`) reads "Rest week · 0 done · 0 to do" and every day "Rest / Rest day".
After the check-in (`noplan-1019-after-checkin-*`) the call says "No session planned · There's
nothing in your plan for today yet", while the card beneath it still says "No session planned ·
Rest is the plan today." The signed-off 323 words say "A declined plan writes nothing: Home goes on
saying 'No session planned' from 19 Oct" (`docs/drafts/2026-10-07-batch-323-wording.md`); the
empty-day fallbacks predate that and were not changed. After a decline the "Your next plan is
ready" card goes and Home offers no route back to the builder (it sits under More).

**What Mark experiences.** A plan that has ended looks like a plan that prescribes rest, which is
the one reading DV-1 was meant to rule out. **Fix.** One empty-plan state: "No plan loaded" on
Home and Week, with "Make your next plan" linking to the builder. A few hours. **Where:** before
19 Oct matters only if he declines; it adds clarity, not caution, so after 21 Oct by the rule — but
if Mark declines on 12–18 Oct, Craig should know the screens will read as rest (**for Craig**).

### UX333-07 — Medium · The REM line Mark called "muddled and flawed" on 8 Oct is still asked of him every morning

**Evidence — observed, implemented.** 8 Oct, 09:57–10:06 (chat): Mark asked what the check-in's
"After a short or broken night, protect the next full night rather than catching up early; REM
rebounds when you give it the back end of a normal sleep" meant; the coach's own explanation got
the example backwards and conceded it; Mark's verdict: "clearly muddled and flawed", and the plain
version he wrote himself ("if have bad night still stick to normal day and bedtime routine"). The
line is a fixed template (`rem_interventions.py`, `rem_rebound_recovery`). It is still on the
check-in's "Last night's REM focus" with Tried it / Didn't try it / Not sure (`core-check-in-*`,
9 Oct state) and in the 10 Oct brief's chronic actions (`real-1010-brief`). He is asked each day
whether he tried an instruction he has told the app he cannot parse. **Fix.** Replace the template
with his own words (they are better); words need sign-off. Minutes. **Where:** any time (a
wording change; Craig's sign-off); R6 owns whether the advice is right (HS332-04 covers the
17 °C half of the same block).

### UX333-08 — Low · Notifications "blocked" help sends an Android user to iPhone Settings

**Evidence — observed, implemented.** Settings, with permission denied (`core-settings-*`):
"Notifications are blocked for CheckMark. Turn them back on in iPhone Settings › Notifications ›
CheckMark". The string is fixed in `SettingsPage.tsx`; Mark has used Android Chrome since 16 Sep
(device rows, per the device-access note). This was UX241-07's fix. **Fix.** Pick the line by
platform ("Chrome › Site settings › Notifications" on Android). Minutes. **Where:** after G8.

### UX333-09 — Low · Raw timestamps survive on Home's reads; small text and thin links remain

**Evidence — observed, implemented.** Home's strength, walk and flexibility reads show "Generated
08/10/2026, 13:02:36" (`story-home-1008`; four `formatDateTime` call sites in `DashboardPage`), the
form UX241-14 fixed for the brief only. Text at 11–12 px is still common (Sleep 72 elements, Week 49,
the builder 208; it now scales with the root size, so UX241-12's "hard-coded" half is fixed, the
"small" half is not); the chart axis labels on Sleep and Trends stay fixed when the root size
grows (14 and 11 elements). Inline links are 16–20 px tall: "I disagree with today's call" (162 ×
20), "This looks wrong" (102 × 20), "Where these numbers come from" (16 px). Light mode has four
contrast misses (the holiday "Resumed" chip 3.77:1, the Trends legend 3.78:1); dark mode none.
**Fix.** One date formatter everywhere; 14 px floor for body text; 44 px hit areas on the three
links (padding, not size). Under a day. **Where:** after G8.

### UX333-10 — Low · Week does not carry the Zwift rail's warning

**Evidence — proved (`rail-paused-week`).** With the rail `paused`, Home's card says "Not reaching
Zwift: intervals.icu has paused your account…"; Week shows the same day's ride as "To do" with no
warning. 326 put the line on Home's card only. Mark checks Week (his 8 Oct message). **Fix.** The
same one line on Week's today row and in the week header. An hour. **Where:** after G8.

## 4. Follow-through

### 4.1 Wave #4's findings (UX241-01…15), re-verified on `42a6a98`

| ID | Wave #4 finding | Status now | Label | Evidence |
|---|---|---|---|---|
| UX241-01 | Brief lost four sections on a model swap | **fixed** | observed | 10 Oct v58 brief renders six sections (Your question, Sleep and recovery, Thermal, Experiment update, Chronic pattern actions, Today's call) |
| UX241-02 | `/brief` cannot tell failed from not-started; no retry | **fixed** | proved | `state-failed-brief`: "Couldn't finish your written brief · Today's call and your plan above are complete without it · Try again"; `state-generating-*`: "Writing your brief"; the call and Today actions render above both |
| UX241-03 | Raw JSON on a schema mismatch | **open, never placed** | proved | UX333-03: one missing field blanks Home; failures show raw server text |
| UX241-04 | Verdict 3,080 px down `/brief` | **fixed** (the hero); written call section still last | observed | Hero at the top (y≈200); "Today's call" heading at y 6,093 of 6,945 → queued 318 (DV-4) |
| UX241-05 | Coach shows 60 of 268, rest unreachable | **fixed** | observed | "Load earlier messages" present; thread opens at the newest (0 px below) |
| UX241-06 | Coach thread has no schema guard | **fixed** | implemented | `coachThreadSchema.parse` in `CoachLauncher` (both pages) |
| UX241-07 | Notification enable fails silently; denied = dead button | **shipped differently, partly sound** | observed + implemented | Denied state now explained, but only for iPhone (UX333-08). Push itself works: one active FCM (Android) subscription, last used 10 Oct 08:35 UTC, 0 failures |
| UX241-08 | Home's sleep line leaks a raw grade, truncates mid-number | **fixed** | observed | "7h 31m asleep · Good · REM 73m, in 65–90" (10 Oct); no truncation at 390 px |
| UX241-09 | His check-in words hidden in an accordion | **fixed** | observed | Home: "You said: OK · Feel an improvement this morning…" under the call |
| UX241-10 | Nothing says what the app cannot see | **fixed** | observed | Standing line on the brief and in the failed state |
| UX241-11 | Stale-brief detection Home-only | **fixed** | implemented | `useDailyLoopFreshness` used by Home and the brief |
| UX241-12 | 25 hard-coded sub-14 px sizes | **partly** | observed | Now rem-based (scale with the root), but 11–12 px text is still widespread (UX333-09) |
| UX241-13 | One control under 44 px | **fixed for that control; new ones** | observed | Home: 0 targets under 44 px on 9 Oct; `/brief` has three 16–20 px links and the builder 273 40-px buttons (UX333-04, -09) |
| UX241-14 | Raw "Generated 01/09/2026, 09:25:19" | **partly** | observed | Brief: "Written at 08:50 this morning"; Home's strength/walk/flexibility reads still raw (UX333-09) |
| UX241-15 | Cold time-to-content 4.9–11.7 s | **dropped (premise false), now measured** | observed | Production bundle: Home 0.85 s median on a desktop CPU, 2.65 s with a 4× slower CPU and 9 Mbps, uncompressed transfer; all JS 1.5 MB raw / 476 KB gzip; daily-loop 41 KB. Mock API has no server time, so production adds the API's latency (not measured) |

### 4.2 Later findings in this area

| ID | Finding | Status | Label | Evidence |
|---|---|---|---|---|
| DV-1 | Nothing planned after 18 Oct and nothing tells Mark | **shipped differently, partly sound** | proved | The ask works (`state-nextplan-home-1012`: "Your next plan is ready … Review it"); the no-plan state reads as planned rest (UX333-06) |
| DV-3 | The morning after a chest report is ordinary | **fixed** | proved | Crafted onto 9 Oct: "Chest or heart symptoms on Tuesday · Have they gone, and have you spoken to your GP or 111? Until you have, hard sessions are easy rides." with three answers; clear and unalarming. HS332-05 (R6) is the open half |
| DV-4 | Home says what, not why; the brief says why, last | **queued (317, 318), still accurate** | observed | 10 Oct: Home explains the call only by the *mild* resting-HR signal ("Counted in today's call"); the *marked* HRV reason that set the call is not on Home |
| 326 | Zwift rail states | **fixed as signed off** | proved | All six states render the 326 words (`rail-*`); `login_due` adds the dated reminder; an old server keeps "Already in Zwift". Week lacks the warning (UX333-10) |
| AI329-03 | Colour words still reach Mark | **R3's; screens clean** | observed | No colour word on Home or the brief's hero in any render; the Sleep page shows a "Red" chip for the room (a room grade, not the day's call) |

### 4.3 Mark's own words since 1 Sep that concern screens and flows

From `brief_messages` (his turns since 1 Sep matching screen or flow words, 38 rows read) and
`feedback` (27 rows since 1 Sep, 6 with text). Coaching complaints are R4's (BATCH_330 §4.5);
health wording R6's.

| Date | What he said (short) | Status | Evidence |
|---|---|---|---|
| 5 Sep | Check-in notes "not sure why you can't read them" | **Fixed** | implemented: the coach's live block carries today's check-ins (`chat_context`) |
| 7 Sep | "Unclear from morning brief" whether to do the 22-min dumbbell session | **Partly** | Home's card now names a weights day; a Recovery day's call ("rest or an easy spin") still says nothing about the strength session that day |
| 9 Sep | Bodyweight workout filed as a dumbbell workout (feedback, "way off") | **Fixed** | observed: 8 and 10 Oct reads name the Daily Bodyweight Workout |
| 13 Sep | Could not understand a brief line ("reaching Green from below that raw floor requires …") | **Partly** | That wording is gone; the 10 Oct brief still says "The deterministic app also offers a swap" and "rated marked" (→ 318) |
| 27 Sep | Don't use language that "would cause alarm" | **Partly** | Home and hero colour-free (observed); colour still in post-ride reads and briefs (AI329-03) |
| 8 Oct | The check-in's REM line is "clearly muddled and flawed" | **Not fixed** | UX333-07 |
| 8 Oct | Sweet Spot "already moved … showing there" on the Week tab | **Not fixed, recurred 10 Oct** | UX333-01, UX333-02 |


## 5. G8 and parked rows re-verified

| Row | Touches this lens | Verdict |
|---|---|---|
| 317 (Home shows why) | DV-4 | **Still accurate**, with a sharper case: on 10 Oct Home shows the mild resting-HR line and not the marked HRV reason that set "Take the edge off". `TodaysCallHero.tsx` still renders headline, line and reading only |
| 318 (brief leads with the call) | UX241-04's tail, DV-9 | **Still accurate**: written call section last (y 6,093 of 6,945); engine terms present ("rated marked", "the deterministic app"); the 10 Oct brief quotes the deep-sleep band as 16–20 % where the app's table holds 12–20 % (DV-9's class) |
| 322 (record what he rode) | UX333-01 | **Accurate but narrower than the problem**: 322.2 links each ride to the version pushed *for grading*; nothing in it makes a screen show that version. Extend it, or ship UX333-01 with CR327-01 |
| 320 (tonight's advice) | UX333-07 | Accurate; the REM line's wording is a separate, smaller fix |
| 321 (three small fixes) | — | 321.1 (swap withheld off the bike) is untouched by this lens; still accurate as written |
| 316, 311, 308, 319 | — | Outside this lens; no screen claim to re-verify |
| Parked 208, 209, 210, 276 | — | No screen claim. 276 depends on 274's dispute records: the "This looks wrong" links that feed it are 20 px tall (UX333-09) |

## 6. For reconsideration

- **Decision on the 324 wording (signed off under the 6 Oct delegation).** "Effort (seconds)",
  "Recovery (seconds)" and a one-tap Decline were signed off on Mark's behalf. New evidence: the
  live editor asks for 1500 seconds for a 25-minute block, and Mark writes sweet-spot blocks in
  minutes (UX333-04). Worth a second look by Craig, not a re-argument.
- **The "suggest, then let him act" shape of Home's adjustment card (Decision #99's pre-push and
  the approve/ignore card).** Two independent fixes for one session are offered at once and
  neither knows about the other (UX333-02). That is not the decision's intent; it is how the
  swap offer and the approval card were each added. A single "choose one" card is a design change,
  so it is listed here for Craig rather than assumed.

## 7. Hypotheses

- H1. A PWA left open overnight keeps the previous bundle; after a release that renames or removes
  a field, Mark's first morning view would be UX333-03's JSON until a reload. Not observed in
  production (no client error logging to check).
- H2. With the swap carrying the recovery event to Sunday (UX333-01, live), Sunday's post-ride read
  will grade a 29-min spin against the 58-min Sweet Spot and call it short or under. Check after
  he rides (R4 asked for the same).
- H3. The "Something changed" state-change messages can fire on any morning where he fixes a
  shortfall before 10:45 (UX333-02); how often has not been counted.

## 8. Limitations

- **Writes were not exercised for real.** Every write (check-in submit, approve, swap, accept,
  chat send) was refused by the mock and the driver; flows after a write were reproduced by
  serving the envelope the API returns afterwards (labelled `proved`), not by running the write.
- **No model call** ($0): the plan-change card was crafted; the coach's words in it are not the
  model's (R3 has the paid evidence).
- **Production latency** is not in the timings: the mock answers instantly; the API's own time on
  `daily-loop` was not measured (no token).
- **Headless Chromium is not his phone.** Android Chrome's text scaling, the installed PWA chrome,
  and the real push prompt were not reproduced; push health was read from the subscription table.
- **The 10 Oct fixtures are from 08:05 UTC.** Mark moved the Sweet Spot at 10:08 UTC; the renders
  show the state before that, the SQL in UX333-01 the state after.
- `/notifications/preferences` writes a default row on GET, so it failed on the read-only
  connection and was not captured; Settings rendered without it.

## 9. Probe log

| When (UTC) | What | Size |
|---|---|---|
| 9 Oct 22:35 | `dump_fixtures.py` under `railway run`: 39 GET routes through the real app on a read-only connection, rolled back; one write probe refused | 39 envelopes, ~0.6 MB |
| 10 Oct 08:05 | `dump_1010.py`: 9 GET routes for the 10 Oct morning, same guards | 9 envelopes, ~0.2 MB |
| 10 Oct 07:46–08:06 | Playwright against the mock: 83 renders (core × 2 themes, states, story, builder, chat, offline), plus `measure.mjs` (7 routes × 2 profiles × 3 runs) | scratch only |
| 10 Oct 12:4x | SQL: `information_schema.columns` for `brief_messages`, `feedback`, `workout_delivery_proposals`, `push_subscriptions` | < 5 KB |
| 10 Oct 12:4x | SQL: Mark's chat turns since 1 Sep matching screen/flow words (38 rows, 300 chars each) | ~15 KB |
| 10 Oct 12:4x | SQL: `feedback` since 1 Sep (27 rows) and the one 10 Oct row's analysis (700 chars) | ~5 KB |
| 10 Oct 12:48 | SQL: 10 Oct analyses list and planned rows; delivery proposals 8–11 Oct (no JSONB beyond two keys) | ~2 KB |
| 10 Oct 12:5x | SQL: `refresh_tokens` platform of the last 6 rows; `push_subscriptions` last 6 (host, counts) | ~1 KB |

No paid call. No device token minted or read. No non-GET reached any real server: the browser
driver answered every non-GET itself, and the mock's log (305 requests) holds one POST, a
deliberate check of its own 405 at 07:46 UTC, refused.

