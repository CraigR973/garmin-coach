# Batch 328 — Data, security and operations review (audit wave #5, R2)

**Date:** 9 Oct 2026
**Wave:** audit wave #5 (Batches 327–333), pass R2 — see `docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`
**Lens:** security and site-reliability engineer
**Mode:** read-only. No code, production row, Railway, Vercel, Supabase, Sentry or GitHub
setting was changed. Paid Anthropic budget for this pass: $0; spent: $0.
**Code baseline:** `42a6a98` (`docs: close out Batch 326`); production `/api/v1/health`
reported `42a6a98` on 9 Oct 22:1x UTC, web 200.
**Predecessor:** `BATCH_237_DATA_SECURITY_OPS_REVIEW.md` (1 Sep, 17 findings DS237-01..17).

*(In progress — sections are filled as the pass runs.)*

## 1. Summary

*(written last)*

## 2. What optimal looks like

*(written last)*

## 3. Findings

### 3.0 The failure chain, class by class (the first lead)

Re-traced from the code at `42a6a98` and `job_runs`; "tagged" means the event goes through
`admin_alert()` and carries `admin_alert=<kind>`. **Reaches Craig today:** "rule" = only once
Craig creates the planned Sentry rule (STATUS, Needs Craig 4); "default" = only if the Sentry
project's own default alerting emails him (unknown, §8), and then once per issue (DS328-01);
"no" = nothing is sent anywhere.

| Failure | Detected by | Reaches Craig today | What Mark sees |
|---|---|---|---|
| Garmin slow, 5xx, timeout, 429 | `activity-poll`/`wake-check`/`morning-sync` `log.exception` (untagged) + `job_runs` failed/degraded (4 + 3 + 3 since 1 Sep) | default | Brief later (11:00 backstop) or on thin data; "Garmin data missing" push in the evening |
| Garmin token expired (~mid-2027) | `garmin_reauth_required` `log.error` (untagged); Batch 267 refuses the password login off a TTY | default | As above, every day until re-minted |
| Hive refresh token expired | `hive temperature poll failed` (untagged) + `job_runs` failed | default | "Hive temperature stale" push; **and an SMS code every ~5 min to the account phone** (DS328-03) |
| Anthropic credit exhausted / spend-cap 400 | `anthropic_text` classifies both as `billing` → `admin_alert` kind `billing` (tagged) | rule | The call (graded before the brief since 302), "Writing your brief" → failure card with Try again |
| Anthropic timeout / 5xx | retried, then `generation_failure` (tagged) | rule | Same failure card |
| Malformed output (missing sections) | `morning_analysis_missing_required_sections` **warning** — below Sentry's event level | no | The malformed brief, as written |
| Empty output | `MorningAnalysisError` → `generation_failure` (tagged) | rule | Failure card |
| A scheduled job crashes | `run_tracked_job`: "escaped its result boundary" (untagged) + `job_runs` failed | default | Depends on the job |
| The in-process scheduler stops, API still up | **nothing** — the watchdog never runs, health has no scheduler field (DS328-02) | no | Missing brief, no rides reaching Zwift, no pushes |
| A Railway cron crashes | Railway marks the execution `CRASHED`; the process dies before Python (exec-form `if`) or before `init_sentry` (config) | no (Railway mail: §7) | Nothing (the in-process job does the work) |
| Database reaches 90% / 500 MB | `operator storage alert` once per UTC day (untagged); at 500 MB every write fails and each job logs its own error | default | At 500 MB: check-ins, briefs and syncs fail |
| Nightly backup fails | `operator backup alert` (untagged) + `audit_log` row + `job_runs` failed | default | Nothing |
| A backup cannot be restored | `backup-drill` skips `not_configured` and logs a **warning** (5 of 5 runs) | no | Nothing |
| intervals.icu paused (326) | `intervals-rail` → `delivery_rail` (tagged), 14 days ahead and on the day | rule | Home says rides are not reaching Zwift |
| Railway ahead of Vercel, or the reverse | `deploy-freshness` reads Railway twice (DS328-06) | no | Old web against a new API; a schema mismatch shows raw `ZodError` text (UX241-03, open) |
| Egress over the free cap | the meter books ~15 MB a night for ~146 MB (DS328-05) | no | Nothing until Supabase restricts |

**What reaches nobody today:** a stopped scheduler, an unrestorable backup, a malformed brief,
a crashed Railway cron, and real egress. Everything else reaches Craig only through Sentry,
and only the seven tagged kinds would be caught by the rule he has yet to create.

### DS328-01 — High — Craig's only alert route catches a minority of the failures that matter, and fires once per issue

**Evidence:** implemented (code), observed (Railway variables, `job_runs`), docs (Sentry).

- **The route.** Since Batch 291 (Decision #381) every operator alert is meant to reach Craig
  through Sentry, by one rule: "a new issue tagged `admin_alert`". `SENTRY_DSN_BACKEND` is set
  on all three Railway services (`api`, `weekly-review`, `trend-narratives`; names read with
  `railway variables --json`, values never printed). The rule itself is still Craig's console
  step (STATUS, Needs Craig 4), so today nothing is guaranteed to email him; whatever reaches
  him comes from the Sentry project's own default alerting, which this pass cannot read.
- **What the rule would catch.** `admin_alerts.KINDS` has seven tags: billing,
  generation_failure, longitudinal, cross_surface_disagreement, figure_contest,
  verdict_less_cautious, delivery_rail. **Every other operator signal is a plain `log.error`
  with no tag**, so the planned rule never sees it: `operator storage alert`
  (`scheduler._log_storage_operator_alert`), `operator egress alert`, `operator backup alert`
  (nightly backup failed, restore drill failed), `operator alert` (`_log_operator_alert`,
  e.g. `metric_baselines_stale`), `scheduled job ledger is stale` (the watchdog, which never
  runs — DS328-02), `scheduled job escaped its result boundary`, and every job's own
  `log.exception` (Hive poll, Garmin activity poll, morning sync, wake check, autopush,
  weekly review, state change, fan control).
- **"A new issue" fires once per issue.** Sentry's issue-alert triggers are "a new issue is
  created", "an issue escalates", "a resolved issue regresses", or "an event … is captured"
  (with a frequency filter); throttling is per issue (Sentry docs, *Issue alert
  configuration*). An alert that recurs into the same issue — the storage alert re-fired once
  per UTC day for 35 days — notifies on its first event only, unless the issue was resolved
  in between.
- **The message Sentry groups on is unstable.** structlog hands the standard-library record a
  dict (`ProcessorFormatter.wrap_for_formatter`), so Sentry's `logentry.message` is the dict's
  text including a microsecond `timestamp` and the per-day byte counts (proved: driving
  `configure_logging` + a capture handler with the real storage alert gives
  `type(record.msg) = dict` and a message beginning `{'kind': 'database_storage_critical',
  'all_databases_bytes': …, 'timestamp': '2026-10-09T…'}`). Sentry groups message-only events
  on "the message without any parameters" (Sentry docs, *Event grouping*); whether its
  server-side normalisation strips the timestamp and numbers is undocumented. Either every
  re-fire is one issue (one email ever) or every re-fire is a new issue (one email a day, and
  ungroupable noise). Neither is a designed behaviour.
- **What the 35-day storage episode tells us** (observed, `job_runs` daily maxima): critical
  from 2 Sep (452.8 MB) to 24 Sep; warning on 25 Sep after the purge (449.7 MB); critical
  again from 26 Sep (450.4 MB) to 7 Oct 08:09 (458.1 MB). Before 12 Sep there was no DSN; from
  12 to 24 Sep the Sentry organisation had no error quota (`429 error_usage_exceeded`,
  DECISIONS #329 / STATUS "quota is back" 24 Sep), so every event was dropped; from 24 Sep the
  `api` process's events could arrive. Craig acted on 7 Oct ("A Sentry storage alert this
  morning", STATUS). So the alert arrived at most 13 days after it could have, and 35 days
  after the condition began; this pass cannot tell whether earlier emails arrived and were
  read.

**What Craig experiences:** a storage, backup, egress, stale-scheduler, Hive or Garmin failure
reaches him only if Sentry's defaults happen to email him on that event, once.
**Fix (small):** (1) route every operator `log.error` through `admin_alert` with its own kind
(storage, egress, backup, backup_drill, ledger_stale, job_failed), about 8 call sites and a
test that greps for untagged operator events; (2) render a stable Sentry message (pass
`event` as the record message and the fields as `extra`, or set a fingerprint of
`["admin_alert", kind]` in `before_send`); (3) Craig's rule: **When** "an event is captured",
**If** tag `admin_alert` is set, **throttle** 24 hours — so each kind emails at most once a day
for as long as it keeps firing. Code ≈ half a day; the rule is a console step.
**Where:** after G8 (adds no caution to Mark's coaching). The console rule can be created any
time and should be, before 21 Oct.

### DS328-02 — Med-High — Nothing watches the scheduler: the watchdog has never run, and both "durable" Railway crons crash on every execution

**Evidence:** observed (`job_runs`, Railway executions), proved (config validation), implemented, docs (Railway).

- **The watchdog has never run.** `ledger-freshness` (Batch 242.5) is deliberately not on the
  in-process scheduler and needs "its own clock: a Railway cron service, or anything
  external" (`scheduled-jobs-cron.md`). No such service exists: `coach.job_runs` holds **0**
  `ledger-freshness` rows in its whole history (24,481 rows since 15 Aug).
- **The two Railway crons have never completed a run.** `weekly-review`: **18 of 18**
  executions `CRASHED` (9 Aug – 4 Oct), each 0.6–5.6 s. `trend-narratives`: **40 of 40**
  `CRASHED` (20 Sep – 9 Oct), 0.8–3.2 s. No `job_runs` row has ever come from either: every
  `weekly-review` and `trend-narratives` row starts at hh:mm:00.00x, the in-process
  APScheduler's signature, and the in-process scheduler registers both jobs
  (`create_scheduler`: `weekly_review_delivery`, `trend_narratives`). No log line from either
  container reaches Railway's log store.
- **Why (two independent defects).** (a) Both services' `startCommand` (in `.railway/railway.ts`)
  is shell syntax (`if [ "$(TZ=Europe/London date …)" = … ]; then …`). Railway runs a
  Dockerfile service's start command in exec form ("commands ran in exec form do not support
  variable expansion … wrap your command in a shell", Railway docs, *Build and start
  commands*), so there is no `if` to execute; the image's own `CMD` (which does wrap in
  `sh -c` and already has the London-time guard via `SCHEDULED_JOB`/`SCHEDULED_LONDON_HHMM`)
  is overridden. (b) Even if it ran, `trend-narratives` lacks `SUPABASE_SERVICE_KEY` and
  `FRONTEND_ORIGIN`: importing `src.run_scheduled` with exactly that service's variable names
  (dummy values) fails `Settings` validation — "Refusing to start with weak/missing secrets:
  supabase_service_key is empty; frontend_origin must not be empty…" — before `init_sentry()`
  runs, so Sentry would never hear of it (proved; `weekly-review`'s names import cleanly).
- **The runbook says the opposite.** `scheduled-jobs-cron.md` states "`weekly-review` and
  `trend-narratives` have durable external paths" and was "verified 2026-08-26"; the
  executions on 9, 16 and 23 Aug had already crashed.
- `/api/v1/health` returns `{status, sha}` only, and `/ready` checks the database; neither
  says whether the scheduler is alive.

**What it means:** if the `api` process's APScheduler stops while uvicorn keeps answering
(an exception in the scheduler thread, a wedged event loop), the hive poll, wake check,
backup, egress/storage meter, autopush to Zwift and evening alerts all stop with no signal to
anyone; Railway shows a healthy service and green health checks. Mark would notice first,
through a missing brief or a ride that never reached Zwift. Railway may also be emailing
Craig about ~16 crashed executions a week (hypothesis — see §7), which trains him to ignore
Railway mail.
**Fix (small, ~1–2 h, hosting change = Craig's go):** drop the two `startCommand`s (the image's
`CMD` already does the London-time guard), add `SUPABASE_SERVICE_KEY` and `FRONTEND_ORIGIN` to
`trend-narratives` or relax the validation for job runners, add a third cron service
`ledger-freshness` (`SCHEDULED_JOB=ledger-freshness`, every 2 h), and add a `scheduler`
liveness field to `/api/v1/health` (age of the newest `job_runs` row) so the existing
"Production deploy freshness" workflow or any free uptime monitor can alarm on it. Correct
the runbook. Or decide the crons are not wanted and delete them (the in-process scheduler
already runs both jobs) — but then the watchdog still needs a clock.
**Where:** before 21 Oct? No (no caution to Mark's coaching); first thing after G8, or folded
into 308's tidy-up. It is a hosting change, so Craig's.

### DS328-03 — Medium — An expired Hive refresh token would text an MFA code every 5 minutes, all day

**Evidence:** proved (real `HiveClient` + `retry_sync`, fake Cognito), observed (variable names).

`HiveClient.login` falls back to a full email/password login whenever the refresh-token
resume fails **and** `HIVE_EMAIL`/`HIVE_PASSWORD` are set. Both are set on the `api` service
(Decision #59 moved production to the refresh token; the password variables were never
removed). Cognito sends the SMS code when the password verifies, before returning the
`SMS_MFA` challenge the code then rejects. Driving the real `fetch_payloads` under the real
`retry_sync` with a refresh that fails and a password login that answers `SMS_MFA`: **3
refresh attempts and 3 password logins per poll** with the production variable shape; with
no password variables, 3 refreshes and **0** password logins. The poll runs every 15 minutes,
so a dead refresh token means up to 12 SMS codes an hour (288 a day) to the Hive account's
phone until someone acts — the same class as the Garmin MFA-email incident, which was closed
by deleting `GARMIN_EMAIL`/`GARMIN_PASSWORD`. The runbook (`sync-and-analysis.md`) still tells
the operator to fix a Hive auth error by updating `HIVE_EMAIL`/`HIVE_PASSWORD`.
What Craig sees: an untagged `hive temperature poll failed` (DS328-01). What Mark sees: a
"Hive temperature stale" push at evening alerts, and (if the account phone is his) a stream of
Hive codes. The refresh token's lifetime is not recorded anywhere; it has worked since June.
**Fix:** delete `HIVE_EMAIL` and `HIVE_PASSWORD` from the `api` service (a credential change,
Craig's), or make the fallback refuse when a token blob is configured (one line and a test);
correct the runbook. **Where:** the variable deletion any time Craig likes (it removes a
failure mode and touches no coaching); the code guard after G8.

### DS328-04 — High — The public repository holds a real household's home address, phone and email, and Mark's health record

**Evidence:** observed (git history, GitHub API), implemented. No image or value is reproduced here.

The repository has been public since 12 Jul, when it was made public to clear a GitHub
Actions billing block (STATUS log, 12 Jul); it is still public (`gh api … .visibility`),
0 forks, 0 stars. What a stranger can read today, at `HEAD`:

- **`apps/api/tests/fixtures/hive/getAll.json`** (committed 20 Jun, `e37582c`): an unredacted
  Hive account dump — the account holder's first and last name, street address and KA
  postcode, home coordinates to seven decimal places, email, a +44 phone number, and the
  hub's IP and MAC addresses. The holder's first name is not Mark's, so this is very
  probably a second person who never agreed to any of it. Two tests read the file.
- **118 app screenshots** in `docs/reviews/batch-156/`, `batch-192/`, `batch-241/screenshots/`
  (7 Jul – 2 Sep): Mark's name in the header, real dates, his sleep scores, HRV, readiness,
  REM %, VO₂max, age band and briefs (one viewed to confirm; described, not reproduced).
- **Data extracts:** 12 JSON app states in `docs/reviews/batch-241/`, the 39 KB verdict-replay
  fixture (84 HRV and 28 resting-HR values from real mornings), the notes-eval fixtures
  (56 of Mark's real check-in notes, committed on Craig's go, Decision #368), the 56 KB
  `predict-out.json` beside the 6 Oct review (196 HRV values), `plan_no2.json` (his plan),
  two root PDFs (integrity reports).
- **Prose:** `STATUS.md`, `DECISIONS.md`, the ledger and reviews name him (3,112 lines mention
  "Mark" across 414 files), his age, town (Kilmarnock and its lat/long in 22 files), his
  medication (vitamin D and fish oil, 8–9 files), symptom handling, HRV and sleep history.
  1,020 of the 1,223 commits touch those three files.
- **What a stranger learns:** who Mark is, where the household lives (to the house), a phone
  and email for the account holder, his age, daily health metrics since June, his training,
  his notes about how he feels, and what the app does when he reports chest symptoms.
- **Exposure so far:** GitHub traffic shows 1 page view in 14 days (Craig) and 3,997 clones
  by 687 unique cloners — almost all CI runners and Vercel/Railway builds, so this cannot
  separate a stranger's clone from our own. Public GitHub is routinely scraped; assume copies
  exist.

**Options priced (nothing changed):**

| Option | Cost | Does NOT fix |
|---|---|---|
| A. Make the repo private | Actions minutes: CI ≈ 11 billable min a run (7 jobs, measured on 8 runs) × 399 runs in Sep ≈ 4,400 min, plus ≈ 160 deploy-freshness runs ≈ 500 min → ≈ 4,900 min/month against 2,000 included (Free) or 3,000 (Pro); overage at $0.006/min ≈ **$17/month on Free, ≈ $11 + $4 on Pro** (GitHub docs, *GitHub Actions billing*). Craig's plan could not be read (`gh api user` returns no plan). Halving CI (one wave per PR, path filters) brings it near the free allowance. Vercel and Railway build from private GitHub repos on their current plans. | Copies already scraped or cloned; the data stays in history for anyone given access. |
| B. Rewrite history (`git filter-repo` on the fixture, screenshots, extracts, PDFs) | Every SHA after 20 Jun changes: 1,223 commits, 150 remote branches, and **1,308 backticked SHA citations** in DECISIONS/STATUS/ledger stop resolving. 373 PRs keep the old commits reachable through read-only `refs/pull/*` and cached views until **GitHub Support** dereferences them (GitHub docs, *Removing sensitive data*). Every clone (shared checkout, scratch clones, CI caches) must be re-cloned or it can push the data back. | The prose in STATUS/DECISIONS (cannot be filtered without gutting the decision log); forks (none today); copies already taken. |
| C. Both, plus stop adding | A + B, and a CI check that fails on new images or JSON under `docs/` and on fixture files carrying `address`/`phone`/`email` keys. | Copies already taken. |
| D. Minimum now | Delete `getAll.json`'s identity block in a normal commit (replace with synthetic values) and go private. ≈ 30 min + the Actions cost. | History, until B. |

**Fix and where:** D at once (it changes no app behaviour, no coaching, and removes a third
party's address from public view), then Craig decides B. The repo visibility is Craig's
setting; this is the one item here worth doing **before 21 Oct** (not a coaching change, so
the G8 hold does not bind it). See also §6 (Decision #368).

### DS328-05 — Medium — Our own housekeeping is probably most of the database egress, and the meter cannot see it

**Evidence:** computed (production aggregates, `pg_stat_statements` deltas), implemented.

The free plan allows 5.5 GB of egress a month per organisation. No other app's tables remain
in this project (0 `public` tables since the movie app moved to Neon, 24 Sep); whether other
projects share the organisation was not checked. Two drivers dominate, both ours:

1. **The nightly `pg_dump`.** It reads every `coach` table except `activity_timeseries`
   through the pooler as uncompressed `COPY` text; `--format=custom` compresses afterwards,
   inside `pg_dump`. The text size of the dumped tables today, summed server-side
   (`sum(octet_length(row::text))`): `sleep` 59.7 MB, `temperature_readings` 30.1 MB,
   `daily_metrics` 25.6 MB, `analyses` 15.2 MB, `activities` 6.8 MB, `job_runs` 6.4 MB, the
   rest ≈ 2.2 MB — **≈ 146 MB a night, ≈ 4.4 GB a month**, ~9.7× the 15.1 MB archive the
   meter books for it. `backup.py` still carries the comment DS237-03 showed false ("Custom
   format is compressed on the way out of the server"), and the meter adds only *today's*
   archive to the month, so earlier nights drop out of the month total altogether.
2. **The meter reading its own history.** Each 15-minute `egress-budget` run re-reads every
   `counters` row of the month so far (Batch 247's monthly comparison) — quadratic in the day
   of the month. Measured: that statement returned 47,382 rows in the 13.2 h between two
   `pg_stat_statements` snapshots on 9 Oct (day 9); counters average 218–232 bytes of JSON.
   September: ≈ 2,885²/2 ≈ 4.2 M rows ≈ **0.9–1.0 GB**, matching the statement's 4.76 M rows
   since the stats reset.
3. Everything Mark does is small beside these: HTTP responses were 77 MB in September
   (`http_response_bytes_month`); the 5-second brief polling is ~1–2 MB a morning (STATUS);
   the full-history temperature and fan reads (`temperature_readings` 10.5k rows and
   `fan_state_readings` 4.1k rows per call, no date window, a few calls a day) ≈ 0.5 MB each.

So September's egress was probably ≈ 5–5.5 GB — at or near the cap — almost all of it
backup and meter (the dump was smaller early in the month, so September itself sits at the
lower end). This is an estimate: wire-protocol overhead adds a little, and Supabase's
own figure is dashboard-only (§8). **What Craig should read:** Supabase → Organisation →
Usage → Egress, the daily bars for 1 Sep – 9 Oct; a step of roughly 0.15 GB at 03:00 UTC every
night confirms (1), a ramp through each month confirms (2).
**What happens at the cap:** on 4 Aug the restriction landed on the platform APIs, not the
pooler, so the app stayed up (DECISIONS #262); a repeated overage on the free plan is
Supabase's to act on (§7).
**Fix (≈ half a day, no migration):** (a) the meter keeps a running month total — read only
the newest row, or `select sum((counters->>'http_response_bytes_delta')::bigint)` server-side
(one number instead of thousands of rows); (b) the nightly dump becomes authored tables only
(analyses, check-ins, chat, plans, knowledge base, profiles, proposals — a few MB), with the
upstream-replayable raw payloads (`sleep`, `daily_metrics`, `activities`) dumped weekly,
cutting ≈ 4 GB a month; `temperature_readings` has no upstream and stays nightly, but its
`raw_payload` (≈ 2.8 KB a row) is the bulk and could be dropped after a week; (c) count the
backup at its uncompressed size and delete the false comment. **Where:** after G8; (a) is
safe to do any time.

### DS328-06 — Medium — The deploy check cannot see Vercel, and its only red results are false

**Evidence:** observed (GitHub Actions, headers, production history), implemented.

`deploy-freshness.yml` polls two endpoints, but Vercel's `/api/v1/health` is a rewrite to
Railway (`vercel.json`; the response carries `x-railway-edge`), so **both checks read
Railway's SHA**. Proof that this matters: on 1 Oct Vercel refused every build from 09:26
(Decision #369, `2dd88ab`'s production build failed), and the freshness run for that merge at
14:19 UTC passed. The same flaw sits in the close-out's production check ("health SHA + web
200": the web returns 200 from the previous build). Separately, **all 20 failures since 1 Sep
were false**: in each, both endpoints served a *newer* SHA than the one expected (checked with
`git merge-base --is-ancestor`), because a docs commit merged within 15 minutes of a code
commit. 20 of 200 runs is a 10% false-red rate, and a real stale deploy would look identical.
What Craig sees: a red X on `main` once every few merges that he has learned to ignore, and no
red at all when the web did not deploy. **Fix (≈ 1 h):** the web build writes `version.json`
with `VERCEL_GIT_COMMIT_SHA`; the monitor reads it for the Vercel half and treats a descendant
SHA as success. **Where:** after G8 (or with 308).

### DS328-07 — Low — A training week went without its review because the holiday started on its Sunday

**Evidence:** observed (`job_runs`, `analyses`, `activities`), implemented.

`run_weekly_review_delivery` skips a profile when *today* (the Sunday) is inside a holiday
window. On Sun 27 Sep the holiday had begun, so the review of 21–27 Sep was skipped
(`holiday_away`) though Mark recorded **17 activities** from 21 to 26 Sep; the 4 Oct skip
(a week wholly away) is the intended case. Stored `weekly_review` rows run to the week of
14 Sep; nothing reviewed 21–27 Sep, and nothing told him. **Fix:** skip only when the whole
week (or most of it) is inside the window; ≈ 1 h with a test. **Where:** after G8; low stakes.

### DS328-08 — Low — Daily jobs drop a missed run silently

**Evidence:** observed (`job_runs`), implemented.

Every daily cron job is registered with `coalesce=True` and APScheduler's default
`misfire_grace_time` (only `zwift_rail_check` sets 3,600 s), so a run whose minute passes
while the loop is busy or the container is restarting is dropped. Observed once since 1 Sep:
no `post-workout-backstop` on 27 Sep (a slow-Garmin day before Batch 312). 38 of 39 days
otherwise, and since 312 the loop has not been blocked. Backups, the baseline refresh and the
11:00 morning backstop share the exposure, and nothing would notice a skipped day (DS328-02).
**Fix:** `misfire_grace_time=3600` on the daily jobs (idempotent ones only) — a few lines.
**Where:** fold into whichever batch takes DS328-02.

### DS328-09 — Low — Dev tooling carries 47 advisories the gate never reads

**Evidence:** observed (`pnpm audit`, 9 Oct).

The CI gate runs `pnpm audit --prod` and passes today with its six reviewed exceptions
(re-run locally: "JS dependency audit passed"); `pip-audit` on the locked API requirements
finds nothing. Without `--prod`, `pnpm audit` lists 53 advisories, including two critical in
`tinypool` and one in `vitest` (UI server), and highs in `vite`, `ws`, `fast-uri`, `js-yaml`,
`brace-expansion`. They live in test and build tooling that runs on Craig's Mac and CI, not in
the shipped bundle, so the risk is to the developer machine, not to Mark. **Fix:** a dev-tool
bump batch (vitest, vite) when convenient; accept otherwise. **Where:** after G8.

## 4. Follow-through

Every wave #4 finding in this lens (DS237-01..17) and every later finding in the area,
re-checked on `42a6a98` and production on 9 Oct. "Table said" is the shared follow-through
table's status; where this pass disagrees, the row says so.

| ID | Finding (1 Sep) | Status now | Evidence |
|---|---|---|---|
| DS237-01 | No operator alert reaches anyone | **open, narrowed** | observed/implemented: DSN on all 3 services (since 12 Sep); events dropped 12–24 Sep (org quota); job runner logs to Sentry since 4 Oct (#381); rule not created; only 7 kinds tagged, storage/backup/egress/watchdog/job crashes are not; "new issue" fires once per issue → DS328-01 |
| DS237-02 | Database ~90% of cap, unmonitored | **fixed** | observed: meter since 2 Sep, sums every database since 325; 174.5 MB this database / 189.6 MB summed on 9 Oct 22:21 UTC (was 458 MB on 7 Oct 08:09); ≈ 1 MB/day since → ~260 days to the 450 MB critical line. The alert's delivery is DS328-01 |
| DS237-03 | Egress meter wrong three ways | **shipped differently, partly unsound** (table said fixed) | implemented: A relabelled `http_response_bytes` with `measures=` (sound); C now monthly (sound, but re-reads the whole month every 15 min ≈ 1 GB/month); **B open** — the backup is still booked at its compressed archive size and the false "compressed on the way out of the server" comment is still in `backup.py` → DS328-05 |
| DS237-04 | No backup ever proved restorable | **open** | observed: `backup-drill` 5 of 5 `skipped not_configured`, logged at warning (never reaches Sentry); `BACKUP_RESTORE_DATABASE_URL` absent from the `api` variable names; nightly `backup` 39/39 since 1 Sep (55/55 since 16 Aug), 15.1 MB, 7 kept, all on one Railway volume (`api-volume`, ams) beside the service — no off-site copy; `pg_dump` 17.11 (24 Sep) ≥ server 17.6 |
| DS237-05 | RLS does not constrain the application | **queued (209)** | observed: 32/32 RLS, 0/32 FORCE, all owned by `postgres`; 1 profile, so 209's trigger has not fired |
| DS237-06 | 13 live 365-day device tokens, no way to see them | **deferred-with-trigger; worse** | observed: **16** live device tokens (oldest 22 Jun, newest 17 Sep, expiry to Sep 2027); `used_at` is never set on device tokens, so a live device cannot be told from a dead one; auth router still `activate`/`revoke` (self)/`me`. Trigger (compromise or second user) not fired |
| DS237-07 | Unused RLS-bypassing key required at startup | **accepted-and-closed — now has a cost** | proved: `Settings` refuses to start without `SUPABASE_SERVICE_KEY`; it is one of the two reasons the `trend-narratives` cron cannot run (DS328-02) |
| DS237-08 | Audit log records one thing | accepted-and-closed; unchanged | observed: `audit_log` holds only `backup_failed` (7 rows) |
| DS237-09 | F4 PII wider than described | **fixed (observed)** | the newest stored morning packet carries no `latitude`/`longitude`/`userId` (server-side boolean) |
| DS237-10 | Activation rate limit is one global bucket | accepted-and-closed; unchanged | implemented: `@limiter.limit("10/hour")` keyed on remote address behind Vercel's rewrite; codes single-use (atomic `used_at` update), 30-minute expiry; 31 activation codes ever, 0 live |
| DS237-11 | Co-resident app's event trigger runs inside every migration | **superseded** | observed: the co-tenant's 27 tables were archived and dropped 24 Sep; `public.rls_auto_enable()` + `ensure_rls` were **kept on purpose** as this app's own RLS guard. Still `SECURITY DEFINER`, executable by `anon` (advisor WARN), but it returns `event_trigger`, so it cannot be called directly |
| DS237-12 | `coach` and the public app share one advisor queue | **superseded** | observed: no other app's tables; the advisor's 3 WARNs (`pg_trgm` in `public`, `rls_auto_enable` ×2) are objects this app kept; 28 INFO deny-all notices for `coach`; `check_rls_posture.py` run read-only against production: passed |
| DS237-13 | Only production profile is `admin` | accepted-and-closed; unchanged | observed: 1 profile, admin |
| DS237-14 | Activation codes travel in a query string | accepted-and-closed; not re-checked | claimed |
| DS237-15 | Stale-deploy detection human-only | **open — the table's "premise was wrong" is itself wrong** | observed: the workflow's Vercel endpoint is rewritten to Railway, so it reads Railway's SHA twice; it passed on 1 Oct while Vercel was refusing builds; all 20 of its reds since 1 Sep were false → DS328-06 |
| DS237-16 | A 401 clears the token, not the persisted brief | **fixed (implemented)** | `lib/api.ts`: 401 → `clearTokens()` + `clearPersistedCache()` |
| DS237-17 | Three residual full-row reads | **fixed (observed)** | the full-row `temperature_readings` read (raw payload included) did not run between the two 9 Oct snapshots; the projected temperature and fan reads still fetch full history per call (≈ 0.5 MB each, DS328-05 item 3) |
| 1001-SE-8 | `updated_at` before `created_at` | open (observed) | 113 `workout_delivery_proposals` rows; cosmetic |
| 1001-SE-9 | CI runs PostgreSQL 16; production 17.6 | open (implemented) | `ci.yml` still starts the runner image's 16 |
| 1001-N1 | Database at 453 MB, alert firing for days | **fixed (observed)** | as DS237-02 |
| Incident: Garmin MFA emails | password-login fallback emailed codes | fixed for Garmin (Batch 267 refuses off a TTY; `GARMIN_EMAIL`/`PASSWORD` deleted) — **the Hive twin is open** | proved → DS328-03 |
| Incident: Sentry quota | org out of error quota, 12 Sep | fixed 24 Sep (STATUS) | claimed; a repeat would drop events again silently (§7) |

## 5. G8 and parked rows re-verified

| Row | Touches this lens how | Verdict |
|---|---|---|
| **208** co-resident app | 208.1 routes "the public app's" advisor WARNs to its owner | **Decayed — premise gone.** No co-resident app remains (0 `public` tables since 24 Sep); the 3 remaining WARNs are this app's own kept objects; counts (27 `public`, 29 `coach`) are stale (0, 32). 208.2's durable half is now only "own organisation for billing" and DS328-05's shared org quota. Recommend: close 208.1; re-scope 208.2 to "is the org shared with any other project?" |
| **209** RLS constrains the app | RLS/FORCE posture | **Accurate apart from counts** (29 → 32 tables; still 0 FORCE; still CI on PG16). Trigger (second user / least-privilege login) not fired |
| **210** no pooled connection idles across a model call | pooler | **Accurate as amended 31 Aug.** Lines moved (`reviews.py` now takes `pg_try_advisory_xact_lock` at :930; `generation_requests.py` yields at :459/:474/:493). Batch 312 records no pooler refusal since 30 Aug; trigger stays fired but quiet |
| **276** a dispute suppresses the input | data | **Accurate; its own gate says do not run yet:** `coach.disputes` holds **0** rows, so 276.4 ("if Mark has contested nothing, this batch does not run") applies |
| **318** brief post-check | 318.3 "a miss alerts through `admin_alert`" | Accurate, but its alert inherits DS328-01: a repeating miss is one issue and emails once. Fold DS328-01's rule shape (event captured, 24 h throttle) into 318's acceptance |
| **308** the ladder goes | removes `VERDICT_ENGINE` | Accurate for this lens (`VERDICT_ENGINE` is not set on Railway, so the default graded engine runs). A natural home for DS328-02's cron clean-up and the runbook correction |
| 316, 311, 317, 319, 320, 321, 322 | coaching and copy | Nothing in this lens |

## 6. For reconsideration

*(pending)*

## 7. Hypotheses

- Railway emails project members about crashed deployments/executions by default; if so,
  Craig has received ~16 crash notices a week from the two crons since 20 Sep (unverified:
  notification settings are not readable from the CLI).

## 8. Limitations

- Sentry cannot be read from this machine (no CLI, no token): which events arrived, how they
  were grouped, and which alert rules exist are inferred from code, Railway and `job_runs`.
  Posting a probe event to Sentry would be a write and was not done.

## 9. Probe log

| # | What | Result size |
|---|---|---|
| 1 | `job_runs` grouped by job/status/reason since 1 Sep | 32 rows |
| 2 | `job_runs`: `ledger-freshness` all-time count, first row, total, cron-timed rows | 1 row |
| 3 | `egress-budget` daily maxima of storage/egress counters, 28 Aug – 9 Oct | 43 rows |
| 4 | Railway variable **names** for `api`, `weekly-review`, `trend-narratives` (`railway variables --json`, keys only) | 3 lists |
| 5 | Railway `deploymentInstanceExecutions` for both crons (saved earlier in `scratchpad/wave5/r2/exec_*.json`) | 58 executions |
| 6 | Railway `deploymentLogs` / `environmentLogs` around the 9 Oct 12:32 UTC cron execution | 0 lines from the cron |
| 7 | Local: `Settings` import with each cron's variable names, dummy values (`probe_cron_import.sh`) | trend-narratives refuses, weekly-review imports |
| 8 | Local: structlog → stdlib record shape for the storage alert (`probe_logrecord.py`) | `record.msg` is a dict |
| 9 | Local: Hive expired-refresh fallback (`probes/hive_fallback_probe.py`) | 3 password logins per poll |
| 10 | `GET /api/v1/health` (Railway direct) and web `/` | sha `42a6a98`, 200 |
