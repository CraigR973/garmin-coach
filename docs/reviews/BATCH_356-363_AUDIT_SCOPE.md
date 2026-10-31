# Batches 356–363 — full-app review (wave #6)

**Opened 31 Oct 2026 (about 01:00 GMT).** Scope, decisions and guardrails agreed with Craig
before any pass ran. The sixth full-app wave; the last was wave #5 (Batches 327–333, 7–10 Oct,
at `42a6a98`). No delta review ran in between.

Reviewed SHA: **`083e012`** (`docs: close out Batch 341`). Production's `/api/v1/health`
reports it on Railway direct and on the Vercel proxy; the web returns 200. No PR is open.
Since wave #5: 105 commits, 48 of them code (Batches 334–355 and the G8 run); migrations
`038`–`041`; service modules 131 → 150; app source +12,900 / −2,718 lines; eight prompts
re-versioned (morning v58 → v65, chat v20 → v30, weekly review v11 → v14, post-ride
v18 → v19, strength v7 → v8, memory read v3 → v4, insights v2 → v4, experiment evaluation
v1 → v2); the rule ladder, its prompt and the engine switch deleted (Batch 308).

**Why a full panel, not a delta:** the delta procedure escalates when the change touched the
core decision's rules, and 8 of the 48 code changes did (Batches 308, 311, 316, 317, 321, 336,
339, 343); Craig asked for a thorough review "as a world class cycling/fitness coach and AI
engineer", to make sure everything works as expected and the product is optimal.

## The app, in one screen

- **User and job.** Mark, Craig's father, a masters cyclist who trains indoors on Zwift with
  dumbbell strength at home. One user; Craig operates it. The app is his private coach: a
  morning call on what to ride, a read after each session, a weekly review, a chat, a block
  training plan (Plan No. 3, and the next plan built from it), and his bedroom temperature.
- **Core decision.** The daily call: the graded verdict engine (the only engine since Batch
  308) with acute rails (HRV, resting HR), floors (a symptom anywhere, the chest or heart
  follow-up, poor readiness) and a session action (as planned, eased, held, moved, swapped,
  rest). It also offers his FTP after a ramp test and drafts the next plan.
- **What it changes outside itself.** Zwift workouts through intervals.icu; strength workouts on
  his Garmin calendar; the Dreo bedroom fan; web push to his Android phone; his FTP (one tap).
- **Data.** Garmin sleep, HRV, resting HR, readiness and activities; Hive room temperature;
  weather; his check-ins (blood pressure, symptoms, notes, feel); chat; supplements; his home
  coordinates. Health data, and the repository is public.
- **Models.** Claude Sonnet 5 on about a dozen paths (the morning brief, chat, the post-ride
  and strength reads, the weekly review, the nightly memory read, the notes reader, trends, the
  monthly analysis). Code decides the call; the model explains it, and the brief is checked
  deterministically since Batch 318.
- **Where it runs.** Railway (the API with its in-process scheduler, plus two crons), Vercel
  (the PWA), Supabase on the free plan (195 of 500 MB on 31 Oct).
- **What has gone wrong before.** Wave #5 graded honesty C+ and noticing a failure D+; an eased
  ride travelled across three days (fixed by Batch 335); personal data in the public repo
  (DS328-04); Railway's 21 Oct security incident (keys rotated 24–25 Oct); the Hive outage of
  20–25 Oct; the Anthropic spend cap reached on 29 Oct; the first nightly memory read failed
  (29 Oct, fixed); the first v65 brief failed its own check (30 Oct).

## The panel

| Batch | Pass | Lens | Deliverable | Prefix | Model · effort |
|---|---|---|---|---|---|
| 356 | R1 | Code and architecture (senior software engineer) | `BATCH_356_CODE_REVIEW.md` | CR356 | Opus 5.5 · high |
| 357 | R2 | Data, security and ops (security and site-reliability engineer) | `BATCH_357_DATA_SECURITY_OPS_REVIEW.md` | DS357 | Opus 5.5 · high |
| 358 | R3 | AI and LLM engineering (AI engineer) | `BATCH_358_AI_ENGINEERING_REVIEW.md` | AI358 | Opus 5.5 · high |
| 359 | R4 | Coaching integrity (cycling coach for masters athletes) | `BATCH_359_COACHING_INTEGRITY_REFRESH.md` + summary block in `COACHING_INTEGRITY_AUDIT.md` | CI359 | Opus 5.5 · high |
| 360 | R5 | Strength and the whole athlete (strength and fitness coach) | `BATCH_360_FITNESS_REVIEW.md` | FC360 | Opus 5.5 · high |
| 361 | R6 | Sports medicine and sleep (sports-medicine doctor with a sleep scientist) | `BATCH_361_HEALTH_SCIENCE_REVIEW.md` | HS361 | Opus 5.5 · high |
| 362 | R7 | UX and the live app, with Mark's scorecard (product designer) | `BATCH_362_UX_LIVE_APP_REVIEW.md`, `BATCH_362_MARK_SCORECARD.md` | UX362 | Sonnet 5.5 · high |
| 363 | R8 | Statistics and measured effects (applied statistician) | `BATCH_363_STATISTICS_REVIEW.md` | ST363 | Opus 5.5 · high |

Synthesis afterwards into `BATCH_356-363_REMEDIATION_ROADMAP.md` and
`BATCH_356-363_FOLLOW_THROUGH.md` (Opus 5.5 · extra-high). Ledger rows only after Craig's go,
written from the roadmap.

**Why each lens is here:**
- **R1** — the ladder deleted, nine jobs moved onto one loop and +12,900 lines; only it reads
  structure, failure paths and test strength.
- **R2** — Railway's security incident, the Hive sign-in rework, the backup split and a new
  nightly paid job; only it asks whether a failure reaches Craig and whether a backup restores.
- **R3** — eight prompts re-versioned, the brief's own deterministic check, the nightly memory
  read that turns chat into stored context; only it reads prompts, evals and cost.
- **R4** — eight rule changes to the daily call, the FTP from a ramp test, the progress signal,
  the Zwift and Garmin delivery; the core decision, judged by the coach who would make it.
- **R5** — dumbbell sessions now reach his watch and legs stay off the day before VO₂ work;
  only it judges strength programming for a masters rider.
- **R6** — symptom floors widened, one usual HRV, tonight's advice, bedroom alerts; Mark's
  safety and the honesty of every health claim.
- **R7** — Home, Week, the memory asks and the FTP offer are all new; one story across
  screens, and Mark's scorecard. Runs last.
- **R8** — Craig's addition (31 Oct): every measured effect Mark is told (the REM experiment,
  tonight's advice as weak evidence, "ready for a little more", the driver correlations, the
  baselines) judged on its statistics. New lens in the shared catalogue.

**Considered and rejected:** privacy and data protection (inside R2: the public repo and the
data held); folding strength into R4 (offered; Craig kept eight passes).

## The five questions every pass answers in its lens

1. Is it correct and safe?
2. Is it honest with Mark: does what he reads match what the app decided and what his data shows?
3. Is it doing its job: helping him train, recover and sleep better?
4. Would a failure be noticed, by the app, by Craig and by Mark?
5. Can it be run and changed cheaply: complexity, cost, data, hosting?

For each: what optimal looks like, and the smallest set of changes that gets there. Where
something is already near-optimal, say so. No invented findings.

## Decisions at scoping (Craig, 31 Oct, about 01:00 GMT)

1. **Panel:** eight passes — the seven proposed plus a statistician.
2. **Production access:** read-only, unattended. Passes run with permissions bypassed so they
   never wait on Craig; only the guardrails below keep them read-only.
3. **Paid cap:** $2 for the whole review, Anthropic API, logged below.
4. **Batches 356–363 reserved**, one per pass. `DECISIONS.md` numbers are assigned at
   `/batch-start`, never by the review.
5. **The run:** sequential, one session at a time, started and checked by the session that ran
   this check-in (Craig: "run all these sequentially, using this session to orchestrate"),
   starting at once and running overnight.

## How it runs (this wave's variant of `docs/agent-commands/review-wave.md`)

Order: pack (Sonnet · high) → R1 → R2 → R3 → R6 → R4 (not before Sun 1 Nov 18:30 London, after
the first v14 weekly review at 18:00) → R8 → R5 → R7 → synthesis. Each step runs in its own app
worktree cut from `main`, so other work in the main checkout cannot change what a pass reads.
The state file, the pack and the reports live only in the main checkout's gitignored
`scratchpad/wave6/`. **Passes commit nothing:** the synthesis copies the reports into
`docs/reviews/` on this branch, adds the roadmap, the follow-through and the STATUS line, and
opens the PR, merged only on Craig's word. Between steps the orchestrator checks the result,
sends Craig a one-screen note, checks Claude usage (pause and ask above 80% of the week; wait
for the 5-hour reset above 85% of it) and starts the next step. A heartbeat every 3 hours
resumes a step stopped by a usage limit; the Mac is held awake for the run.

## Live constraints

- **No trial or freeze is running.** Nothing in the backlog is buildable without Craig.
- **Craig's call on tightening the v65 brief** waits on the 31 Oct and 1 Nov briefs and may land
  during the review. Passes judge `083e012` and note any drift; they do not chase it.
- **Scheduled read-only checks** run at 31 Oct 12:50 GMT and 1 Nov 18:25 (the loop, the memory
  read, the brief's own check, the split backup, the first v14 weekly review, the first full
  archive). They are not part of this review; passes may read their results.
- **Supabase free plan:** egress and the 500 MB cap; every read projected and windowed.
- **The repo is public:** Mark only in short phrases; nothing captured, extracted or
  screenshotted is committed.
- **Claude usage:** 9% of the week used at the start (resets Fri 6 Nov 02:00 GMT).

## Guardrails

- **Read-only.** No change to code, production data, Railway, Vercel, Supabase or Sentry; no
  write to Garmin, Hive, intervals.icu, Zwift or the Dreo fan; no push or message to Mark; no
  device token minted. Passes make no commit, push or branch switch anywhere.
- **Production SQL** through the Supabase MCP, `coach` schema, SELECT only, column-projected
  and windowed; never a large JSON column a pass will not read.
- **Probes in the deployed container or through `railway run`** open a READ ONLY transaction
  (asserting `SHOW transaction_read_only` is on) or roll back, with a `faulthandler` watchdog;
  afterwards nothing is left idle in a transaction.
- **Paid calls** only within the $2 cap; prefer stored `coach.analyses` rows and the free
  `count_tokens`; keys only inside Railway's environment, never printed; every call logged.
- **Evidence labels** on every finding: observed, computed, proved, implemented. A ledger row,
  close-out note or STATUS line is a claim, not evidence.
- **Settled decisions** cited by number under "For reconsideration"; queued and parked rows
  re-verified, not re-reported.
- **Fast lane:** a live defect hurting Mark goes to Craig at once with one recommended action;
  any fix is its own batch in its own session, never part of the review.

## Pre-review findings (31 Oct, 00:45–00:55 GMT, read-only)

- **P1 (observed) → R3.** The first v65 morning brief (30 Oct) failed its own deterministic
  check: the call ran past the 120-word cap and used a retired colour word. Known; Craig's call
  on tightening waits on the 31 Oct and 1 Nov briefs.
- **P2 (observed; a hypothesis) → R6, R7.** The bedroom alert was graded "critical" at 20.2 °C
  on 29 and 30 Oct and "warning" at 19.7–19.9 °C, and the evening nudge was "critical" on 27,
  28 and 29 Oct. Hypothesis: the 19.5 and 20 °C lines and the "critical" grade may overstate the
  evidence for an older sleeper (R6 checks the primary sources); a nightly "critical" is also an
  alert-fatigue question (R7).
- **P3 (observed) → R2.** The weekly restore drill last ran 25 Oct as "skipped" (not
  configured): no backup has ever been test-restored (wave #5's DS328-11).
- **P4 (observed) → R2.** Ten days of job history are healthy apart from the known Hive outage
  (failed polls until 25 Oct 20:02 UTC) and one degraded morning backstop (23 Oct); the job
  loop's first live runs (30 Oct 19:00 and 20:30) succeeded.
- **P5 (observed), context.** Database 195 of 500 MB; nothing idle in a transaction; Mark
  checked in every day for 14 days and chatted on 28 and 29 Oct; no symptom reported in 14 days.

## Paid-call log

| When (UTC) | Pass | Purpose | Model | Tokens in / out | Cost |
|---|---|---|---|---|---|
| — | — | none yet | — | — | $0 |
