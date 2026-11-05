# Batch 371 — console choices for Craig

5 Nov 2026. Decision 477 is a proposal, not approval. No new accounts, variables, keys, uploads, restores or service deletions have been made.

## Recommended setup

| Purpose | Choice | Cost |
|---|---|---|
| Disposable restore database | Neon Free, PostgreSQL 17, Frankfurt | $0; 1 GB and 100 CU-hours/month |
| Weekly archive away from Railway | Private Backblaze B2 bucket, EU region | First 10 GB free; no card needed to start |
| Encryption and weekly proof | age key generated on Craig's Mac; private copy in his password manager and a GitHub Actions secret | $0; standard public-repository runners are free |

Allow about 20–30 minutes for Craig's setup, then roughly one implementation day and the normal gates/deploy. No Anthropic calls. Free limits are limits, not a guarantee of service; do not upgrade a plan automatically. Current retained backups total 95,803,348 bytes; the largest is 17,745,028 bytes. The current database tables excluding replayable per-second samples occupy about 81 MB. Restore size and compute must still be proved by the real drill.

```text
Railway: dump → encrypt with PUBLIC key
                   │ weekly encrypted copy
                   ▼
             private B2 bucket
                   │ read-only download
                   ▼
GitHub: PRIVATE key → decrypt → Neon restore → checks
```

The private key never enters Railway. GitHub can decrypt the archive; Neon receives the restored health data. Those are explicit parts of this proposal. GitHub's runner must emit only safe counts/status, upload no archive or database artifacts, cache no decrypted data and clean its workspace. A wrong restore target could overwrite a database: use a dedicated project and database, reject production, pin the allowed restore host/database, and reset only that disposable target. No restore credential for production is supplied to GitHub.

I rejected a Railway-only restore because it would require either keeping the decryption key beside the archives or retaining plaintext. I prefer Neon over a second free Supabase project because Neon resumes its idle compute automatically; Supabase's free project can pause after a week of low activity. A second Supabase project is compatible with the dump's existing auth policies, but Neon needs tested bootstrap definitions for the Supabase-specific roles/functions. The real restore must pass; parsing an archive is insufficient.

## 1. Restore database — Craig's console steps

1. Open [Neon Console](https://console.neon.tech/), create/sign in to a Free account, and remain on **Free**. No card or paid upgrade.
2. Choose **New Project**, name it `garmin-coach-restore`, region **AWS Europe (Frankfurt)**. Expand **Postgres database**, select **PostgreSQL 17** (production is 17.6). Leave other services disabled and create the project.
3. Use **Databases** to create `coach_restore` with the project's owner role; it must contain no other application data. Leave the free scale-to-zero setting enabled.
4. Choose **Connect**, select the project's default branch, database `coach_restore` and its owner role. Turn **Connection pooling off**. Keep TLS required. Save the direct connection URL in your password manager.
5. After approval, put that URL in the Garmin Coach repository's GitHub **Settings → Secrets and variables → Actions → New repository secret**, named `BACKUP_RESTORE_DATABASE_URL`. Do not paste it in chat or commit it. The code will not consume it until the approved workflow is built.

The weekly drill replaces the disposable `coach` schema, checks the newest full and nightly archives, and verifies schema/version, authored records, weekly-only data and excluded sample rows. The restore database remains a disposable copy, not an application endpoint. Clearing its restored rows after verification can be included in the approved drill; it never clears production.

## 2. Weekly archive — Craig's console steps

1. Open [Backblaze B2 signup](https://www.backblaze.com/sign-up/cloud-storage). Choose the **EU** data region when creating the account. Enable account MFA and save recovery details privately. No payment method is required for this proposed small private bucket.
2. Under **B2 Cloud Storage → Buckets → Create a Bucket**, choose a globally unique name such as `garmin-coach-backups-craigr973`, with **Files in Bucket are Private**. Keep all file versions initially. No automatic deletion or retention purge is approved here.
3. Under **Application Keys → Add a New Application Key**, create `garmin-coach-uploader`: restrict it to that bucket, prefix `coach/`, access **Write Only**. Do not use an account/master key in Railway. Save its key ID and application key in your password manager.
4. Create `garmin-coach-restore-reader` for the same bucket/prefix, access **Read Only**. Save its key ID and application key privately. This pair goes to GitHub only.
5. Record the bucket ID from its details. After approval, Railway's **api → Variables** will receive exactly `BACKUP_B2_BUCKET_ID`, `BACKUP_B2_KEY_ID`, `BACKUP_B2_APPLICATION_KEY` and the public recipient `BACKUP_AGE_RECIPIENT`. GitHub receives the reader as `BACKUP_B2_READ_KEY_ID` and `BACKUP_B2_READ_APPLICATION_KEY`, plus `BACKUP_B2_BUCKET_ID` as an Actions variable.

Before use, inspect the uploader's actual capabilities. The UI label **Write Only** is not treated as proof that deletion is denied; if its grants include deletion or bucket administration, narrow them to the required upload capability before enabling it. That narrowing must not create a new account-wide key in the app. The reader must have no upload/delete capability. Files use unique dated names; the drill checks age, integrity and a successful restore of the downloaded ciphertext, rather than trusting an upload response.

The proposed weekly export includes the newest full archive and newest nightly archive, so the external drill proves both. Per-second activity samples remain excluded as today. Keep all offsite copies initially and report storage growth; an archive purge needs separate exact-scope approval. At current sizes a year of weekly pairs is roughly 1.4 GB before growth/version overhead, below the 10 GB free allowance. Above the free allowance, current B2 pricing is $6.95/TB/month; stop and ask before enabling paid capacity. A failed free upload must alert, never count as a successful backup.

## 3. Encryption key — Craig's Mac and GitHub steps

Install age if it is absent:

```sh
brew install age
```

Generate a dedicated key once; do not overwrite an existing key:

```sh
umask 077
mkdir -p "$HOME/.config/garmin-coach"
age-keygen -o "$HOME/.config/garmin-coach/backup-age-key.txt"
```

Save the complete private file in your password manager, with a separate recovery copy. Losing every private copy makes the encrypted backups unrecoverable.

After approval, add the private file as the GitHub secret without printing it:

```sh
gh secret set BACKUP_AGE_IDENTITY --repo CraigR973/garmin-coach < "$HOME/.config/garmin-coach/backup-age-key.txt"
```

Print only its public recipient:

```sh
age-keygen -y "$HOME/.config/garmin-coach/backup-age-key.txt"
```

That `age1…` recipient is the Railway `BACKUP_AGE_RECIPIENT` value. The private `AGE-SECRET-KEY…` value never goes there. A local-key-only alternative avoids a GitHub decryption secret but requires Craig's Mac to perform the restore drill; it would not provide an unattended weekly proof while his Mac is unavailable.

The workflow is proposed for schedule/manual dispatch on reviewed `main` only, with minimal permissions and no pull-request trigger. Public code and public job logs are not permission to publish health data. GitHub's scheduled-job delays/inactivity disabling must remain visible in the watchdog: no successful restore within 8 days is a failure to investigate, not green because Railway's scheduler ran.

## 4. Source/live corrections before implementation

- The current restore drill is already weekly, Sunday 04:00 UTC, but all **9** recorded runs skipped `not_configured`; it restores plaintext archives from the Railway volume only. Encryption therefore requires moving the real decrypt/restore proof off Railway, rather than just setting its existing optional variable.
- The retained volume has **7 nightly and 1 full** archive; “whole health record” excludes per-second samples in every archive, and sleep/daily metrics are weekly-only. Preserve that scope. New retained archives must be encrypted; existing plaintext archives need a separately reviewed conversion/retirement step after encrypted copies are proved, with no blind deletion.
- Both `weekly-review` and `trend-narratives` still exist. Their deletion is already approved (2 Nov). Tell Craig immediately before deletion; review a fresh exact-two-service plan, preserve `api`, its volume/domain and all other settings, and update the whole-project Railway definition so they cannot return.
- `public.rls_auto_enable()` grants EXECUTE through **PUBLIC** as well as directly to `anon` and `authenticated`. Revoking only the named roles leaves both able to execute. Propose revoking from **PUBLIC, anon, authenticated**, retaining the owner/event trigger. This expands the literal migration statement and needs Craig's decision before building it. It changes no policy or health data.

## Approval required

Approve the three recommended homes, the private key in GitHub as well as your password manager, the exact Railway/GitHub settings above, and the corrected PUBLIC revoke. Approval includes writing/deleting only the dedicated disposable restore data during each drill. It does not approve production data deletion, retiring existing plaintext archives, a paid upgrade, extra service deletion or changes to production credentials. Craig performs the account/key console steps; do not put secret values in chat.

Once approved and the console inputs exist: implement, test encryption/failure paths and the real offsite restore, delete only the two approved crons after notice, migrate the grants, then run both CI waves and normal production close-out. Until then, this batch stays at its owner gate.

## Sources checked 5 Nov

- [Neon pricing](https://neon.com/pricing): Free $0, no card, 1 GB and 100 CU-hours/project/month.
- [Neon project creation](https://neon.com/docs/manage/projects) and [connection URL](https://neon.com/docs/connect/connect-from-any-app): project/version/region and direct connection.
- [Backblaze pricing](https://www.backblaze.com/cloud-storage/pricing) and [signup](https://www.backblaze.com/sign-up/cloud-storage): first 10 GB free; no card to start.
- [B2 app-key console](https://www.backblaze.com/docs/cloud-storage-create-and-manage-app-keys) and [capabilities](https://www.backblaze.com/docs/cloud-storage-application-key-capabilities): bucket/prefix and separate permissions.
- [age](https://github.com/FiloSottile/age): dedicated public-recipient/private-identity encryption.
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) and [secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets): standard public-repository runners free; console/CLI secret entry.
- [Supabase Free](https://supabase.com/kb/faqs/platform/database-only-cost): 500 MB, two active free projects, pauses after low activity.
