# Batch 357 — Data, security and operations review (wave #6, pass R2)

**Pass R2** · reviewed SHA `083e012` (production serves it; no api or cron deploy since 30 Oct 15:18 UTC) · lens: security and site-reliability engineer · read-only · paid calls: **none ($0)**.
Run 1 Nov 2026, 01:42–(see end) GMT. Production read with projected SELECTs (Supabase MCP), `get_advisors`, read-only Railway CLI (`status`, `deployment list`, `logs`, variable **names** only) and `gh api` reads. Nothing written anywhere but the wave's scratch folder and this session's scratchpad.

**FAST LANE raised mid-pass (01:50 GMT, to the orchestrator):** Garmin's stored login has been refused since 00:25 GMT 1 Nov (DS357-01).

## 1. Summary

**Grade C.** The perimeter is sound: the database cannot be reached from outside the app, tokens expire and are checked, no secret has ever been committed, storage and egress are under control. What holds the grade down is the same thing wave #5 graded D+: **a failure still does not reach Craig.** Today proves it: Garmin's login has been refused since 00:25 GMT and no alert exists for it. The watchdog built for a stopped scheduler has never run once, the two Railway crons meant as a second runner never run a job but keep copies of every secret, and the only backups sit unencrypted beside the service and have never been restored.

1. **Correct and safe?** The boundary yes; the data's durability no (DS357-04), and health text may leave for Sentry in exception frames (DS357-05).
2. **Honest with Mark?** At risk today: if Garmin stays refused, he is shown a held brief that reads like his watch's fault (DS357-01).
3. **Doing its job?** Jobs run on time (the in-process scheduler wrote every row); four degraded backstops in October were three weather blips and one undecidable brief failure (DS357-06).
4. **Would a failure be noticed?** No: of 16 failure classes, one has a route Craig is known to receive (§2a). D.
5. **Cheap to run and change?** Two dead cron services triple every rotation and every build (DS357-03); a failed morning is unexplainable after a week (DS357-06).

## 2. Findings (at most ten, Highs first)

Two High, two Med-High, two Medium, two Low.

### DS357-01 — High — FAST LANE — Garmin's stored login is refused since 00:25 GMT today, and nothing tells Craig
- **Evidence: observed.** `coach.job_runs`: `activity-poll` **failed** (`activity_poll_failed`, empty counters) at 00:25 and 01:25 UTC on 1 Nov; the 21:25, 22:25 and 23:25 UTC runs on 31 Oct succeeded. Railway `api` logs (current deployment): six `garmin token blob rejected` warnings (`error_class: GarminConnectAuthenticationError`, three per run, i.e. the retry loop), then `garmin activity poll failed` with `GarminLoginError: Garmin token blob failed and credentials are not configured`. `GARMIN_TOKENSTORE_B64` is still set on `api` (name checked, value not read) and `api` has not redeployed since 30 Oct 15:18, so the refusal came from Garmin's side (revoked or expired OAuth1 token, a Garmin password change, or a Garmin auth incident; the logs cannot tell which). `wake-check` still records `succeeded` only because it does not call Garmin before the 03:30 London window opens.
- **What Mark experiences if it persists (implemented):** from 03:30 the wake poll cannot read last night; his check-in waits on inputs ("held for unsynced inputs"), and the 11:00 backstop grades without the night or holds the morning. His ride sync stops, so post-ride reads and the deviation verdict do not arrive. He is told, in effect, that his watch has not synced, when the fault is the server's login.
- **Would anyone notice? (implemented):** no. The failure is a plain `log.exception` and a `warning`; neither carries the `admin_alert` tag, and there is no Garmin equivalent of the Hive `stale_source_alert` that reaches Craig. Batch 267 split `GarminLoginError` from transient errors so it *could* be routed, but no route was built. It reaches Craig only if Sentry emails him on a new issue by default (unknown: no Sentry access).
- **Fix and cost:** now: Craig re-checks the 02:25/03:25 UTC polls and, if still failing, re-mints the token blob (Mark's MFA code; a credential change, so Craig's step). Durable: tag `GarminLoginError` (and `hive_reauth_required`) as an `admin_alert` kind `source_auth`, under an hour plus a test.
- **Where it goes:** fast lane (Craig's re-mint); the tag folds into 337.1 or a small new row ahead of it.

### DS357-02 — High — Nothing outside the process watches the app, and the one watchdog built for it has never run
- **Evidence: observed + implemented.**
  - `ledger-freshness` (Batch 242.5's dead-scheduler watchdog, "external runner only" by design) has **0 rows in `job_runs`, ever**. It has no Railway service, no cron and no GitHub schedule; the only external runners are the two cron services of DS357-03, which run other jobs.
  - `/api/v1/health` never touches the database; `/api/v1/health/ready` does, but **nothing calls `ready` on a schedule**: Railway's health check uses `/health` and only at deploy; `deploy-freshness` runs only after a CI run on `main` and reads `/health` SHAs. On 25 Oct the database was unreachable from about 09:48 to 19:10 UTC (STATUS) while `/health` stayed 200; four daily jobs and the 18:00 weekly review were lost and no system raised it.
  - The Sentry route that every `admin_alert` relies on has no confirmed rule: Decision #451 deferred 337 ("skip the alerts reach me batch for now"), Batch 345 waits on it, and Sentry was not readable here. Sentry issue alerts fire on an issue's *first* event (or a regression), so a repeating failure of one kind alerts once at most ([Sentry: issue alert configuration](https://docs.sentry.io/product/alerts/create-alerts/issue-alert-config/)).
  - Of 66 `log.error`/`log.exception` sites in `src/`, 10 call `admin_alert`. Today's live example is DS357-01.
- **What Craig experiences:** he learns of an outage from Mark, from a scheduled review check, or by chance. The 25 Oct outage and today's Garmin refusal are two in eight days.
- **Fix and cost (smallest set):** one external probe that needs no new platform: a GitHub Actions `schedule` (every 15–30 min) that GETs `/api/v1/health/ready` and runs `ledger-freshness` logic against a read-only endpoint (or `railway run`-free: an authenticated `/health/jobs` that returns overdue jobs), failing the workflow so GitHub emails Craig. GitHub's failed-workflow email is the one route Craig already receives. Half a day to a day. Then 337.1's Sentry rule for the in-process alerts.
- **Where it goes:** undefer the watchdog part of 337 (337.2) now, ahead of the Sentry decision; it does not need it.

### DS357-03 — Med-High — The two Railway cron services never run a job, yet hold copies of every production secret they were given
- **Evidence: computed + observed.**
  - All 47 `trend-narratives` and `weekly-review` rows since 20 Sep start **within 3 ms after the minute** (e.g. 12:30:00.0008): that is APScheduler in the API process. A cron container cannot start its Python job that close to the minute. The single row outside that band is the 25 Oct 20:34 manual catch-up.
  - Railway `deployment list`: 60 `trend-narratives` deployments (26 Oct–30 Oct) and the same pattern for `weekly-review`; `railway logs -d` returns **no deploy-log line for any of the 60**, including those live across an 11:30/12:30 UTC fire time (28 Oct 11:46–13:41). Build logs are readable, so the log route works. Either Railway never starts these crons or they print nothing; neither command line's `echo` branch appears.
  - Both still carry `ANTHROPIC_API_KEY`, `DATABASE_URL`, `SENTRY_DSN_BACKEND` and the VAPID private key (names only checked); `weekly-review` also has `SUPABASE_SERVICE_KEY`. The 24 Oct rotation had to swap the database password on all three services (STATUS).
  - The `trend-narratives` command gates on London time reading exactly `1230`, so even a firing container a minute late would skip (R1's lead, confirmed by reading).
- **What it costs:** two extra copies of every secret on a platform that reported a breach on 21 Oct; every rotation is three edits; every push builds three images (60 deployments in five days); and Decision #266's "weekly review runs in both on purpose" redundancy did not cover the one Sunday it was needed (25 Oct).
- **Fix and cost:** delete both cron services (Craig's hosting change), or repurpose one as DS357-02's external watchdog with only `DATABASE_URL` (read-only role ideally) and the Sentry DSN. An hour plus Craig's console step.
- **Where it goes:** 337.2 (already names "both Railway crons crash"); its premise has decayed from "crash" to "never run". For reconsideration: Decision #266.

### DS357-04 — Med-High — The only backups are unencrypted archives on the breached platform, next to the service, and none has ever been restored
- **Evidence: observed + implemented.** The nightly `pg_dump` (7 kept) and the new Sunday full archive (4 kept) land on Railway volume `api-volume`, mounted in the `api` service (`.railway/railway.ts`); `backup.py` writes them owner-only but not encrypted. `backup-drill` has 3 of 3 `skipped (not_configured)` rows (11, 18, 25 Oct); `BACKUP_RESTORE_DATABASE_URL` is not among `api`'s variable names. Supabase's free plan has no automatic backups or point-in-time recovery ([Supabase: free-plan backups](https://supabase.com/kb/faqs/platform/free-plan-backups)). The first full archive is due 1 Nov 03:00 UTC, after this pass started; see §5.
- **What it means:** the archives hold Mark's whole health record (check-ins, symptoms, chat, sleep, HRV). Railway asked customers on 21 Oct to treat every variable as exposed; whether volumes were exposed is not stated in the repo. A Railway volume loss, an account lock-out or a deleted Supabase project loses the data with no tested way back.
- **Fix and cost:** encrypt archives with a public key whose private half is off-platform (age/gpg, under an hour); copy the weekly full archive off Railway (a scheduled GitHub Action pulling it is not possible without exposing it; simplest is Craig's machine or a private bucket); set the drill's database (a free Neon/second Supabase project, Craig's). A day plus Craig's account steps.
- **Where it goes:** 337.4 (DS328-11), with encryption added; undefer it independently of the Sentry decision.

### DS357-05 — Medium — Sentry receives the local variables of every failing frame, which can include Mark's health data
- **Evidence: implemented** (not observed: no Sentry access). `init_sentry` sets `send_default_pii=False` and a `before_send` that drops only `display_name`/`username`. The installed SDK (`sentry-sdk` 2.63.0) defaults `include_local_variables=True`, and its default scrubber removes credential-like keys only (`password`, `token`, `api_key`…). So a `log.exception` inside the morning pipeline, the coach chat or the memory reader ships the frame's locals (check-in notes, symptom answers, packets, prompt text), trimmed by the SDK's size limits, to a third-party processor. `exc_info` on the 66 error sites makes this the common case, not an edge.
- **What it means:** health data leaves the two processors the app's privacy stance names (Supabase, Anthropic) for a third, without a decision recording it.
- **Fix and cost:** `include_local_variables=False` (or strip `frames[].vars` in `before_send`) plus a unit test on the option. Fifteen minutes.
- **Where it goes:** a small new row; or with 337.1, since that batch already edits Sentry routing.

### DS357-06 — Medium — A degraded morning cannot be explained after a week: the failing stage is not recorded and Railway keeps logs about seven days
- **Evidence: computed + observed.** R1's lead. `morning-sync` was `degraded/step_failures` on 14, 17, 19 and 23 Oct. The counters separate them: on 14, 17 and 19 Oct `days` (weather days synced) is **0** against 9 on every other day, so those three are **Open-Meteo input failures**, harmless to Mark (his brief was already written and the forecast rows from the day before cover him). On 23 Oct weather and Garmin synced (`days` 9, `sleep` 4) yet `analyses_existing`, `analyses_generated` and `drivers_cached` are all 0 with one failure: a failure inside `generate_brief` at stage 1, 2 or 3. That is consistent with R1's CR356-01 (stage 2) **and** with a failed brief write on the day the Anthropic key was swapped (a `morning` generation request then completed at 10:55 UTC with a `brief_ready_push`). The log lines that would decide it are gone: `railway logs` returns nothing for the 23 Oct deployments (retention about seven days, per the project's own note).
- **What it means:** CR356-01 "has it fired?" stays unanswerable, and so will the next one unless the review runs within a week.
- **Fix and cost:** add `failed_steps` (names) to the job's counters and to `_isolated`'s outcome; `job_runs` keeps them indefinitely. Under an hour.
- **Where it goes:** with CR356-01's fix (same file).

### DS357-07 — Low — Daily cron jobs keep APScheduler's one-second misfire grace
- **Evidence: implemented + observed.** `create_scheduler` sets `misfire_grace_time=3600` on four jobs only (rail check, retention, proposal expiry, drill); APScheduler 3.11's default is **1 second**. A loop stalled for more than a second at 11:00:00 London, or a deploy that restarts the process at that minute (DS328-08), drops the backstop, the weekly review or the memory read with a warning only. Observed: no `missed by` line in two days of `api` logs, so it is not firing now (Batch 312 moved Garmin and Hive off the loop).
- **Fix and cost:** `AsyncIOScheduler(job_defaults={"misfire_grace_time": 900, "coalesce": True})`. Ten minutes plus a test.
- **Where it goes:** with 337.7 (DS328-08).

### DS357-08 — Low — A `SECURITY DEFINER` function in `public` is executable by `anon` and `authenticated`
- **Evidence: observed** (`get_advisors`, `pg_proc`). `public.rls_auto_enable()` returns `event_trigger`, so a call through `/rest/v1/rpc/` cannot run its body: harmless today, but it is the only advisor warning. It enables RLS on new tables in `public` only; `coach` tables rely on migrations, and all 32 have RLS (observed). `pg_trgm` sits in `public` (advisor warning, cosmetic).
- **Fix and cost:** `REVOKE EXECUTE … FROM anon, authenticated` in a migration. Five minutes; a database change, so with the next migration.
- **Where it goes:** fold into 209 (RLS) or any batch that ships a migration.

### 2a. Failure class → detected by → reaches Craig? → what Mark sees (headline question 1)

"Tagged" = an `admin_alert` kind, which reaches Craig only if the Sentry rule exists (unconfirmed; Decision #451). "Untagged" = a plain error log, which reaches him only if Sentry emails on any new issue by default (unknown).

| Failure | Detected by → reaches Craig? | What Mark sees |
|---|---|---|
| Garmin login refused (live now) | `job_runs` failed; untagged → **no** | brief held as if his watch had not synced; no ride reads |
| Garmin slow / 429 | retried; transient class | later brief |
| Hive down (20–25 Oct) | `job_runs` failed ×483; `hive_reauth_required` untagged → no | `stale_source_alert` push to him (7, 13–25 Oct) |
| Open-Meteo down | `degraded` row (14/17/19 Oct) → no | nothing (yesterday's forecast) |
| intervals.icu dormant | rail check, tagged `delivery_rail` → if rule | delivery warning |
| Dreo | fan job `skipped` → no | fan auto off |
| Anthropic 400 (credits or cap) | tagged `billing` → if rule | failure card + Retry; "today's call is ready" push |
| Timeout / malformed output | tagged `generation_failure` → if rule | failure card + Retry |
| Brief fails its own check | tagged `brief_check` (fired 31 Oct 09:07, logs) → if rule | the brief, as written |
| A job crashes | `job_runs` failed; watchdog never runs → **no** | depends on job |
| The scheduler stops | nothing (DS357-02) → **no** | no brief, no pushes |
| A cron crashes | crons never run (DS357-03) | — |
| DB full | `egress-budget` degraded `storage_critical`; untagged → no | writes fail |
| DB unreachable, `/health` 200 (25 Oct) | readiness says so, nobody asks → **no** | app errors; lost jobs |
| Backup fails / unrestorable | `job_runs` + untagged log → no; drill never ran | nothing until needed |
| Web and API out of step | `deploy-freshness` after CI on `main` → **yes** (GitHub email) | stale UI until refresh |

Only the last row has a route Craig is known to receive today.

## 3. Follow-through corrections (rows of the pack's table in this lens)

| Row | Pack says | Corrected to |
|---|---|---|
| DS328-02 | open; who runs the crons unverified | **open, premise changed:** the crons never run a job (0 of 47 rows; 0 deploy-log lines in 60 deployments); the API runs both jobs (DS357-03). The watchdog has 0 rows ever (DS357-02) |
| DS328-01 / DS237-01 | open; 9+ untagged sites | open; 10 of 66 error sites tagged; live example DS357-01 (Garmin auth) |
| DS328-04 | open | open, unchanged (observed): fixture identity block present (booleans: email, phone, postcode, coordinates, names all true), public since 20 Jun; 132 images, 3 screenshot folders (134 files), 2 root PDFs; notes-eval fixtures with real notes still tracked |
| DS328-05 | fixed (unproven) | unchanged; first full archive due 1 Nov 03:00 UTC (see §5) |
| DS328-10 | open | open, observed: public repo, secret scanning, push protection, validity checks, Dependabot security updates disabled; no rulesets; `main` unprotected |
| DS328-11 / DS237-04 | open | open, and wider: archives unencrypted on the breached platform (DS357-04) |
| DS237-05 (FORCE RLS) | deferred | accurate: 32 of 32 tables have RLS, 0 FORCE, `anon` has no usage on `coach` and no grants (observed). The external boundary is sound |
| DS237-06 (device tokens) | 42 unrevoked, expiry unchecked | **16 live** device tokens (365-day, expiring 22 Jun–17 Sep 2027; 5 from Jun, 8 Jul, 3 Sep) for one user; the other 26 unrevoked rows have expired. Still deferred; a revoke-all before a re-share is cheap |
| R1 lead: `degraded` backstops 14–23 Oct | — | 3 of 4 are Open-Meteo (computed); 23 Oct undecidable (DS357-06) |

**No live secret in git history (computed).** A pattern scan of every added line on all refs (Anthropic keys, Postgres URLs with passwords, JWTs, VAPID, Garmin blob, intervals key) found only placeholders (`<password>`, localhost) and the football app's test JWTs.

## 4. Queued and parked items in this lens, re-verified

| Item | Verdict |
|---|---|
| 337 (deferred, Decision #451) | **Mostly accurate; three decays.** 337.2's premise "crash" is now "never run" (DS357-03); 337.3 *is* R1's CR356-01 (same handler) and should leave 337 so it does not wait on the Sentry decision; 337.7 should name the one-second default (DS357-07). 337.1–337.6, 337.9, 337.10 references hold. A ledger line near the end still calls PR #380 a draft; it merged on 20 Oct (Batch 345) |
| 338 (decision-gated) | Accurate. 338.1–338.2 references hold at `083e012`. Nothing done |
| 209 (deferred until a second user) | Accurate in substance; its counts have decayed (29 → 32 tables, all RLS, 0 FORCE) |

## 5. For reconsideration · Hypotheses · Cross-lens leads · Limitations · Probe log

**For reconsideration.**
- **Decision #451 (337 deferred, "skip the alerts reach me batch for now").** New evidence: two operator-invisible failures in eight days (25 Oct database, 1 Nov Garmin login), the watchdog that would see a stopped scheduler has never run, and 337.2–337.4 and 337.7 do not depend on the Sentry rule that made 337 feel optional. Suggest splitting 337: the external watchdog, CR356-01/337.3, encryption and an off-Railway copy now; the Sentry rule and digest when Craig chooses.
- **Decision #266 (weekly review runs in the API and the cron on purpose).** The cron half has not run in the window this pass can see (DS357-03); the redundancy is on paper only.

**Near-optimal, leave alone (observed):** the external database boundary (no `anon` usage on `coach`, RLS on all 32 tables, no grants); device-token checks (expiry and revocation enforced on every request; activation links single-use, sign-in rate-limited); no secret in git history; 0 connections idle in a transaction; storage 196 MB for the coach database (221 MB all databases) of 500 MB, growing about 1.5 MB a day; the egress meter and split backup working as designed on their first day; `brief_check` firing as tagged (31 Oct 09:07).

**Hypotheses (unverified).**
- H1: today's Garmin refusal is a revoked OAuth1 token (a Garmin password change, or Garmin invalidating sessions after unusual sign-ins) rather than an outage; three attempts per hour all return an authentication error, not 5xx/429.
- H2: Railway may not start these cron services at all (`buildOnly: true` on every cron deployment, and not one runtime log line); proving it needs Railway's dashboard, which this pass could not read.
- H3: Sentry may already hold Mark's health text in exception frames (DS357-05); only someone with Sentry access can check.

**Cross-lens leads for the synthesis (not chased).**
- **R7:** what Mark's screen says when Garmin auth, not his watch, is the cause (DS357-01): the copy should not blame his watch.
- **R3:** the 23 Oct failed brief write on the key-rotation day; whether a revoked or wrong key is classified `billing`, `auth` or `other`, and what Mark was told.
- **Synthesis:** a standing guard for each of DS357-02/03/04: "the watchdog wrote a row in the last 24 h", "no service holds `ANTHROPIC_API_KEY` that does not use it", "a backup archive was restored in the last 7 days".

**Limitations.**
- **Sentry not readable** (no token): whether any alert rule exists, and whether today's Garmin failure produced an email, is unknown.
- Railway log retention is about seven days and per deployment, so 14–23 Oct log lines were gone; the cron question rests on `job_runs` timing and empty deploy logs, not on Railway's cron history page.
- The first full archive (1 Nov 03:00 UTC) and the 02:25 UTC Garmin poll were after this pass's evidence cut-off unless stated below.
- No probe ran the real backup or restore code (no restore database exists; a local `pgserver` restore would test the code, not the archive).
- Supabase's own egress dashboard and billing were not read.

**Probe log** (PROD = production read; all read-only; nothing written outside the scratch folders).
| # | What | Result |
|---|---|---|
| 1 | PROD `railway status`, `deployment list` (3 services, JSON) | cron deployments `buildOnly`, start commands as in `railway.ts` |
| 2 | PROD `railway logs -d` for all 60 `trend-narratives` deployments, and `weekly-review`'s latest | 0 lines each; build logs readable |
| 3 | PROD `railway logs` api, 2 days, `@level:error` / `@level:warn` / "missed by" | 11 error lines (2 Garmin poll, 1 brief_check, startup noise), 7 warnings (6 Garmin token), 0 missed |
| 4 | PROD api logs for the 23 Oct deployments | empty (retention) |
| 5 | PROD `railway variables --json`, names only, 3 services | lists in DS357-01/03 |
| 6 | PROD SQL: `job_runs` trend-narratives / weekly-review / ledger-freshness, 45 days (47 rows) | DS357-02/03 |
| 7 | PROD SQL: `job_runs` morning-sync non-ok (8 rows) and daily `days` counter (24 rows) | DS357-06 |
| 8 | PROD SQL: `brief_generation_status` 10 Oct–1 Nov (22 rows); 23 Oct analyses / generation requests / audit (4 rows) | DS357-06 |
| 9 | PROD SQL: `job_runs` activity-poll / wake-check from 31 Oct 21:00 (28 rows) | DS357-01 |
| 10 | PROD SQL: `refresh_tokens` counts by purpose and month; `pg_stat_activity` idle-in-transaction; database size | §3 |
| 11 | PROD `get_advisors(security)`; SQL on `pg_proc`, `pg_class`/`pg_policy` grants, `authenticator` config | DS357-08, §3 |
| 12 | `gh api` repo security settings, branch protection, rulesets | §3 |
| 13 | Local: fixture identity booleans; `git ls-files` images/PDFs/screenshots; history secret scan (counts only) | §3 |
| 14 | Local: SDK defaults (`sentry-sdk` 2.63.0, APScheduler 3.11.2) | DS357-05/07 |
| 15 | Web: Sentry issue-alert docs; Supabase free-plan backup FAQ | cited |
| — | Paid calls | **none ($0)** |
