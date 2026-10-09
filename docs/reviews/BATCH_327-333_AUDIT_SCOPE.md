# Batch 327–333 — full-app audit wave (wave #5)

**Opened 2026-10-07 (night).** Scope, decisions and constraints agreed with Craig before
any pass ran. This is the fifth full-app wave; the previous four were Batches 153–156,
188–192, 211 and 236–241 (1 Sep, at `2178381`). Coaching integrity stands at **B+**
(moved down from A− at Batch 239).

Reviewed SHA: **`42a6a98`** (`docs: close out Batch 326`). Production's
`/api/v1/health` reports `42a6a98…` on Railway direct and on Vercel same-origin; the web
returns 200. No PR is open. Since wave #4: 101 squash-merged PRs (Batches 242–326),
migrations `031`–`037`, and 131 service modules (92 at wave #4).

## The seven passes

| Batch | Pass | Lens | Deliverable | Finding prefix |
|---|---|---|---|---|
| 327 | R1 Code and architecture | Senior software engineer | `BATCH_327_CODE_REVIEW.md` | CR327 |
| 328 | R2 Data, security and ops | Security and site-reliability engineer | `BATCH_328_DATA_SECURITY_OPS_REVIEW.md` | DS328 |
| 329 | R3 AI and LLM engineering | AI engineer | `BATCH_329_AI_ENGINEERING_REVIEW.md` | AI329 |
| 330 | R4 Coaching integrity (5th refresh) | Cycling coach for masters athletes | `BATCH_330_COACHING_INTEGRITY_REFRESH.md` + summary block in `COACHING_INTEGRITY_AUDIT.md` | CI330 |
| 331 | R5 Strength, mobility and the whole athlete | Strength and fitness coach | `BATCH_331_FITNESS_REVIEW.md` | FC331 |
| 332 | R6 Health, sleep and medical safety | Sports-medicine doctor with a sleep scientist | `BATCH_332_HEALTH_SCIENCE_REVIEW.md` | HS332 |
| 333 | R7 UX and the live app, plus Mark's scorecard | Product designer | `BATCH_333_UX_LIVE_APP_REVIEW.md`, `BATCH_333_MARK_SCORECARD.md` | UX333 |

Synthesis afterwards into `BATCH_327-333_REMEDIATION_ROADMAP.md`, in wave #4's format.
Ledger rows are authored from the roadmap, not from the passes, and only after Craig's go.

**Order.** R1, R2, R3 and R6 run together. R4, R5 and R7 start once R3 has reported (a
prompt defect and a coaching defect are often the same defect). One subagent per pass,
each writing its report to disk as it goes; the synthesis re-verifies every High and every
headline claim against production or the shipped code before it goes in.

## The five questions every pass answers in its lens

1. Is it correct and safe?
2. Is it honest with Mark: does what he reads match what the app decided and what his data shows?
3. Is it helping him get fitter, on and off the bike?
4. Would a failure be noticed, by the app, by Craig and by Mark?
5. Can it be run and changed cheaply: complexity, cost, data, hosting?

For each: what optimal looks like, and the smallest set of changes that gets there. Where
something is already near-optimal, say so. No invented findings.

## Decisions taken at scoping (Craig, 7 Oct)

1. **All seven passes.**
2. **Production access approved, read-only.** Supabase SQL through the MCP
   (column-projected, windowed); `railway run` only for read-only or rolled-back probes,
   each with a `faulthandler` watchdog; Railway logs.
3. **Anthropic spend cap: $2 for the whole wave.** Reserved for a handful of probes of
   whether Mark's own words can steer the coach into offering to cut protected work from
   Plan No. 3. Everything else uses stored `coach.analyses` rows and the free
   `count_tokens`. Every paid call is logged below.
4. **Batches 327–333 reserved.** `DECISIONS.md` numbers are assigned at `/batch-start`,
   never when authoring.
5. **Craig's 6 Oct delegation covers the G8 run, not this review.** Every decision here is his.

## Live constraints

- **The 7–20 Oct trial is running** (ladder against graded; STATUS, "The side-by-side").
  The G8 run resumes **Wed 21 Oct 12:00** (scheduled task) at the trial addendum.
- **Nothing recommended here lands before 21 Oct**, except a fix that only adds caution to
  a genuine safety gap, and for that Craig is asked first.
- **Order every recommendation around G8's queue** — 316 → 311 → 308 → 317 → 318 → 321 →
  319 → 320 → 322 — and the parked 208, 209, 210 and 276. Where a queued row already covers
  a problem, the pass re-verifies the row against the code (`docs/agent-commands/batch-start.md`
  step 4) and says whether it has decayed, instead of reporting the problem again.
- **Plan No. 3** (Mon 19 Oct – Sun 17 Jan) is drafted and waits for Mark. Home asks him
  from Mon 12 Oct. If he declines or has not decided by 19 Oct, Home reads "No session
  planned" from 19 Oct. Its ramp test is Tue 20 Oct (ERG on).
- **intervals.icu** pauses a free account 90 days after the last website login; the next
  pause falls on 5 Jan (week 12 of Plan No. 3) unless Craig logs in again or takes Supporter.
- **Supabase free plan:** 500 MB database-size limit (measured on the sum over every
  database), 5.5 GB egress a month, no managed backups. The repo is **public**.

## Guardrails

- **Read-only.** No change to code, production data, Railway, Vercel, Supabase or Sentry.
  No device token is minted (that is a production write). Nothing is sent to Mark. If a step
  would write anywhere other than this report branch, stop and ask Craig.
- **Settled decisions are not re-litigated.** A pass that disagrees cites the `DECISIONS.md`
  number and the new evidence under "For reconsideration".
- **Evidence labels**, as in `COACHING_INTEGRITY_AUDIT.md`: `observed` (seen in production
  data or logs), `computed` (derived from production data by a script), `proved` (the real
  function driven with crafted inputs, or a test that fails when the fix is reverted),
  `implemented` (read in the code). Unverified ideas go under "Hypotheses". A ledger row,
  close-out note or STATUS line is a claim, not evidence: every headline number is
  re-derived from production or by running the shipped code.
- **The repo is public.** Mark is quoted only in short phrases, where his exact words
  matter. No screenshots, page captures or data extracts are committed: they stay in the
  gitignored `scratchpad/` and are described in the reports.
- **Production SQL:** tables live in the `coach` schema (`public` holds an unrelated app).
  Check-ins are `manual_entries` (several a day; use the one each morning actually used).
  Timestamp column names vary (`created_utc`, `created_at`, `entry_at_utc`,
  `generated_at_utc`, `started_at_utc`): check `information_schema.columns`.
- **No local Postgres:** DB tests skip locally. Quote the skip count and read CI logs.
- **Probes drive the real functions** from scratch scripts outside the repo; the logic is
  never re-implemented. A revert-the-fix test runs in a throwaway clone outside the shared
  checkout.
- **Physiological claims** endorsed or challenged cite primary sources that were read, and
  say where the evidence is weak or contested.
- **Other sessions share this checkout.** `git rev-parse --abbrev-ref HEAD` before every
  commit. There is no `jq`; use `gh --jq`.

## Pre-review findings — logged before any pass, because they gate several

All observed in production on 7 Oct, 22:30–23:40 UTC.

1. **The storage meter sat at critical for 35 days and nobody acted until a review
   looked** (observed, `coach.job_runs`; implemented, `scheduler.py` egress-budget job).
   `storage_stage_ordinal` read 2 (critical, ≥ 90% of 500 MB) on every `egress-budget` run
   from 2 Sep to 7 Oct 08:09 UTC, 3,333 runs marked `degraded`. The job logs
   `operator storage alert` at error level once per UTC day (it compares against today's
   earlier runs only). Batch 325's close-out says the alert "fired every morning since
   27 Sep"; the counters say since 2 Sep. Either Sentry was not receiving it until late
   September, or it was and a repeating issue did not notify. **Seeded into R2 as its
   first lead** (what reaches Craig, for each failure class).
2. **No backup has ever been restored** (observed). `backup-drill` ran 5 times since
   6 Sep and skipped every time with `not_configured`. The nightly `backup` job succeeded
   37 of 37. Seeded into R2.
3. **The coach cannot see what the app's own rules now do** (observed,
   `coach.brief_messages`, 7 Oct 17:27 UTC). Mark asked whether his holiday-return concern
   had been "factored in now", since Craig had said he made code changes. The coach replied
   that nothing it held documented such a change and it could not confirm it. Batch 310's
   holiday catch-up has been live since 5 Oct. Seeded into R3 and R4 (honesty, and what the
   coach's context carries about the rules).
4. **Plan No. 3 is untouched and undecided** (observed, `coach.knowledge_base`):
   `generated_block` v2 active, `status` draft, revision 0, no changes, start 19 Oct.
5. **Today, 7 Oct** (observed): the stored call is "As planned" with "Some fatigue"
   (graded engine, Amber, a training day); the planned 60-minute Zone 2 was pushed on
   11 Jul and not adjusted; he rode 60 minutes indoors at 175 W average at 13:56 UTC (his
   Zwift folder was missing that day); a post-ride read was written. 8 Oct is the W12
   Sweet Spot, pushed unadjusted on 11 Jul.
6. **Database size:** 164 MB this database, 179 MB summed over every database
   (187,330,737 bytes on the meter's last run), against the 500 MB limit (observed).
7. **Sentry cannot be read from this machine** (no CLI, no token). What reaches Craig is
   established from the code, Railway logs and `job_runs`. STATUS still lists the
   `admin_alert` rule as Craig's to create.

**Resumed 9 Oct.** A usage limit stopped every pass on 7 Oct before any finding was written;
the passes were relaunched on 9 Oct against the same SHA (production still serves `42a6a98`).
Live state since (observed): **8 Oct** was graded Red, "Recovery day" / "Still recovering", on
a training day; at 10:07 UTC an eased Sweet Spot was pushed for 8 Oct *and* the 10 Oct Sweet
Spot was pushed carrying `adjustment.verdict` Red, beside an unadjusted "Easy Z2" for 8 Oct; he
rode 45 minutes at 178 W that morning. **9 Oct** is a rest day ("Some fatigue"). The
`intervals-rail` job reads `ok` (rail state 0) on every run since 326 shipped. The 8 Oct
deliveries are seeded into R4 (what reaches the trainer against what Home shows).

Also recorded: job failures since 1 Sep — `activity-poll` failed 4 times (27 Sep ×3,
29 Sep), `morning-sync` degraded 3 times (3 Sep, 26 Sep, 2 Oct), `wake-check` degraded 3
times, `longitudinal-analysis` degraded once (4 Oct, the save bug fixed in PR #358);
`weekly-review` skipped 27 Sep and 4 Oct (`holiday_away`).

## The follow-through table

Every wave #4 finding (99) and every finding of the reviews since, with its disposition
(fixed, open, shipped differently, superseded, dropped, deferred, accepted, queued), is
built in the scratchpad and re-verified by the pass that owns its area. The merged table
is in the roadmap.

## Paid-call log

| When (UTC) | Pass | Purpose | Model | Tokens in / out | Cost |
|---|---|---|---|---|---|
| — | — | — | — | — | $0.00 |
