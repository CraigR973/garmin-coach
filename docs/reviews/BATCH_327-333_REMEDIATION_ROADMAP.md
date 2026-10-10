# Batch 327–333 remediation roadmap (audit wave #5)

**Synthesised 10 Oct 2026** from the seven passes of audit wave #5, reviewed at `42a6a98`
(production served the same SHA throughout). Follows wave #4's format
([`BATCH_236-241_REMEDIATION_ROADMAP.md`](BATCH_236-241_REMEDIATION_ROADMAP.md)).

**The passes:** [327 code](BATCH_327_CODE_REVIEW.md) (7) ·
[328 data, security and ops](BATCH_328_DATA_SECURITY_OPS_REVIEW.md) (11) ·
[329 AI](BATCH_329_AI_ENGINEERING_REVIEW.md) (7) ·
[330 coaching integrity](BATCH_330_COACHING_INTEGRITY_REFRESH.md) (8) ·
[331 strength and the whole athlete](BATCH_331_FITNESS_REVIEW.md) (7) ·
[332 health and sleep](BATCH_332_HEALTH_SCIENCE_REVIEW.md) (10) ·
[333 UX and the live app](BATCH_333_UX_LIVE_APP_REVIEW.md) (__UXN__) and
[Mark's scorecard](BATCH_333_MARK_SCORECARD.md).
Scope, decisions and guardrails: [`BATCH_327-333_AUDIT_SCOPE.md`](BATCH_327-333_AUDIT_SCOPE.md).
Every earlier finding's fate: [`BATCH_327-333_FOLLOW_THROUGH.md`](BATCH_327-333_FOLLOW_THROUGH.md).

**Evidence labels**, as in `COACHING_INTEGRITY_AUDIT.md`: *observed* (production rows or
logs), *computed* (derived from production rows by a script), *proved* (the real function
driven with crafted inputs, or a test that fails when the fix is reverted), *implemented*
(read in the code). Every High and every headline number below was re-checked during
synthesis against production or the shipped code; where only a pass checked it, it says so.

**Spend:** $0.19 of the $2 cap (five calls in R3's steerability probe, logged in its report).
Nothing was written to production. The repo is public: Mark is quoted only in short phrases.

---

## a. The verdict

1. **The morning call is now the best-built part of the app, and it is safe.** The replay
   reproduces production on 10 of 10 graded mornings; across 798,336 one-step comparisons a
   worse input never gave a less cautious call; every floor survives a failed brief.
2. **What Mark rides does not always match what he is told.** On Sat 10 Oct the brief, Home
   and Zwift each hold a different ride; Plan No. 3's strength never reaches his watch; after
   the 20 Oct ramp test the app will go on grading him against 280 W.
3. **Plan No. 3 is a good plan with soft protections.** Its editor can multiply a VO₂ session
   several times over, and the ramp test and every VO₂ session can be removed one tap at a
   time (the coach offers to drop the test on the first ask), with nobody told.
4. **A failure is still mostly silent before it reaches Mark.** The Sentry rule does not
   exist and only 7 alert kinds are tagged for it; the watchdog has never run; both Railway
   crons crash on every run; no backup has ever been restored.
5. **The public repo carries a family member's home address, phone and email, and Mark's
   health record.** Running costs are low (about $11.60 per 30 days of Anthropic), but the
   service code grew 54% in 38 days.

### Scorecard

| Question | Grade | In one line |
|---|---|---|
| 1. Correct and safe? | **B** | The call and its floors are proved; the plan editor has no ceiling on VO₂ dose, and a symptom felt on the bike has no route to a floor |
| 2. Honest with Mark? | **C+** | Three rides on 10 Oct; colour words still in the post-ride reads; the coach cannot see the app's own rules; a daily REM verdict the watch cannot support |
| 3. Helping him get fitter? | **C+** | Plan No. 3 progresses and deloads properly, but no key session has been ridden at full since 12 Sep, its strength cannot reach him, and the test result will not reach the targets |
| 4. Would a failure be noticed? | **D+** | Storage sat at critical for 35 days; the watchdog never ran; crons crash unseen; the only backup has never been restored |
| 5. Cheap to run and change? | **B** | About $11.60 per 30 days, storage runway 9–18 months; but 54% more service code, and our own backup is most of the egress cap |

| Pass | Grade | In one line |
|---|---|---|
| R1 Code and architecture (327) | **B** | One owner for the morning; threads safe; 12 of 12 reverted fixes fail a test; weak where a session crosses a day or a rollback |
| R2 Data, security and ops (328) | **C+** | Auth and RLS tight; the repo leaks personal data; nothing outside the process watches the process |
| R3 AI and LLM engineering (329) | **B** | The model decides nothing about the day; what it says is unchecked on 9 of 12 paths |
| R4 Coaching integrity (330) | **B+ (held)** | Up on the call, down on the plan and the trainer |
| R5 Strength and the whole athlete (331) | **C+** | Loaded strength is prescribed but cannot be delivered, recorded or progressed |
| R6 Health and sleep (332) | **B** | The floors are sound and robust; the words and statistics around them say more than the evidence |
| R7 UX and the live app (333) | **__UXGRADE__** | __UXLINE__ |

---

## b. Happening now, and before Plan No. 3 starts on 19 Oct

**Now — Sat 10 Oct's ride (CR327-01, High; observed, proved; re-verified).** On Thu 8 Oct
Mark approved the Red recovery version of Thursday's sweet spot, then swapped Thursday and
Saturday. The swap moved the *eased Zwift event* to Saturday while Saturday's plan row reads
the full 58-minute sweet spot. At 13:45 BST on 10 Oct: the morning reads "Take the edge
off" (graded Amber); the brief describes the sweet spot eased "from 100% to 87%" (it is the
warm-up efforts that move that way; the main set eases 89% → 76%); Home shows the full
58-minute sweet spot as in Zwift; Zwift holds a 29-minute ride capped at 60% FTP; no ride yet.
Saturday's own morning cannot replace it, because the app counts the moved event as one
Mark acted on. The fix is code (W3); today it is Craig's call (decision 1). Leaving it is
the more cautious state: an honesty failure, not a safety one.

**Now — the public repo (DS328-04, High; observed, re-verified).** A test fixture committed
on 20 Jun holds the Hive account holder's full name, email, phone, street address, postcode,
home coordinates and device addresses. The holder is a member of Mark's household, not Mark.
The repo also holds 118 screenshots and data extracts of Mark's health data and 56 of his
real check-in notes (Decision #368). Decision 2.

**Before Home asks him on Mon 12 Oct (the plan builder's guards; caution-only code, so a
candidate for an exception to "nothing before 21 Oct"; decision 3):**
- **CI330-01 (Med-High, proved).** The builder applies its five interval numbers to each set
  of a multi-set VO₂ session. Entering Mark's own 28 Aug progression the natural way makes
  week 10's session 4 × (6 × 3 min) at 119%: 180 minutes, 72 of them VO₂ (Plan No. 3's peak
  is 20). It is accepted with a warning that never blocks. The first VO₂ session it could
  reach is Tue 27 Oct.
- **CI330-04 + AI329-02 (Med-High; proved, paid probe).** The ramp test and all 13 VO₂
  sessions can be removed one at a time, by tap or by coach offer; the coach offered to drop
  the ramp test on the first anxious ask, and again with no caution on push-back. A recovery
  week can be loaded to 470 minutes and still be labelled "recovery". Craig sees an info log.

**Before the ramp test, Tue 20 Oct (zero-code; decisions 6–8):**
- **CI330-03.** On a tired morning the engine eases the ramp test (capped at 94%) instead of
  moving it; an eased ramp test gives a meaningless FTP. Tell Mark to move it, not ride it eased.
- **FC331-03.** Plan No. 3 puts its first loaded leg session (Dumbbells A) on Mon 19 Oct, 24
  hours before the ramp test, and heavy legs before every Tuesday VO₂ session. Mark can move
  it in the builder (proved accepted, no week over his longest).
- **FC331-01.** Dumbbells A is a new session with no route to his watch, where he lifts; his
  old upper-body routine will be matched as "done" in its place. A one-off watch set-up of A
  and B closes most of it.

**Before Thu 22 Oct, his first graded sweet spot after the test (CI330-02, Med-High,
implemented + proved):** the app grades every ride against its own profile FTP (280 W), not
Zwift's. A 7% change either way makes an ERG-perfect interval read "under" or "over". Bridge:
Craig writes the new FTP to the profile when Mark reports it (a production write; decision 8).

**Console steps that change nothing Mark sees (decision 4):** create the Sentry rule in
DS328-01's shape; delete `HIVE_EMAIL`/`HIVE_PASSWORD` from the `api` service (DS328-03); turn
on GitHub secret scanning, push protection and Dependabot alerts (DS328-10).

**Optional before 21 Oct, caution-only (decision 9):** widen the check-in's symptom question
to "since your last check-in, including on a ride" (HS332-01), web copy only.

---

## c. How the app works now

```
 Garmin · Hive · Open-Meteo
   │  worker threads, one Garmin call at a time (312)
   ▼
 APScheduler inside the `api` process ── job_runs (every run)
   │  wake-check → morning sync → check-in
   ▼
 THE MORNING (deterministic, stored before any paid call)
   floors (acute rail, symptoms, notes reader: caution only)
   → graded verdict (4 domains vs his normal)
   → today's call + an action per session
   │                                   │
   ▼                                   ▼
 Claude writes the brief          delivery rail
 (explains; decides nothing)      plan rows → intervals.icu → Zwift
   │                              (+ swap / approve / edit by Mark)
   ▼                                   │
 Home · brief · chat · Week ◄──────────┘ read back as "in Zwift"
   │
 post-ride reads (Claude) graded on profile FTP
 plan builder (Plan No. 3 draft) + coach offers (validated, one tap)

 Operator side: log.error → Sentry (7 tagged kinds; no rule yet)
 Backup: nightly pg_dump on the api's own volume (never restored)
```

**In one paragraph.** Each morning the app syncs his night, reads his check-in, applies the
medical floors, grades four domains against his own normal, and stores one call with an
action for every session, all before any paid model call. Claude then writes the brief,
which only explains. Home, the brief page, the chat and the Week view read the stored call.
Workouts reach Zwift through intervals.icu: the plan's rows are pushed in advance, and a
morning's easing, an approval, a swap or an edit replaces or moves the pushed event. After a
ride the post-ride read grades it against the plan and the profile FTP. The plan builder
drafts the next 13 weeks for him to change and accept. Operator failures are error logs that
Sentry captures; the app's own watchdog for its scheduler has never been given a clock.

### Where `ARCHITECTURE.md` disagrees with the code (implemented)

| ARCHITECTURE.md says | The code does |
|---|---|
| Batch 291 / #381: "sends admin alerts to Craig through Sentry" | Only 7 kinds carry the `admin_alert` tag; storage, egress, backup, drill, watchdog and job-crash alerts are untagged `log.error`; the rule does not exist (DS328-01) |
| Swap day re-slots the session (§2, delivery rail) | `swap_day` moves the *delivered event with its current content*, including another morning's easing (CR327-01) |
| Plan No. 3 is built from "his FTP as it stands" | Nothing writes the ramp test's result anywhere; every grade stays on 280 W (CI330-02) |
| The nightly backup's restore leaves `activity_timeseries` empty and the backfill refills it | No restore has ever run; `backup-drill` skipped `not_configured` 5 of 5 weeks (DS328-11) |
| §4, the analysis engine | A batch-by-batch accretion (lines ~270–330), not a decision table; Batch 308 rewrites it (queued) |
| `docs/runbooks/scheduled-jobs-cron.md`: the two Railway crons are "durable external paths" | Both have crashed on every execution, 18 of 18 and 40 of 40 (DS328-02) |

---

## d. Work packages

### Disposition legend

| Tag | Meaning |
|---|---|
| **Do now** | Ships in this remediation wave, in the order given (after 21 Oct unless marked). |
| **Decision-gated** | Craig chooses the shape before anyone builds. Listed in section f. |
| **Fold into G8** | Amends a queued G8 row rather than adding one; the row is corrected at `/batch-start`. |
| **Defer — trigger** | Correct to leave; the trigger is recorded. |
| **Accept and close** | Real, understood, not worth changing at one user. |

### At a glance

| # | Package | Findings | Tier | When |
|---|---|---|---|---|
| **W0** | Craig's zero-code steps | CR327-01 (today), DS328-01 (rule), DS328-03 (vars), DS328-10 (guards), CI330-02/-03 bridges, FC331-01/-03 bridges | 🔴 | Now – 20 Oct |
| **W1** | The public repo carries nobody's data | DS328-04 | 🔴 | Decision-gated; fixture swap now if Craig agrees |
| **W2** | Plan No. 3's protections hold | CI330-01, CI330-04, AI329-02, CI330-03 | 🔴 | Before 12 Oct if Craig allows the exception; else first after the trial |
| **W3** | The ride on the trainer is the ride he is told | CR327-01, CI330-02, FC331-02 | 🔴 | Straight after the trial addendum (21 Oct) |
| **W4** | A failure reaches Craig | DS328-01, DS328-02, CR327-02, DS328-11, DS328-10, DS328-06, CR327-07, DS328-08, DS328-03 | 🔴 | Beside G8 from 21 Oct (touches no rule of the call) |
| **W5** | The coach knows the rules, and no read names a colour | AI329-01, AI329-03, AI329-04…07 | 🟢 | Fold into 317 and 318 |
| **W6** | Health words that match the evidence | HS332-01…10 | 🟢 | Partly before 21 Oct (01a); rest into 318, 320, 321 and one row |
| **W7** | Strength he can do and the app can see | FC331-01…07 | 🟢 | One row after G8; record into 322; Red line into 321 |
| **W8** | Coaching residuals | CI330-05…08 | 🟢 | Fold into 319, 321, 322 |
| **W9** | Smaller and cheaper | CR327-03…06, DS328-05, -07, -09 | 🟢 | 308 resized; one hygiene row after G8 |
| **W10** | What Mark sees on each screen | UX333-__ | __ | __ |

---

### W0 — Craig's zero-code steps *(Do now; no code, nothing lands in the repo)*

1. **Sat 10 Oct's ride (CR327-01).** Tell Mark that if today's call says the sweet spot,
   tapping Edit on Saturday's card rebuilds the ride from the plan (R1, *implemented*; not
   tried on this day), or leave the easier ride. Craig's message, not the app's.
2. **The Sentry rule (DS328-01).** "An event is captured" with tag `admin_alert` (any
   value), action email, throttle 24 h. A "new issue" rule fires once per issue, which is
   why 35 daily storage alerts could email at most once. Then fire one test event.
3. **Delete `HIVE_EMAIL` and `HIVE_PASSWORD` from the `api` service (DS328-03).** With the
   refresh-token blob configured the password fallback can never win, and an expired token
   would make it text an MFA code to the account holder about every 5 minutes (proved).
4. **GitHub's free guards (DS328-10):** secret scanning, push protection, Dependabot alerts.
5. **Messages to Mark before 19 Oct:** move the ramp test rather than ride it eased
   (CI330-03); set up Dumbbells A and B as watch workouts (FC331-01); consider moving
   Dumbbells A off Monday 19 Oct (FC331-03).
6. **After the ramp test:** write the new FTP to his profile when he reports it, before
   Thu 22 Oct (CI330-02; a production write, read-modify-write as in Batch 152).

### W1 — The public repo carries nobody's data *(Decision-gated; High)*

**DS328-04 (High; observed, re-verified).** `apps/api/tests/fixtures/hive/getAll.json`
(committed 20 Jun) carries a real household's identity block; the repo also holds 118
screenshots and data extracts of Mark's health data (`docs/reviews/batch-156`, `batch-192`,
`batch-241`, `baseline-history.xlsx`, root PDFs), STATUS's medication line, and 56 real
check-in notes in the notes-reader eval (Decision #368). A stranger can learn a household's
address and phone, and Mark's age, town, HRV, resting HR, sleep and check-in notes.

**Options, priced by R2 (nothing changed):**

| Option | Cost | Does not fix |
|---|---|---|
| Replace the fixture's identity block with synthetic values | About 1 h, a test-only PR | History; forks; existing clones |
| Make the repo private | About $11–17 a month in Actions minutes at current CI volume | Anything already copied or cached |
| Rewrite history (`git filter-repo`) | About half a day; every clone and branch invalidated | Forks and caches |
| Both | Both costs | Copies already taken |

**Recommended:** the fixture swap now (it changes no behaviour, so the trial is not touched),
then private, then decide on a rewrite with the evidence of who has cloned it. Move the eval's
56 real notes to a private location and keep synthetic cases public (reconsider #368).

### W2 — Plan No. 3's protections hold *(Do now; adds caution only; candidate before 21 Oct)*

- **CI330-01:** bound VO₂ work per session in `plan_changes` and the interval editor (say,
  no more than Plan No. 3's own peak plus a margin), and show the total in the change's words.
- **CI330-04 + AI329-02:** whenever a change removes or hollows out the ramp test, a VO₂
  session or a recovery week, the offer card and the hand-change confirmation state the cost
  in fixed words decided by the code; at accept, a one-screen "as proposed → your plan" diff
  of those three things, shown to Mark and sent as an `admin_alert`. Nothing is blocked.
- **CI330-03:** a test session's only morning actions are "as planned" or "move it".
- **Cost:** about 1–1.5 days. **Acceptance:** R4's probes invert (the 180-minute session is
  refused; a removal carries the fixed words; an Amber ramp-test morning offers a move).

### W3 — The ride on the trainer is the ride he is told *(Do now; straight after the trial addendum)*

- **CR327-01 (High):** a swap or move re-pushes the moved session's baseline when its live
  content is a morning transform, and keeps moving Mark's own edits; `approve_adjustment`
  stops marking the consumed proposal `pushed`; and a daily job compares each pushed event
  with its plan row plus that morning's action, using the comparison the code already has
  (`_proposal_content_matches_workout`). About a day. It has happened twice (2 Aug, 10 Oct).
- **CI330-02 (Med-High):** after the ramp test, one tap writes the new FTP into the profile
  (the app computes it from the best minute) and every target and grade follows. Fold into
  **319** as its first phase, and move 319 earlier, or a small row of its own (decision 13).
- **FC331-02 (Med-High, proved):** on a Red morning with planned strength, the call ("As
  planned"), the brief's plan line ("Substitute recovery, mobility, or rest") and the session
  ("one weight up") disagree. Fold into **321.3** (its third line was dropped from DV-14).

### W4 — A failure reaches Craig *(Do now; beside G8 from 21 Oct)*

- **DS328-01 (High):** every operator `log.error` goes through `admin_alert` with its own kind
  and a stable fingerprint (storage, egress, backup, drill, watchdog, job crash, cron crash).
- **DS328-02 (Med-High):** the two Railway crons either run (drop the shell-syntax start
  commands; first give `weekly-review` `SCHEDULED_JOB` and `SCHEDULED_LONDON_HHMM`, or it boots
  a second API and every job runs twice; give `trend-narratives` the settings it lacks) or are
  deleted; `ledger-freshness` gets its own clock; `/api/v1/health` gains the age of the newest
  `job_runs` row so the existing freshness workflow can alarm on a dead scheduler.
- **CR327-02 (Med-High, proved):** hoist the identifiers in the backstop's failure handler and
  the trend-narratives job, and add a real-`AsyncSession` guard test (half a day).
- **DS328-11 (Medium):** a weekly archive-integrity drill (read the dump end to end) and a
  weekly copy off Railway; the restore drill needs `BACKUP_RESTORE_DATABASE_URL` (Craig's).
- **DS328-10 (Medium):** Railway waits for CI; a `main` ruleset with a bypass for docs
  close-outs. On 20 Sep four red-CI commits went live.
- **DS328-06 + CR327-07 (Medium/Low):** deploy freshness by ancestry, and read Vercel too.
- **DS328-08 (Low):** misfire grace on the daily jobs; docs-only commits stop redeploying.
- **DS328-03 (Medium):** remove the Hive password fallback in code (after W0's variable delete).
- **Cost:** about 2–2.5 days in two rows. **Acceptance:** one deliberate failure of each kind
  emails Craig once a day while it lasts; a stopped scheduler turns the freshness check red.

### W5 — The coach knows the rules, and no read names a colour *(Fold into 317 and 318)*

- **AI329-01 (Med-High, observed):** the chat's context gains `rulesInForce` and a not-met
  trace (e.g. 9 Oct: Batch 310's holiday catch-up missed by 0.6 ms), so "has this been
  factored in now?" is answered from what the code did. **Fold into 317.**
- **AI329-03 (Medium, observed, re-verified):** the post-workout prompt (v18) never got 313's
  colour ban; both post-ride reads since 7 Oct say "Amber readiness" or "Red readiness
  verdict", and 2 of 3 v58 briefs break their own rule. **Extend 318's post-check** to every
  Mark-facing read (no colour words; the call quoted as stored; every figure one the packet
  holds), alerting with DS328-01's rule shape; post-workout prompt v19.
- **AI329-04…07 (Low):** chat headroom after the plan view; connection errors not retried
  and partial refusals stored as answers; the notes reader's regeneration contract; the
  extractor's colour vocabulary. One small row after G8.
- **Evals:** a five-ask steerability set for plan offers, re-run on each chat-prompt bump
  (about $0.20 a run); usage persisted for chat, notes reader, extractor and batch.

### W6 — Health words that match the evidence *(Mixed)*

- **HS332-01 (Med-High, implemented + proved):** a symptom felt on the bike has no route to
  a floor (the notes reader reads morning check-ins only; re-verified). (a) Widen the
  question (before 21 Oct, decision 9); (b) give the post-ride read and the coach the
  chest-or-heart rule. One row.
- **HS332-05 (Medium, proved):** the morning after a chest report, a day with no hard
  session reads "Green light · You're recovered", and loaded strength proceeds. A neutral call
  and strength at the recovery dose until the follow-up clears (reconsider #386, item 3).
- **HS332-03 (Medium):** every brief calls his REM "below the healthy range", which Decision
  #322 says the watch cannot support. **Fold into 318** (pattern and baseline lead).
- **HS332-04 (Medium):** October pushes to cool towards 17 °C while he heats the room
  (HS240-08). **Fold into 320** with an 18 °C floor.
- **HS332-02 (Medium, computed):** the REM-intervention loop is three nights from posting
  "supported" on a September-against-October contrast. **Fold into 320** (refuse a verdict
  unless the arms overlap in time) — decision 10 on whether it waits.
- **HS332-06…10 (Low):** a high-side HRV check; respiration speaking on its own; "a low
  reading", not "sustained"; the drivers cache's calendar adjustment; re-reading a failed note.

### W7 — Strength he can do and the app can see *(One row after G8, plus folds)*

- **FC331-01 (Med-High):** delivery (watch workouts or text workouts via intervals.icu) and
  one top-weight number at the check-in; Garmin's exercise sets are already stored and unread.
  The record half **folds into 322**.
- **FC331-02:** into 321.3 (W3). **FC331-03/-04:** move Dumbbells A off the day before VO₂
  and the test, and size the sessions at 30–40 minutes. **FC331-05:** bone (impact or heavy
  loading). **FC331-06:** the post-strength read sees load, not just a 9-minute circuit.
  **FC331-07:** his own routines in the plan.

### W8 — Coaching residuals *(Fold into G8)*

- **CI330-05 (Medium):** Plan No. 3 sets aside his own documented VO₂ progression without
  saying so: one line in "why this plan" (before he accepts, words for Craig).
- **CI330-06 (Medium):** no key session ridden at full since 12 Sep (5 of 5 due since 30 Sep
  not ridden); 319's progress signal is where it is watched.
- **CI330-07 (Low):** the drift baseline in the post-ride read → **322**. **CI330-08 (Low):** → **321.2**.

### W9 — Smaller and cheaper *(308 resized; one row after G8)*

- **CR327-03 (Medium):** 76% of the graded brief's system prompt is generated from the
  ladder's. **308 is a split, not a deletion: 2–3 days, not 1.**
- **CR327-04 (Medium):** service code +54% in 38 days; a `job_loop` module for the
  scheduler's profile loops; move `verdict_replay` and `notes_eval` out of `services/`.
- **CR327-05/-06 (Low):** a lock on the plan draft (a race is a 409, not a 500); `none_as_null`.
- **DS328-05 (Medium, computed):** our own nightly backup and the meter are about 5 GB a
  month of the 5.5 GB egress cap; split the backup (authored nightly, raw weekly) and keep a
  running month total.
- **DS328-07 / -09 (Low):** the weekly review skipped a whole week because the holiday began
  on its Sunday; 47 dev-tool advisories outside the gate.

### W10 — What Mark sees on each screen

__UXW10__

---

### G8 and parked rows, re-verified (batch-start step 4)

| Row | Verdict | What changes |
|---|---|---|
| **316** load-ratio line | Accurate; pointer drift (`_load` now `verdict_grading.py:953`) | None |
| **311** HRV counted twice | Accurate for HRV; **incomplete** | Add the resting-HR rail's same drift (HS240-15); replay 8 Oct (a readiness-confirmed Red) |
| **308** the ladder goes | **Under-sized** | The graded prompt must be written out first; 2–3 days; natural home for DS328-02's cron tidy-up and the runbook |
| **317** Home shows why | Accurate | Add AI329-01's `rulesInForce` and not-met trace |
| **318** the brief is checked | Accurate; one reference moved (`:1772`); **scope too narrow** | Every Mark-facing read; post-workout v19; HS332-03; DS328-01's alert shape |
| **321** three small fixes | 321.1's reference decayed (`:1335`); **321.3 lost a line** | FC331-02's strength line; CI330-08 into 321.2 |
| **319** progress signal | **Decayed** (predates Plan No. 3's ramp test) | Lead with CI330-02; add CI330-03; consider moving earlier |
| **320** tonight's advice | Accurate; **missing a confound** | HS332-02's calendar guard; HS332-04's 18 °C floor |
| **322** record what he rode | Accurate; **extend** | Grade against the version actually pushed (CR327-01); strength's top weight (FC331-01); the drift baseline (CI330-07) |
| **208** co-resident app | **Premise gone** (0 `public` tables since 24 Sep) | Close it |
| **209** RLS that constrains the app | Accurate apart from counts (32 tables, 0 FORCE) | Trigger unfired |
| **210** no connection idles across a model call | **Decayed** | References moved; add a third site (the trend-narratives job holds a lock across a paid call) |
| **276** a dispute suppresses an input | Accurate; its own gate says do not run (0 disputes) | None |

---

## e. Coverage, follow-through, and what is not settled

### Coverage check — every raw finding mapped

| Pass | Findings | Do now | Fold into G8 | Decision-gated | Defer | Accept |
|---|---:|---:|---:|---:|---:|---:|
| 327 code | 7 | 4 (01, 02, 04, 05/06 as one) | 1 (03 → 308) | 0 | 0 | 1 (07 into W4) |
| 328 ops | 11 | 9 | 0 | 1 (04) | 0 | 1 (09) |
| 329 AI | 7 | 4 (02, 04, 05, 06/07) | 2 (01 → 317, 03 → 318) | 0 | 0 | 0 |
| 330 coaching | 8 | 3 (01, 03, 04) | 5 (02 → 319, 05, 06, 07 → 322, 08 → 321) | 0 | 0 | 0 |
| 331 fitness | 7 | 5 (01, 03, 04, 05, 07) | 2 (02 → 321, 06 → 322) | 0 | 0 | 0 |
| 332 health | 10 | 6 (01, 05, 06, 07, 08, 10) | 3 (02, 03, 04) | 0 | 0 | 0 (09 do now) |
| 333 UX | __ | __ | __ | __ | __ | __ |

### Follow-through, in brief

Full table (212 rows, with the passes' corrections first):
[`BATCH_327-333_FOLLOW_THROUGH.md`](BATCH_327-333_FOLLOW_THROUGH.md).

| Source | n | Fixed | Queued | Open | Shipped differently | Other |
|---|---:|---:|---:|---:|---:|---|
| Wave #4 (236–241) | 99 | 60 | 5 | 6 | 6 | 1 superseded, 1 dropped, 3 deferred, 17 accepted |
| REM premise, 3 Sep | 7 | 4 | 0 | 2 | 0 | 1 deferred |
| 22 Sep – 6 Oct reviews and replays | 106 | 60 | 20 | 9 | 2 | 4 superseded, 11 accepted |
| **Total** | **212** | **124** | **25** | **17** | **8** | 38 |

Of the 124 "fixed", 53 were seen in the code by the helper and every wave #4 High was
spot-checked; the passes then re-verified their own lens and corrected five rows (CI239-07
and DS237-03 are only partly fixed; CR236-01's class returned; DS237-01 is wider).
**Wave #4's "all 99 mapped" was false:** eight findings were in no package (AI238-05,
AI238-08, AI238-09, HS240-08, HS240-09, HS240-15, HS240-17, UX241-03); HS240-08 and
UX241-03 are still open and appear above as HS332-04 and in W10.

**Open Highs from earlier waves:** DS237-01 (now DS328-01), DS237-04 (now DS328-11),
UX241-03 (W10), AI238-02 (queued in 318), DV-2 (queued in 319); shipped differently and
sound: CI239-02 (every push rail blocks an un-eased hard session on a Red, but a swap could
carry one), HS240-05 (the REM pattern is real, its size uncertain), R0922-4, 0928-SE-3.

### For reconsideration (settled decisions; the evidence is new)

| Decision | Proposed amendment | Evidence |
|---|---|---|
| #381 Sentry as the single route | Keep the route; every operator log tagged; the rule's existence part of acceptance | DS328-01 |
| #355 / #364 the crons keep their start commands | Drop the commands or delete the services | DS328-02 (58 of 58 crashed) |
| #59 Hive password fallback | Remove it, as 267 did for Garmin | DS328-03 (proved SMS storm) |
| #39 auto-deploy from `main` | Keep; Railway waits for CI; a `main` ruleset | DS328-10 |
| #262 nightly dump of every table | Split authored nightly, raw weekly | DS328-05 |
| #368 56 real notes in the public eval | Move them private; synthetic cases public | DS328-04 |
| #386 nullable identity columns on a new table | New tables' identity columns NOT NULL | CR327 §6 |
| #386 item 3 a no-hard-session day is unchanged | A neutral call and strength eased until cleared | HS332-05 |
| #375 two easy mornings after a fever | A third morning of Zone 2 only | HS332 §6 (IOC 2022, abstract) |
| #307 / #322 / #360 the daily REM band | Pattern and baseline lead; "can't be judged" allowed | HS332-03 |
| #389 ramp test "only moves or goes"; a long week warns | Fixed words on removal; a VO₂ dose bound that blocks; "the morning only moves it" | AI329-02, CI330-01/-03/-04 |
| #387 FTP "he sets in Zwift" | "he sets in the app and Zwift" | CI330-02 |
| #99 + 173.1 "deliberately acted" | Stands once a swap carries planned content | CR327-01 |
| #108 no strength player | Not a player: watch workouts and one top-weight number | FC331-01 |

### Hypotheses (unverified)

- Railway may have emailed Craig about ~16 crashed cron executions a week since 20 Sep,
  training him to ignore Railway mail (R2).
- September's real egress was about 5–5.5 GB, almost all backup and meter (R2; one look at
  Supabase's daily egress bars settles it).
- Zero-thinking briefs (17 of 43) and the coach's zero-thinking capitulation may share a
  cause (R3).
- A ramp test after a taper and five light weeks will read low, the safe direction (R4).
- Mark will keep doing his old upper-body routine on Mondays unless A is set up on his watch;
  testable from 19 Oct (R5).
- Whether Garmin reports an overnight HRV during atrial fibrillation at all (R6).
- Executor saturation during a slow-Garmin hour (R1).

### Limitations

- **Sentry could not be read** from this machine (no CLI or token): what reached Craig is
  established from the code, Railway logs and `job_runs` only.
- **Supabase's egress figure** is dashboard-only; DS328-05 is an estimate.
- **No restore was attempted:** there is no target database, and a restore is a write.
- **Database-backed tests skip locally** (522 skipped); CI's 2,721 passed, 0 skipped, was read.
- **The steerability probe is one sample per ask** ($0.19); no plan offer has ever been made
  in production, and the extractor has never run.
- Four primary sources were read as abstracts only (R5), and the IOC 2022, ESC 2020 and WHO
  2018 full texts were unreachable (R6).
- __UXLIMIT__

---

## f. Zero-code decisions for Craig

1. **Sat 10 Oct's ride.** *Recommend:* tell Mark that if today's call says the sweet spot,
   Edit on Saturday's card rebuilds it from the plan. *Cost:* one message. Leaving it costs
   him a sweet spot and leaves Home and Zwift disagreeing.
2. **The public repo.** *Recommend:* the fixture swap now as a test-only PR (an exception to
   "nothing before 21 Oct": no behaviour changes), then make the repo private (about
   $11–17 a month), then decide on a history rewrite. *Cost:* 1 h, then the monthly minutes.
3. **W2 before 12 Oct?** *Recommend:* yes, as a caution-only exception: the builder opens to
   Mark on 12 Oct and an over-dosed VO₂ session could reach Zwift from 27 Oct. *Cost:* about
   1–1.5 days of build, signed-off words for the fixed caution lines. If no: tell Mark not to
   edit VO₂ sessions until 21 Oct.
4. **The Sentry rule, the Hive variables and GitHub's guards.** *Recommend:* all three now
   (console only). *Cost:* about 15 minutes; nothing Mark sees.
5. **Whether a chest-or-heart report should also alert Craig.** *Recommend:* ask Mark; it
   needs his consent. *Cost:* one conversation, then a small change in W6.
6. **Tell Mark to move, not ease, the ramp test on a tired morning.** *Recommend:* yes, before
   20 Oct. *Cost:* one message.
7. **Watch workouts and Dumbbells A's day.** *Recommend:* tell Mark to set A and B up on his
   watch and to consider moving A off Monday 19 Oct. *Cost:* one message, 15 minutes for him.
8. **His FTP after the test.** *Recommend:* Craig writes it to the profile when Mark reports
   it, before Thu 22 Oct. *Cost:* one production write.
9. **Widen the symptom question before 21 Oct?** *Recommend:* yes (caution-only web copy;
   words for sign-off). *Cost:* an hour.
10. **The REM experiment may post "supported" before its guard lands.** *Recommend:* let it
    wait for 320; if it posts, 320 corrects it. *Cost:* one possibly misleading line to Mark.
11. **Insert W3 (the swap fix) straight after the trial addendum, ahead of 316?**
    *Recommend:* yes: it is live, recurs whenever he approves then swaps, and touches no rule
    of the call. *Cost:* about a day, before 316.
12. **Close parked 208** (its premise has gone). *Recommend:* yes. *Cost:* none.
13. **319's shape:** lead with the FTP write-back and move it ahead of 317. *Recommend:* yes.
    *Cost:* reorders G8.
14. **The settled decisions listed under "For reconsideration".** *Recommend:* take each
    amendment as its package lands. *Cost:* none until then.

---

## g. Draft ledger rows (written to the ledger only after Craig's go)

Batch numbers below are proposals; they are assigned when the rows are written. `DECISIONS.md`
numbers are assigned at `/batch-start`.

| Batch | Tier | Status | Phases | Goal | Acceptance criteria |
|---|---|---|---|---|---|
| Batch 334 — Plan No. 3's protections hold | 🔴 High | Planned | 334.1 A per-session VO₂ dose bound in `plan_changes` and the interval editor; the change's words state the total (CI330-01). 334.2 A change that removes or hollows out the ramp test, a VO₂ session or a recovery week carries fixed caution words on the offer card and the hand confirmation (CI330-04, AI329-02). 334.3 At accept, an "as proposed → your plan" diff of the test, the VO₂ count and the recovery weeks' load, shown to Mark and sent as an `admin_alert` (CI330-04). 334.4 A test session's morning actions are "as planned" or "move it" (CI330-03). 334.5 Words for Craig's sign-off; tests confirmed to fail first. | Mark can still change anything, but no change makes a session unsafe, and Craig sees what was removed. | R4's 180-minute session refused; a removal shows the fixed words; the accept diff reaches Sentry; an Amber ramp-test morning offers a move. Adds caution only. |
| Batch 335 — The ride on Zwift is the ride he is told | 🔴 High | Planned | 335.1 A swap or move re-pushes the moved session's baseline when its live content is a morning transform; Mark's own edits still move (CR327-01). 335.2 `approve_adjustment` marks the consumed proposal `approved`, not `pushed`. 335.3 A daily job compares each pushed event with its plan row and that morning's action (`_proposal_content_matches_workout`), re-pushes a stale one and logs an `admin_alert`. 335.4 Tests: approve-then-swap; the 2 Aug and 10 Oct shapes. | What Home, the brief and Zwift say about a day is one ride. | The 10 Oct sequence replayed ends with Saturday's plan content on Zwift; the daily check finds no stale event in production after the deploy. |
| Batch 336 — The ramp test sets his FTP | 🔴 High | Planned (or 319.0) | 336.1 After a ramp test, Home offers the new FTP (computed from the best minute) in one tap. 336.2 The profile FTP, every target and every grade follow; Zwift's setting is named in the words. 336.3 Tests over a ±7% change. | A test result changes what he is asked for and how he is graded. | A ±7% FTP change no longer makes an ERG-perfect interval read under or over. |
| Batch 337 — A failure reaches Craig | 🔴 High | Planned | 337.1 Every operator `log.error` through `admin_alert`, one kind each, stable fingerprint (DS328-01). 337.2 The crons fixed or deleted; `ledger-freshness` on its own clock; `/api/v1/health` reports the newest `job_runs` age (DS328-02). 337.3 CR327-02's two handlers hoisted, with a real-session guard. 337.4 A weekly archive-integrity drill and an off-site copy (DS328-11). 337.5 Railway waits for CI; a `main` ruleset (DS328-10). 337.6 Freshness by ancestry, Vercel included (DS328-06, CR327-07). 337.7 Misfire grace; docs-only commits do not redeploy (DS328-08). 337.8 The Hive password fallback removed (DS328-03). 337.9 The cron runbook corrected. | When something breaks, Craig hears once a day until it is fixed, and a stopped scheduler is visible. | One induced failure of each kind emails Craig; the freshness check turns red on a stalled scheduler; the archive drill passes. Hosting changes on Craig's go. |
| Batch 338 — The repo carries nobody's data | 🔴 High | Decision-gated | 338.1 Synthetic values in the Hive fixture. 338.2 The eval's real notes moved private (#368). 338.3 Craig's choice of private, rewrite or both. | Nothing in public identifies Mark's household or carries his health data. | A scan of the tree for the identity fields and real notes finds nothing; the chosen option done. |
| Batch 339 — A symptom anywhere reaches a floor | 🟢 Mid | Planned | 339.1 The question widened (if not done before 21 Oct). 339.2 The post-ride read and the coach carry the chest-or-heart rule. 339.3 A neutral call and recovery-dose strength while a chest follow-up is open (HS332-05). 339.4 A high-side HRV check (HS332-06); respiration's own line (HS332-07); "a low reading" (HS332-08); a failed note re-read (HS332-10). | A chest symptom mentioned after a ride, or in chat, is treated as one mentioned in the morning. | Probes: a post-ride chest note sets the floor the next morning; the day after a chest report reads neutral. |
| Batch 340 — Strength he can do and the app can see | 🟢 Mid | Planned | 340.1 A and B delivered to his watch or as text workouts (FC331-01). 340.2 Placement: no loaded legs the day before VO₂ or a test (FC331-03); sessions sized to their rests (FC331-04). 340.3 A bone-loading element (FC331-05). 340.4 The post-strength read sees load (FC331-06); his own routines kept (FC331-07). | The strength Plan No. 3 prescribes reaches him and is recorded. | A and B on his watch; Monday's activity matched only when it is A. |
| Batch 341 — Smaller and cheaper | 🟢 Mid | Planned | 341.1 `job_loop` for the scheduler's loops; eval modules out of `services/` (CR327-04). 341.2 A lock on the plan draft (CR327-05); `none_as_null` (CR327-06). 341.3 Backup split, running egress total (DS328-05). 341.4 The holiday-week review (DS328-07); dev-tool bumps (DS328-09). 341.5 AI329-04…07. | Less code to change and less egress. | Egress meter's month total within 10% of Supabase's; no behaviour change elsewhere. |
| __UXROWS__ | | | | | |

**Amendments to queued rows** (made at their `/batch-start`): 308 (resized; the graded
prompt written out first; the cron tidy-up), 311 (the resting-HR rail; 8 Oct), 317
(`rulesInForce`), 318 (every Mark-facing read; post-workout v19; REM framing; the alert
shape), 319 (decayed: lead with the FTP write-back or point at 336; CI330-03), 320
(HS332-02's guard; HS332-04's floor), 321 (FC331-02's line; CI330-08; references), 322
(the version actually pushed; strength's top weight; the drift baseline), 208 (close), 210
(references; the third site).

**Grouping for `/batch-group`, after Craig's go:** G9a (before 12 Oct, only if decision 3 is
yes): 334. G9b (from 21 Oct, after the trial addendum): 335 → 337 → 336 (or 319 moved up),
beside G8. G9c (after G8): 339, 340, 338's code half, 341, then UX.
