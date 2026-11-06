# Batch 371 — backup isolation and spare services

6 Nov 2026. Decision 477. **Built, unmerged, not closed.** Craig approved the provider/key/settings scope and PUBLIC revoke. He is creating Neon/B2; their details remain missing. No live offsite archive/restore proof exists yet. No paid call, production data deletion, existing archive retirement, API deploy or production migration has occurred.

## How recovery works

The API creates an owner-only dump in Linux RAM, reads its complete data stream, encrypts to an off-platform age identity's public recipient and publishes only ciphertext on the retained volume. Seven new encrypted nightly and four full archives remain the local retention policy; existing plaintext is preserved. Missing key, corrupt data or failed encryption stops the backup rather than retaining plaintext. Sunday exports both the newest full and nightly ciphertext to private B2, with independent bucket/prefix-scoped upload and read keys. The uploader has no read/delete/admin rights. Downloads are bounded and checksum-checked.

GitHub's reviewed-main-only Sunday 04:17 UTC workflow decrypts and restores both archives into the dedicated Neon `coach_restore` database. It rejects production/other targets and verifies server identity/absence of another application's tables before writes. It restores existing Supabase RLS dependencies through isolated no-login roles/NULL uid, checks schema/version/authored data/exclusions, then clears the disposable schema. Only safe status/counts are printed, with no database stderr, tracebacks, archive artifacts or caches. A killed runner can leave the disposable copy until cleanup; a failed run must be investigated.

The API's daily 05:00 UTC `backup-drill` checks the actual public workflow result without a private key or restore URL. Missing, stale or failed proof fails; the latest completed failure cannot hide behind an older success. `/health/jobs` independently requires a successful proof within eight days. Both offsite archives may be up to eight days old (weekly RPO), so a midweek manual proof can verify the existing weekly pair without pretending a new nightly export happened. The external 30-minute watchdog reads the result.

Migration 045 removes EXECUTE from PUBLIC, anon and authenticated on `public.rls_auto_enable()`, retaining owner/event-trigger use. Plain test Postgres without the hosted function is supported. Downgrade deliberately does not re-open the public privilege.

## Completed operational work

- The fresh Railway plan named two service deletions and the already documented API-default drift (restart policy/sleep flag). The whole-project plan was **not applied**. Exact service IDs/project/environment selectors deleted only `trend-narratives` and `weekly-review`, following Craig's approval of 2 Nov and a notice immediately before action on 6 Nov. The in-process jobs remain.
- A complete before/after configuration comparison found `api` and `api-volume` equal. The service inventory is now API only; API deployment `2e95682a-9868-47da-a2d7-a63dee5a0bd3` remained SUCCESS. All direct/proxy health/readiness/jobs/auth/web checks passed on main `97b92c0`. No API restart or merge inside the morning hold.
- A dedicated age identity was generated in the Mac's private configuration folder (0700 directory/0600 file), saved to GitHub `BACKUP_AGE_IDENTITY`, and its matching public recipient staged in Railway with `--skip-deploys`. The actual private/public pair passed a synthetic encrypt/decrypt round trip. Secret contents were never printed or committed. Craig must save his password-manager recovery copy.
- No B2 or Neon account/resource was created by the agent. Their credentials remain absent. Craig confirmed that he will create those resources; the agent will apply the approved settings from private files. The local optional bucket-key helper creates minimal scoped keys, refuses overwrites and never puts master credentials into the app or stdout/argv.

## Validation

Final full local gate: **3,466 backend passed, 0 skipped**, on reset Postgres at migration 045; shared 60/web 680; Ruff/format/mypy pass; web build/lint pass (0 errors, 9 existing warnings). The final full run took 135.42 seconds. Both exact-head push/PR CI waves are required and exposed in the draft PR's checks; there is no merge until inputs/live verification prerequisites are ready.

Earlier fixture/stale-assertion failures and an AsyncMock warning were corrected; no unrelated behaviour assertion was removed. One in-flight full run was stopped to incorporate guard changes and restarted on a reset database; only complete runs count as gates. Safety review added foreign-table rejection, weekly-age support for midweek manual proof, empty/ambient host-override rejection, hostname-verified TLS with system roots and no credential forwarding on helper redirects.

The real synthetic PostgreSQL integration creates fresh databases, uses real pg_dump/age/pg_restore for full and nightly archives, restores an actual auth-dependent policy, compares authored JSON, checks weekly-only/sample exclusions, clears the disposable schema and exercises the real privilege-revoke SQL. Local pgserver/tools are PostgreSQL 16.2; production/Neon target 17 is a **live verification prerequisite**, not inferred from this local test. CI installs age and uses its runner PostgreSQL. The offsite workflow explicitly installs the PostgreSQL 17 client from PGDG.

Other checks cover tamper/wrong-key cleanup, no plaintext on the retained volume, missing public key before dumping, failed integrity, least-privilege bucket authentication, receipt verification, corrupt/oversized downloads, pagination/age selection, production/pooler/alias target rejection, no target mutation before both archives decrypt/check, upload failure propagation, and proof freshness/latest-failure rules. Public logs contain synthetic data only. No multi-row JSONB-heavy model read was added; watchdog uses the small typed job-ledger projection. Morning/notes-reader prompt modules remain unchanged.

The recovery recipe chooses the newest archive by date, not the nightly label. Sunday's full may be newer than Saturday's newest nightly; in that case it restores authored state by itself. A newer nightly needs only the full archive's raw sleep/daily-metrics rows added. The legacy local proof helper now leaves the newer dated archive last, tested on both sides of Sunday; the external proof continues to validate each kind independently and then clears the target.

## Remaining release gates

1. Craig creates Neon/B2 and supplies private file paths, saves a recovery-key copy; the agent sets the approved remaining Railway/GitHub settings without exposing secrets. Verify key scopes/TLS/target before enabling export.
2. Both exact-head CI waves pass. Merge only outside 06:00–11:00 London, once inputs are ready. Until then production continues its existing backup code.
3. On the deployed image, create/check encrypted copies without deleting existing plaintext, copy the weekly pair, manually run the real GitHub restore on reviewed main, verify Neon/PostgreSQL 17 and cleanup, time the drill and drive the real evidence lookup. Missing live proof is a blocker.
4. Verify exact deployed SHA, actual frontend SHA, all required routes/jobs/readiness/auth/web and a read-only container smoke. Only then can the normal close-out proceed; any remaining plaintext retirement requires Craig's exact-scope decision after encrypted copies are proved. No paid upgrade or production data deletion is authorised here.
