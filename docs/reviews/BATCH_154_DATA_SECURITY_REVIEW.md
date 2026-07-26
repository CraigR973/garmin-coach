# Batch 154 full-app data / security review

**Date:** 2026-07-26

**Branch:** `chore/batch-154-data-security-review`

**Mode:** diagnose-only — documentation only; no product code, migration,
production data, or runtime configuration changed

**Production database reviewed:** Supabase project
`pzqmswvozjnkxbqqowuj`, `coach` schema, read-only catalog/advisor queries

## Executive summary

The core access-control posture held:

- all **26** live `coach` tables have RLS enabled;
- `anon`, `authenticated`, and `service_role` have neither `USAGE` on the
  `coach` schema nor DML privileges on its tables;
- all **94** FastAPI endpoints are accounted for: 82 require `CurrentUser`, 3
  require `AdminUser`, and the 9 public endpoints are the intended auth,
  health, and VAPID-key surfaces;
- the recently added completed-read, analysis-chat, and learning routes enforce
  caller ownership in code; no cross-user read/write path was confirmed;
- the Anthropic API key, Garmin credentials/token blob, Hive refresh-token
  blob, JWT signing secrets, and raw stored bearer tokens are not emitted by
  normal runtime logs; and
- confirmed learning has no code path into deterministic Green/Amber/Red,
  thresholds, data-quality rules, objective metrics, or the Red-never-VO2
  delivery gate.

The review found **seven material issues: one High, five Medium, and one Low**:

1. the legacy name + four-digit PIN fallback has no durable lockout despite
   retaining lockout fields/constants, and its reset flow logs a live bearer
   reset JWT at INFO;
2. an accepted learning proposal can be edited into a new durable statement
   that is no longer bound to its cited evidence, then propagated into future
   model prompts;
3. the committed JS lockfile contains one High and three Moderate advisories,
   while CI audits only Python and Python production resolution is not locked;
4. Garmin/Hive bootstrap helpers print bearer token blobs by default or write
   them without enforcing restrictive permissions, while the scheduled
   database backup writes unbounded plaintext dumps with default permissions;
5. expensive authenticated work, most clearly self-hosted Piper synthesis,
   lacks a per-user rate or concurrency boundary;
6. RLS protects against direct Data API roles but not the FastAPI backend,
   which connects as the `postgres` owner and bypasses every policy; the live
   posture also relies on untested grant/exposed-schema invariants; and
7. the learning ownership gate is correct in code but has no explicit
   cross-user endpoint regression test.

Each finding below has a provisional remediation-batch stub. The identifiers
are review-local placeholders, not allocated ledger batch numbers.

## Acceptance result

| Batch 154 acceptance item | Result |
|---|---|
| Record every `coach.*` table's RLS state | **Pass.** All 26 are recorded below and live RLS is enabled on each. |
| Prove learning cannot reach verdicts, thresholds, data-quality rules, or Red-never-VO2 | **Pass for deterministic behavior.** The only write destination is `learned_context`; deterministic classification and delivery guards do not consume it. Narrative prompt integrity has the evidence-drift gap in DS154-02. |
| No secret logged on any path | **Fail.** The PIN reset bearer JWT is logged at INFO, and the operator bootstrap scripts print Garmin/Hive bearer blobs by default (DS154-01/04). The Anthropic key itself is not logged. |
| Confirm endpoint ownership scoping or raise gaps | **Pass for implementation.** No cross-user route was confirmed. One missing negative regression test is DS154-07. |
| Ranked findings map to remediation batches | **Pass.** R154-A through R154-G below. |
| Diagnose-only apart from optional `admin_alert_user_id` seed | **Pass.** No mutation was performed. At kickoff the seed was moved to a standalone ops batch because it requires resolving Craig's production profile UUID and mutating Railway configuration, neither of which belongs in a read-only review. |

## Ranked findings

### DS154-01 — High — the legacy PIN/reset fallback has no durable brute-force guard and logs its reset bearer credential

**Evidence**

- Login and PIN reset accept exactly four digits
  (`apps/api/src/routers/auth.py:51-53`, `82-93`).
- Constants and profile columns still describe a five-attempt, 15-minute
  durable lockout (`apps/api/src/auth.py:26-33`,
  `apps/api/src/models/profile.py:47-48`), and `rate_limit.py` explicitly says
  the in-process counter is only a short-term layer over that DB lockout
  (`apps/api/src/rate_limit.py:16-19`).
- The login handler neither reads `locked_until` nor increments/resets
  `failed_login_count`; a wrong PIN immediately returns 401
  (`apps/api/src/routers/auth.py:143-168`). The unit test deliberately supplies
  `failed_login_count=99` and still expects an ordinary 401
  (`apps/api/tests/test_auth.py:192-204`).
- The only effective login guard is SlowAPI's in-memory
  `5/15 minutes` bucket keyed by display name + remote address. It resets with
  the process and can be split across source addresses or future replicas.
- `POST /pin/reset-request` creates a 30-minute bearer JWT and logs the raw
  token at INFO (`apps/api/src/routers/auth.py:398-423`,
  `apps/api/src/auth.py:110-129`). Anyone with log access during that window can
  set a new four-digit PIN and the reset then revokes the user's existing
  tokens.
- The stronger primary path is sound: one-use 30-minute activation codes mint
  random 365-day opaque device tokens, only SHA-256 hashes are stored, and
  every request rechecks that the profile is active and not deleted
  (`apps/api/src/routers/auth.py:264-335`, `apps/api/src/auth.py:137-195`).
  Production config rejects weak/missing JWT secrets
  (`apps/api/src/config.py:99-126`).

**Impact**

The private deployment and IP/name rate limiter reduce casual exposure, but
the fallback credential has only 10,000 possible values and no persistent
attempt state. The reset design also makes the application log a credential
delivery channel. This is a confirmed secret-log violation and a direct
account-takeover path for anyone who obtains the reset token.

**Existing decision**

This is the still-open P1-1/P3-3 finding from `docs/reviews/v1-v2-review.md`.
The architecture already chose passwordless device activation as the end
state and says not to spend a separate product phase polishing the temporary
PIN system. This review does not reverse that decision; it confirms the risk
remains until Auth Phase 3 removes or fully disables the fallback.

**Proposed remediation batch R154-A — complete Auth Phase 3**

- Remove the production name/PIN login, PIN change, PIN reset-request, and PIN
  reset surfaces after every intended device has an activation/recovery path.
- If removal cannot ship immediately, stop logging reset JWTs and replace the
  log-as-delivery mechanism with an authenticated, single-use operator flow.
- Revoke residual PIN-era refresh tokens as part of cutover and verify the
  passwordless device-token revocation/recovery runbook.
- Add production-mode tests proving the PIN routes are unavailable and no raw
  bearer credential reaches structured logs.

### DS154-02 — Medium — accepted learning edits are not evidence-bound and can inject future narrative prompts

**Evidence**

- Initial extraction is strong: strict typed JSON fixes the destination to
  `learned_context`; code validates durable taxonomy, real source IDs, verbatim
  user-authored quotes, forbidden verdict/data-quality language, and repeated
  evidence for uncued recurring themes
  (`apps/api/src/services/conversation_learning.py:217-295`).
- Distillation writes only `pending` proposal rows. Pending/rejected proposals
  never enter the knowledge base; acceptance is an explicit authenticated
  action.
- On acceptance, however, caller-supplied edited text is checked only by
  `statement_is_durable`. It is not checked for semantic or textual support by
  the proposal's original evidence (`conversation_learning.py:589-622`).
- The accepted statement is stored beside the unchanged old evidence and
  appended to the active version of `knowledge_base.section='learned_context'`
  (`conversation_learning.py:624-662`).
- A crafted but blacklist-avoiding durable instruction — for example a
  statement telling the narrative coach to disregard prior guidance and
  prescribe maximal work — can therefore be substituted at confirmation even
  when its evidence says something unrelated.
- `learned_context_packet` labels the content
  `classificationImpact: "none"` and includes a natural-language rule
  (`apps/api/src/services/learned_context.py:9-20`). That is useful prompt
  guidance, not a sanitizer or an enforcement mechanism for generated prose.

**What is and is not reachable**

- **Not reachable:** `_morning_verdict`, Green/Amber/Red, thresholds,
  #133/#135 data-quality logic, objective metric assembly, knowledge-base
  sections other than `learned_context`, plan mutation, and the code-side
  Red-never-VO2 delivery gate. Morning computes its deterministic verdict
  independently; post-session packets likewise consume learned memory only as
  narrative context.
- **Reachable after human acceptance:** future Anthropic prompts for morning
  and post-session prose. A hostile accepted statement can bias explanation or
  advice and can make prose contradict the deterministic verdict even though
  it cannot change the verdict value or deliver a blocked workout.
- **Threat precondition:** the authenticated user must accept the proposal or
  submit the edited statement. This confirmation gate materially lowers
  likelihood, which is why this is Medium rather than High.

**Test gap**

Tests prove verdict-language edits are rejected and a reasonable paraphrase is
accepted, but they do not prove that an edit remains supported by the recorded
evidence or that an instruction-shaped, blacklist-avoiding edit is rejected
(`apps/api/tests/test_conversation_learning.py:271-375`).

**Proposed remediation batch R154-B — evidence-preserving learning acceptance**

- Prefer immutable extracted statements at acceptance, or constrain editing to
  an evidence-supported correction flow that re-runs the same candidate
  validation against current user-authored sources.
- Reject instruction-shaped memory and separate factual memory from prompt
  instructions structurally; do not rely on a growing phrase blacklist alone.
- Delimit learned statements as untrusted quoted data in every model prompt and
  add contradiction tests showing accepted memory cannot make output advise
  against the deterministic verdict/guardrails.
- Add adversarial tests for unrelated edited statements, prompt-injection
  wording, stale/missing evidence, and supported paraphrases.

### DS154-03 — Medium — vulnerable JS dependencies are locked while CI has no JS audit and Python builds are not reproducible

**Evidence**

- `pnpm audit --prod --audit-level low` against the committed lockfile found:
  - **High:** `postcss@8.5.14`, path traversal / arbitrary `.map` disclosure,
    [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849);
  - **Moderate:** `react-router@6.30.4`, backslash open redirect,
    [GHSA-wrjc-x8rr-h8h6](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6);
  - **Moderate:** `react-router-dom@6.30.4`, open redirect leading to XSS,
    [GHSA-jjmj-jmhj-qwj2](https://github.com/advisories/GHSA-jjmj-jmhj-qwj2);
    and
  - **Moderate:** `react-router@6.30.4`, SSR hydration constructor injection,
    [GHSA-337j-9hxr-rhxg](https://github.com/advisories/GHSA-337j-9hxr-rhxg).
- The app declares `react-router-dom ^6.30.4` and PostCSS/Tailwind build
  dependencies (`apps/web/package.json:47`, `81-82`).
- CI's `security-audit` job installs and runs only `pip-audit`
  (`.github/workflows/ci.yml:162-173`). The former JS audit was removed when
  npm retired an endpoint, but no replacement was added.
- Python runtime requirements are lower bounds rather than exact pins/hashes
  (`apps/api/requirements.txt:1-24`). The Railway image uses mutable
  `python:3.12-slim` and resolves those ranges afresh during each build
  (`Dockerfile:1-9`), so CI cannot prove the package set in an already-running
  image.
- Resolving the Python requirements on 2026-07-26 with `uv pip compile` and
  auditing that exact resolution with `pip-audit --no-deps --disable-pip`
  found **no known runtime-package vulnerabilities**. Direct
  `pip-audit -r` could not create its macOS temporary venv in this local
  environment; the compile-then-audit path is the recorded fallback.
- The installed development environment separately reports vulnerabilities in
  its old `pip`/`setuptools`, but those packages are not declared runtime
  requirements and do not establish the versions inside the current Railway
  image.

**Applicability**

- PostCSS processes repository-owned CSS only during the static Vercel build;
  the app has no user-submitted CSS processor. The advisory's required
  untrusted-CSS path is not reachable at runtime.
- The app is a Vite client-side app using React Router declarative mode, not
  Framework/Data mode SSR hydration, so the constructor-injection advisory is
  not applicable.
- Current navigation targets are constants, deterministic backend action
  routes, or push URLs normalized through `new URL` and restricted to the
  current origin. No query-string-controlled redirect target was found, so the
  two open-redirect advisories have no confirmed exploit path today.
- These compensating facts lower immediate exploitability, but do not justify
  keeping known-vulnerable packages or leaving the JS tree unaudited. The
  localStorage-held 365-day device token makes a future browser XSS especially
  consequential (`apps/web/src/lib/tokens.ts:1-42`).

**Proposed remediation batch R154-C — reproducible dependency security**

- Update/override PostCSS to at least 8.5.18.
- Plan and test the React Router 7.18+ migration; preserve the existing
  same-origin navigation normalization and CSP.
- Add a maintained JS advisory command to CI and fail on applicable High
  findings, with explicit reviewed exceptions for non-reachable build/SSR
  advisories rather than silently omitting the ecosystem.
- Produce a hashed Python runtime lock/constraints file from the declared
  inputs and build/audit that exact set; pin the runtime image by supported
  version or digest and retain an SBOM/build manifest.
- Add a tracked-content/history-aware secret scanner to CI; the review's
  high-confidence tracked-file pattern scan found no committed credential but
  is not a replacement for a dedicated scanner.

### DS154-04 — Medium — token bootstrap and database-backup artifacts do not enforce secret/data-at-rest hygiene

**Evidence**

- The Garmin bootstrap prints `GARMIN_TOKENSTORE_B64` to stdout when
  `--env-output` is omitted; its file path writes both the tokenstore location
  and bearer blob with ordinary `Path.write_text`
  (`scripts/bootstrap_garmin_tokenstore.py:15-46`).
- The Hive bootstrap likewise prints the base64 JSON containing username +
  Cognito refresh token by default or writes it with ordinary
  `Path.write_text` (`scripts/bootstrap_hive_tokenstore.py:23-59`).
- Neither helper creates output atomically with mode `0600`, checks an existing
  file's ownership/mode, or warns that stdout may be captured by terminal,
  shell, CI, or remote-session logs. File permissions therefore depend on the
  operator's umask.
- Normal Garmin/Hive runtime paths do not log the blobs: the values are decoded
  in memory and failures use generic messages
  (`apps/api/src/services/garmin_sync.py:123-189`,
  `environment_sync.py:121-167`, `443-451`).
- The daily backup runs `pg_dump` without a schema filter and writes a
  plaintext `.sql` file under `/tmp/garmin_coach_backups`; directory/file mode
  is not set and no retention or deletion policy is applied
  (`apps/api/src/services/backup.py:53-103`,
  `apps/api/src/config.py:93-94`). On the shared Supabase database, the absence
  of `--schema=coach` can include data beyond this app when the connection role
  can read it.
- The backup service correctly strips the database password from the process
  argv and supplies it through `PGPASSWORD`; logs contain only filename/size on
  success. The issue is plaintext artifact scope, permission, and retention,
  not password exposure.

**Impact**

The token blobs are durable bearer credentials that can resume Garmin/Hive
sessions. The backup can contain longitudinal health, profile, chat, and auth
data — potentially more than the `coach` schema — and accumulates for the life
of the container. A permissive umask, captured operator output, container
debug access, or another same-user process can expose long-lived credentials
or a broad plaintext data copy.

**Proposed remediation batch R154-D — secure operator artifacts and backups**

- Make stdout secret emission an explicit `--stdout` opt-in; default to a
  securely created `0600` file or a direct secret-manager/Railway-variable
  workflow.
- Create tokenstore directories/files with restrictive modes, refuse unsafe
  existing targets, and document safe rotation/revocation.
- Decide whether the in-container backup is still useful beside Supabase's
  managed backups. If retained, restrict it to `coach`, create directory/files
  `0700`/`0600`, encrypt before durable storage, cap retention, remove failed
  partials, and test mode/scope/expiry.
- Never attach raw token or dump content to logs, alerts, tickets, or review
  artifacts.

### DS154-05 — Medium — expensive authenticated work has no per-user rate or concurrency boundary

**Evidence**

- `POST /api/v1/tts/synthesize` requires an active user and explicit hosted-TTS
  consent, but has no `@limiter.limit`, per-user concurrency guard, or queue
  (`apps/api/src/routers/tts.py:75-110`).
- Each unique caller-provided string can contain up to 6,000 characters and
  bypass the 20-entry content cache. Piper runs a CPU-bound subprocess in a
  worker thread with a 90-second timeout
  (`apps/api/src/services/tts_cache.py:20-44`,
  `apps/api/src/services/piper_tts.py:25-32`, `45-92`).
- SlowAPI limits exist on login/refresh/activation/PIN-change/reset and push
  test, but not TTS, learning distillation, review/trend/handover generation,
  block generation/refinement, or several other paid/CPU-heavy authenticated
  paths.
- Device tokens are intentionally long-lived (365 days) and stored in browser
  localStorage. A stolen but unrevoked token can therefore drive the same
  expensive routes as the legitimate user.

**Impact**

The intended 1–2 trusted users make accidental or malicious pressure unlikely,
but a compromised token, retry loop, or concurrent tabs can exhaust a small
Railway instance and/or create avoidable paid model calls. Authentication
protects data ownership; it is not a workload budget.

**Related finding**

CR153-04 already found missing request identity/leases for duplicate generation.
This security finding broadens the remediation boundary to per-user abuse and
local CPU saturation rather than creating a competing idempotency design.

**Proposed remediation batch R154-E — authenticated workload budgets**

- Add per-user rate limits and a small global/per-user semaphore or DB-backed
  lease for TTS and every paid generation boundary.
- Give identical work an idempotency identity and return/reuse in-flight or
  cached work instead of launching another call.
- Bound queue depth and return an honest retryable 429/503 without spawning
  more subprocesses.
- Add tests for concurrent TTS/generation, unique-input cache bypass, stolen
  token revocation, and recovery after timeout.

### DS154-06 — Medium — live RLS is a Data API backstop, not backend row isolation, and its safety invariants can drift silently

**Evidence**

- All live tables have `relrowsecurity=true`, but all have
  `relforcerowsecurity=false`. FastAPI connects as the `postgres` table owner,
  so every backend query bypasses RLS by design
  (`migrations/versions/015_coach_rls.py:14-21`).
- Twenty-two tables intentionally have no policies. For direct non-owner roles
  that is deny-all, not a missing user predicate.
- The four policy-bearing tables retain migration 001's policies:
  `profiles`, `refresh_tokens`, `push_subscriptions`, and
  `notification_preferences`. They omit an explicit `TO authenticated`; the two
  UPDATE policies omit `WITH CHECK`; and every policy calls `auth.uid()`
  directly rather than `(select auth.uid())`
  (`migrations/versions/001_core_schema.py:233-257`).
- Those policy weaknesses are not exploitable now because `anon`,
  `authenticated`, and `service_role` lack schema usage and table DML grants.
  They become relevant if direct Data API access is ever granted.
- The only `coach` function, `coach.set_updated_at()`, is invoker-security and
  executable by `PUBLIC`, with no fixed `search_path`. Callers still cannot
  resolve it without `coach` schema usage, but Supabase correctly reports
  `function_search_path_mutable`.
- `test_coach_rls_migration.py` proves model tables appear in the migration
  coverage constants. It does not assert the live no-grant posture, exposed
  schema configuration, `FORCE RLS`, policy roles/`WITH CHECK`, or application
  role privileges.

**Impact**

A future stray grant or exposed-schema change is contained by deny-all on 22
tables, but the legacy policy tables would suddenly rely on older,
under-specified policy definitions. More importantly, an application ownership
bug or SQL injection in FastAPI is not contained by RLS at all: the connection
role can read every user's health data. This is a known architecture tradeoff,
not evidence of a current leak, but its blast radius is Medium for sensitive
multi-user data.

**Advisor interpretation**

- Supabase reports **no `rls_disabled` finding** for `coach`.
- It reports 22 INFO
  `rls_enabled_no_policy` notices. These are expected for the deny-all/Data API
  posture; see the
  [Supabase lint explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).
- It reports the one WARN
  [`function_search_path_mutable`](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable)
  on `coach.set_updated_at`.
- Additional advisor findings in `public` belong to the other application
  sharing this Supabase project. They were not reclassified as Garmin Coach
  findings because no Garmin role has `coach` access through them; they should
  remain in that application's own security review.

**Proposed remediation batch R154-F — least-privilege backend role and live RLS drift checks**

- Decide whether to move FastAPI from `postgres` to a dedicated least-privilege
  app role. If cross-user RLS is desired, add complete policies and validate
  behavior under that real role before enabling `FORCE ROW LEVEL SECURITY`.
- Harden existing policies with explicit roles, `(select auth.uid())`, and
  `WITH CHECK` for UPDATE. Revoke unnecessary function execution and set a safe
  function `search_path`.
- Add a read-only deployment/CI posture check that fails if any `coach` table
  lacks RLS, the Data API roles gain schema/table privileges unexpectedly, or
  the exposed-schema list changes.
- Keep application-layer ownership tests even if RLS becomes effective;
  defense in depth must not replace correct queries.

### DS154-07 — Low — learning ownership is enforced but lacks a cross-user endpoint regression test

**Evidence**

- Proposal listing filters `ConversationLearningProposal.user_id ==
  player.id`; review locks the row and returns the same 404 for missing or
  foreign-owned proposals (`apps/api/src/services/conversation_learning.py:552-587`).
- The completed-read lookup filters both workout linkage and `Analysis.user_id`;
  a foreign workout ID returns the honest empty state. Its DB test explicitly
  covers an owner and a stranger
  (`apps/api/tests/test_plan_actions.py:1141-1171`).
- Brief chat verifies the `Analysis.user_id` before reading/writing messages,
  and tests unknown 404 plus foreign-owner 403
  (`apps/api/src/services/brief_chat.py:175-205`,
  `apps/api/tests/test_brief_chat.py:309-346`).
- Feedback has the same ownership gate and negative tests
  (`apps/api/src/services/feedback.py:104-113`,
  `apps/api/tests/test_feedback.py:121-161`).
- Conversation-learning integration tests cover extraction, pending-only
  distillation, accept/reject, KB versioning, and verdict-lever rejection, but
  do not attempt to list/review another profile's proposal.

**Impact**

No exploitable cross-user learning path was found. The risk is regression:
this is one of the newest and most sensitive write paths, and its ownership
contract is less directly pinned than adjacent completed-read/chat/feedback
routes.

**Proposed remediation batch R154-G — complete ownership regression matrix**

- Add DB-backed endpoint tests proving a second profile cannot list, accept,
  edit, or reject the owner's learning proposal and that no KB version is
  written.
- Add a small route-inventory test/lint that requires every non-public endpoint
  to declare `CurrentUser` or `AdminUser`; keep explicit ownership tests for
  every path-ID resource.
- Document the household fan-control assumption: today any authenticated
  profile can control the shared Dreo account. If a second user must not share
  that device, add an ownership/role model before onboarding them.

## Live RLS inventory

The catalog was queried read-only on 2026-07-26. Every row below has:

- `RLS = enabled`;
- `FORCE RLS = false`;
- no `anon`, `authenticated`, or `service_role` DML privilege; and
- no direct role access because all three roles also lack `USAGE` on `coach`.

`Policy posture` describes only direct Data API behavior. FastAPI uses the
owner role and depends on the application ownership sweep in the next section.

| Table | RLS migration | Policy posture |
|---|---|---|
| `profiles` | 001 | own-row SELECT/UPDATE via `auth.uid()` |
| `refresh_tokens` | 001 | own-row SELECT/INSERT/DELETE via `auth.uid()` |
| `push_subscriptions` | 001 | own-row SELECT/INSERT via `auth.uid()` |
| `notification_preferences` | 001 | own-row SELECT/UPDATE via `auth.uid()` |
| `audit_log` | 001 | no policy → deny-all non-owner |
| `daily_metrics` | 015 | no policy → deny-all non-owner |
| `sleep` | 015 | no policy → deny-all non-owner |
| `activities` | 015 | no policy → deny-all non-owner |
| `activity_timeseries` | 015 | no policy → deny-all non-owner |
| `temperature_readings` | 015 | no policy → deny-all non-owner |
| `fan_state_readings` | 015 | no policy → deny-all non-owner |
| `weather_daily` | 015 | no policy → deny-all non-owner |
| `metric_baselines` | 015 | no policy → deny-all non-owner |
| `manual_entries` | 015 | no policy → deny-all non-owner |
| `plan_blocks` | 015 | no policy → deny-all non-owner |
| `planned_workouts` | 015 | no policy → deny-all non-owner |
| `workout_delivery_proposals` | 015 | no policy → deny-all non-owner |
| `garmin_workout_deliveries` | 015 | no policy → deny-all non-owner |
| `analyses` | 015 | no policy → deny-all non-owner |
| `feedback` | 015 | no policy → deny-all non-owner |
| `experiments` | 015 | no policy → deny-all non-owner |
| `knowledge_base` | 015 | no policy → deny-all non-owner |
| `alembic_version` | 015 | no policy → deny-all non-owner |
| `brief_messages` | 019 | no policy → deny-all non-owner |
| `brief_generation_status` | 020 | no policy → deny-all non-owner |
| `conversation_learning_proposals` | 021 | no policy → deny-all non-owner |

There are no `coach` views. The sole function is `coach.set_updated_at()`,
covered in DS154-06.

## Endpoint authorization inventory

The inventory is AST-derived from every FastAPI route decorator under
`apps/api/src/routers`, then each path-ID and recent sensitive service was
deep-read for ownership predicates.

| Router | Endpoints | Public | `CurrentUser` | `AdminUser` |
|---|---:|---:|---:|---:|
| `auth` | 9 | 6 | 3 | 0 |
| `bedroom` | 1 | 0 | 1 | 0 |
| `block_generator` | 5 | 0 | 5 | 0 |
| `breathwork_brief` | 1 | 0 | 1 | 0 |
| `brief_chat` | 2 | 0 | 2 | 0 |
| `coaching_state` + coach-memory | 7 | 0 | 4 | 3 |
| `daily_loop` | 4 | 0 | 4 | 0 |
| `experiments` | 6 | 0 | 6 | 0 |
| `fan` | 2 | 0 | 2 | 0 |
| `feedback` | 1 | 0 | 1 | 0 |
| `handover` | 3 | 0 | 3 | 0 |
| `health` | 2 | 2 | 0 | 0 |
| `holiday` | 3 | 0 | 3 | 0 |
| `insights` | 4 | 0 | 4 | 0 |
| `me` | 1 | 0 | 1 | 0 |
| `notifications` | 6 | 1 | 5 | 0 |
| `plan_actions` | 10 | 0 | 10 | 0 |
| `restructure` | 2 | 0 | 2 | 0 |
| `reviews` | 2 | 0 | 2 | 0 |
| `sleep` | 1 | 0 | 1 | 0 |
| `strength_brief` | 1 | 0 | 1 | 0 |
| `trends` | 4 | 0 | 4 | 0 |
| `tts` | 2 | 0 | 2 | 0 |
| `walking_brief` | 1 | 0 | 1 | 0 |
| `workout_delivery` | 14 | 0 | 14 | 0 |
| **Total** | **94** | **9** | **82** | **3** |

The nine intended public endpoints are:

- six auth-flow routes: login, refresh, logout, activate, reset request, reset;
- liveness and readiness; and
- the VAPID public key.

`CurrentUser` resolves either a verified access JWT or a hashed opaque device
token, then loads an active, non-deleted profile. `AdminUser` checks the role
from that live DB profile rather than trusting the JWT role claim
(`apps/api/src/auth.py:158-207`).

### Sensitive recent-route conclusions

- **Completed read:** lookup includes `Analysis.user_id == player.id` and the
  requested `planned_workout_id`; the foreign-user test passes.
- **Analysis chat:** analysis ownership is checked before message history or
  writes; unknown/foreign tests pass and no failed model call writes half a
  turn.
- **Learning:** list/distill sources and proposals are user-filtered; review
  returns 404 for missing/foreign ownership. DS154-07 records only the missing
  explicit negative test.
- **Feedback/experiments/plan/delivery IDs:** resource services either query
  with `user_id == player.id` or fetch then reject a mismatched owner before
  mutation. No cross-user read/write was confirmed.
- **Shared household hardware:** fan commands are authenticated but control the
  shared Dreo account rather than a user-owned fan row. This matches the current
  single-household deployment assumption; DS154-07 says to settle it before an
  unrelated second user is onboarded.

## Secret, log, and envelope review

### Verified controls

- Anthropic's API key exists only in the `x-api-key` request header. Runtime
  error logging records status, classified reason, provider error type, and
  provider message — never request headers, payload, or the key
  (`apps/api/src/services/anthropic_text.py:109-188`).
- Garmin and Hive runtime exceptions do not interpolate credential/blob
  values. Garmin may include the configured tokenstore **path**, not its
  content.
- JWT/device/refresh raw tokens are returned only at issuance. Database rows
  keep hashes; refresh rotation/revocation is implemented.
- Production requires distinct strong JWT signing secrets, private VAPID,
  Supabase service key, Anthropic key, database URL, and a non-local frontend
  origin before startup.
- Production OpenAPI/docs are disabled; CORS is restricted to the configured
  frontend; Vercel sets a same-origin CSP, frame denial, `nosniff`, restrictive
  permissions policy, and no third-party script origin (`vercel.json:16-29`).
- API-facing Anthropic failures use generic user messages on the current
  in-request chat/check-in paths. Review/trends/handover can expose only the
  service's small static `ReviewError` strings through `errors[].detail`; no
  provider response body, prompt, credential, or traceback was found in those
  envelopes.
- A high-confidence scan of tracked non-doc files found no Anthropic, GitHub,
  Supabase secret, private-key, AWS access-key, or JWT-shaped credential.
  This did not scan Git history and is not a CI control.

### Confirmed exceptions

- PIN reset logs the live reset bearer (DS154-01).
- Bootstrap helpers deliberately emit Garmin/Hive bearer blobs (DS154-04).
- Plaintext broad-scope database backups are written with implicit
  permissions/retention (DS154-04).

## Verification performed

- Live Supabase security and performance advisors, plus read-only catalog
  checks for tables, RLS/FORCE state, policies, role schema/table privileges,
  functions, and views.
- Migration cross-check across 001, 015, 019, 020, and 021 and the pure
  migration/model coverage test.
- Static inventory of all 94 FastAPI route decorators and auth dependency
  annotations; deep read of recent/sensitive path-ID ownership services and
  negative tests.
- Threat-model trace from user-authored source → extracted candidate → pending
  proposal → review/edit → versioned KB → morning/post-session packets →
  deterministic verdict/delivery boundaries.
- Runtime log/error scan across auth, Anthropic, Garmin, Hive, backups,
  schedulers, and envelope exception paths.
- Dependency audits:
  - `pnpm audit --prod --audit-level low`: completed with 1 High + 3 Moderate
    findings;
  - `uv pip compile` current runtime resolution →
    `pip-audit --no-deps --disable-pip`: no known runtime-package
    vulnerabilities;
  - installed local Python environment audit: only local `pip`/`setuptools`
    toolchain advisories, not declared app runtime dependencies.
- Focused backend pytest:
  `test_coach_rls_migration`, `test_conversation_learning`,
  `test_brief_chat`, `test_plan_actions`, `test_auth`, `test_config`,
  `test_anthropic_text`, and `test_backup`:
  **62 passed / 35 expected Postgres-backed skips**.
- Tracked-content credential-pattern scan: no match.

## Scope boundaries

This review intentionally does not:

- fix or reprioritize the findings before Craig reviews them;
- seed `admin_alert_user_id` or mutate Railway/Supabase/Vercel production
  configuration;
- change product code, tests, migrations, policies, prompts, verdicts,
  thresholds, or the phase ledger status;
- perform Batch 155's model-behavior/coaching-integrity evaluation; or
- perform Batch 156's live cross-route UX walkthrough.

`ARCHITECTURE.md` remains unchanged because the review diagnosed residual
implementation and operational risk without changing the accepted system
specification or data model.
