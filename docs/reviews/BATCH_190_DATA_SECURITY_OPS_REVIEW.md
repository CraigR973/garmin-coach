# Batch 190 — Data, security and operations review refresh

**Date:** 2026-08-06
**Branch:** `chore/batch-190-data-security-ops-review`
**Tier:** 🔴 High
**Mode:** diagnose-only — no product code, migration, provider configuration,
database policy or production data was changed
**Code baseline:** `7e77169..9947be1` (Batches 157–189)
**Production baseline:** Supabase project `pzqmswvozjnkxbqqowuj`, Railway
production, and the Vercel same-origin proxy, observed 2026-08-06

This review refreshes Batch 154's data/security baseline after the device-token
cutover, the rolling coach conversation, migrations 022–026, the 4 August egress
incident, and the first external Railway cron service. It is evidence and
remediation planning only. Remediation stubs below deliberately have no batch
numbers until the wave-2 findings are triaged together.

---

## Executive summary

**The coach data boundary is closed to Supabase's client roles, and the new API
surface is authenticated and user-scoped.** Production is at Alembic `026`; all
28 `coach` tables have RLS enabled. The four legacy client-facing tables carry
the nine policies hardened by migration `025`; the other 24 intentionally have
no policies, so they deny all rows to non-owner roles. `anon`, `authenticated`
and `service_role` have no `USAGE` or `CREATE` on `coach` and no table grants.
There are no `coach` views, no `coach`↔`public` foreign keys or triggers, and no
non-coach function body references `coach.*`. Supabase's security advisor reports
no `coach` warning: only 24 informational “RLS enabled, no policy” notices, which
describe the intended deny-all posture.

The route sweep is similarly reassuring. The ten router modules changed since
the Batch 154 baseline expose 40 current endpoints: one public activation
endpoint and 39 routes whose dependency graph reaches `get_current_user` (or
admin). The repository-wide guard sees 91 API routes, permits exactly four
public method/path pairs, and fails on any other unauthenticated route. The new
rolling coach thread filters by `BriefMessage.user_id`; an optional read anchor
is ownership-checked before it reaches context or the model; unknown
`originKind` strings normalize to the controlled `general` origin rather than
entering a prompt. The post-session read returns the same `absent` state for a
foreign UUID and an unknown/owned-without-read UUID. The learning proposal rail
returns 404 for cross-user list/mutation attempts and has a regression proving
no knowledge-base write occurs.

**The operational controls are materially better than on 4 August, but they are
not yet dependable failure controls.** Production now has a ready 5 GB Railway
volume mounted at `/data/backups`; the 4, 5 and 6 August archives exist, are
owner-only, use PostgreSQL 17's custom format, and have valid TOCs. The latest is
7,842,096 bytes and contains 27 `coach` table-data entries, while keeping the
`activity_timeseries` definition and excluding its rows. The hourly Garmin poll
also keeps the count+latest-timestamp settled-stream guard, so an unchanged
sample stream is no longer rewritten ~96 times and an empty parse cannot erase
stored samples.

What remains is the distinction between **recent success** and **reliable
operation**. Railway still marks the API service `sleepApplication=true`, while
10 of 11 externally runnable jobs exist only in that API's in-process
APScheduler; only `weekly-review` has an external cron service. Every scheduler
coroutine catches its top-level exception and returns normally, and
`run_scheduled.py` therefore exits 0 on an internal failure. There is no durable
per-run ledger or alert. Backup is the clearest consequence: seven failure audit
rows span 29 July–4 August, nothing paged, and the new archive has been
TOC-inspected but never restored into a disposable database. On the Supabase
Free plan, that is the sole recovery system.

Deployment health has the same shape. Direct Railway and Vercel-proxied health
both served current `main` SHA `9947be1` during this review, and readiness was
`db: ok`. The app exposes the SHA, but no automation compares it with GitHub
`main`; the close-out runbook is the only detector. A Railway platform incident
already demonstrated that a merge webhook can be dropped without producing a
failed deployment.

**9 findings: 3 High, 4 Medium, 2 Low** (`DS190-01…09`), ranked severe-first.

---

## 190.1 — Authorization sweep

### Route inventory for the 157–187 delta

`git diff 7e77169..9947be1 -- apps/api/src/routers` changes exactly these ten
router modules. “Protected” means FastAPI's resolved dependency graph reaches
`get_current_user`/`require_admin`, not merely that a type annotation looks
right.

An AST comparison of method/path decorators accounts for the lifecycle as well
as the current surface. Three endpoints were added: `POST /auth/revoke` and
`GET`/`POST /coach/messages`. Six legacy PIN/JWT endpoints were removed:
`POST /auth/login`, `/logout`, `/refresh`, `/pin/reset`, `/pin/reset-request`,
and `PUT /auth/me/pin`. The other 37 current method/path pairs are unchanged but
live in modules whose dependencies or implementation changed, so all are kept in
the table rather than reviewing only the three additions.

| Router | Current routes | Authorization / ownership disposition |
|---|---:|---|
| `auth.py` | 4 | `POST /activate` is deliberately public and rate-limited; revoke, `GET /me`, and `PATCH /me` require the live opaque device token. Revocation and profile update are constrained to `user.id`. |
| `brief_chat.py` | 2 | Both per-read routes require `CurrentUser`; unknown read → 404, foreign read → 403; writes use the authenticated user id. |
| `coach_chat.py` | 2 | Both rolling-thread routes require `CurrentUser`; list history is filtered by user; optional `analysisId` goes through the same ownership check. |
| `coaching_state.py` | 7 | The three admin-state routes require `AdminUser`; four coach-memory/learning routes require `CurrentUser`. Knowledge-base, planned-workout and proposal writes are service-scoped to the player. |
| `daily_loop.py` | 4 | All require `CurrentUser`; date-keyed manual/check-in/status writes pass the player into the service. |
| `handover.py` | 3 | All require `CurrentUser`; snapshot/run/export are assembled for that player. |
| `plan_actions.py` | 10 | All require `CurrentUser`; UUID-keyed edits resolve through owned service queries. The new post-session read checks owned workout first and non-discloses foreign/unknown ids as `absent`. |
| `reviews.py` | 2 | Both require `CurrentUser`; period reads/generation are player-scoped. |
| `trends.py` | 4 | All require `CurrentUser`; seasonal, year-on-year and narrative paths are player-scoped. |
| `tts.py` | 2 | Both require `CurrentUser`; consent and synthesis use the authenticated profile. |

Repository-wide, `test_route_auth_inventory.py:13-56` allows only:

- `GET /api/v1/health`
- `GET /api/v1/health/ready`
- `POST /api/v1/auth/activate`
- `GET /api/v1/push/vapid-public-key`

All other routes must resolve an auth dependency. The current application has
91 API routes, so the delta did not create an unguarded endpoint.

### New identifier and origin paths

- `BriefChatService._owned_analysis` reads the anchor, returns 404 if missing and
  403 if its `user_id` differs (`services/brief_chat.py:291-300`). Both inline
  and rolling POST paths call it before context assembly or the Anthropic call.
- Rolling history filters `BriefMessage.user_id == player.id`
  (`services/brief_chat.py:332-352`). Writes set `user_id=player.id`
  (`:427-445`).
- `originKind` is capped at 32 characters and normalized through a fixed
  vocabulary. The injection-shaped regression proves an unknown string becomes
  `general` and does not reach the prompt.
- The post-session read first selects `PlannedWorkout.id` **and**
  `PlannedWorkout.user_id`; only then does it read an analysis or generation
  status. Foreign, unknown, and owned-without-read ids all return `absent`.
- Conversation-learning proposal list/accept/edit/reject are cross-user tested:
  the foreign list is empty, all three mutations return 404, and no knowledge
  base row is written.

No direct authorization bypass was found. The two low-severity hardening points
are **DS190-08** (inconsistent 403/404 disclosure) and **DS190-09** (a redundant
user predicate is absent from one history query).

---

## 190.2 — Deployed RLS and the shared database boundary

### Live `coach` state

Read-only catalog and advisor queries against production established:

| Control | Live result |
|---|---|
| Alembic version | `026` |
| Tables | 28/28 `relrowsecurity=true`; 0 `relforcerowsecurity=true` |
| Policies | 9 policies on `profiles`, `refresh_tokens`, `push_subscriptions`, `notification_preferences`; all restricted to `authenticated`; both update policies have `WITH CHECK` |
| Deny-all tables | 24 tables have RLS and no policy; non-owner roles see no rows |
| Schema/table grants | `anon`, `authenticated`, `service_role`: no `USAGE`/`CREATE` on `coach`, no table grants |
| Views / cross-schema edges | no `coach` views; no cross-schema FKs/triggers; no non-coach function definition references `coach.*` |
| Trigger helper | `coach.set_updated_at` is not security-definer; `search_path=coach,pg_temp`; no execute grant to public/client roles |
| Security advisor | 24 INFO `rls_enabled_no_policy` notices for `coach`; **0 WARN** for `coach` |

The 24 advisor notices are expected for a server-only schema and not missing
work: without a policy RLS denies non-owner access. Supabase's remediation page
is retained for reference:
<https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy>.

There is still one important limitation. Railway connects as the `postgres`
table owner; owners bypass ordinary RLS because `FORCE ROW LEVEL SECURITY` is
off. RLS therefore blocks Supabase client roles and future accidental grants,
but does not contain an ownership bug in the FastAPI process (**DS190-05**).

### The co-resident `public` application

The shared project also contains the movie/public app: 27 `public` tables, all
RLS-enabled. There is no database object that crosses into `coach`, and the
client roles cannot use `coach`, so the current app boundary holds.

It is not an operational or security *failure* boundary. The same project and
database owner share resource limits, maintenance, credentials and blast radius.
The live security advisor reports public-schema warnings: five mutable function
search paths, `pg_trgm` installed in `public`, and four `SECURITY DEFINER`
functions executable by both `anon` and `authenticated`. Three of the four are
trigger/event-trigger functions that cannot perform their trigger work as an RPC,
and `get_my_role()` has a pinned empty search path, so this review did not prove a
direct coach exploit. They remain outstanding warnings in the co-resident app,
and the shared boundary turns its mistakes and workload into coach risk
(**DS190-06**).

---

## 190.3 — Backup durability and recoverability

The phase-batch row's “ephemeral `BACKUP_DIR`” statement is stale. Decision #262
closed that part on 4 August; this review re-verified it live rather than relying
on the decision log.

| Check | Live evidence |
|---|---|
| Storage | Railway `api-volume`, state `READY`, 5,000 MB, mounted to API at `/data/backups`; production `BACKUP_DIR=/data/backups` |
| Survives deploys | archives pre-date the current 6 August deployment and remain on the mounted volume |
| Recent archives | `20260804_095905` 7,745,327 B; `20260805_030000` 7,772,432 B; `20260806_030000` 7,842,096 B |
| Permissions | directory `0700`; all archives `0600` |
| Tool/format | `pg_dump`/`pg_restore` 17.10; custom compressed archive |
| Scope | only schema `coach`; latest TOC has 27 table-data entries, no `activity_timeseries` data entry, and does retain that table's definition |
| Retention | code keeps the newest seven archives |
| Off-site | one 4 August archive was manually downloaded and SHA-matched; later copies currently remain on Railway |

The service uses a hidden partial file, replaces it atomically only after
`pg_dump` succeeds, keeps the password out of argv, and prunes only filenames
matching its own strict pattern (`services/backup.py:63-123`). Those controls
hold.

Two recovery claims are not yet established. `pg_restore --list` proves the
archive can be parsed, not that schema and data restore cleanly into PostgreSQL.
No disposable-database restore drill has been recorded. And backup failure only
writes an audit row plus a structured log; nothing alerts. Production contains
seven `backup_failed` audit rows from 29 July through 4 August—the exact outage
that went unnoticed. Supabase's current backup guidance says Free-plan users
should export and keep off-site copies; managed daily backups are a paid-plan
feature: <https://supabase.com/docs/guides/platform/backups>. This makes the
alert/restore gap **DS190-03**, not a paperwork issue.

---

## 190.4 — Egress after the 4 August incident

The provider alert recorded **15.19 GB used against its then-displayed 5.5 GB
cap**. Supabase's current public egress page lists **5 GB uncached egress on the
Free plan**, calculates usage across the organisation and billing period, and
counts database/Supavisor traffic:
<https://supabase.com/docs/guides/platform/manage-your-usage/egress>. The exact
live dashboard meter was not available through the read-only connector, so this
review does not invent a post-incident number or silently replace the historical
5.5 GB notification with today's published 5 GB allowance.

### Mitigations verified as holding

1. **Dump scope and compression.** `pg_dump --format=custom --schema=coach
   --exclude-table-data=coach.activity_timeseries` remains in production code
   (`services/backup.py:96-110`). The latest archive is 7.84 MB. At that size, a
   30-day run is roughly 0.24 GB rather than the prior whole-project hundreds of
   MB per night.
2. **Settled-stream idempotency.** The hourly poll selects only stored count and
   latest timestamp, skips an identical non-empty stream, rewrites a changed
   stream, and never deletes for an empty parse (`services/garmin_sync.py:403-445`).
   Regressions cover repeat poll, later-timestamp/same-count, and empty payload.
3. **Current mutation history matches the incident.** Production statistics
   still record 9,788,160 inserts and 8,697,747 deletes against 596,040 live
   `activity_timeseries` rows; statistics have not been reset, so they preserve
   the old amplification rather than proving it continues. Current source and
   tests prove the old unconditional loop is gone.

### Remaining amplification paths

- A manual whole-database or full-`coach` dump that omits the exclusion can
  immediately re-export the ~596k-row stream and the 2.5m-row public movie data.
- The public app and all other active projects in the same Supabase organisation
  consume the same Free-plan egress budget; this repo cannot impose a budget on
  them.
- Historical backfill can repopulate/rewrite the replayable stream. Although
  inserts are inbound, a later unscoped dump or inspection turns that stored
  volume back into egress.
- Each changed activity still rewrites its whole stream once. That is bounded by
  the settled check, but a continuously changing or repeatedly repaired activity
  is intentionally not append-only.
- There is no automated org-usage threshold, daily delta report or kill switch.
  The next warning can therefore arrive only after the shared cap is nearly or
  fully spent (**DS190-07**).

The most important positive observation is that normal API code does not read
`ActivityTimeSeries` at all; only sync writes it and backup excludes it. The
largest coach table is therefore no longer a routine response-egress path.

---

## 190.5 — Scheduler, cron and deployment reliability

### What is running now

- Railway API: current deployment `SUCCESS`, exact `main` SHA `9947be1`, volume
  mounted, `sleepApplication=true`.
- `SCHEDULER_ENABLED` is unset, so the API default is `true`
  (`config.py:91-92`). It registers backup, Hive, wake, morning, activity,
  post-workout, autopush, weekly review, state change, evening and fan jobs
  (`scheduler.py:1351-1510`).
- Railway external cron: only `weekly-review`, scheduled at both DST candidates
  `0 17,18 * * 0`, with a London-hour gate and `restartPolicyType=NEVER`.
- Live freshness was good at the observation point: Hive temperature at 10:50,
  activity update at 08:44, current-day daily/sleep data, analysis at 10:45, and
  the 03:00 backup file. This is evidence of recent execution, not a guarantee.

The repo's own runner explains that an in-process web scheduler is unreliable
when the container is not continuously running (`run_scheduled.py:1-11`), and
the runbook records prior missed polls. Yet the API remains sleep-enabled and 10
of the runner's 11 named jobs have no external service. A wall-clock job cannot
coalesce a run it was never alive to observe, and interval seeding only helps
after a wake. That is **DS190-01**.

Every scheduler job owns its top-level `try/except`, logs and returns. The
external runner simply awaits it (`run_scheduled.py:49-76`), so internal failure
still exits 0. Railway sees success, `restartPolicyType=NEVER` does not help, and
there is no durable job-run ledger or monitor that asserts “job X succeeded in
its window.” CR189-20 identified the exit-code symptom; the live topology makes
its operational consequence broader (**DS190-02**). CR189-02's poisoned-Session
morning abort is also still open and makes a loud failure contract more urgent.

### Deploy freshness

`GET /api/v1/health` exposes Railway's injected SHA
(`routers/health.py:13-16`). At review time:

- direct Railway health: `9947be11e948a894c19ce90eb999455d3486422e`
- Vercel same-origin health: the same SHA
- readiness: `{"status":"ready","db":"ok"}`

No workflow or external monitor compares those values with GitHub `main`. The
only comparison lives in human close-out instructions/runbooks. After the 30
July Railway platform incident, the GitHub merge webhook was dropped rather than
queued and there was no failed deployment to inspect; production silently stayed
on the previous SHA until a source redeploy. Current freshness is therefore a
pass, while future stale-SHA detection is **DS190-04**.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| DS190-01 | **High** | Ten of eleven scheduled workloads depend on APScheduler inside a Railway service explicitly configured to sleep |
| DS190-02 | **High** | Scheduler jobs swallow top-level failures and the external runner exits 0; there is no durable per-run success signal or alert |
| DS190-03 | **High** | The sole Free-plan backup can fail without paging and has never passed a full disposable restore drill |
| DS190-04 | Med | SHA health exists, but no automation detects a dropped deploy webhook or stale Railway/Vercel production |
| DS190-05 | Med | The FastAPI app connects as table owner, so ordinary RLS does not contain an app ownership bug |
| DS190-06 | Med | Coach and a public movie app share one Supabase project/owner/quota; public-schema advisor warnings remain in the shared blast radius |
| DS190-07 | Med | Egress mitigations hold, but there is no org-level budget monitor and other projects/manual dumps can consume the shared allowance |
| DS190-08 | Low | Brief-chat returns 403 for a foreign read and 404 for an unknown read, revealing existence to an authenticated second user |
| DS190-09 | Low | Per-read history ownership-checks the analysis but does not redundantly filter messages by `user_id` |

### DS190-01 — High — sleeping web process is still the scheduler

**Evidence.** Railway reports `sleepApplication=true`; API `SCHEDULER_ENABLED`
defaults true; only `weekly-review` has an external cron service; the runbook and
runner already state that the web process missed jobs when it was not continuous.

**Impact.** Wake detection, the 11:00 verdict backstop, activity reads, bedtime
alerts, fan reconciliation and backup can silently miss their window. A recent
fresh row does not establish an SLO.

**Remediation stub.** Either make API execution genuinely always-on, or create
external run-to-completion services for every required job. Prefer an explicit
cadence/owner table, DST-safe gates for wall-clock jobs, idempotency/locks for
overlap, then disable the in-process scheduler only after each external job has
proved successful.

### DS190-02 — High — a failed job still reports success

**Evidence.** Each coroutine catches its own outer exception; `_run()` observes
no result and raises nothing. The runbook explicitly says the runner exits 0 on
internal failure. Only logs describe the outcome; most jobs do not persist even
that outcome.

**Impact.** Railway/GitHub cron cannot alert from exit state. A failed weekly
review or backup looks like a successful execution, and absence of a job is
indistinguishable from a no-op without manually interpreting provider logs.

**Remediation stub.** Define a typed job result/failure contract, let external
mode exit non-zero after audit/log cleanup, and persist a per-job run row with
scheduled window, started/finished timestamps, status, reason and counters. Add
an independent freshness monitor; do not use the same scheduler to monitor
itself. Carry CR189-02's required Session rollback into the same remediation.

### DS190-03 — High — sole backup is alertless and restore-unproven

**Evidence.** Durable volume, recent archives, modes, tool version, scope and TOC
all pass. Seven production failure rows were recorded without paging. No full
restore has been recorded, and later daily copies have not been moved off
Railway.

**Impact.** A syntactically valid archive may still fail on ownership,
extensions, migration state or data constraints when urgently restored. A base
image regression can again erase the recovery window before anyone notices.

**Remediation stub.** Alert outside the end-user profile model (provider log
alert, operator-only channel, or external monitor), run a scheduled disposable
restore with row/schema invariants, record the result, and define an encrypted
off-site cadence plus RPO/RTO. Keep health data access narrow and audited.

### DS190-04 — Medium — deploy freshness is human-only

**Evidence.** Health exposes SHA and both paths are current today. No CI/monitor
compares `origin/main` to direct Railway and Vercel-proxied health; the dropped
webhook incident produced no failed deployment.

**Impact.** A green merge and green Vercel deploy can coexist with a stale API,
silently serving old schema or policy behavior until manual close-out.

**Remediation stub.** After `main` changes, poll both health paths to the expected
SHA with a bounded timeout, then alert on mismatch/unknown. Keep the current
human close-out check as a second control, not the only control.

### DS190-05 — Medium — RLS does not constrain the app owner

**Evidence.** 28/28 tables have RLS but none has FORCE RLS; production tables are
owned by `postgres`, the Railway connection role. Client roles have no coach
grants, so the external boundary passes while the server bypass remains.

**Impact.** A missing `user_id` predicate in a FastAPI query can cross the two
private users even though RLS is “enabled.” RLS currently protects against
PostgREST/client-role exposure, not application authorization defects.

**Remediation stub.** Design a least-privilege application login and test it
against every write path, or use FORCE RLS with a deliberate server policy and
request-scoped identity. Do not flip FORCE on production without a migration,
connection-role rehearsal, scheduler/backup exceptions and rollback plan.

### DS190-06 — Medium — shared public app remains in the blast radius

**Evidence.** No live cross-schema object or grant reaches coach, which passes.
The same project nevertheless holds 27 public-app tables and advisor WARNs for
mutable search paths, a public extension and callable security-definer
functions. Project owner, maintenance and quota are shared.

**Impact.** A public-app incident can exhaust database connections/egress,
complicate backup/restore, or turn an owner credential compromise into access to
private health data even when SQL object boundaries are currently correct.

**Remediation stub.** Route the public warnings to that app's owner immediately.
For durable isolation, move coach to its own Supabase project and preferably its
own organisation so billing quotas are not shared; rehearse export/import,
rotate credentials and verify exact-SHA health after cutover.

### DS190-07 — Medium — egress has no budget control

**Evidence.** Narrow compressed backups and settled-stream detection pass, but
there is no usage poll/threshold. Supabase documents egress as organisation-wide;
the same organisation has other active projects. A manual unscoped dump bypasses
the code control.

**Impact.** A recurrence can restrict platform traffic before CheckMark can
diagnose it, even if this repo's normal backup remains small.

**Remediation stub.** Capture the provider usage meter daily, alert at staged
thresholds and on anomalous deltas, document only the scoped dump command, and
assign each shared project an internal budget. Consider a separate organisation
or paid headroom after measuring steady-state usage.

### DS190-08 — Low — foreign and unknown reads have different status codes

**Evidence.** `_owned_analysis` returns 404 when absent and 403 when owned by the
other profile. Plan-action and learning paths intentionally non-disclose with
`absent`/404.

**Impact.** An authenticated second user who obtains or guesses a UUID can
confirm that a read exists. UUIDv4 entropy and the private two-user deployment
make exploitation unlikely, but the behavior is avoidably inconsistent.

**Remediation stub.** Return the same 404 for absent and foreign anchors, retain
the distinction only in structured server logs, and update the explicit 403
regression.

### DS190-09 — Low — inline history relies on a write invariant

**Evidence.** `history()` first verifies the analysis belongs to the player, then
selects messages only by `analysis_id` (`services/brief_chat.py:302-320`). Normal
writes always set the same player id, so no current HTTP path can create the
inconsistent row.

**Impact.** A repair script, future writer or data-corruption bug that associates
another user's message with the owned analysis would make it visible.

**Remediation stub.** Add `BriefMessage.user_id == player.id` to the history
query and a deliberately inconsistent-row regression. Consider a composite
database invariant if anchored messages must always share the analysis owner.

---

## 190.6 — Remediation order and verification ledger

Suggested order, without allocating implementation batches:

1. **Make failures observable first:** DS190-02 and DS190-03, including non-zero
   external exits, job-run evidence, backup paging and a real restore drill.
2. **Make execution durable:** DS190-01, one external/always-on cadence at a time,
   preserving overlap idempotency until cutover.
3. **Detect stale deploys:** DS190-04 is small and protects every later fix.
4. **Separate blast radii and budgets:** DS190-06/07; at minimum fix public
   advisor warnings and add org-level egress thresholds before considering a
   project/organisation move.
5. **Deepen data authorization:** DS190-05 requires a designed role migration;
   DS190-08/09 are small app-level hardening changes that can land independently.

### Evidence ledger

| Area | Method | Result |
|---|---|---|
| Authorization | Diff inventory + FastAPI dependency graph + ownership-path review + targeted regressions | 40 delta-router routes accounted for; no unauthenticated private route or direct cross-user bypass found |
| RLS | Live `pg_catalog`/`information_schema`, migration head, grants, policy and dependency queries | 28/28 RLS; nine hardened policies; client roles sealed; app-owner bypass remains |
| Advisors | Live Supabase security/performance advisors | no coach WARN; 24 expected coach INFO; public-app WARNs recorded |
| Backup | Railway volume metadata/files, SSH mode/tool inspection, `pg_restore --list`, live audit aggregates | durable recent archives pass structural checks; alert and actual restore do not |
| Egress | Incident stats, live archive size, source/test inspection, live table stats, current provider docs | both incident mitigations hold; no exact dashboard meter/threshold control |
| Scheduler | Railway service/cron manifests, production env defaults, source/runbook and live freshness | recent executions fresh; topology and failure semantics remain unreliable |
| Deployment | Railway deployment history + direct/proxied health/readiness | current exact SHA passes; automatic stale detection absent |

### Explicit non-actions

- No RLS policy, grant, function, schema, row or migration was changed.
- No Railway, Vercel, Supabase or GitHub configuration was changed.
- No backup was downloaded during this review and no sensitive row payload was
  copied into the repository.
- No external cron was triggered; live checks were read-only.
- The Batch 190 ledger row remains Planned and unstruck until explicit
  `/phase-closeout 190`.
