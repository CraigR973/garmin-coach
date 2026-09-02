# Batch 237 — Data, security and operations review

**Date:** 2026-09-01
**Wave:** audit wave #4 (Batches 236–241), pass 2 of 6 — see
`docs/reviews/BATCH_236-241_AUDIT_SCOPE.md`
**Tier:** 🔴 High
**Mode:** diagnose-only. No product code, migration, database policy, provider
configuration or production row was changed. Every production statement in this
document is a `SELECT`, a catalog read, a read-only container probe, or an
unauthenticated HTTP GET.
**Code baseline:** `2178381` (`docs: close out batch 233`)
**Production baseline:** Supabase project `pzqmswvozjnkxbqqowuj` (PostgreSQL
17.6), Railway `api` + `weekly-review`, Vercel `garmin-coach-one.vercel.app`,
all observed 2026-09-01.
**Predecessor:** `BATCH_190_DATA_SECURITY_OPS_REVIEW.md` (2026-08-06). Every
DS190 finding is re-verified below.

**Egress discipline.** The Supabase org is over its 5 GB free-plan egress
allowance until 2026-09-21. Every query in this review is column-projected or a
server-side aggregate; no JSONB payload column was ever transferred, and the
largest result set returned to the reviewer was 18 rows.

---

## Executive summary

**The security boundary is in good shape and has got better.** All 29 `coach`
tables have RLS enabled; `anon`, `authenticated` and `service_role` have no
`USAGE` on the schema and no table grants; there are no `coach` views, no
cross-schema foreign keys, and no function outside `coach` whose body mentions
`coach.`. The Supabase security advisor reports **zero WARN for `coach`** —
25 INFO `rls_enabled_no_policy` notices that describe the intended deny-all
posture, and nothing else. The performance advisor reports **zero WARN for
`coach`** as well. All 91 API method/path pairs resolve an auth dependency
except the four deliberately public ones, and both of Batch 190's low-severity
authorization findings (DS190-08 403/404 disclosure, DS190-09 missing redundant
`user_id` predicate) have been **fixed** and carry comments naming the finding
they closed.

**Execution reliability has genuinely moved.** Batch 190's headline finding —
ten of eleven jobs riding an APScheduler inside a service Railway was told to
sleep — no longer holds: `sleepApplication` is now `false`, `numReplicas` is 1,
and fourteen days of `job_runs` show `hive-poll` firing 1,370 times against a
15-minute schedule (≈ every 14.7 minutes). The typed `JobResult` / `job_runs`
ledger that DS190-02 asked for exists and works.

**What has not moved is the part that turns a failure into a person knowing
about it.** Production has *no* operator alert route at all. `SENTRY_DSN_BACKEND`
is unset, so `main.py` never initialises Sentry; `ADMIN_ALERT_USER_ID` is unset,
so Batch 141's admin push is dormant; and the `alert_route:
provider_log_or_external_monitor` field that four separate alert helpers stamp
onto their log lines names a consumer that does not exist. Two jobs failed in
the last fortnight — `longitudinal-analysis` on 2026-08-25 (`unhandled_exception`)
and `morning-sync` on 2026-08-28 (`morning_pipeline_failed`) — and both are
visible only because this review went looking in the table.

**Three measurements are worse than the documents assume.**

1. **The database is at roughly 90% of the free-plan storage cap, and nothing
   watches it.** `pg_database_size` is **451,267,731 bytes** against a
   documented 500 MB Free-plan allowance. `coach.activity_timeseries` is
   353 MB of that. Growth measures ≈1.85 MB/day. This app has already filled
   its disk once (DECISIONS #93, 2026-06-28, at ~625 MB — the incident where
   `VACUUM FULL` could not run because there was no room to write the copy).
   Egress got a meter after its incident; storage got nothing.
2. **The egress meter is wrong in three independent ways at once**, not one.
   On 2026-08-30 — the day Supabase attributed 6.475 GB to this project — the
   meter recorded **16,312,169 bytes** and stayed at stage `ok`. That is a
   ~397× understatement, and two of the three causes were never recorded.
3. **No backup of this application has ever been restored.** `backup-drill` has
   **zero** `job_runs` rows in the whole history of the table, is not registered
   in the scheduler, and `BACKUP_RESTORE_DATABASE_URL` is unset so a manual run
   would fail immediately. Retention is seven days on one Railway volume with
   no off-site copy, and 353 MB / 665,259 rows of `activity_timeseries` are
   excluded from every archive by design.

**Batch 208–210 triggers.** 208's durable half is **not** triggered by anything
new, but this review found a concrete mechanism for it that the row lacks
(DS237-11). 209's trigger has **not** fired: still one production profile, still
no second user; the posture is unchanged at 29/29 RLS, **0/29 FORCE**, all owned
by `postgres`. 210's trigger already fired twice and Batch 232 amended the row
accordingly; nothing in this pass changes that.

**17 findings: 4 High, 5 Medium, 8 Low** (`DS237-01…17`).

---

## 237.1 — What moved since Batch 190

| DS190 | Batch 190 state | 2026-09-01 state |
|---|---|---|
| **DS190-01** sleeping web process is the scheduler | `sleepApplication=true`; 10/11 jobs in-process | **Largely closed.** `sleepApplication=false`, `numReplicas=1`, `restartPolicyType` `ON_FAILURE` on the running manifest. 14 days of `job_runs`: `hive-poll` 1,370 runs, `wake-check` 1,360, `egress-budget` 1,341, `backup` 14/14, `evening-nudge` 14/14. Topology is unchanged (one external cron) but the premise that made this High is gone. Residual folds into DS237-01. |
| **DS190-02** a failed job reports success | no ledger, external runner exits 0 | **Half closed.** `JobResult`/`JobStatus`, `run_tracked_job` writing `coach.job_runs` in an independent session, and `exit_code` 1 for `degraded`/`failed` all shipped. The other half — that nothing reads the ledger — is **DS237-01**. |
| **DS190-03** backup alertless and restore-unproven | 7 failure rows, no drill | **Split.** The backup itself is now healthy and correct (below). Alerting is still absent (**DS237-01**); the restore drill has still never run (**DS237-04**). |
| **DS190-04** deploy freshness is human-only | current SHA, no automation | **Unchanged.** Both surfaces serve `21783812758d002477a5f6bad33845c7a084b854`, equal to local `main`. Still no automated comparison. **DS237-15**. |
| **DS190-05** RLS does not constrain the app owner | 28/28 RLS, 0 FORCE | **Unchanged**, now 29/29 and 0 FORCE. **DS237-05**. |
| **DS190-06** shared public app in the blast radius | boundary holds; public WARNs | **Boundary re-verified holding.** The public advisor picture has *improved*: all four `SECURITY DEFINER` functions now carry pinned `search_path`s, and 26 of 27 `public` tables are RLS deny-all. Five mutable-search-path WARNs remain, all on `SECURITY INVOKER` trigger functions. Batch 208.1 is still unstarted. **DS237-12**, plus the new mechanism in **DS237-11**. |
| **DS190-07** egress has no budget control | none | **A meter shipped (Batch 204) and it does not measure egress.** **DS237-03**. |
| **DS190-08** 403 for foreign, 404 for unknown | open | **Fixed.** `BriefChatService._owned_analysis` (`services/brief_chat.py:312-330`) returns 404 for both and keeps the distinction in a structured log. |
| **DS190-09** history relies on a write invariant | open | **Fixed.** `history()` now filters `BriefMessage.user_id == player.id` alongside `analysis_id` (`services/brief_chat.py:343-352`). |

---

## 237.2 — Live RLS and database posture

Measured 2026-09-01 against production.

| Control | Live result |
|---|---|
| Alembic head (DB) | `030` — matches `migrations/versions/030_rem_intervention_feedback.py` |
| PostgreSQL server | 17.6 |
| `coach` tables | **29 / 29 `relrowsecurity = true`** |
| `coach` FORCE RLS | **0 / 29 `relforcerowsecurity = true`** |
| `coach` table owners | 1 distinct owner: `postgres` — the role FastAPI connects as |
| `coach` policies | 9 policies across 4 tables (`profiles`, `refresh_tokens`, `push_subscriptions`, `notification_preferences`) |
| `anon` / `authenticated` / `service_role` on `coach` | `USAGE` **false**, `CREATE` **false**, **zero** table grants |
| `coach` views / materialized views | 0 |
| Cross-schema FKs between `coach` and `public` | 0 |
| Non-`coach` functions whose body references `coach.` | 0 |
| `public` tables | 27, all RLS-enabled, 26 of them deny-all |
| Database size | **451,267,731 bytes** (`coach` 414,670,848 · `public` 23,740,416) |

**Security advisor, live.** 25 INFO `rls_enabled_no_policy` for `coach` (up from
24 — `job_runs` arrived with migration `027`), 26 INFO for `public`, and
**0 WARN for `coach`**. The 12 WARNs are all `public`: five
`function_search_path_mutable`, one `extension_in_public` (`pg_trgm`), and eight
`SECURITY DEFINER` executable notices covering four functions. Three of those
four (`handle_new_user`, `lock_role_column`, `rls_auto_enable`) return
`trigger`/`event_trigger` and cannot be invoked as a PostgREST RPC; the fourth,
`get_my_role()`, has `search_path=""`. Batch 190's conclusion is re-verified,
and the four functions' `search_path`s are now all pinned, which they were not
in August.

**Performance advisor, live.** 84 lints, **0 WARN for `coach`**: 9 INFO
unindexed foreign keys and 1 INFO unused index (`ix_experiments_user_status`) in
`coach`; every WARN (2 `auth_rls_initplan`, 5 `multiple_permissive_policies`)
belongs to the co-resident `public` app.

**One nuance nobody has recorded.** The nine `coach` policies from migration
`025` all key off `auth.uid()` (`025_security_ops_rls_hardening.py:68-113`).
This application does not use Supabase Auth — it issues its own opaque device
tokens — so no client will ever present a Supabase JWT, and `auth.uid()` can
only ever evaluate to `NULL` here. Those policies therefore deny everything,
exactly like the 25 tables with no policy at all. That is fail-closed and not a
defect, but it means the "four client-facing tables are policy-protected /
twenty-five are deny-all" distinction in the Batch 190 write-up describes intent
rather than a behavioural difference. Recorded so a future reader does not
mistake the nine policies for working access control.

---

## 237.3 — Authentication and authorization

**Model.** `POST /api/v1/auth/activate` exchanges a single-use, 30-minute,
256-bit activation code (`secrets.token_urlsafe(32)`, SHA-256 hashed at rest)
for a 365-day opaque device token, also 256-bit and SHA-256 hashed at rest
(`auth.py:22-42`, `routers/auth.py:56-124`). Resolution is a single join that
requires the row to be `purpose='device'`, unrevoked, unexpired, and to belong
to an active, non-deleted profile (`auth.py:50-68`).

**Consumption is atomic.** The activation code is consumed by an
`UPDATE … WHERE used_at IS NULL … RETURNING user_id` (`routers/auth.py:65-78`),
so two concurrent redemptions of the same code cannot both succeed. Replay of a
used, revoked or expired code returns the same 401 as an unknown code.

**Route surface.** 91 method/path pairs. Exactly four resolve no auth
dependency, and they are the four the repository guard permits
(`tests/test_route_auth_inventory.py:13-18`): `GET /api/v1/health`,
`GET /api/v1/health/ready`, `POST /api/v1/auth/activate`,
`GET /api/v1/push/vapid-public-key`. Three routes are admin-gated, all in
`routers/coaching_state.py`.

**Rate limiting.** Nine paid-generation routes share one 30/hour budget keyed by
the resolved profile id (`rate_limit.py:37-41`), TTS synthesis has its own
60/hour, the notification test-push 5/hour, and `/activate` 10/hour. Spot-checks
of the nine unlimited routers (`strength_brief`, `walking_brief`,
`breathwork_brief`, `plan_actions`, `block_generator`, `insights`,
`restructure`, `workout_delivery`, `experiments`) found no Anthropic call site,
so the paid surface is covered.

**Cross-user reachability.** Production holds exactly **one** profile
(`4c20033a-…`, role `admin`, `Europe/London`, active, not deleted). No second
user exists, so no cross-user path can be exercised in production today. The
structural answer is unchanged and is DS237-05: the application connects as the
table owner with FORCE RLS off, so nothing below the ORM enforces the `user_id`
predicate.

**What the credential inventory shows.**

| `purpose` | rows | revoked | used | live & unexpired | latest expiry |
|---|---:|---:|---:|---:|---|
| `device` | 31 | 18 | — | **13** | 2027-08-06 |
| `activation` | 28 | 5 | 23 | 0 | 2026-08-06 |
| `refresh` (legacy) | 73 | 73 | — | 0 | 2026-08-25 |

Thirteen live 365-day bearer credentials for one person, with no `last_used_at`
column on `refresh_tokens` and no in-app device list. That is **DS237-06**.

---

## 237.4 — Secrets

**Repository.** `.env.example` contains placeholders only; no real key, token or
password appears in it. The one real identifier committed is
`INTERVALS_ATHLETE_ID=i618709` (also a `config.py` default) — an account
identifier, not a credential.

**Railway `api` service** holds 15 non-platform variables. `SENTRY_DSN_BACKEND`
is **not** among them, and neither is `ADMIN_ALERT_USER_ID`, `SCHEDULER_ENABLED`,
`FORWARDED_ALLOW_IPS`, `BACKUP_RESTORE_DATABASE_URL`, or any `ANTHROPIC_*`
variable other than the key — consistent with `.env.example`'s note that
production runs on code defaults.

**Railway `weekly-review` service** holds 7, including a second copy of
`SUPABASE_SERVICE_KEY` and `VAPID_PRIVATE_KEY`.

**Findings from the inventory.**

- `SUPABASE_SERVICE_KEY` is set in both services, is **forced to be non-empty in
  production** by `config.py:262-263`, and is **read by no code in the
  repository** (grep across `apps/`, `scripts/`). It authenticates as
  `service_role`, which has `rolbypassrls = true`. It cannot reach `coach` —
  `has_schema_privilege('service_role','coach','USAGE')` is `false` — but it is
  a full RLS-bypassing credential for the co-resident app's 27 `public` tables,
  held for no reason by an application that never uses it. **DS237-07.**
- `GARMIN_PASSWORD`, `HIVE_PASSWORD` and `DREO_PASSWORD` are all present
  alongside the token stores that are the actual operating path. `HIVE_PASSWORD`
  cannot even be used headlessly (Cognito SMS MFA, DECISIONS #59), and
  `GARMIN_TOKENSTORE_B64` is set. The Hive and Dreo credentials carry
  physical-world authority — heating and a bedroom fan. Keeping the Garmin
  password is a defensible self-heal trade when the garth cache expires
  (~mid-2027); keeping the Hive password is not, since it cannot complete a
  login. Noted here rather than raised as its own finding, because the exposure
  is bounded by the same Railway account that already holds `DATABASE_URL`.

**Secrets in logs.** A grep of every `log.*()` call in `apps/api/src` for
token/password/key/credential/payload/prompt arguments returns exactly two hits,
both benign (`scheduler.py:1860` logs the *reason* `no_dreo_credentials`;
`routers/auth.py:145` logs a profile UUID). The backup service keeps the
password out of `argv` by passing `PGPASSWORD` in the child environment and
strips it from the DSN it does pass (`services/backup.py:55-61, 108-124`).
Sentry — if it were ever enabled — runs `send_default_pii=False` plus a
`before_send` that strips `display_name`/`username` (`main.py:59-76`).

**PII to third parties.** See **DS237-09**: `docs/claude-api-review.md`'s F4 is
unmoved and is in fact wider than F4 described.

---

## 237.5 — The egress meter that reads green in the wrong direction

The follow-up recorded by Batch 235 is real, and it is three defects, not one.

**Defect A — the meter counts the opposite direction.**
`EgressBudgetMiddleware` (`middleware.py:25-42`) sums `Content-Length` on
outbound HTTP responses. The traffic that bills is pooler → application: a
`sleep` row is 12,670 bytes on disk and 105,550 on the wire (DECISIONS,
Batch 235). The proxy cannot observe that direction at all.

**Defect B — the one "exact" contributor is counted at the wrong size.**
`run_egress_budget_check` adds the day's backup archive size
(`scheduler.py:390-394`), and `services/backup.py:96-99` justifies it with the
comment *"Custom format is compressed on the way out of the server, which is
what actually bills as egress."* That is false. `pg_dump --format=custom`
compresses **client-side**, inside `pg_dump`, after receiving an uncompressed
`COPY` stream; PostgreSQL 17 has no libpq protocol compression. Measured
server-side with `sum(length(col::text))` — a scalar aggregate, so the
measurement itself moved a few bytes:

| Table | uncompressed JSON text in the archive's scope |
|---|---:|
| `sleep.raw_payload` | 46,128,872 B |
| `daily_metrics.raw_payload` | 20,235,344 B |
| `temperature_readings.raw_payload` | 15,842,197 B |
| `analyses.context_packet` + `raw_response` | 6,737,666 B |
| `activities.raw_summary` | 5,160,923 B |
| `weather_daily.raw_payload` | 27,326 B |
| **JSONB total** | **94,132,328 B** |

Plus every typed column in 28 tables. So the nightly dump pulls **well over
100 MB** across the pooler and is recorded as the 10.5 MB archive it writes —
roughly **3 GB/month of real egress against a 5 GB monthly org-wide allowance,
booked as ~0.3 GB.**

**Defect C — a daily total is compared against a monthly cap.**
`evaluate_stage(bytes_used_today, BUDGET_BYTES=5_500_000_000)`
(`services/egress_budget.py:41-50`) is called with `total_today`
(`scheduler.py:415-417`). `BUDGET_BYTES` is the **org-wide monthly** free-plan
cap. Warning therefore fires at 2.75 GB **in a single day**; a steady 200 MB/day
— 6 GB/month, over the cap — scores 0.036 and reads `ok` forever.

**What the meter actually reported.** Eight days of `egress-budget` counters:

| Date | `response_bytes_delta` sum | max `total_bytes_today` | max stage |
|---|---:|---:|---:|
| 2026-09-01 | 1,766,889 | 12,521,616 | 0 (`ok`) |
| 2026-08-31 | 2,696,241 | 13,359,947 | 0 |
| **2026-08-30** | **5,763,178** | **16,312,169** | **0** |
| 2026-08-29 | 2,291,883 | 12,739,447 | 0 |
| 2026-08-28 | 4,549,120 | 14,884,680 | 0 |
| 2026-08-27 | 1,771,456 | 12,007,377 | 0 |
| 2026-08-26 | 3,557,638 | 13,683,704 | 0 |

2026-08-30 is the incident day Supabase attributed **6.475 GB** to this project.
The meter said 16.3 MB and `ok`. **≈397× understated.**

**Fix shape.** Three parts, in order of value.

1. **Truth in labelling, immediately.** Rename the counter and its alert copy to
   `http_response_bytes`. It is a fine leading indicator of *API* traffic; it is
   not egress, and the alert currently says it is.
2. **Measure the direction that bills, cheaply.** The dominant term in both the
   2026-08-04 and 2026-08-30 incidents was JSONB text, and SQLAlchemy gives a
   one-line hook for exactly that: pass a `json_deserializer` to
   `create_async_engine` that adds `len(raw)` to a process counter before
   `json.loads(raw)`. Every JSON/JSONB byte crossing the pooler is then counted
   exactly, for the cost of one `len()` per value. Add a flat per-row estimate
   for typed columns from `after_cursor_execute`'s row count if a total is
   wanted, and drain both into the existing `job_runs` counter alongside the
   HTTP number rather than instead of it — the comparison between the two is
   itself the diagnostic.
3. **Fix the two arithmetic errors while the file is open.** Estimate the
   backup's wire cost as the uncompressed dump size (or simply measure the
   `pg_dump` child's stdout/stderr-free byte throughput), and stage against a
   *rolling 30-day* total, not a single day, against the monthly cap.

Nothing here needs a Supabase Management API. It stays a proxy — but a proxy
pointed at the right direction, at the right scale, over the right window.

---

## 237.6 — Backups

**What is right, verified live in the container.**

| Check | Evidence |
|---|---|
| Volume | Railway `api-volume`, 4.6 G filesystem, 71 M used, mounted at `/data/backups`; `BACKUP_DIR=/data/backups` |
| Currency | 7 archives, `coach_20260826_030000.dump` … `coach_20260901_030000.dump`, one per night, latest 10,754,727 B |
| Job record | `job_runs`: `backup` **succeeded 14 / 14** in the last 14 days, last start 2026-09-01 03:00:00 UTC |
| Permissions | directory `0700`, every archive `0600` |
| **Version pin** | `pg_dump (PostgreSQL) 17.11` / `pg_restore 17.11` against **server 17.6** — the client is ahead of the server, so the mismatch that silently broke five nights cannot recur. The PGDG pin in the `Dockerfile:5-19` holds. |
| Structure | `pg_restore --list` on the latest archive exits 0, 245 entries, **28 `TABLE DATA` entries** (27 at Batch 190 + `job_runs`), `activity_timeseries` retains its table/PK/unique/index/FK definitions with **no** data entry |
| Failure history | `coach.audit_log` holds 7 `backup_failed` rows, all from the 2026-07-29 → 2026-08-04 outage; none since |

**What is still not established, and it is the whole point of a backup.**

- **`backup-drill` has never run.** Zero rows in `coach.job_runs` for that job
  name, ever — not just in the 14-day window. `run_backup_restore_drill`
  (`scheduler.py:325-343`) exists and is wired into `run_scheduled.py:71`, but
  it is **not** among the 16 jobs `create_scheduler()` registers, and
  `BACKUP_RESTORE_DATABASE_URL` is unset in production, so a manual invocation
  would fail at the first call. Batch 196 built the machinery; nothing has ever
  used it against a real archive.
- **Retention is 7 days, single-location.** `BACKUP_RETENTION_COUNT` prunes to
  seven; all seven live on one Railway volume in the same account as the
  application. There is no off-site copy and no documented RPO/RTO. Corruption
  noticed on day eight is unrecoverable, and Supabase's Free plan has no managed
  backup or PITR behind it.
- **353 MB / 665,259 rows of `activity_timeseries` are in no archive.** That is
  a deliberate egress trade and the largest single reason the dump is 10.5 MB
  rather than hundreds — but it means a restore returns an application whose
  per-second sample history is gone, and two live read paths
  (`post_workout_analysis.py:855-866`, `post_walk_analysis.py:574-585`) query
  that table. Batch 190 recorded that "normal API code does not read
  `ActivityTimeSeries` at all"; that is **no longer true**.

---

## 237.7 — Job failure visibility

**The ledger works.** `run_tracked_job` (`services/job_runs.py:118-176`) catches
anything that escapes the operation, converts it to
`JobResult.failed("unhandled_exception")`, and writes the row in its **own**
session so a poisoned job session cannot erase the evidence. `scheduled_window`
files each run into the cadence bucket it belongs to. `run_scheduled.py:86-90`
raises `SystemExit(1)` for `degraded` and `failed`.

**Nothing reads it.** The only consumer of `JobRun` anywhere in the application
is `run_egress_budget_check`, reading *its own* prior counters
(`scheduler.py:400-406`). There is no freshness monitor, no "job X has not
succeeded in its window" check, and no alert.

**Last 14 days, from `coach.job_runs`:**

| Job | succeeded | skipped | failed | last start (UTC) |
|---|---:|---:|---:|---|
| `hive-poll` | 1,370 | — | — | 2026-09-01 12:04 |
| `wake-check` | 1,360 | — | — | 2026-09-01 12:05 |
| `egress-budget` | 1,341 | — | — | 2026-09-01 11:53 |
| `fan-control` | 650 | 708 | — | 2026-09-01 12:06 |
| `activity-poll` | 357 | — | — | 2026-09-01 11:52 |
| `evening-alerts` | 224 | — | — | 2026-08-31 21:45 |
| `autopush` | 42 | — | — | 2026-09-01 12:00 |
| `backup` | 14 | — | — | 2026-09-01 03:00 |
| `evening-nudge` | 14 | — | — | 2026-08-31 19:00 |
| `post-workout-backstop` | 14 | — | — | 2026-08-31 19:30 |
| `state-change` | 14 | — | — | 2026-09-01 10:45 |
| **`morning-sync`** | 13 | — | **1** | 2026-09-01 10:00 |
| `baseline-refresh` | 6 | — | — | 2026-09-01 01:30 |
| **`longitudinal-analysis`** | — | 7 | **1** | 2026-09-01 11:15 |
| `weekly-review` | 2 | — | — | 2026-08-30 17:00 |
| **`backup-drill`** | **—** | **—** | **—** | **never** |

The two failures:

- `2026-08-28 10:00` `morning-sync` → `morning_pipeline_failed`, 97.9 s
- `2026-08-25 11:15` `longitudinal-analysis` → `unhandled_exception`, 0.78 s

**Both went to nobody.** `morning-sync` failing is a morning Mark did not get a
brief from the backstop; whether the wake-triggered path covered it is not
recorded in this table. That is DS237-01, and it is the highest-value fix in
this pass.

The one absence-detector that exists is Batch 228's `metric_baselines_stale`
check inside `evening-alerts`, which emits `_log_operator_alert` — into the same
route with no consumer.

**The `weekly-review` cron is correct.** `0 17,18 * * 0` with the start command
gating on `TZ=Europe/London date +%H = 18`, `restartPolicyType=NEVER`. Two runs
in 14 days is exactly right. The gated hour exits 0 from the shell without
writing a `job_runs` row, which is fine but means "no row for hour 17" and "the
container never started" are indistinguishable — a detail for whatever freshness
monitor gets built.

---

## 237.8 — The co-resident public application

The SQL boundary **holds**, re-verified: no cross-schema foreign key, no `coach`
view, no non-`coach` function body referencing `coach.`, no schema `USAGE` and no
table grant for `anon`/`authenticated`/`service_role`. `service_role` bypasses
RLS but cannot reach the schema, so even the service key does not open `coach`.

Two things are new since Batch 190.

**The public app's own posture improved.** 26 of its 27 tables are RLS-enabled
with no policy, and all four of its `SECURITY DEFINER` functions now pin
`search_path`. The residual WARNs are five `SECURITY INVOKER` trigger functions
with mutable search paths, `pg_trgm` in `public`, and the eight advisory notices
about those four definer functions — three of which return `trigger` or
`event_trigger` and cannot be reached as an RPC.

**A mechanism for the shared blast radius that Batch 208.2 does not name.** The
database carries an event trigger `ensure_rls` on `ddl_command_end`, owned by
`postgres`, whose function is `public.rls_auto_enable()` — an object belonging to
the co-resident app. It fires on **every DDL statement in this database**,
including every `alembic upgrade head` that runs in this app's container start
command (`Dockerfile:67`). Today's body only acts on `schema_name IN ('public')`
and wraps its `ALTER TABLE` in its own `EXCEPTION WHEN OTHERS`, so it is benign.
But it is a foreign object executing inside this application's migration
transactions, and the API's `CMD` is `alembic upgrade head && uvicorn …` — a
migration failure is a boot failure. That is a sharper argument for 208.2 than
"shared owner, shared quota", and it costs nothing to record. **DS237-11.**

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| DS237-01 | **High** | No operator alert reaches anyone, on any path — both halves of the design are unwired in production |
| DS237-02 | **High** | The database sits at ~90% of the Free-plan storage cap, growing ~1.85 MB/day, with no monitor — the one cap this app has already been bitten by |
| DS237-03 | **High** | The egress meter is wrong in three independent ways and reported 16.3 MB / `ok` on a 6.475 GB day |
| DS237-04 | **High** | No backup has ever been restored; the drill is unregistered and its target unconfigured; 7 days, one location, one large table absent |
| DS237-05 | Med | RLS still does not constrain the application, and the nine policies that exist can never evaluate true |
| DS237-06 | Med | Thirteen live 365-day device tokens on one profile, with no last-used, no device list and no revoke-all |
| DS237-07 | Med | An unused, RLS-bypassing Supabase service key is required at startup and held in two services |
| DS237-08 | Med | The audit log has one writer and records no user action at all |
| DS237-09 | Med | F4 is unmoved and wider: Mark's home coordinates reach Anthropic twice per morning brief with no consumer |
| DS237-10 | Low | The activation rate limit is effectively one global bucket, not per-client |
| DS237-11 | Low | A co-resident app's event trigger executes inside every migration this app deploys |
| DS237-12 | Low | Batch 208.1 is unstarted: `coach` and the public app share one advisor queue |
| DS237-13 | Low | The only production profile is `admin`, so the admin gate separates nothing |
| DS237-14 | Low | Activation codes travel in a query string |
| DS237-15 | Low | Stale-deploy detection is still human-only (DS190-04, unmoved) |
| DS237-16 | Low | A 401 clears the device token but not the persisted brief cache |
| DS237-17 | Low | Three residual Batch 235-class full-row reads remain |

---

### DS237-01 — High — no operator alert reaches anyone, on any path

**What is wrong.** The application has a carefully designed two-tier alerting
model and neither tier is connected in production.

- The **push** tier: `NudgeAlertService.push_admin_generation_alert`
  (`services/nudge_alerts.py:685-729`) pushes to
  `settings.admin_alert_user_id`. `ADMIN_ALERT_USER_ID` is **not present** in
  the Railway `api` service's variables, so `raw_admin_id` is `""` and the
  method returns `False` before touching the session. Dormant, exactly as the
  docstring anticipated.
- The **log** tier: four helpers — `_log_backup_operator_alert`,
  `_log_operator_alert`, `_log_egress_operator_alert` (`scheduler.py:346-372`,
  `429-437`) and the `log.error("brief_generation_admin_alert", …)` inside the
  push method — all emit at `error` level with
  `alert_route="provider_log_or_external_monitor"`. That field names a consumer.
  **There is no consumer.** `SENTRY_DSN_BACKEND` is not set on either Railway
  service, so `main.py:68` never calls `sentry_sdk.init`, and nothing in the
  repository configures a log drain or external monitor.
- The **ledger** tier: `coach.job_runs` records every outcome faithfully and is
  read by nothing except the egress job reading its own counters.

**Where.** `config.py:207-211`; `main.py:59-76`; `services/nudge_alerts.py:696-716`;
`scheduler.py:346-372`, `429-437`; `services/job_runs.py:118-176`;
Railway `api`/`weekly-review` variable sets.

**Failure scenario (already happened, twice).** On 2026-08-28 `morning-sync`
failed after 97.9 s with `morning_pipeline_failed`; on 2026-08-25
`longitudinal-analysis` failed with `unhandled_exception`. Both wrote a `failed`
row. No push fired, no Sentry event was created, no exit code was observed
(both ran in-process, not through `run_scheduled.py`). Craig learned about both
from this review, four and seven days later. Scale that to the failure mode the
alerting was *built* for — the 2026-07-21 Anthropic credit freeze and the
2026-08-31 spend-cap freeze — and the app silently stops producing Mark's brief
until he mentions it.

**Evidence.** `proved` for the configuration (variable listings, `main.py`'s
guard, the empty-string early return) and for the two failed rows. `observed`
for "nobody was told", inferred from the absence of any consumer rather than
from a missed notification.

**Fix shape.** In increasing cost:

1. **Two environment variables.** Set `SENTRY_DSN_BACKEND` on both services —
   `main.py` already initialises on it, with PII scrubbing and a 5% trace rate
   — and set `ADMIN_ALERT_USER_ID` to a Craig-owned profile. That single change
   converts every existing `log.error` alert hook from decoration into a real
   signal, with no code at all. Note the admin push needs a *second* profile to
   exist, which prod does not currently have; the Sentry half needs nothing.
2. **A freshness job that reads the ledger it already has.** One query per
   expected cadence — "did job X record a non-failed run in its most recent
   window?" — emitted as one `operator alert` per stale job. It must not run
   inside the scheduler it monitors; the `weekly-review` cron service is the
   existing external foothold.
3. **Widen the boundary that swallowed the spend cap.** The gotcha recorded in
   STATUS stands: a configured-spend-cap rejection arrives as HTTP 400
   `invalid_request_error` and `classify_anthropic_error` maps it to
   `invalid_request`, which fires no admin alert. Match on the wording as well
   as the status, or treat any repeated `invalid_request` on a paid path as
   operator-alertable.

---

### DS237-02 — High — the database is at ~90% of the storage cap, unmonitored

**What is wrong.** `pg_database_size` measures **451,267,731 bytes**
(430 MiB). Supabase's published Free-plan database-space allowance is 500 MB,
and DECISIONS #34/#93 already treat that number as a hard constraint. Nothing in
the application, the scheduler or any runbook measures it. Egress got a meter
after its incident; storage — which has *also* already caused an incident — got
nothing.

**Where.** `coach.activity_timeseries` is **370,565,120 bytes** (353 MB) of the
total: 223 MB heap, 130 MB across three indexes, 665,259 rows spanning
2025-06-24 → 2026-09-01. `public` (the co-resident app) is 23.7 MB. The rest of
`coach` is 44 MB.

**Growth, measured two independent ways.** Batch 190 recorded 596,040 live
`activity_timeseries` rows on 2026-08-06; today's count is 665,259 — 2,662
rows/day over 26 days. Counting forward instead, 77,334 rows carry a
`timestamp_utc` inside the last 30 days — 2,578/day. At 557 bytes/row including
indexes that is ≈1.45 MB/day, and `temperature_readings` (~180 KB/day),
`job_runs` (7,413 rows since 2026-08-15, ~436/day, no retention policy at all)
and `sleep` add ≈0.4 MB/day. **≈1.85 MB/day, ≈56 MB/month.**

**Failure scenario.** At 1.85 MB/day the remaining 48.7 MB to a 500 MB quota is
consumed in **about four weeks** — putting the crossing in late September 2026,
overlapping the 2026-09-21 egress-cap reset. Supabase restricts a Free-plan
project that exceeds its allowance. Worse, this app has already been to the
harder version of this wall: DECISIONS #93 records the 2026-06-28 backfill
overshooting to ~625 MB and **filling the physical disk**, at which point
`VACUUM FULL` could not run because there was no room to write the compacted
copy, and the escape was a dump → `TRUNCATE` → reload of 508,293 rows. Reaching
that state again while the org is *also* over its egress cap would be a bad
week.

**Evidence.** `proved` for every measurement (live `pg_database_size`,
`pg_total_relation_size`, row counts, two independent growth anchors).
`observed` for the 500 MB allowance — taken from Supabase's published Free-plan
limits and from DECISIONS #34/#93, not from the account dashboard, which the
read-only connector does not expose. The crossing date is a projection, and is
labelled as one.

**Fix shape.**

1. **Measure it, in the job that already exists.** `run_egress_budget_check`
   runs every 15 minutes, already opens a session, already reads `job_runs`, and
   already has a staged-threshold alert with once-per-day-per-stage
   deduplication. Adding `select pg_database_size(current_database())` to its
   counters and a second staged evaluation against a storage budget is a small,
   well-precedented change — and it gives a durable time series to project from
   instead of two anchors a month apart.
2. **Give `activity_timeseries` a retention window.** It is 78% of the database,
   is excluded from every backup, and has 14 months of history. A rolling window
   (12 months would reclaim little today but bounds the future; 6 months would
   reclaim ~150 MB now) turns unbounded growth into a constant. Check the two
   live readers' windows first — `post_workout_analysis` and
   `post_walk_analysis` read per-activity, and `_recent_walks` looks back
   `ACTIVE_RECOVERY_WINDOW_DAYS`.
3. **Prune `job_runs`.** 436 rows/day with no retention is ~58 MB/year of
   evidence about jobs that succeeded. Keep 90 days.
4. **Remember the trap.** Any reclaim planned near the wall must not depend on
   `VACUUM FULL`, `CLUSTER` or a CTAS — all three need the new copy's size free.
   `DELETE` + plain `VACUUM` reclaims to the free-space map without shrinking
   the file; only the dump/truncate/reload path works once the disk is full.

---

### DS237-03 — High — the egress meter is wrong in three directions

**What is wrong.** Fully written up in §237.5. In summary: it counts HTTP
response bytes rather than pooler → application bytes (Defect A); it books the
nightly backup at its *compressed archive* size on the strength of a source
comment that is factually wrong about where `pg_dump -Fc` compresses (Defect B);
and it compares a single day's total against the **monthly org-wide** cap, so
its thresholds are ~30× too loose (Defect C).

**Where.** `middleware.py:25-42`; `services/egress_budget.py:23-50`;
`scheduler.py:376-437`; `services/backup.py:96-99`.

**Failure scenario — the one that already happened.** On 2026-08-30 Supabase
attributed 6.475 GB to this project and restricted the organisation. The meter
recorded 16,312,169 bytes for that day and never left stage `ok`, so the
`degraded` exit code never fired and no alert was staged. A ~397× understatement
in the one instrument built to prevent that outcome. It is still exactly as
wrong today.

**Evidence.** `proved`: the code paths, the eight days of stored `job_runs`
counters, and the server-side `sum(length(col::text))` measurement showing
94.1 MB of JSON text alone inside the backup's scope against a 10.5 MB archive.

**Fix shape.** As set out in §237.5 — rename the existing counter to
`http_response_bytes` and keep it; add a DB-direction counter via a measuring
`json_deserializer` on the async engine (which captures the dominant term
exactly, for one `len()` per JSON value); size the backup at its uncompressed
wire cost; and stage against a rolling 30-day window rather than a single day.
Report both numbers side by side — a large gap between them *is* the diagnostic
that the two incidents lacked.

---

### DS237-04 — High — no backup has ever been proved restorable

**What is wrong.** Everything about the backup is right except the part that
matters. Archives are current (7 nights, one per night, `backup` 14/14 in
`job_runs`), owner-only (`0700`/`0600`), taken by a client newer than the server
(`pg_dump` 17.11 vs PostgreSQL 17.6 — the pin that broke five nights is holding),
and structurally sound (`pg_restore --list` exits 0, 245 entries, 28 `TABLE DATA`
entries, `activity_timeseries` definition retained and data excluded).

But `pg_restore --list` proves an archive can be *parsed*. Nothing has ever
proved one can be *restored*. `backup-drill` has **zero `job_runs` rows in the
entire history of the table**; `run_backup_restore_drill` is not among the 16
jobs `create_scheduler()` registers; and `BACKUP_RESTORE_DATABASE_URL` is unset
in production, so the manual `python -m src.run_scheduled backup-drill` path
would fail at its first argument. Batch 196 built the machinery and it has never
touched a real archive.

Alongside that: retention is 7 days, all seven copies live on the same Railway
volume in the same account as the application, there is no off-site copy and no
stated RPO/RTO, and Supabase's Free plan provides no managed backup or PITR
underneath.

**Where.** `scheduler.py:325-343`, `2043-2245` (the registration list);
`run_scheduled.py:71`; `config.py:247-250`; `services/backup.py`;
Railway `api` variables; `coach.job_runs`.

**Failure scenario.** A migration or a repair script corrupts `knowledge_base`,
`plan_blocks` and `planned_workouts` — the state that is *not* re-derivable from
Garmin. Craig reaches for `coach_20260901_030000.dump` and discovers on the
night it matters whether the archive restores cleanly through ownership,
extensions, enum types (`action_type`, `actor_type` are `create_type=False`
enums) and the `alembic_version` row. If it does not, there is no second copy
and no PITR. If the corruption is eight days old, there is no copy at all. And
in every case the restored database has no `activity_timeseries`.

**Evidence.** `proved` for the archive checks, the version comparison, the
scheduler registration list, the unset variable and the zero drill rows.

**Fix shape.**

1. **Run one drill by hand, this week.** Provision a disposable Postgres, set
   `BACKUP_RESTORE_DATABASE_URL`, run `python -m src.run_scheduled backup-drill`
   under `railway run`, and record the counters it returns
   (`restored_tables`, `profiles`, `analyses`,
   `excluded_activity_timeseries_rows`). The same-host refusal guard already
   protects against pointing it at production.
2. **Then register it** — weekly is enough — so a regression in the archive
   surfaces within seven days rather than at the moment of need.
3. **Get one copy off Railway.** Even a manual monthly download to encrypted
   local storage converts "one volume in one account" into a second failure
   domain. Batch 190 recorded one such download on 2026-08-04; nothing since.
4. **Decide about `activity_timeseries` explicitly.** Either accept in writing
   that a restore loses the per-second history (and note that two live read
   paths depend on it), or fold it into the retention decision from DS237-02 so
   a *bounded* window becomes small enough to include.

---

### DS237-05 — Medium — RLS does not constrain the application

**What is wrong.** Unchanged from DS190-05 and from Batch 209's row, re-measured
today: **29 / 29** `coach` tables have RLS enabled, **0 / 29** have
`FORCE ROW LEVEL SECURITY`, and all 29 are owned by `postgres` — the role
`DATABASE_URL` connects as. A table owner bypasses ordinary RLS. Client roles
hold no `coach` grants, so the *external* boundary genuinely passes; what RLS
does not do is constrain the application itself.

The new observation is that the nine policies which *do* exist are inert. All
nine key off `auth.uid()` (`025_security_ops_rls_hardening.py:68-113`), and this
application never issues a Supabase Auth JWT — it authenticates with its own
opaque device tokens. `auth.uid()` can therefore only ever be `NULL` here, so
the four "policy-protected" tables behave identically to the 25 deny-all ones.
That is fail-closed and harmless, but it means the policy count is not evidence
of anything.

**Where.** `database.py`, `config.py` (`database_url`);
`migrations/versions/025_security_ops_rls_hardening.py:60-175`; live
`pg_class.relforcerowsecurity`.

**Failure scenario.** A future query that reads a UUID-keyed row without a
`user_id` predicate returns the other profile's data, and RLS — which every
dashboard reports as "enabled" — does nothing to stop it. Today this is
unreachable: production holds exactly one profile.

**Evidence.** `proved` for the posture and the ownership; `observed` for the
`auth.uid()` inference (no Supabase Auth user exists, and no code path mints a
Supabase JWT).

**Fix shape.** Batch 209's row is still the right plan and its two shapes are
still the right fork. **Its trigger has not fired** — there is no second user
and no move to a least-privilege login — so this stays deferred, with one
correction to make in the row: it should say that the nine existing policies
cannot be relied on as a starting point for shape (b), because they are keyed to
an identity this application never presents. Any FORCE-RLS design needs a
request-scoped session variable and a matching policy written from scratch, plus
documented exceptions for the scheduler, the backup job and the migration
runner.

---

### DS237-06 — Medium — thirteen live 365-day device tokens, and no way to see them

**What is wrong.** `coach.refresh_tokens` holds **13** unrevoked, unexpired
rows with `purpose='device'` for the single production profile, latest expiry
2027-08-06. Each is a 256-bit bearer credential granting the full API surface —
including, since that profile is `admin`, the three admin routes. The table has
no `last_used_at` column (`models/refresh_token.py:11-25`), so there is no way
to tell which of the thirteen are live browsers and which are abandoned. The
only revocation surface in the app is `POST /api/v1/auth/revoke`, which revokes
**the token used to make that request** — you cannot list your devices, and you
cannot revoke one you no longer hold. The out-of-band escape is
`activate.py --revoke-existing-devices`, which revokes all of them at once from
the CLI.

**Where.** `models/refresh_token.py:11-25`; `auth.py:23`
(`DEVICE_TOKEN_TTL = timedelta(days=365)`); `routers/auth.py:127-145`;
`activate.py:46-55`.

**Failure scenario.** Mark activates the PWA on a phone he later replaces, a
tablet, and two browsers. Those credentials remain valid for a year in
`localStorage` on devices nobody controls any more. If one is sold, restored
from a backup or handed on, it reads his complete health record and can rewrite
his knowledge base — and neither he nor Craig can tell which of the thirteen it
was, or revoke it without cutting off every device at once.

**Evidence.** `proved` — live counts, the model definition, the router surface.

**Fix shape.** Small and self-contained: add `last_used_at` to `refresh_tokens`
and stamp it on resolution (throttled to, say, once an hour per token, so it is
not a write per request); add `GET /api/v1/auth/devices` returning
`device_hint` + created + last-used for the caller's own profile, and
`POST /api/v1/auth/devices/{id}/revoke` scoped to `user_id`; and expire tokens
idle for more than ~90 days at resolution time. The 365-day TTL itself is a
reasonable trade for a PWA with no refresh flow — the gap is visibility, not
lifetime.

---

### DS237-07 — Medium — an unused RLS-bypassing key is required at startup

**What is wrong.** `SUPABASE_SERVICE_KEY` is set on **both** Railway services,
is forced non-empty in production by `config.py:262-263`, and is **read by no
code in this repository** — `supabase_service_key` appears only in its own
declaration, that validator, and one test fixture. It is the Supabase
service-role key: `service_role` carries `rolbypassrls = true`.

The exposure is precisely bounded, and smaller than the name suggests:
`has_schema_privilege('service_role','coach','USAGE')` is **false**, so the key
cannot reach a single `coach` table through PostgREST. What it *does* open is
the co-resident application's 27 `public` tables — `email_accounts`,
`chat_messages`, `chat_conversations`, `gift_links`, `admin_actions` among them
— with RLS bypassed.

**Where.** `config.py:56-58`, `262-263`; Railway `api` and `weekly-review`
variable sets.

**Failure scenario.** Any compromise or accidental disclosure of this API's
environment — a leaked deploy log, a misconfigured `railway run`, a contractor
with Railway access — hands over full RLS-bypassing read/write on a *different*
application's user data, obtained from a service that never had a reason to
carry it. It also means the co-resident app's blast radius runs in both
directions, which Batch 208's row only argues one way.

**Evidence.** `proved` — the grep, the validator, the variable listings, and the
`rolbypassrls` / `has_schema_privilege` measurements.

**Fix shape.** Delete `supabase_service_key` from `config.py` and its production
validator, and remove the variable from both Railway services. If a future
Supabase-client path needs it, reintroduce it as an optional setting scoped to
that path. This is a one-line removal that closes a credential rather than
managing it.

---

### DS237-08 — Medium — the audit log records one thing, and it is not a user action

**What is wrong.** `coach.audit_log` has exactly **one** writer in the entire
application: `run_scheduled_backup`'s failure branch (`scheduler.py:165-176`).
Sixty days of production data contain **7 rows**, all `backup_failed`, all from
the 2026-07-29 → 2026-08-04 outage. `ActionType` (`models/notification.py:19-22`)
defines three values, one of which — `player_pin_reset` — refers to an
authentication mechanism that was removed in the device-token cutover.

Not recorded anywhere: device activation, device revocation, admin coaching-state
writes, knowledge-base edits, plan mutations, holiday/reset changes, and the
`GET /api/v1/handover/export` full-record export.

**Where.** `models/notification.py:19-22`, `59-80`; `scheduler.py:165-176`;
`routers/coaching_state.py:246, 329, 352`; `routers/handover.py:129`.

**Failure scenario.** A device token is compromised. The attacker exports the
full handover record and rewrites two knowledge-base sections so the coach gives
worse advice. Afterwards there is nothing to reconstruct from: no record of when
the token was used, from where, or what it changed. The `knowledge_base` row
carries `updated_by_profile_id` and a timestamp, so the *last* writer is known —
but not the sequence, and not the read.

**Evidence.** `proved` — the single `AuditLog(` construction site, the enum, and
the live 60-day aggregate.

**Fix shape.** Write an audit row for the small set of events that would matter
in an incident: activation, revocation, each admin coaching-state write, and
each handover export. The table, model and independent-session pattern already
exist; this is enum values plus call sites. Retire `player_pin_reset` in the
same migration.

---

### DS237-09 — Medium — F4 is unmoved, and wider than F4 described

**What is wrong.** `docs/claude-api-review.md` F4 flagged three fields sent to
Anthropic with no consumer. All three are still there, and there is a fourth
instance the review did not catch.

- `morning_analysis.py:1275-1279`: `userId`, `latitude`, `longitude` in the
  profile packet.
- `post_workout_analysis.py:493`: `userId` in the profile packet.
- **`morning_analysis.py:1568-1570`: `latitude` and `longitude` again**, inside
  `_weather_packet`. Same coordinates, second copy, same request.

No system prompt references any of them, and weather is already resolved into
`environment.weather` before the packet is built. `displayName` is different and
should stay — the coach addresses Mark by name.

The profile row confirms both coordinate columns are populated. So every morning
brief sends a third party Mark's precise home location twice, plus a stable
cross-request correlator, attached to his sleep times, heart-rate variability
and body weight.

**Where.** `services/morning_analysis.py:1275-1279`, `1568-1570`;
`services/post_workout_analysis.py:493`.

**Failure scenario.** No exploit is required — this is standing disclosure. The
packet is also stored in `coach.analyses.context_packet`, so the coordinates are
in every archive and every future export as well. The concrete risk is that a
third-party retention window, subpoena or breach ties a precise residential
address to a named individual's health record, for data that buys nothing: the
model never reads it.

**Evidence.** `proved` for the code and for the populated columns; `observed`
that no prompt references the fields (Batch 238's pass is better placed to
re-confirm the prompt side).

**Fix shape.** Delete `userId`, `latitude` and `longitude` from both profile
packets and from `_weather_packet`. This bumps no prompt version in substance
but does change the serialized packet, so check whether `PROMPT_VERSION`
handling treats a packet-shape change as orphaning stored analyses before
shipping. Separately, and as a zero-code decision for Craig: Anthropic offers
zero-data-retention arrangements, and nothing in `DECISIONS.md` records whether
one was sought for an application whose entire payload is one named person's
health data.

---

### DS237-10 — Low — the activation rate limit is one global bucket

**What is wrong.** `limiter = Limiter(key_func=get_remote_address)`
(`rate_limit.py:12`), and `POST /api/v1/auth/activate` is decorated with the
bare `@limiter.limit("10/hour")` (`routers/auth.py:57`), so it keys on the
client address rather than on `per_user_key`. The container runs
`uvicorn src.main:app --host 0.0.0.0 --port $PORT` (`Dockerfile:67`) with no
`--forwarded-allow-ips`, and `FORWARDED_ALLOW_IPS` is not set, so uvicorn's
default trusts forwarded headers only from `127.0.0.1`. Behind Railway's edge
proxy, every request therefore presents the same peer address and shares one
bucket. The counter is in-process and resets on every deploy.

**Where.** `rate_limit.py:9-12`; `routers/auth.py:56-57`; `Dockerfile:67`;
Railway `api` variables.

**Failure scenario.** Someone who can reach the public Railway origin —
`api-production-e2bc7.up.railway.app` is directly addressable, not only through
Vercel — sends ten junk activation attempts and blocks Mark's genuine activation
for the rest of the hour, repeatable indefinitely. Brute force is not a concern:
the codes are 256-bit and single-use. The upside of the current arrangement is
that forwarded headers are *not* trusted, so the limit cannot be evaded by
spoofing `X-Forwarded-For` — the failure is availability, not bypass.

**Evidence.** `observed`. Derived from the uvicorn invocation and the absent
environment variable. Not probed live, deliberately: exercising it would consume
the activation budget for an hour, which is a side effect this review will not
take.

**Fix shape.** Either widen the limit and add a per-code attempt counter so a
flood of *distinct* invalid codes is what gets throttled, or accept the
behaviour and record it — but first confirm empirically what
`request.client.host` actually is on Railway, since the whole finding rests on
that inference. A one-line temporary debug log on the health endpoint would
settle it without touching the activation path.

---

### DS237-11 — Low — a co-resident app's event trigger runs inside every migration

**What is wrong.** The database carries an event trigger `ensure_rls` on
`ddl_command_end`, owned by `postgres`, executing `public.rls_auto_enable()` — a
`SECURITY DEFINER` function belonging to the co-resident application. It fires
on every DDL statement in the database, including every statement of every
`alembic upgrade head` this application runs at container boot.

Today it is benign: its loop filters `schema_name IN ('public')` and wraps its
`ALTER TABLE` in `EXCEPTION WHEN OTHERS`, so it neither touches `coach` nor
raises. This app enables RLS on its own tables explicitly in its own migrations
(e.g. `027_job_runs.py:83`), so it does not depend on the trigger either.

**Where.** live `pg_event_trigger`; `Dockerfile:67`
(`alembic upgrade head && uvicorn …`); `migrations/versions/027_job_runs.py:83`.

**Failure scenario.** The other app's owner edits `rls_auto_enable` — widens the
enforced schema list, or moves work outside the inner exception handler. The
next `alembic upgrade head` in this app's container raises, the `&&` short-circuits,
uvicorn never starts, and the API is down for a change made in a different
codebase by someone who does not know this application exists.

**Evidence.** `proved` for the trigger's existence, ownership and current body;
`observed` for the failure scenario, which is a mechanism, not an occurrence.

**Fix shape.** No code change. Add this mechanism to Batch 208.2's row as the
concrete form of the shared blast radius — it is a better argument for the
project split than "shared owner and quota", because it names a way the other
app can stop this one from booting. If 208.2 is declined, the cheap mitigation
is to split the `CMD` so a migration failure is distinguishable from a boot
failure in Railway's logs.

---

### DS237-12 — Low — `coach` and the public app still share one advisor queue

**What is wrong.** Batch 208.1 — route the co-resident app's advisor warnings to
its owner — is unstarted. A single `get_advisors` call returns `coach` and
`public` findings interleaved: today 12 WARNs and 51 INFOs, of which **zero
WARNs and 25 INFOs** are `coach`'s.

**Where.** Supabase project `pzqmswvozjnkxbqqowuj`, one advisor surface for both
schemas.

**Failure scenario.** A genuine `coach` WARN — a new table shipped without RLS,
a policy regression — arrives in a queue that is 12 WARNs deep with somebody
else's backlog, and is not noticed. The current signal-to-noise happens to be
good; it is good by luck, not by routing.

**Evidence.** `observed` — the live advisor output.

**Fix shape.** Exactly as 208.1 specifies: configure per-project notification
routing if Supabase's Free plan allows it, or document the split explicitly in
the ops runbook (`coach` findings are the ones whose `metadata.schema` is
`coach`) so a human triaging the list has a rule. Worth doing regardless of
208.2.

---

### DS237-13 — Low — the only production profile is `admin`

**What is wrong.** The single production profile carries `role = admin`, so
`require_admin` (`auth.py:85-90`) separates nothing: the three admin
coaching-state routes are reachable by the same device token that reads the
daily loop. The design already recognises the tension — `admin_alert_user_id` is
deliberately *not* the admin role, because "the primary user holds that role,
and an ops alert must never land on his phone" (`config.py:206-210`).

**Where.** live `coach.profiles`; `auth.py:85-90`;
`routers/coaching_state.py:246, 329, 352`.

**Failure scenario.** A stolen or leaked device token does not merely read
Mark's health record; it can rewrite the knowledge base that drives every future
brief. The privilege boundary that would have contained it exists in code and is
collapsed in production.

**Evidence.** `proved` — one profile, role `admin`.

**Fix shape.** Seed a separate operator profile for Craig with `role = admin`
and demote Mark's to `player`, then verify that every route Mark actually uses
still resolves. This also unblocks the push half of DS237-01, which needs a
second profile to exist. Check first whether any coaching path depends on Mark's
role — the seed logic and the admin coaching-state routes are the places to
look.

---

### DS237-14 — Low — activation codes travel in a query string

**What is wrong.** `activate.py:22-25` mints
`{frontend_origin}/activate?code={code}` deliberately, because install flows
preserve a query parameter more reliably than a fragment. The consequence is
that a live, unused activation code appears in Vercel's edge access logs, in the
browser address bar and history, and in any `Referer` a sub-resource load
generates before the page scrubs it. `ActivatePage.tsx:58-61` does scrub —
`history.replaceState(null, '', '/activate')` on success — and stores the code
in `localStorage` only between arrival and consumption, removing it on both
success and failure.

**Where.** `activate.py:22-25`; `apps/web/src/pages/ActivatePage.tsx:35-70`.

**Failure scenario.** Someone with access to Vercel's logs, or to the browser
history of the machine the link was opened on, replays the code before it is
consumed. Bounded hard by single-use consumption and a 30-minute TTL, and the
links are delivered person-to-person.

**Evidence.** `proved` for the URL shape and the scrubbing; `observed` for the
logging, which was not inspected in Vercel.

**Fix shape.** Accept and document, or move the code to the fragment with the
existing query-parameter path kept as the install-flow fallback — the frontend
already reads both (`ActivatePage.tsx:35-41`). Low value either way.

---

### DS237-15 — Low — stale-deploy detection is still human-only

**What is wrong.** Unmoved from DS190-04. `GET /api/v1/health` exposes the
Railway-injected SHA and both surfaces are correct right now — Railway direct
and the Vercel same-origin proxy both serve
`21783812758d002477a5f6bad33845c7a084b854`, equal to local `main`, with the web
root returning 200 and unauthenticated `GET /api/v1/daily-loop` returning 401 on
both paths. No workflow or monitor compares those values with GitHub `main`; the
close-out runbook is still the only detector, and the 2026-07-30 Railway
incident already demonstrated a merge webhook being dropped with no failed
deployment to inspect.

**Where.** `routers/health.py`; `docs/agent-commands/`; no CI job.

**Fix shape.** After `main` moves, poll both health paths to the expected SHA
with a bounded timeout and fail the workflow on mismatch. It is small, and it
protects every other fix in this list. Fold it into DS237-01's monitor rather
than building a second mechanism.

---

### DS237-16 — Low — a 401 clears the token but not the persisted brief

**What is wrong.** `apps/web/src/lib/api.ts:63-67` handles a 401 by calling
`clearTokens()` and redirecting to `/access`. It does **not** call
`clearPersistedCache()`. The `AuthContext` logout and activation paths do call
both (`AuthContext.tsx:64-66`, `85-87`), so only the involuntary-expiry path
leaves the dehydrated `daily-loop` query — the morning brief — sitting in
`localStorage` under `gc-rq-cache`.

**Where.** `apps/web/src/lib/api.ts:63-67`; `apps/web/src/lib/queryClient.ts:46-55`.

**Failure scenario.** A device whose token was revoked keeps yesterday's brief
readable in `localStorage` until the 24-hour `maxAge` or the next build's
`buster` invalidates it. Bounded, single-device, and the persistence design is
otherwise careful — only `daily-loop` is ever written to disk, by an explicit
allowlist.

**Fix shape.** One line: call `clearPersistedCache()` alongside `clearTokens()`
in the 401 branch.

---

### DS237-17 — Low — three residual Batch 235-class full-row reads

**What is wrong.** Batch 235 fixed the history windows but three per-request
paths still materialise whole rows including JSONB the caller never reads:

- `post_workout_analysis.py:855-866` and `post_walk_analysis.py:574-585` —
  `select(ActivityTimeSeries)` for a whole activity, pulling
  `raw_metrics` (averaging 91 bytes, retained in full for outdoor rides) for
  every sample when the analysers use only the typed float columns.
- `services/brief_chat.py:326` — `_owned_analysis` runs
  `select(Analysis).where(Analysis.id == analysis_id)` purely to check
  ownership, materialising `context_packet` and `raw_response` (≈6.2 KB of JSON
  text per row on average). `history()` discards the returned object entirely.

**Where.** as listed.

**Failure scenario.** Not an incident on its own — these are bounded per-request
reads, not the 120-night windows that caused the 2026-08-30 event. They are
listed because the pattern is the one the app has now been bitten by twice, and
because DS237-03's fix will make them visible in the new counter.

**Evidence.** `proved` — the queries and the model definitions;
`observed` for the size estimates, taken from table-level aggregates rather than
per-call measurement.

**Fix shape.** `load_only` on the two time-series reads and a
`select(Analysis.user_id)` scalar in `_owned_analysis`, with the full row loaded
only by the caller that actually needs it. `services/bulk_history_reads.py` is
the existing home for the pattern.

---

## What is done well

Worth stating plainly, because most of this pass's findings are about
instrumentation rather than design.

- **The `coach` data boundary is genuinely sealed.** No schema `USAGE`, no table
  grants, no views, no cross-schema foreign keys, no foreign function touching
  `coach`, zero advisor WARNs on either the security or the performance side.
  Even `service_role` — which bypasses RLS — cannot reach a single row. That is
  the property that matters most for a private health record, and it holds under
  direct measurement.
- **The route guard is a real guard.** `test_route_auth_inventory.py` resolves
  FastAPI's dependency *graph* rather than reading annotations, and asserts the
  public set is exactly four entries — so it fails both on a new unguarded route
  and on a new public one. 91/91 routes conform.
- **Both of Batch 190's authorization findings were fixed properly**, with
  comments naming the finding, a structured log preserving the operator-visible
  distinction, and a redundant predicate defended in prose rather than left as
  an accident.
- **The credential design is sound.** 256-bit opaque tokens, SHA-256 at rest,
  single-use activation consumed by an atomic `UPDATE … RETURNING`, revocation
  and expiry both checked on every request, legacy PIN/JWT endpoints removed and
  their 73 refresh rows all revoked.
- **Spend is bounded by design, not by hope.** Nine paid-generation routes share
  one 30/hour budget keyed by the resolved profile so a stolen token cannot
  multiply its allowance across endpoints, and the fallback key is a hash of the
  bearer, never the bearer itself.
- **The `job_runs` ledger is well built.** An independent session so a poisoned
  transaction cannot erase the evidence, a cadence-window bucket so absence is
  answerable, typed statuses, and non-zero exits for the external runner. The
  only thing missing is a reader.
- **The backup itself is careful work.** Hidden partial file replaced atomically
  only on success, password out of `argv`, `0600`/`0700`, pruning restricted to
  a strict filename pattern, schema-scoped, the largest table's data excluded,
  and a PGDG-pinned client that is now correctly ahead of the server.
- **Self-hosted Piper for read-aloud** means brief text never leaves this
  infrastructure even when the hosted voice is used — a privacy decision taken
  at real build cost (DECISIONS #190).
- **The frontend's persistence is deliberately bounded.** An explicit allowlist
  of one query key, a 24-hour max age, a build-hash buster, and cache clearing
  on both activation and logout. The CSP on Vercel is tight (`script-src 'self'`
  plus one hash, `connect-src 'self'` plus Sentry), which is what makes the
  `localStorage` token an acceptable trade.
- **Batch 190's biggest operational finding was actually fixed.**
  `sleepApplication` is off, and fourteen days of ledger data show the jobs
  firing on cadence. That is the difference between a review that gets read and
  one that gets filed.

---

## The three highest-value fixes

1. **Make one alert ring (DS237-01).** Set `SENTRY_DSN_BACKEND` on both Railway
   services and `ADMIN_ALERT_USER_ID` to an operator profile. Two environment
   variables convert four existing alert helpers, the Batch 141 billing alert
   and every `log.exception` in the scheduler from decoration into a signal —
   with no code change at all. Then add a ledger-freshness check that runs
   outside the scheduler it watches. Every other finding in this document is
   more expensive to detect than to fix, and this is the one that changes that.

2. **Measure the storage cap before it measures you (DS237-02).** Add
   `pg_database_size()` to the `egress-budget` job's counters and a staged
   threshold against 500 MB — the job already runs every 15 minutes, already
   writes counters, already dedupes its alerts. Then give
   `activity_timeseries` a retention window: it is 78% of the database, is in no
   backup, and this app has already had to escape a full disk once by
   dump/truncate/reload. Four weeks of projected headroom is not enough runway
   to be discovering this from a restriction email.

3. **Restore one backup (DS237-04).** Provision a disposable database, set
   `BACKUP_RESTORE_DATABASE_URL`, and run
   `python -m src.run_scheduled backup-drill` by hand — then register it weekly.
   The machinery has existed since Batch 196 and has never once been pointed at
   a real archive. On a Free plan with no PITR, seven days of unverified
   archives on a single volume is the entire recovery story, and it is currently
   an assumption rather than a fact.

---

## Evidence ledger

| Area | Method | Result |
|---|---|---|
| RLS posture | Live `pg_class`, `pg_policies`, `information_schema.role_table_grants`, `has_schema_privilege`, `pg_auth_members` | 29/29 RLS, 0/29 FORCE, single owner `postgres`, client roles hold nothing on `coach` |
| Advisors | Live Supabase security + performance advisors | 0 WARN for `coach` on both; 25 security INFO and 10 performance INFO for `coach`; all 12 security WARNs and all 7 performance WARNs belong to `public` |
| Schema boundary | Cross-schema FK, view, function-body and event-trigger catalog queries | 0 FKs, 0 views, 0 foreign functions referencing `coach`; one foreign event trigger firing on all DDL (DS237-11) |
| Authorization | FastAPI dependency-graph walk over the live app + source review of the two DS190 fixes | 91 pairs, 4 public (the permitted set), 3 admin-gated; DS190-08 and DS190-09 both fixed |
| Credentials | Live `refresh_tokens` aggregate + model + router review | 13 live device tokens, 365-day TTL, no last-used, no device list |
| Secrets | `railway variables` name-only listing on both services + repo grep | No secret in the repo; one unused RLS-bypassing key required at startup; no secret or PII in any log call |
| Egress meter | Source review + 8 days of stored `job_runs` counters + server-side `length(col::text)` aggregates | Three independent defects; 16.3 MB / `ok` recorded on a 6.475 GB day |
| Storage | `pg_database_size`, `pg_total_relation_size`, `pg_relation_size`, two independent growth anchors | 451.3 MB against a 500 MB allowance; ~1.85 MB/day; no monitor anywhere |
| Backups | `railway ssh` directory listing, `stat`, `pg_dump --version`, `pg_restore --list`, `job_runs`, `audit_log` | 7 current archives, correct modes, client 17.11 > server 17.6, 28 TABLE DATA entries; drill never run, target unset, not registered |
| Jobs | 14-day `job_runs` aggregate by job and status + scheduler registration list + cron manifest | 16 registered jobs, 2 failures nobody saw, `backup-drill` never run, one external cron correctly gated |
| Deployment | Direct Railway + Vercel-proxied health, web root, unauthenticated daily-loop | Both surfaces on `2178381` = local `main`; web 200; unauthenticated 401 on both paths |

## Explicit non-actions

- No RLS policy, grant, function, schema, row, migration or database setting was
  changed.
- No Railway, Vercel, Supabase or GitHub configuration was changed. Every
  `railway` invocation was a read; environment variables were listed by **name
  only** and no value was printed except the four non-secret ones quoted above.
- No backup was created, downloaded or restored. The container probe read
  directory metadata and parsed one archive's table of contents in place.
- No scheduled job was triggered and no generation was run; no Anthropic spend
  was incurred by this pass.
- No rate-limit budget was consumed: DS237-10 was deliberately left as an
  inference rather than probed.
- No health-data row payload was copied into this repository.
- The Batch 237 ledger row remains Planned and unstruck until explicit
  `/phase-closeout 237`.
