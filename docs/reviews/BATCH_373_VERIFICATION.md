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

Full local gate: 3,420 backend tests passed, 0 skipped (fresh Postgres at migration 044); Ruff check/format and mypy passed; shared 59 and web 662 passed; web build passed; lint 0 errors, 9 existing warnings. The first full run found 3 stale test fixtures (3,417 passed, 0 skipped); corrected, the final full run is green. The approved compatibility change adds paired backend/legacy-schema checks; its final full gate and exact-SHA push/PR CI are running. Production verification follows the green gate.

## Rollout hold found during verification

The original claim that no screen reads `liveOrigin` is true, but incomplete: old installed clients require it in `dailyLoopDeliverySchema`, used by runtime validation. A synthetic response with the field absent fails the previous schema; the same response with `liveOrigin: null` passes. `useDailyLoop` recovers this validation failure by returning an empty `plannedWorkouts` list; check-in and answer mutations parse strictly. The PWA uses prompted updates, so a deployment does not update all running clients. No affected-device failure is claimed; this is a deterministic schema-compatibility proof.

Craig approved "Keep the temporary null field (recommended)" on 5 Nov. The API keeps a constant-null wire field while its computation and current shared declaration are removed. Backend response and previous-schema regressions pin the compatibility. Full wire deletion is explicitly deferred until the installed clients update.
