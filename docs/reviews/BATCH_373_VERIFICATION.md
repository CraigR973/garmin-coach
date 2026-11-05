# Batch 373 — Deletion residue

5 Nov 2026. Decision 475. Base `1dd118c`.

## Acceptance

- Removed the 507-line retired progression module and its four tests. No production importer existed; the current generator still uses `next_plan`.
- Removed the unused daily-loop `liveOrigin` field from computation and the current shared schema; the API retains a constant null for older clients; screen fixtures no longer supply it. Internal executable-coaching origin remains in use.
- Weekly mix requires explicit session actions to call a session dropped; missing actions no longer invoke the retired ladder fallback. Historical delivery readers remain covered.
- A packet whose `subjectDate` is after 30 Sep 2026 and lacks an engine logs `stored_morning_missing_engine` and uses graded semantics. Historical and undated packets keep their reader.
- Nullable JSONB class test inspects every registered table. It found inherited `audit_log.changes` beside `manual_entries.tonight_advice_feedback_json`; both use `none_as_null=True`. No migration or historical rewrite.

## Evidence

Production preflight (read-only transaction, watchdog, counts only): 0 JSON nulls in the manual-entry field; 0 post-switch morning packets missing an engine. Both prompt modules have identical Python ASTs to the base: only morning comment history changed. No paid eval or regeneration. No multi-row reads of a JSONB-heavy model were introduced or changed.

Final local gate: **3,421 backend passed, 0 skipped**, on a reset Postgres at migration 044; Ruff check/format and mypy passed; shared 60 and web 662 passed; web build passed; lint 0 errors, 9 existing warnings. Both exact-final-head CI waves pass on `c7d9d3b` (`42082823058` push; `42082831390` PR); merge CI `42083901904` and freshness pass on `e465ba5`. No frontend layout changed, so no visual acceptance claim is made.

Production verification (5 Nov, 18:32 GMT): both health routes serve `e465ba5`; both readiness routes report db ok and jobs ok; both protected daily-loop and coach-message routes return 401; web / and /login return 200. Vercel deployment `dpl_Bj3TJjtzwqDEfwMnvEMAWU6KNHSu` is READY, production target, exact merge SHA, and the custom domain's served entry bundle carries that build buster. Container smoke: 8 of 8 pass, read-only transaction with watchdog: retired module absent, nullable JSONB settings, unchanged prompt version, active profile, current graded morning, live weekly mix, Home's null compatibility fields, 0 manual-entry JSON nulls.

Operational exceptions: first Railway build failed with curl exit 18 during the PostgreSQL signing-key download, before application build; an exact-SHA retry succeeded. No Vercel production deployment appeared automatically despite its enabled Git link; the same Git SHA was deployed through the API, without changing configuration. Trigger cause is unresolved. One health probe returned 502 during cutover; subsequent full checks passed. The first smoke harness omitted the coach schema search path; corrected, it passes without writes. No production data, credentials, hosting settings or prompt changed.

## Rollout hold found during verification

The original claim that no screen reads `liveOrigin` is true, but incomplete: old installed clients require it in `dailyLoopDeliverySchema`, used by runtime validation. A synthetic response with the field absent fails the previous schema; the same response with `liveOrigin: null` passes. `useDailyLoop` recovers this validation failure by returning an empty `plannedWorkouts` list; check-in and answer mutations parse strictly. The PWA uses prompted updates, so a deployment does not update all running clients. No affected-device failure is claimed; this is a deterministic schema-compatibility proof.

Craig approved "Keep the temporary null field (recommended)" on 5 Nov. The API keeps a constant-null wire field while its computation and current shared declaration are removed. Backend response and previous-schema regressions pin the compatibility. Full wire deletion is explicitly deferred until the installed clients update.
