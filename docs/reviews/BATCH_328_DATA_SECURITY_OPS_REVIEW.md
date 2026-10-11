# Batch 328 — Data, security and operations review (audit wave #5, R2)

**Date:** 9–10 Oct 2026 (resumed 10 Oct after a usage-limit stop)
**Wave:** audit wave #5 (Batches 327–333), pass R2 — see `docs/reviews/BATCH_327-333_AUDIT_SCOPE.md`
**Lens:** security and site-reliability engineer
**Mode:** read-only. No code, production row, Railway, Vercel, Supabase, Sentry or GitHub
setting was changed; Railway was read with `railway config plan` (which changes nothing) and
`railway run` only for the read-only RLS posture check. Paid Anthropic budget for this pass:
$0; spent: $0.
**Code baseline:** `42a6a98` (`docs: close out Batch 326`); production `/api/v1/health`
reported `42a6a98` on 9 Oct 22:1x UTC and again on 10 Oct ≈ 07:40 UTC, web 200.
**Predecessor:** `BATCH_237_DATA_SECURITY_OPS_REVIEW.md` (1 Sep, 17 findings DS237-01..17).

## 1. Summary

**Grade: C+.** Eleven findings: 2 High, 1 Med-High, 5 Medium, 3 Low. The security boundary
is tight (95 of 99 operations need a device token, RLS deny-all passes, no live secret in
history, storage has 9–18 months of runway), but the public repo carries a third party's home
address and Mark's health record (DS328-04), and the app cannot tell anyone it has stopped.
1. **Correct and safe — C+.** Auth, RLS and secret scope are sound; the public repo (DS328-04), red builds that deploy anyway (DS328-10) and a Hive fallback that would text an MFA code every 5 minutes (DS328-03) are not.
2. **Honest with Mark — B.** Nothing in this lens misleads him; one training week went unreviewed without a word (DS328-07).
3. **Helping him get fitter — B+ (enabling).** Every daily job ran on 38–39 of 39 days; Hive 0 and Garmin 4 poll failures since 1 Sep.
4. **Failure noticed — D.** The watchdog has never run; both Railway crons crashed 58 of 58 times; only 7 alert kinds are tagged and the rule is not created; the storage alert fired for 35 days first (DS328-01, DS328-02); the backup has never been restored (DS328-11).
5. **Cheap to run and change — B−.** Hosting costs nothing, but our own backup and meter are most of the egress cap (DS328-05), and 124 docs-only pushes redeployed production (DS328-08).

## 2. What optimal looks like

**Optimal, in this lens:**
- **One alert route that sees every operator signal.** Every operator `log.error` goes through
  `admin_alert` with its own kind and a stable fingerprint; one Sentry rule ("an event is
  captured", tag `admin_alert`, 24 h throttle) emails Craig at most once a day per kind while a
  fault lasts; each close-out that adds a kind fires a test event.
- **Something outside the process watches the process.** `/api/v1/health` says how old the newest
  `job_runs` row is; the existing freshness workflow or a free uptime monitor alarms on it; the
  ledger watchdog runs on its own clock. Cron services either run or do not exist.
- **Production takes only green builds, and only builds that change something.** Railway waits
  for CI; `main` requires the CI check with a bypass for docs close-outs; docs-only commits do not
  redeploy; the freshness check reads both Railway and Vercel and accepts descendants.
- **Nothing identifying in public.** No real address, phone, health metric or note in a public
  repo or its history.
- **Backups that are proved and kept apart.** Authored tables nightly, raw replayable ones weekly;
  the archive read end to end every week; a copy off Railway every week.
- **The meter counts what Supabase bills.** A running month total, the backup at its wire size.
- **No password fallback where a token exists.**

**Already near-optimal (protect it):** the auth surface and device-token design; RLS posture and
the Data API lock-down; secret scope on Vercel and GitHub (public values only, no Actions
secrets); storage retention and runway; the `pg_dump` 17 pin and the 7-archive rotation; the
dependency gates on shipped code (`pip-audit` clean, `pnpm audit --prod` with six reviewed
exceptions); job cadence; Garmin and Hive off the event loop since 312.

**Smallest set of changes, in order:**
1. **Before 21 Oct? — Craig's console and credential steps, no code, no coaching change:**
   create the Sentry rule in DS328-01's shape; delete `HIVE_EMAIL`/`HIVE_PASSWORD` from `api`
   (DS328-03); replace the Hive fixture's identity block and decide private vs history rewrite
   (DS328-04); turn on secret scanning, push protection and Dependabot alerts (DS328-10).
   None changes what Mark sees.
2. **First ops batch after G8 (≈ 1.5–2 days):** route every operator log through `admin_alert`
   with a fingerprint (DS328-01); fix or delete the crons, add a `ledger-freshness` clock and a
   scheduler-liveness field, correct the runbook (DS328-02); misfire grace and watch paths
   (DS328-08); Railway wait-for-CI and a `main` ruleset (DS328-10); the archive-integrity drill and
   an off-site copy (DS328-11); the Vercel half of the freshness check with R1's CR327-07 (DS328-06).
   It sits naturally beside R1's CR327-02 fix and 308's tidy-up.
3. **Egress (≈ half a day):** running month total and a split backup cadence (DS328-05).
4. **When convenient:** the holiday-week review rule (DS328-07); dev-tool bumps (DS328-09).

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
| Garmin token expired (garth's cache lasts about a year; AGENTS.md) | `garmin_reauth_required` `log.error` (untagged); Batch 267 refuses the password login off a TTY | default | As above, every day until re-minted |
| Hive refresh token expired | `hive temperature poll failed` (untagged) + `job_runs` failed | default | "Hive temperature stale" push; **and an SMS code every ~5 min to the account phone** (DS328-03) |
| Anthropic credit exhausted / spend-cap 400 | `anthropic_text` classifies both as `billing` → `admin_alert` kind `billing` (tagged) | rule | The call (graded before the brief since 302), "Writing your brief" → failure card with Try again |
| Anthropic timeout / 5xx | retried, then `generation_failure` (tagged) | rule | Same failure card |
| Malformed output (missing sections) | `morning_analysis_missing_required_sections` **warning** — below Sentry's event level | no | The malformed brief, as written |
| Empty output | `MorningAnalysisError` → `generation_failure` (tagged) | rule | Failure card |
| A scheduled job crashes | `run_tracked_job`: "escaped its result boundary" (untagged) + `job_runs` failed. Two handlers crash inside themselves after a rollback (R1's CR327-02): a failed month narrative never sends its designed alert; a failed backstop step loses the brief and sends a false one | default | Depends on the job |
| The in-process scheduler stops, API still up | **nothing** — the watchdog never runs, health has no scheduler field (DS328-02) | no | Missing brief, no rides reaching Zwift, no pushes |
| A Railway cron crashes | Railway marks the execution `CRASHED`; the process dies before Python (exec-form `if`) or before `init_sentry` (config) | no (Railway mail: §7) | Nothing (the in-process job does the work) |
| Database reaches 90% / 500 MB | `operator storage alert` once per UTC day (untagged); at 500 MB every write fails and each job logs its own error | default | At 500 MB: check-ins, briefs and syncs fail |
| Nightly backup fails | `operator backup alert` (untagged) + `audit_log` row + `job_runs` failed | default | Nothing |
| A backup cannot be restored | `backup-drill` skips `not_configured` and logs a **warning** (5 of 5 runs) | no | Nothing |
| intervals.icu paused (326) | `intervals-rail` → `delivery_rail` (tagged), 14 days ahead and on the day | rule | Home says rides are not reaching Zwift |
| Railway ahead of Vercel, or the reverse | `deploy-freshness` reads Railway twice (DS328-06); its reds are mostly false (CR327-07) | no | Old web against a new API; a schema mismatch shows raw `ZodError` text (UX241-03, open) |
| A push with red CI | nothing: Railway does not wait for CI and `main` is unprotected (DS328-10) | no | The red build, live |
| A deploy lands on a daily job's minute | nothing: the run is dropped (1 s grace) (DS328-08) | no | That day's job does not run |
| Egress over the free cap | the meter books ~15 MB a night for ~146 MB (DS328-05) | no | Nothing until Supabase restricts |

**What reaches nobody today:** a stopped scheduler, an unrestorable backup, a malformed brief,
a crashed Railway cron, real egress, a red build going live, and a daily job lost to a deploy.
Everything else reaches Craig only through Sentry, and only the seven tagged kinds would be
caught by the rule he has yet to create.

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
- **What Sentry's own default might send.** A new project can be created with Sentry's default
  issue alert, which now fires when "a new issue is marked high priority" or an existing one
  escalates to high priority on a surge of events; error-level events are given high priority
  (Sentry changelog, *Issue alerts now have priority conditions*). So *if* Craig kept that
  default, any new error-level issue — tagged or not — emails him once, and a daily repeat does
  not. Whether the default exists cannot be read from here (§8); that is the "default" column in
  §3.0.
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
`CMD` already does the London-time guard) — **but first set `SCHEDULED_JOB=weekly-review` and
`SCHEDULED_LONDON_HHMM=1800` on `weekly-review`, which has neither today**: without them the
image's `CMD` falls through to `alembic upgrade head` and uvicorn, so the cron would boot a
second API with a second in-process scheduler and every job would run twice. Add `SUPABASE_SERVICE_KEY` and `FRONTEND_ORIGIN` to
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

### DS328-06 — Medium — The deploy check cannot see Vercel

**Evidence:** observed (GitHub Actions, response headers, production history), implemented.

`deploy-freshness.yml` polls two endpoints, but Vercel's `/api/v1/health` is a rewrite to
Railway (`vercel.json`; the response carries `x-railway-edge`), so **both checks read
Railway's SHA**. Proof that this matters: on 1 Oct Vercel refused every build from 09:26
(Decision #369, `2dd88ab`'s production build failed), and the freshness run for that merge at
14:19 UTC passed. The same flaw sits in the close-out's production check ("health SHA + web
200": the web returns 200 from the previous build; on 10 Oct the page's `last-modified` was
7 Oct 22:32 UTC, which a check could read but none does).
The check's other defect — red when a docs commit follows within its window — is R1's
**CR327-07**; this pass measured its size: **all 20 failures since 1 Sep were false** (in each,
both endpoints served a *newer* SHA, checked with `git merge-base --is-ancestor`), 20 of 200
runs, so a real stale deploy would look like the noise Craig has learned to ignore.
What Craig sees: a red X on `main` every few merges that means nothing, and no red at all when
the web did not deploy. **Fix (≈ 1 h, beside CR327-07's ancestry fix):** the web build writes
`version.json` with `VERCEL_GIT_COMMIT_SHA`; the monitor and the close-out read it for the
Vercel half. **Where:** after G8 (or with 308).

### DS328-10 — Medium — Nothing enforces the green gate before production, and GitHub's free guards are off

**Evidence:** observed (GitHub API, Railway deployments and live config), implemented.

The close-out rule (AGENTS.md) is "every CI check green … before the merge", and `main`
auto-deploys (Decision #39). Nothing in the platform holds that rule:

- **Railway deploys without waiting for CI.** `.railway/railway.ts` declares the source as
  `github("CraigR973/garmin-coach", { checkSuites: false })`, and the live configuration matches
  (`railway config plan`, read-only, 10 Oct: only the two known `api` default-value diffs).
- **`main` is unprotected:** no branch protection (`404 Branch not protected`), 0 rulesets.
  **118 of 219** commits on `main` since 1 Sep carry no PR number — mostly docs close-outs by
  design, but not only.
- **It has happened.** On 20 Sep four code commits for Batch 266 (`dd10279`, `5b92f9b`,
  `64d9f8c`, `9e57e10`) were pushed straight to `main`, **each with CI red**; Railway built and
  deployed every one (each later superseded, status `REMOVED`, not `FAILED`) until `1b21ffb`
  went green 40 minutes later. The reds were in tests, so no harm is observed. STATUS (5 Aug,
  Batch 188) records a concurrent session landing a commit on `main` by accident, which is the
  other way an unchecked change reaches production. The deploy-freshness workflow skips when
  CI is red, so nothing checked those deploys either.
- **A public repo with secret scanning, push protection and Dependabot alerts all disabled**
  (`security_and_analysis`: every field `disabled`; `vulnerability-alerts` 404). All three are
  free on public repositories. CI's Gitleaks job scans full history on every run, but only
  after the push, when a leaked token is already public. This pass's own history scan for
  credential shapes (Anthropic, GitHub, Supabase, Sentry DSN, AWS, Postgres URLs, JWTs and the
  app's own secret variable names) found **only placeholders and the forked app's fake test
  JWTs** — no live secret (computed; pattern-based, so not proof of absence).
- **The live RLS posture check never runs in CI:** `check_rls_posture.py --allow-missing-url`
  skips because the repo has **0 Actions secrets** (no `RLS_POSTURE_DATABASE_URL`). Run by hand in
  this pass it passed; nothing would catch drift between reviews.

**What Craig experiences:** nothing, until a red build reaches Mark. **Fix:** (1) console, minutes,
free: turn on secret scanning, push protection and Dependabot alerts; (2) Railway "wait for CI"
(`checkSuites: true` in `railway.ts`, then `railway config apply` — a hosting change, Craig's),
watching the first push to confirm the deploy-freshness workflow (a `workflow_run` after CI) does
not hold the deploy; (3) a ruleset on `main` requiring the CI check, with Craig's account allowed
to bypass for docs close-outs; (4) optionally an `RLS_POSTURE_DATABASE_URL` Actions secret on a
read-only role. **Where:** (1) any time, it touches no coaching; (2)–(4) after G8.

### DS328-11 — Medium — The only backup sits beside the service and has never been restored

**Evidence:** observed (`job_runs`, Railway config, variable names), implemented. Re-states the
open wave #4 High DS237-04 with what has changed.

- **Taken every night:** `backup` 40 of 40 since 1 Sep (55 of 55 since 16 Aug), ≈ 15 MB, 7 kept,
  `pg_dump` 17.11 against server 17.6. Supabase's free plan has no managed backup, so this is the
  only copy of Mark's authored history (analyses, check-ins, chat, plans, knowledge base).
- **One place:** the archives live on `api-volume` (Railway, `ams`, 5 GB, usage alerts at
  80/95/100 %), mounted into the `api` service itself. A Railway account, project or region loss
  takes the database's only backup with it.
- **Never restored:** `backup-drill` skipped 5 of 5 Sundays (`not_configured`; no
  `BACKUP_RESTORE_DATABASE_URL`), logged at **warning**, which Sentry does not capture. The
  runbook's off-site step ("once a week after the Sunday restore drill passes, download the newest
  archive … store it off-site") is conditioned on a drill that has never passed, so its stated
  7-day RPO for a platform loss rests on nothing this pass could see (whether Craig pulls copies
  by hand is unknown, §8). The runbook also says `activity_timeseries` is "~85 % of the
  database"; it is 55 % today (95.6 of 174.7 MB), still excluded and replayable from Garmin.

**What Mark would experience:** only if Supabase loses or corrupts the database (or a bad
migration does) *and* the archive proves unreadable or is lost with Railway: the loss of his
history since June.
**Fix (≈ 2 h, no new infrastructure):** a drill mode that needs no target database —
`pg_restore --list` plus `pg_restore --file=/dev/null` on the newest archive reads and
decompresses every table's data and fails on corruption — run weekly with its failure routed
through `admin_alert` (DS328-01); and a weekly off-site copy Craig owns (a laptop pull or a free
object store). The full restore drill stays Craig's G4 item. **Where:** after G8.

### DS328-07 — Low — A training week went without its review because the holiday started on its Sunday

**Evidence:** observed (`job_runs`, `analyses`, `activities`), implemented.

`run_weekly_review_delivery` skips a profile when *today* (the Sunday) is inside a holiday
window. On Sun 27 Sep the holiday had begun, so the review of 21–27 Sep was skipped
(`holiday_away`) though Mark recorded **17 activities** from 21 to 26 Sep; the 4 Oct skip
(a week wholly away) is the intended case. Stored `weekly_review` rows run to the week of
14 Sep; nothing reviewed 21–27 Sep, and nothing told him. **Fix:** skip only when the whole
week (or most of it) is inside the window; ≈ 1 h with a test. **Where:** after G8; low stakes.

### DS328-08 — Low — Every push restarts the scheduler, and a daily job whose minute it hits is dropped

**Evidence:** observed (`job_runs`, Railway deployments), implemented.

- **Restarts are frequent.** Railway built and deployed `api` **212 times** from 1 Sep to
  7 Oct (≈ 5.6 a day; 25 on 27 Sep alone). **124 of them were docs-only commits** (no file
  under `apps/`, `packages/`, `scripts/`, `.github/`, `.railway/` or the Dockerfile), and
  **32 landed inside Mark's morning window** (03:30–11:05 London; 18 of those docs-only). Each
  deploy restarts the process, and the in-process APScheduler with it. The two cron services
  rebuild on every push too.
- **A restart drops a daily run.** Ten daily jobs (backup, baseline refresh, the 11:00 morning
  backstop, post-workout backstop, autopush, weekly review, state change, longitudinal, trend
  narratives, evening nudge) use APScheduler's default `misfire_grace_time`, which is **1 second**
  (`apscheduler/schedulers/base.py`: `job_defaults.get("misfire_grace_time", 1)`). Only four set
  3,600 s: `zwift_rail_check`, `timeseries_retention`, `proposal_expiry`, `backup_drill`.
- **Observed cost so far is small.** Cadence since 1 Sep against the schedule: every daily job
  ran every day except `post-workout-backstop` on 27 Sep (deploys at 19:33 and 19:40 UTC
  bracketed its 19:30 slot, on a slow-Garmin day before Batch 312), and four of 624
  `evening-alerts` slots (22, 24 and 27 Sep — days of 7–25 deploys). The early-September gaps in
  `proposal-expiry` and `timeseries-retention` are the days before those jobs shipped.
- **Exposure:** a deploy at 11:00 London on a morning when wake detection missed would cost Mark
  his brief until he opens the app (the check-in path still writes it); a deploy at 04:00 UTC
  costs a night's backup. Nothing would notice either (DS328-02).

**Fix (a few lines + one config line):** `misfire_grace_time=3600` on the idempotent daily jobs;
and Railway watch paths on all three services so docs-only commits do not deploy (this
needs CR327-07's ancestry rule first, or the freshness check goes red on every docs push).
**Where:** fold into whichever batch takes DS328-02.

### DS328-09 — Low — Dev tooling carries 47 advisories the gate never reads

**Evidence:** observed (`pnpm audit`, 9 Oct).

The CI gate runs `pnpm audit --prod` and passes today with its six reviewed exceptions
(re-run locally: "JS dependency audit passed"); `pip-audit` on the locked API requirements
finds nothing. Without `--prod`, `pnpm audit` lists 53 advisories, 47 outside the six reviewed
exceptions (3 critical, 30 high, 13 moderate, 1 low), including two critical in
`tinypool` and one in `vitest` (UI server), and highs in `vite`, `ws`, `fast-uri`, `js-yaml`,
`brace-expansion`. They live in test and build tooling that runs on Craig's Mac and CI, not in
the shipped bundle, so the risk is to the developer machine, not to Mark. **Fix:** a dev-tool
bump batch (vitest, vite) when convenient; accept otherwise. **Where:** after G8.

### Measured and sound — no finding

**Auth surface** (implemented; proved by enumerating the real app's OpenAPI with dummy settings,
`probes/route_auth.py`). 99 operations: **95 require a device token**, 4 are open by design
(`/health`, `/health/ready`, `/auth/activate`, the VAPID *public* key). The admin surface is 3
operations under `/api/v1/admin/coaching-state`, behind `require_admin`. Device tokens are 256-bit,
stored as SHA-256, checked against revoked/expiry/active-profile on every request; production
serves no `/docs` or `/openapi.json` (404). The web sends a strict CSP, HSTS with preload and
`X-Frame-Options: DENY`. The weak spots are the ones already recorded: 16 live 365-day tokens with
no "last used" (DS237-06), and the app connecting as the table owner `postgres` through Supavisor
(observed in `pg_stat_activity`), so RLS is a Data-API backstop only (DS237-05, parked 209).

**Secrets: presence and scope** (names only; no value read or printed).

| Where | What is there | Note |
|---|---|---|
| Railway `api` | 22 variables: Anthropic, database, Garmin token blob (and a legacy `GARMIN_TOKENSTORE`), Hive token blob **and Hive email/password**, Dreo fan login, intervals.icu key, VAPID pair, Sentry DSN, Supabase service key | Hive password → DS328-03 |
| Railway crons | each holds its own copy of the Anthropic key, database URL and VAPID private key | they never complete a run (DS328-02), so these copies are pure exposure and one more place to rotate |
| Vercel | 2: `VITE_SENTRY_DSN`, `VITE_VAPID_PUBLIC_KEY` | both public by nature |
| GitHub Actions | 0 secrets, 0 variables; workflow token read-only | so the live RLS check never runs (DS328-10) |
| Supabase | Data API (PostgREST) up; 32 of 32 `coach` tables RLS on, deny-all to `anon`/`authenticated`; advisor: 3 WARN, all objects this app kept on purpose | `check_rls_posture.py` passed, run read-only |
| Sentry | not readable from this machine | §8 |

**Storage and growth** (observed, 10 Oct 07:36 UTC): this database **174.7 MB**, every database
summed 189.8 MB (the meter's reading; 171 MB after the 7 Oct VACUUM FULL). Per table and per 30 days:

| Table | Size | Added in 30 days | Retention |
|---|---|---|---|
| `activity_timeseries` | 95.6 MB (55 %) | ≈ 25 MB | 90 days, purging since 24 Sep (1.5–4 k rows a night) — steady state |
| `temperature_readings` | 19.4 MB | ≈ 5.3 MB | none (≈ 1.8 KB a row on disk, 2.8 KB as text, mostly the raw payload) |
| `analyses` | 10.1 MB | ≈ 2.7 MB | none, by design (authored history) |
| `job_runs` | 9.9 MB | ≈ 5.4 MB (13.3 k rows) | none |
| `sleep`, `daily_metrics`, `activities` | 21.7 MB | ≈ 1.2 MB | none (replayable from Garmin) |

Row growth in the unbounded tables is ≈ 15 MB a month; the meter's own sum rose 2.4 MB in the
2.4 days to 10 Oct (≈ 1 MB a day, indexes refilling after the VACUUM FULL). The 450 MB critical
line is therefore 9–18 months away (MB = 10⁶ bytes throughout; the scope's 164/179 MB on 7 Oct
are the same readings in MiB). Near
optimal; a 90-day window on `job_runs` would also shrink DS328-05's quadratic read.

**Scheduled jobs since 1 Sep** (observed, `job_runs`; 39 days to 9 Oct):

| Job | Runs | Not succeeded |
|---|---|---|
| `hive-poll`, 15 min | 3,867 | 0 |
| `wake-check`, 15 min | 3,839 | 3 degraded (step failures) |
| `activity-poll`, hourly | 1,022 | 4 failed (Garmin) |
| `egress-budget`, 15 min | 3,780 | 3,333 degraded (storage critical/warning, to 7 Oct) |
| `fan-control` | 3,815 | 2,359 skipped (outside the night, holiday) |
| `evening-alerts` | 620 | 0 (4 slots missing, DS328-08) |
| `backup`, `baseline-refresh` | 40 each | 0 |
| `morning-sync` (11:00 backstop) | 39 | 3 degraded |
| `state-change`, `evening-nudge` | 39 each | 10 skipped (holiday), 0 |
| `post-workout-backstop` | 38 | 27 Sep missing (DS328-08) |
| `autopush` | 118 | 0 |
| `longitudinal-analysis` | 39 | 31 skipped (no alert route until 291 on 4 Oct), 1 degraded 4 Oct |
| `timeseries-retention`, `proposal-expiry` | 39, 37 | 22 dry runs to 24 Sep; 0 |
| `trend-narratives` (in-process) | 20 | 0 — the Railway cron of the same name: 40 of 40 crashed |
| `weekly-review` (in-process) | 5 | 2 skipped `holiday_away` (27 Sep is DS328-07) |
| `backup-drill` | 5 | 5 skipped (DS328-11) |
| `intervals-rail` (since 326) | 10 | 0 |
| `ledger-freshness` | **0 ever** | DS328-02 |

**Garmin and Hive since Batch 312** (observed): 4 Garmin poll failures and 0 Hive failures in
39 days; the 48 h of `api` logs read (7–9 Oct, 3,964 lines) hold no `garmin_reauth_required`,
no Hive poll failure and no error-level application line (the six lines Railway labels "error"
are uvicorn and Alembic start-up notices on stderr). Neither token's expiry was re-checked.

**Hosting config** (observed): `railway config plan` against the live project shows only the two
known `api` default-value diffs, so `.railway/railway.ts` is what runs — including the cron start
commands that crash (DS328-02) and `checkSuites: false` (DS328-10).

## 4. Follow-through

Every wave #4 finding in this lens (DS237-01..17) and every later finding in the area,
re-checked on `42a6a98` and production on 9 Oct. "Table said" is the shared follow-through
table's status; where this pass disagrees, the row says so.

| ID | Finding (1 Sep) | Status now | Evidence |
|---|---|---|---|
| DS237-01 | No operator alert reaches anyone | **open, narrowed** | observed/implemented: DSN on all 3 services (since 12 Sep); events dropped 12–24 Sep (org quota); job runner logs to Sentry since 4 Oct (#381); rule not created; only 7 kinds tagged, storage/backup/egress/watchdog/job crashes are not; "new issue" fires once per issue → DS328-01 |
| DS237-02 | Database ~90% of cap, unmonitored | **fixed** | observed: meter since 2 Sep, sums every database since 325; 174.5 MB this database / 189.6 MB summed on 9 Oct 22:21 UTC (was 458 MB on 7 Oct 08:09); ≈ 1 MB/day since → ~260 days to the 450 MB critical line. The alert's delivery is DS328-01 |
| DS237-03 | Egress meter wrong three ways | **shipped differently, partly unsound** (table said fixed) | implemented: A relabelled `http_response_bytes` with `measures=` (sound); C now monthly (sound, but re-reads the whole month every 15 min ≈ 1 GB/month); **B open** — the backup is still booked at its compressed archive size and the false "compressed on the way out of the server" comment is still in `backup.py` → DS328-05 |
| DS237-04 | No backup ever proved restorable | **open** | observed: `backup-drill` 5 of 5 `skipped not_configured`, logged at warning (never reaches Sentry); `BACKUP_RESTORE_DATABASE_URL` absent from the `api` variable names; nightly `backup` 39/39 since 1 Sep (55/55 since 16 Aug), 15.1 MB, 7 kept, all on one Railway volume (`api-volume`, ams) beside the service — no off-site copy; `pg_dump` 17.11 (24 Sep) ≥ server 17.6 → DS328-11 |
| DS237-05 | RLS does not constrain the application | **queued (209)** | observed: 32/32 RLS, 0/32 FORCE, all owned by `postgres`; 1 profile, so 209's trigger has not fired |
| DS237-06 | 13 live 365-day device tokens, no way to see them | **deferred-with-trigger; worse** | observed: **16** live device tokens (oldest 22 Jun, newest 17 Sep, expiry to Sep 2027); `used_at` is never set on device tokens, so a live device cannot be told from a dead one; auth router still `activate`/`revoke` (self)/`me`. Trigger (compromise or second user) not fired |
| DS237-07 | Unused RLS-bypassing key required at startup | **accepted-and-closed — now has a cost** | proved: `Settings` refuses to start without `SUPABASE_SERVICE_KEY`; it is one of the two reasons the `trend-narratives` cron cannot run (DS328-02) |
| DS237-08 | Audit log records one thing | accepted-and-closed; unchanged | observed: `audit_log` holds only `backup_failed` (7 rows) |
| DS237-09 | F4 PII wider than described | **fixed (observed)** | the newest stored morning packet carries no `latitude`/`longitude`/`userId` (server-side boolean) |
| DS237-10 | Activation rate limit is one global bucket | accepted-and-closed; unchanged | implemented: `@limiter.limit("10/hour")` keyed on remote address behind Vercel's rewrite; codes single-use (atomic `used_at` update), 30-minute expiry; 31 activation codes ever, 0 live |
| DS237-11 | Co-resident app's event trigger runs inside every migration | **superseded** | observed: the co-tenant's 27 tables were archived and dropped 24 Sep; `public.rls_auto_enable()` + `ensure_rls` were **kept on purpose** as this app's own RLS guard. Still `SECURITY DEFINER`, executable by `anon` (advisor WARN), but it returns `event_trigger`, so it cannot be called directly |
| DS237-12 | `coach` and the public app share one advisor queue | **superseded** | observed: no other app's tables; the advisor's 3 WARNs (`pg_trgm` in `public`, `rls_auto_enable` ×2) are objects this app kept; 28 INFO deny-all notices for `coach`; `check_rls_posture.py` run read-only against production: passed |
| DS237-13 | Only production profile is `admin` | accepted-and-closed; unchanged | observed: 1 profile, admin |
| DS237-14 | Activation codes travel in a query string | accepted-and-closed; unchanged | implemented: `ActivatePage` reads the code from the query or the fragment and scrubs the URL after success; codes single-use, 30 minutes |
| DS237-15 | Stale-deploy detection human-only | **open — the table's "premise was wrong" is itself wrong** | observed: the workflow's Vercel endpoint is rewritten to Railway, so it reads Railway's SHA twice; it passed on 1 Oct while Vercel was refusing builds; all 20 of its reds since 1 Sep were false → DS328-06 (Vercel blindness) and R1's CR327-07 (false reds) |
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

- **Decision #368 — committing 56 of Mark's real check-in notes to the public repository** (on
  Craig's go, 30 Sep). New evidence: DS328-04 measures what the public repo already holds beside
  them (a third party's address and phone, 118 screenshots, HRV/RHR extracts); the notes are the
  most personal item and the easiest to move. Keep the eval; move its real-note fixtures to a
  private location (a private repo or an encrypted CI artefact) and keep only synthetic cases public.
- **Decision #59 — "full email/password login is kept only as a fallback and rejects SMS_MFA".**
  It rejects the challenge, but only after Cognito has sent the SMS; under `retry_sync` that is
  three texts per poll (DS328-03, proved). With the token blob configured the fallback has no
  case it can win; remove it, as Batch 267 did for Garmin.
- **Decision #381 — Sentry as the single operator route.** Keep the route. Its premise that every
  operator alert is one tagged event does not hold: seven kinds are tagged, the storage, egress,
  backup, drill, watchdog and job-crash alerts are not, and the rule itself does not exist yet
  (DS328-01). Amend: every operator `log.error` through `admin_alert`, and the rule's existence
  (with a test event) as part of the acceptance.
- **Decisions #355 / #364 — the two Railway cron services "keep their schedules and start
  commands".** Those start commands have never run (58 of 58 executions crashed, DS328-02), and
  Decision #329's diagnosis of the silent `weekly-review` cron (Sentry init) was true but not the
  reason it was silent. Either drop the start commands so the image's guarded `CMD` runs, or delete
  both services; the in-process scheduler already owns both jobs.
- **Decision #39 — auto-deploy from `main`.** Keep it; add Railway's wait-for-CI and a `main`
  ruleset (DS328-10), so the close-out's green gate is enforced rather than remembered.
- **Decision #262 — the nightly `pg_dump` of every authored and raw table.** Its egress, measured
  at wire size, is ≈ 4.4 GB a month (DS328-05); split the cadence (authored nightly, replayable
  raw weekly).

## 7. Hypotheses

- Railway emails project members about crashed deployments/executions by default; if so,
  Craig has received ~16 crash notices a week from the two crons since 20 Sep (unverified:
  notification settings are not readable from the CLI).
- September's real database egress was ≈ 5–5.5 GB, at or near the 5.5 GB cap, almost all of it
  the backup and the meter (DS328-05's estimate). A 31-day month makes the meter's quadratic read
  ≈ 7 % larger; the dump grows with the tables. Supabase's daily egress bars would confirm or
  refute this in a minute.
- Sentry either folded the 35 daily storage alerts into one issue (one email, ever) or opened a
  new issue each day (a daily email Craig may have filtered); which one depends on server-side
  message normalisation this pass cannot see.
- A deploy during a paid morning call orphans the generation until Batch 144's sweep; 32 deploys
  landed in the morning window since 1 Sep. No orphaned brief was found in the reviews since
  1 Sep, so this is exposure, not observed harm.
- The Hive refresh token has worked since June, so its lifetime is longer than Cognito's 30-day
  default; it is probably years, but Hive's app-client setting is not visible.

## 8. Limitations

- Sentry cannot be read from this machine (no CLI, no token): which events arrived, how they
  were grouped, and which alert rules exist are inferred from code, Railway and `job_runs`.
  Posting a probe event to Sentry would be a write and was not done.
- Supabase's egress figure is dashboard-only; DS328-05 is an estimate from server-side text sizes
  and `pg_stat_statements` deltas. What Craig should read: Supabase → Organisation → Usage →
  Egress, daily bars 1 Sep – 10 Oct.
- GitHub returned no plan for Craig's account, so DS328-04's Actions cost is priced for both
  Free and Pro. Repository traffic cannot separate a stranger's clone from CI and build clones.
- No restore was attempted: there is no throwaway target database, and a restore is a write.
  Whether Craig keeps off-site copies of the archive by hand is unknown.
- The history secret scan is pattern-based (known credential shapes and this app's variable
  names); CI's Gitleaks covers more patterns and passes.
- Deploy-to-job overlap in DS328-08 uses each deployment's creation time (build start), not the
  moment the new container took over, so the attribution of the 27 Sep and evening-alert gaps
  to deploys is likely, not proved.
- Railway logs were read for 48 h (7–9 Oct) only; older failure detail comes from `job_runs`.
- No active probing of the live API beyond unauthenticated GETs of health, docs and the web root.

## 9. Probe log

All production SQL was column-projected or aggregated; no JSONB column was transferred except
`job_runs.counters` for 4 rows. Total read well under 1 MB.

| # | What | Result size |
|---|---|---|
| 1 | `job_runs` grouped by job/status/reason since 1 Sep (run 9 Oct and again 10 Oct) | 32 / 20 rows |
| 2 | `job_runs`: `ledger-freshness` all-time count, first row, total, cron-timed rows | 1 row |
| 3 | `egress-budget` daily maxima of storage/egress counters, 28 Aug – 9 Oct | 43 rows |
| 4 | Railway variable **names** for `api`, `weekly-review`, `trend-narratives` (keys only, 9 and 10 Oct) | 3 lists |
| 5 | Railway `deploymentInstanceExecutions` for both crons (`scratchpad/wave5/r2/exec_*.json`) | 58 executions |
| 6 | Railway `deploymentLogs` / `environmentLogs` around the 9 Oct 12:32 UTC cron execution | 0 lines from the cron |
| 7 | Local: `Settings` import with each cron's variable names, dummy values (`probe_cron_import.sh`) | trend-narratives refuses, weekly-review imports |
| 8 | Local: structlog → stdlib record shape for the storage alert (`probe_logrecord.py`) | `record.msg` is a dict |
| 9 | Local: Hive expired-refresh fallback (`probes/hive_fallback_probe.py`) | 3 password logins per poll |
| 10 | `GET /api/v1/health` (Railway direct and via Vercel), `/docs`, `/openapi.json`, web `/` headers (9 and 10 Oct) | sha `42a6a98`; docs 404; web 200 |
| 11 | Server-side text size per dumped table, `sum(octet_length(row::text))` | 1 row per table |
| 12 | `pg_stat_statements` snapshots 9 Oct 09:17 and 22:2x UTC (`pgss_snap1.txt`) | top 14 statements each |
| 13 | Live device tokens, activation codes, `audit_log` kinds, `disputes`, `updated_at < created_at` counts | 1 row each |
| 14 | Newest stored morning packet: presence of `latitude`/`longitude`/`userId` (server-side booleans) | 1 row |
| 15 | `scripts/check_rls_posture.py` read-only via `railway run` (`probes/rls_posture_wrapper.py`); Supabase advisors | passed; 3 WARN, 28 INFO |
| 16 | Railway `api` 48 h logs (`api_logs_48h.jsonl`) | 3,964 lines |
| 17 | Git history: files added under media/data extensions, Mark/Kilmarnock/medication mentions, commit counts; GitHub traffic API | `public_added_files.txt`, `public_media.txt` |
| 18 | Actions minutes: 8 CI runs' job timings; run counts for September; `deploy-freshness` runs since 1 Sep (`df_runs.txt`, `df_fail.txt`) | 200 runs, 20 failures |
| 19 | `pnpm audit` (all and `--prod`), `pip-audit` on `requirements.lock` | 53 / 6 reviewed / 0 |
| 20 | Per-table size, live/dead tuples (`pg_total_relation_size`, `pg_stat_user_tables`), 10 Oct | 32 rows |
| 21 | Rows added in the last 30 days and oldest row for 7 large tables | 7 rows |
| 22 | `timeseries-retention` last 3 runs' counters; `egress-budget` newest row (storage, HTTP month) | 3 + 1 rows |
| 23 | `longitudinal-analysis` runs since 28 Sep; missing daily runs per job since 1 Sep | 14 + 3 rows |
| 24 | `pg_stat_activity` grouped by user/application/state | 8 rows; nothing idle in transaction |
| 25 | Local: OpenAPI enumeration of the real app (`probes/route_auth.py`) | 99 operations, 4 open, 3 admin |
| 26 | GitHub: Actions secrets/variables (names), deploy keys, branch protection, rulesets, `security_and_analysis`, vulnerability alerts, Actions permissions | 0 / 0 / 0 / none / 0 / all disabled / off / read-only token |
| 27 | Git history credential-shape scan, values never printed | placeholders and fake test JWTs only |
| 28 | Commits on `main` since 1 Sep without a PR number; CI conclusions for the 20 Sep pushes | 118 of 219; 4 red |
| 29 | `railway deployment list --service api --limit 400` (`api_deploys.json`) | 212 since 1 Sep, 124 docs-only, 32 in the morning window |
| 30 | `railway config plan` (read-only) against `.railway/railway.ts` | 1 change on `api` (the two known defaults), 0 add, 0 destroy |
| 31 | `vercel env ls` (names only) | 2 variables |
| 32 | Sentry changelog on default alert priority conditions (web) | — |
