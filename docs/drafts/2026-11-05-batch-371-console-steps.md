# Batch 371 — remaining owner setup

6 Nov 2026. Decisions 477–478. **Neon is no longer required.** Craig approved replacing it with temporary PostgreSQL in GitHub Actions, then asked the agent to implement that change. This guide supersedes the original Neon instructions and broad console key presets.

## What is already done

The agent generated the dedicated age identity at `/Users/craigrobinson/.config/garmin-coach/backup-age-key.txt` (0600 inside a 0700 folder), saved it in GitHub `BACKUP_AGE_IDENTITY`, staged its matching public Railway `BACKUP_AGE_RECIPIENT` without deployment and verified a synthetic round trip. Do not regenerate it. Craig still saves a password-manager recovery copy of the complete existing file.

The two approved retired cron services were deleted by exact ID; the API/volume configuration and API deployment were unchanged. Their in-process jobs remain.

## Only B2 account setup remains with Craig

1. Open [B2 signup](https://www.backblaze.com/sign-up/cloud-storage), choose the EU data region when creating the account and enable MFA. Stay within the free allowance; no paid upgrade is approved.
2. Open **B2 Cloud Storage → Buckets → Create a Bucket**. Choose a unique name such as `garmin-coach-backups-craigr973`, **Private**, keep all versions and no automatic deletion. Record its **bucket ID**, not its name or endpoint.
3. For a new account only, open **Application Keys → Master Application Key → Generate New Master Application Key** and confirm. Save its ID and application key privately in the password manager. For an existing account use the existing master: generating a replacement invalidates the old key. Never put this master in Railway/GitHub or chat.
4. Run the two local helper commands below, replacing `BUCKET_ID` with the actual ID. Each prompts invisibly for the master ID/key and creates a new minimal bucket/`coach/`-scoped key. Upload gets only `writeFiles`; restore gets only `listFiles,readFiles`. Neither can delete files or administer buckets/keys. These exact grants avoid the console presets' extra privileges. The helper saves owner-only JSON and never prints a secret. If either command fails, stop and report the safe error instead of retrying.
5. Save the two resulting keys in the password manager and tell the agent “ready” plus the non-secret bucket ID. Use the private file paths below; never paste secret values in chat. The agent sets all already-approved Railway/GitHub settings.

```sh
/Users/craigrobinson/.local/bin/python3.12 /Users/craigrobinson/garmin-coach/scripts/create_backup_bucket_key.py --bucket-id BUCKET_ID --access upload --output /Users/craigrobinson/.config/garmin-coach/b2-upload-key.json
```

```sh
/Users/craigrobinson/.local/bin/python3.12 /Users/craigrobinson/garmin-coach/scripts/create_backup_bucket_key.py --bucket-id BUCKET_ID --access restore --output /Users/craigrobinson/.config/garmin-coach/b2-restore-key.json
```

## If the local helper fails

Do not repeat key creation or delete an output file blindly. The helper reserves an owner-only file before contacting B2, so an empty file proves neither that no key was created nor that the credentials were wrong. On 7 Nov the upload output existed at zero bytes; the reader file was absent. The original generic error did not preserve a cause. An unauthenticated Python HTTPS check reached B2 with HTTP 401, so TLS works on this Mac; that did not test Craig's credentials or create any key.

The helper now reports a fixed stage, HTTP status and allowlisted provider code without a traceback, URL, header, server message or secret. `--check-only` authorises and reads the key list plus the specified bucket only; it never creates/deletes a key or changes the output file. Add it to the original upload command, keeping the real bucket ID and private output path. It prompts for the existing master ID/key locally; do not regenerate a master. Share only the `CHECK_ONLY` or `FAIL stage=...` line. A matching remote key with no saved secret needs reconciliation before another creation; the agent must not retry automatically.

```sh
/Users/craigrobinson/.local/bin/python3.12 /Users/craigrobinson/garmin-coach/scripts/create_backup_bucket_key.py --check-only --bucket-id BUCKET_ID --access upload --output /Users/craigrobinson/.config/garmin-coach/b2-upload-key.json
```

## Settings the agent applies

| Destination | Name | Source |
|---|---|---|
| Railway API | `BACKUP_AGE_RECIPIENT` | Public recipient, already staged |
| Railway API | `BACKUP_B2_BUCKET_ID` | Bucket ID |
| Railway API | `BACKUP_B2_KEY_ID` / `BACKUP_B2_APPLICATION_KEY` | Upload JSON |
| GitHub secret | `BACKUP_AGE_IDENTITY` | Private age identity, already set |
| GitHub secrets | `BACKUP_B2_READ_KEY_ID` / `BACKUP_B2_READ_APPLICATION_KEY` | Restore-reader JSON |
| GitHub Actions variable | `BACKUP_B2_BUCKET_ID` | Bucket ID |

No `BACKUP_RESTORE_DATABASE_URL` is created or consumed by the new workflow. No Neon setup is needed. Railway changes are staged without deployment until the normal release gate is satisfied. The private age identity never enters Railway.

## How weekly recovery is proved

```text
Railway: RAM dump → integrity read → public-key encryption
                              ↓ weekly full + nightly
                         private EU B2
                              ↓ read-only download
GitHub: decrypt → temporary PostgreSQL 17 → restore/check both
                              ↓
                    stop and destroy database
                              ↓
                public pass/fail → daily watchdog
```

The restore target is created by the drill itself on literal loopback with a random one-run password; it cannot be configured to point at production. The archive is restored by a restricted database owner: no superuser privileges, server-file reads or shell execution. A separate administrator only creates the fresh local database and roles. Native PostgreSQL avoids the repository's known container-pull failures. GitHub temporarily handles plaintext health data, as already approved, but no additional database provider receives it. Private files, local server logs and the cluster are removed after success/failure; a hard-killed runner is discarded. No archive artifact/cache or database stderr is published. A real restored offsite pair, not a synthetic test or skipped job, must pass within eight days.

The previously approved PUBLIC/anon/authenticated execute revoke remains unchanged. Existing plaintext archive retirement, production deletion and paid upgrades remain separate decisions. The batch is built but unmerged; B2 inputs and real offsite proof remain open. Do not merge during 06:00–11:00 London.

## Sources

- [B2 buckets](https://www.backblaze.com/docs/cloud-storage-create-and-manage-buckets) and [application keys](https://www.backblaze.com/docs/cloud-storage-create-and-manage-app-keys).
- [PostgreSQL 17 initdb](https://www.postgresql.org/docs/17/app-initdb.html) and [connection settings](https://www.postgresql.org/docs/17/runtime-config-connection.html).
- Historical provider pricing was checked 5 Nov; no paid capacity is authorised. A free allowance is not a service guarantee.

**7 Nov reconciliation:** Craig's read-only check confirms the private bucket exists and zero upload-name keys are listed. The empty upload output was preserved as `b2-upload-key.failed-empty-2026-11-07.json`; the original upload path is available. Run the upload creation command above once, without `--check-only`, using the same real bucket ID and existing master prompts. Report only success or the safe failure line; do not automatically repeat a failed creation. The original failure cause remains unknown.
