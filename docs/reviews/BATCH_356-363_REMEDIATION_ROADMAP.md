# Batch 356–363 remediation roadmap (review wave #6)

**Synthesised 1 Nov 2026 from 20:45 GMT** from eight passes at `083e012` (production serves
`caae3c4`, which differs only in `STATUS.md`). Scope: [`BATCH_356-363_AUDIT_SCOPE.md`](BATCH_356-363_AUDIT_SCOPE.md).
Every earlier finding's fate: [`BATCH_356-363_FOLLOW_THROUGH.md`](BATCH_356-363_FOLLOW_THROUGH.md).

**Passes:** [356 code](BATCH_356_CODE_REVIEW.md) (7) · [357 ops](BATCH_357_DATA_SECURITY_OPS_REVIEW.md) (8) ·
[358 AI](BATCH_358_AI_ENGINEERING_REVIEW.md) (7) · [359 coaching](BATCH_359_COACHING_INTEGRITY_REFRESH.md) (5) ·
[360 strength](BATCH_360_FITNESS_REVIEW.md) (7) · [361 health](BATCH_361_HEALTH_SCIENCE_REVIEW.md) (6) ·
[362 UX](BATCH_362_UX_LIVE_APP_REVIEW.md) (10) + [Mark's scorecard](BATCH_362_MARK_SCORECARD.md) ·
[363 statistics](BATCH_363_STATISTICS_REVIEW.md) (9). **59 findings: 4 High, 10 Med-High, 26 Medium, 19 Low.**

**Evidence labels:** *observed* (production rows or logs), *computed* (a script over production
data), *proved* (the real function driven, or a test that fails when the fix is reverted),
*implemented* (read in the code). Every High and headline number was re-checked in synthesis:
read-only SQL, the code, and three passes' probes re-run (all matched exactly; §e).
**Spend:** ≈$0.33 of the $2 cap (R3 ≈$0.30, R5 ≈$0.03); synthesis $0. The repo is public:
Mark is quoted only in short phrases.

---

## a. The verdict

1. **The daily call is the best it has been, and safe.** Replay 31 of 31; 0 less cautious
   colours in 1,596,672 comparisons; 5 of 5 key sessions ridden in full since the ramp test
   (wave #5: 0 of 5).
2. **A morning with no overnight data gets no call at all.** 1 Nov: Garmin refused the login
   00:25–12:01 UTC; Home said "something went wrong while writing", Zwift kept the full 2-hour
   ride, the coach said ride as planned; he started riding six minutes before the brief.
3. **A failure still does not reach Craig.** The review found 1 Nov's outage, not the app; the
   watchdog has 0 rows ever; no backup has been restored (9 of 9 drills skipped).
4. **What Mark reads around the call over-claims:** a "critical" bedroom push most evenings
   from a 19:00 reading; legs sessions ticked done that were upper body; "ready for a little
   more" in a recovery week; a sleep "trend" a coin toss gives 63% of weeks; "median" again.
5. **Cheap and well tested** (≈$13–15 a month of Anthropic; 3,222 tests, 0 skipped), but the
   rollback-then-read defect is back a third time.

| Question | Grade (wave #5) | In one line |
|---|---|---|
| 1. Correct and safe? | **B+** (B) | Call and floors proved; no-data morning, outage-day symptoms, legs before VO₂ |
| 2. Honest with Mark? | **B−** (C+) | Zwift line fixed; strength, bedroom, progress and REM claims over-read |
| 3. Helping him get fitter? | **B** (C+) | Key sessions in full; strength not done as written; bedroom advice the wrong way |
| 4. Would a failure be noticed? | **D+** (D+) | 1 Nov raised no alert in 11½ hours; watchdog never ran; no restore |
| 5. Cheap to run and change? | **B** (B) | ≈$13–15 a month, 221 of 500 MB; god-modules and dead code grow |

| Pass | Grade (wave #5) | In one line |
|---|---|---|
| R1 Code (356) | **B+** (B) | 15 of 18 reverted fixes caught; one handler class back again |
| R2 Ops (357) | **C** (C+) | Perimeter sound; nothing outside the process watches it |
| R3 AI (358) | **B** (B) | Holds every protection when pushed; no call on a no-data morning |
| R4 Coaching (359) | **A−** (B+) | Replay 31/31; the progress note counts sprint rides |
| R5 Strength (360) | **C+** (C+) | Reaches his watch; never done as written, recorded as done |
| R6 Health (361) | **B** (B) | Floors A−; the bedroom push and REM bands overstate |
| R7 UX (362) | **B** (B−) | Failure words fixed; wrong cause on 1 Nov; 6.5 pushes a day |
| R8 Statistics (363) | **B−** (new) | Sound machinery; four claims Mark reads fail a noise test |

**Mark's scorecard, re-graded.** R7's grades were provisional. The synthesis adds the strength
record, the bedroom push and the weekly review's claims, all verified in production.

| As Mark sees it | R7 → final | Why |
|---|---|---|
| Right and safe | A− → **B+** | No caution on a no-data morning; 17 °C advice; legs before VO₂ |
| Honest with me | B → **B−** | A ticked done twice; "critical" nightly; "ready for more" |
| Helping me | B → **B−** | 0 of 4 dumbbell sessions as written; bedroom direction |
| Would I know if it broke | C+ → **C** | Words on every failure; the wrong cause on the commonest |
| Quick and easy | **A−** | Unchanged |
| **Overall** | B → **B−** | Same as 10 Oct: better screens, over-claiming words |

---

## b. Happening now, and before Tue 10 Nov

**Now: Garmin is back** (*observed*): token re-minted 12:01 UTC; every activity poll since has
succeeded (latest 20:35 UTC). Cause unconfirmed. A repeat would be silent again: it is filed
`inputs`, which never alerts, and the app re-uses the deployed token instead of keeping each
renewal.

**This week (recovery week, 2–8 Nov).** Tonight's review offered "a ramp test, or one small step
up" into it (CI359-02, *observed*). Tell Mark the recovery week wins. The note can fire again on
Sun 8 Nov, so 367.1 lands before then.

**Before Mon 9 Nov.** All 11 remaining Dumbbells A sessions sit the day before VO₂ (*observed*);
9 Nov's is "one weight up" before 2 × 12 at 130% in ERG. Move A to Thursdays through the app's
own move path before he puts that week on his watch (a moved row leaves the old one on his Garmin
calendar). Keep 2 Nov's light session.

**Before Tue 10 Nov** (first full VO₂ of the build; Thu 12 Nov sweet spot): 364 and 365's
watchdog and Garmin alert. Until then, one line to Mark: no brief by ride time → ride easy.

---

## c. How the app works now

```
 Garmin · Hive · Open-Meteo · intervals.icu · Dreo
   ▼
 APScheduler inside the api ── job_runs per run
   │ wake-check → check-in, or the 11:00 backstop
   ▼
 inputs ready? ─ no ─► nothing stored: no call,
   │ yes               full ride stays on Zwift ◄ 364
   ▼
 THE MORNING (code, stored before any paid call)
 floors → graded domains → call + action/session
   ├─► Claude writes the brief (v65, checked)
   └─► rail → Zwift; dumbbells → watch on tap
   ▼
 Home · brief · Week · chat · weekly review
 bedroom pushes from 19:00 · ≈6.5 pushes/day ◄ 366

 Operator: log.error → Sentry (rule unconfirmed);
 nothing outside the process watches   ◄ 365
 Backups beside the api, unencrypted,
 never restored                        ◄ 371
```

Each morning the app syncs his night, reads his check-in, applies the medical floors, grades
his domains against his own normal and stores one call with an action per session, all before
any paid call. Claude then writes the brief, which explains and is checked. The one hole is
upstream: if the night's data is missing, nothing after the gate runs.

| The docs say | The code does |
|---|---|
| Runbook: the crons are "durable external paths" | Neither has run a job: 48 of 49 rows start within 5 ms of the minute (the scheduler) |
| Batch 196: weekly restore drill, encrypted off-site copies | Drill skipped 9 of 9; archives unencrypted on the api's volume |
| Batch 291: admin alerts reach Craig | Rule unconfirmed; `inputs` failures never alert; Garmin refusal untagged |
| 321.2: missing data holds the call at Amber | Unreachable on a no-Garmin morning (0 of 132) |
| 340: Monday matched only when it is A | The matcher compares session names only |
| 320: an 18 °C floor on cooling advice | "Start pre-cooling toward 17C" sent 8 times to 28 Oct |

---

## d. Work packages

*Do now*: a new row, in this order. *Fold*: into a row in progress. *Decision*: Craig first (§f).
Rows 364–373 are proposals. Caution-only rows can ship and be corrected from Mark's reports
(Craig's 3 Oct rule); Mark-facing words need Craig's sign-off.

| # | Package | When |
|---|---|---|
| W0 | Craig's steps, no code (CI359-03, FC360-03) | This week |
| W1 · 364 | A no-data morning gets a call (5 findings, 4 Med-High) | Before 10 Nov |
| W2 · 365 | Craig hears when it breaks (both ops Highs) | Watchdog before 10 Nov |
| W3 · 366 | One honest bedroom push (High) | After W1 |
| W4 · 367 | Claims that pass a noise test | 367.1 before 8 Nov |
| W5 · 368 | Strength as he does it (High) | Matcher before 9 Nov |
| W6 · 369 | Plain brief, one REM yardstick | November |
| W7 · 370 | Health rules completed | November |
| W8 · 371 | Backups that restore | November |
| W9 · 372 | Home and check-in | November |
| W10 · 373 | Deletion residue | Any time |

**W0 — Craig's steps.** (1) Move Dumbbells A to Thursdays from 9 Nov, after the sweet spot
and 48 h before Saturday's sprints (FC360-03 = CI359-03, Medium, *observed*). (2) One message to
Mark: the recovery week stands whatever the review's last line says; no brief by ride time →
ride easy; Dumbbells A is the legs session, not his upper-body routine. (3) Ask Mark whether he
changed his Garmin password or had a Garmin security email.

**W1 · 364 — A morning with no data still gets a cautious call** *(caution-only; amends #300)*.
CI359-01, AI358-01, UX362-01, HS361-02 (Med-High ×4) and CI359-05. *Observed* 1 Nov: no stored
morning, so no call, no Zwift proposal and no caution on Home; the coach said ride as planned and
that checking in "may trigger that read" (he had). *Proved:* a symptom tapped that day starts no
follow-up, and a fever ends on the next morning's preselected "None". **Fix:** at the backstop
or a check-in with inputs missing, store a code-only morning through the existing 321.2 floor,
no paid brief: Amber "insufficient data", hard work a zone easier, a test moved, recovery-week
targets held, Zone 2 as planned with an easy start; stage 2 proposes the eased ride; Home's
`inputs` words say the watch data has not arrived and what to do if he rides first; the chat sees
the state; symptom chains seed from the check-in; fever gets a "gone?" question. About 2 days.

**W2 · 365 — Craig hears when it breaks** *(split out of 337)*. **DS357-01 (High, *observed*):**
12 Garmin polls refused (00:25–11:25 UTC), filed `inputs`, which never alerts (AI358-02); one
11:00 backstop run made 12 refused logins, so an auth outage hammers Garmin. **DS357-02 (High,
*observed*):** the watchdog has 0 rows ever; nothing polls `/health/ready`; 10 of about 70 error
sites carry `admin_alert`. **CR356-01 (Med-High, *proved*):** the backstop's step handler reads
`profile.id` after its rollback and raises instead of isolating the step (not seen firing).
**Fix:** a scheduled GitHub Action every 30 min reads `/health/ready` and a new read-only
`/health/jobs` (newest run per job, today's brief state, last Garmin and Hive result) and fails,
so GitHub emails Craig: no Sentry rule needed. A `source_auth` alert kind and an
`inputs_provider` reason; no retry of a refused token. Keep each renewed Garmin token and pin
`garminconnect` to 0.3 (decision 6). Hoist CR356-01; tests for 341's three untested reloads
(CR356-02); commit paid reads before the push (CR356-06); `failed_steps` in job counters
(DS357-06); Sentry frame locals off (DS357-05); misfire grace 900 s (DS357-07). About 2 days.

**W3 · 366 — One honest bedroom push** *(decision 4)*. **HS361-01 (High, *observed* + sources):**
"critical" on 13 of 25 evenings, 11 from the 19:00–19:30 reading; asleep, the room averaged
≥20 °C on 1 of those 13 nights; "toward 17C" pushed 8 times. Older sleepers sleep best at
20–25 °C (Baniassadi 2023); WHO's minimum is 18 °C. **ST363-01 (Med-High, *computed*):** the lever
shown to him is the best of about 40 scans, crosses zero with a multiplicity allowance, and
shows no link Sep–Nov (−0.14, −0.41 to +0.15). **UX362-02:** 162 pushes in 25 days, on/off
only. **Fix:** no `critical` for the room; judge the sleep window from 21:30; "keep it at or above
18 °C"; one bedroom push an evening; the lever only after a multiplicity allowance and within a
season; one ride nudge a day; a switch per kind. About 1.5 days.

**W4 · 367 — Progress and trend claims that pass a noise test.** **CI359-02 (Med-High,
*proved* + *observed*) with ST363-02:** the note counts a Zone 2 sprint ride as hard, and ERG
holds every target (55 of 55), so it means "three Greens"; shuffled mornings fire it as often
(P 0.53–0.57). **367.1, before Sun 8 Nov:** hold the note in recovery weeks and within 4 weeks of a
test; key sessions only (hours; adds caution). **367.2–.5:** a measure ERG cannot fix (RPE and
heart-rate drift at key-session power); "the plan's next step looks right"; a noise floor for
the review's sleep trend (ST363-09: half an SE called a rise) and for drift (ST363-03);
experiments judged at fixed points and stored (ST363-04); concurrent measures out (ST363-05);
"worthwhile", not "real, not noise" (ST363-06); ST363-08a/d. About 2 days.

**W5 · 368 — Strength he does, recorded as he does it.** **FC360-01 (High, *observed* +
*proved*):** A on 21 and 26 Oct is `completed` by his upper-body routine; the matcher reads names
only. *Synthesis caution:* all 7 of his bodyweight circuits record a SQUAT category, so match on
a hinge or lunge in a loaded session, not on SQUAT. **FC360-02 (Med-High, *observed*):** "one
weight up" (3 rows) with the 5 and 10 kg dumbbells the app knows; progress by variant, tempo and
reps, and the generator reads the kit. Also FC360-04 (circuits counted apart), FC360-05 = CI359-04
(off-the-bike floor → mobility, *proved* on 12,960 mornings), FC360-07 (watch audit; unschedule
on a move), UX362-08 (the watch button on Home). History stays. About 2 days.

**W6 · 369 — The brief and the review in plain words.** **AI358-03, ST363-08b/c, UX362-04:** 3 of
3 v65 calls failed their check (159, 126, 156 words) because the readiness paragraph sits inside
the call and choice days do not fit; "median" in 4 of 6 briefs since v60 and twice in the review,
after Mark asked about it twice. Pre-write the readiness sentence in plain figures (with his
point: still lower without the holiday), below the call, on change only; statistics words in the
check for briefs and reviews; one repair call on a miss (≈$0.01). **HS361-03, ST363-07, UX362-06:**
REM against a lab age band in 10 of 25 briefs, bands misquoted, a card that "misses" 80% of
nights by construction: one yardstick, his own. AI358-06: record thinking per eval case. About
1.5 days.

**W7 · 370 — Health rules completed** *(caution-only)*. HS361-04 (answers AI358-04, *proved*): the
memory filter passes 18 of 18 crafted health-dismissing statements; never store a health
attribution, route it to Craig. HS361-05: a 9-second heart-rate jump on the bike was read as
artefact; a ride check asks one neutral question. HS361-06: blood pressure has no rule; a
quarterly "any new medicines?". About 1.5 days; pair with 339.5 if Mark consents.

**W8 · 371 — Backups that restore, no spare secrets.** DS357-04 (Med-High): archives of his whole
health record, unencrypted, on the breached platform, never restored: encrypt to an off-platform
key, copy weekly off Railway, run the drill. DS357-03 (Med-High, *computed*): both crons hold every
secret and run nothing: delete them (amends #266). DS357-08: one revoke. About 1 day + your steps.

**W9 · 372 — Home and check-in.** UX362-03 (the tired-morning pick hidden, then doubled: one
control at once, the default said; amends Batch 96's hide-until-read), UX362-05 (seven check-in
asks), UX362-07 ("Done" after the ride), UX362-09 ("No plan loaded"), UX362-10. About 1.5 days.

**W10 · 373 — Deletion residue.** CR356-05 (507 dead lines, `liveOrigin`, ladder branches),
CR356-07 (`none_as_null`, plus a class test). An hour.

**Fold into 345:** delete both source-checked cut paths (CR356-03 = AI358-05; 0 uses in 37
answers); the pass-on claim needs the Sentry rule (AI358-07). **Defer CR356-04** (god-modules):
split when a batch next edits the packet builder or a job. **Still open from wave #5, not placed:**
AI329-01 (the chat cannot see rules checked and not met); 364 gives it the morning's state only.

| Queued row | Re-verified |
|---|---|
| 337 (deferred, #451) | Decayed: crons "crash" → never run; 337.3 is CR356-01. Split into 365 and 371; Sentry rule, ruleset, digest later |
| 338 (decision-gated) | Accurate; nothing done; this PR adds nine reports describing his health in prose |
| 345 (in progress) | Takes CR356-03, AI358-05, AI358-07 |
| 209 (deferred) | Accurate: 32 tables, RLS on, 0 FORCE |
| "Tighten v65" ask | Premise decayed: both misses explained → 369 |
| Garmin hardening card | Folded into 365 |

---

## e. Coverage, re-verification, guards, open questions

| Pass | n | Where they go |
|---|---|---|
| R1 356 | 7 | 01, 02, 06 → 365 · 05, 07 → 373 · 03 → 345 · 04 deferred |
| R2 357 | 8 | 01, 02, 05, 06, 07 → 365 · 03, 04, 08 → 371 (03 on your go) |
| R3 358 | 7 | 01 → 364 · 02 → 365 · 03, 06 → 369 · 04 → 370 · 05, 07 → 345 |
| R4 359 | 5 | 01, 05 → 364 · 02 → 367 · 03 → W0 · 04 → 368 |
| R5 360 | 7 | 01, 02, 04, 05, 07 → 368 · 03 → W0 · 06 decision 2 |
| R6 361 | 6 | 01 → 366 · 02 → 364 · 03 → 369 · 04, 05, 06 → 370 |
| R7 362 | 10 | 01 → 364 · 02 → 366 · 04, 06 → 369 · 08 → 368 · 03, 05, 07, 09, 10 → 372 |
| R8 363 | 9 | 01 → 366 · 07, 08b/c → 369 · 02–06, 08a/d, 09 → 367 |

**59 findings:** 53 do now (two by Craig's hand in W0), 3 fold into 345, 2 decision-gated, 1
deferred. Only 345 takes folds: wave #5's folds into queued rows lost three findings.

| Headline number | What it counts | Synthesis check |
|---|---|---|
| 1,596,672 / 865 | All 865 less cautious actions are the light-week exception (#373) | Probe re-run: identical |
| 13 of 25 "critical" | 13 evenings, rule `peak_20c`, 11 at 19:00–19:30 | SQL: identical; ≥20 °C asleep 1 of 13 |
| 161 pushes | Push rows 7–31 Oct, each sent once; 7 from the Hive outage | SQL: **162** |
| 156 v 97 words | The check counts the call plus the paragraph under it; R7 the call alone | Both right |
| P 0.55, 63%, −0.14 | Progress note, sleep trend, autumn bedroom link on shuffled or home data | Probes re-run: identical |
| ≈$13–15 a month | Analyses 2–31 Oct ≈$8.50 at list rates + chat ≈$0.10–0.14 an answer | SQL |

**Conflicts settled** (*observed*). R4's "call before he rode" is wrong: the ride started 11:59:37
UTC, the brief was ready 12:05:39. R4's lead on 31 Oct's Dumbbells B: the 1 Nov 08:53 activity is
his bodyweight circuit, rightly refused for B, so the review's "still planned" is right (asking
him to confirm it is needless). R6's shape for the memory filter wins over R3's word list. Tue
3 Nov is a recovery-week VO₂ Light (R4 corrects R3); the exposure is 10 and 12 Nov.

**Follow-through.** Wave #5's 60 after the passes' corrections: **34 fixed, 13 partly, 1
shipped differently, 12 open** (the ledger implied 47 fixed). Earlier Highs still open: alerts
(DS328-01), restore (DS328-11), repo data (DS328-04), and the bedroom thresholds, now High.

**Guards** (standing checks, so the next review need not rediscover these):

| Guard | Catches | Where it runs |
|---|---|---|
| Readiness, newest job, brief state, source auth | DS357-01/02 | GitHub Actions, every 30 min |
| `source_auth` alert, daily while it lasts | Garmin or Hive refusal | App → Sentry rule |
| Rollback-then-read scan | CR356-01's class | CI, every PR |
| Nullable JSONB is `none_as_null` | CR356-07's class | CI |
| Statistics words and band figures in the check | AI358-03, HS361-03 | App, each brief and review |
| Shuffle tests on progress, drift, trend, REM, levers | ST363, CI359-02 | CI, synthetic nights |
| No loaded legs the day before VO₂ or a test | FC360-03 | Daily app job → alert |
| Upper body or circuit never completes A | FC360-01 | CI fixture |
| ≤1 bedroom push an evening; pushes a day | HS361-01, UX362-02 | CI + weekly digest |
| A no-data morning stores an Amber call | CI359-01, HS361-02 | CI replay case |
| A backup restored in the last 8 days | DS357-04 | Weekly drill + watchdog |
| Spare secrets, GitHub guards, Sentry test | DS357-03, DS328-10 | Monthly delta checklist |

| Decision | Proposed amendment | Evidence |
|---|---|---|
| #300 no-data brief | Keep for the paid brief; store a code-only call | CI359-01, HS361-02 |
| #451 337 deferred | Split it; the watchdog needs no Sentry decision | DS357-01/02 |
| #266 cron as second runner | Delete the crons | DS357-03 |
| #459 progress note | Fix the session set and measure, not thresholds | CI359-02, ST363-02 |
| #454 HS332-04 left | The pushes do not feed the call; change them alone | HS361-01 |
| #457 rows not rewritten | A to Thursdays; hops from week 4 | FC360-03/06 |
| Batch 96 hide-until-read | Show a pick at once | UX362-03 |
| #431 interval-first levers | Add multiplicity and a season window | ST363-01 |

Holding: #322 (the briefs drift from it), #373 (all 865 flips), #440–#442 (right, unenforced).

**Hypotheses.** His FTP of 267 W may be conservative (a retest after 23–29 Nov settles it). A
Garmin token copied in the 21 Oct breach could have been renewed into one still live (old
refresh tokens survived renewal). Sentry may hold health text in frame locals. Chat v30's ≈27,000
characters of rules may fire outside their case.

**Limitations.** Nobody could read Sentry. Railway keeps logs about 7 days. The replay and test
suite were not re-run here (R4, R1 ran them). The paid probe is one sample per ask. R7 ran headless
on a mock, not his phone. Primary sources were read at abstract level.

---

## f. Decisions for Craig

1. **Go on the roadmap in this order:** 364 → 365 → 367.1 → 368 → 366 → 369 → 370 → 371 → 372
   → 373. *Recommend:* yes. *Cost:* about 14 build-days; your sign-off on Mark-facing words in
   364, 366, 367, 369, 370 and 372. Then `/review-wave rows`.
2. **Plan No. 3 edits** (reconsider #457): A to Thursdays from 9 Nov; two sets of low hops from
   week 4 (FC360-06). *Recommend:* yes, before Mon 9 Nov. *Cost:* 15 minutes; a plan write.
3. **One message to Mark this week** (W0). *Recommend:* yes. *Cost:* one message.
4. **The bedroom fix removes a false alarm, not caution** (your 3 Oct rule). *Recommend:* yes; no
   source supports 20 °C "critical" for an older sleeper with bedding. *Risk:* fewer warm-room
   nudges if wrong; one evening push stays.
5. **Split 337, and your console steps** (about 45 minutes; nothing Mark sees): the Sentry rule
   (event captured, tag `admin_alert`, email, 24 h throttle); GitHub's free guards; delete both
   Railway crons; a free restore database and an off-Railway home for the weekly archive.
   *Recommend:* all. GitHub guards:
   ```bash
   gh api -X PATCH repos/CraigR973/garmin-coach -f "security_and_analysis[secret_scanning][status]=enabled" -f "security_and_analysis[secret_scanning_push_protection][status]=enabled"
   ```
   ```bash
   gh api -X PUT repos/CraigR973/garmin-coach/vulnerability-alerts
   ```
6. **Keep each renewed Garmin token** (365, a credential change). *Recommend:* yes. *Cost:* half a
   day. *Risk:* a bug loses the token; the Railway value stays as a fallback.
7. **Dumbbells:** progress by variant and tempo within 5–10 kg, or buy adjustable dumbbells.
   *Recommend:* variants now; ask Mark about the purchase. *Cost:* plan content only.
8. **The public repo before merging this PR** (338): it adds nine reports describing his health in
   prose. *Recommend:* make the repo private first. *Cost:* wave #5 put it at about $11–17 a month
   in Actions minutes (not re-priced).
9. **Ask Mark whether a chest or heart report may alert you** (339.5, with 364's seeding).
   *Recommend:* ask. *Cost:* one conversation.
10. **Close the "tighten v65" ask through 369.** *Recommend:* yes; both misses are explained.

---

## g. Draft ledger rows (written to the ledger only after Craig's go)

Phases are each package's fix in §d, in the order written there. `DECISIONS.md` numbers are
assigned at `/batch-start`.

| Row | Tier | Acceptance |
|---|---|---|
| 364 No-data morning gets a call | 🔴 | 1 Nov replayed without Garmin stores Amber and eases a hard ride on Zwift; a chest tap on a no-brief day starts the next morning's follow-up |
| 365 Craig hears when it breaks | 🔴 | A forced Garmin refusal turns the check red within 30 min and alerts once; a stopped scheduler turns it red; the rollback scan finds 0 |
| 366 One honest bedroom push | 🔴 | 7–31 Oct replayed gives ≤1 bedroom push an evening and no `critical`; the lever is silent on Sep–Nov data |
| 367 Claims that pass a noise test | 🔴 | No note in a recovery week; shuffle tests hold each claim's false-firing rate under 10% |
| 368 Strength as he does it | 🔴 | The 21 and 26 Oct shapes do not complete A; the circuit never does; no "weight up" beyond his kit |
| 369 Plain brief, one REM yardstick | 🟢 | Replayed 28 Oct–1 Nov briefs pass the check with no statistics word; one REM range on every surface |
| 370 Health rules completed | 🟢 | R6's 25 statements route as specified; a crafted spike asks once; a crafted 185/115 sets the notice |
| 371 Backups that restore | 🔴 | The drill passes weekly; an archive is off Railway and encrypted; no service holds a secret it does not use |
| 372 Home and check-in | 🟢 | One control on a tired morning; REM asks only when issued; "No plan loaded" with something logged |
| 373 Deletion residue | 🟢 | Dead module and field gone; the class test passes |

**Amendments:** 337 split (keeps .1, .5, .6, .9, .10); 345 takes CR356-03, AI358-05, AI358-07.
