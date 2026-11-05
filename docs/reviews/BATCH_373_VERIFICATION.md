# Batch 373 — Deletion residue

5 Nov 2026. Decision 475. Base `1dd118c`.

## Acceptance

- Removed the 507-line retired progression module and its four tests. No production importer existed; the current generator still uses `next_plan`.
- Removed the unused daily-loop `liveOrigin` field from computation, API and shared schema; screen fixtures no longer supply it. Internal executable-coaching origin remains in use.
- Weekly mix requires explicit session actions to call a session dropped; missing actions no longer invoke the retired ladder fallback. Historical delivery readers remain covered.
- A packet whose `subjectDate` is after 30 Sep 2026 and lacks an engine logs `stored_morning_missing_engine` and uses graded semantics. Historical and undated packets keep their reader.
- Nullable JSONB class test inspects every registered table. It found inherited `audit_log.changes` beside `manual_entries.tonight_advice_feedback_json`; both use `none_as_null=True`. No migration or historical rewrite.

## Evidence

Production preflight (read-only transaction, watchdog, counts only): 0 JSON nulls in the manual-entry field; 0 post-switch morning packets missing an engine. Both prompt modules have identical Python ASTs to the base: only morning comment history changed. No paid eval or regeneration. No multi-row reads of a JSONB-heavy model were introduced or changed.

Full local gate and exact-SHA push/PR CI: running. Production deployment and read-only container smoke: pending those gates.
