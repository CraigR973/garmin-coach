# Railway configuration as code

`railway.ts` in this folder is garmin-coach's Railway configuration: the three
services (`api`, `weekly-review`, `trend-narratives`) and the `api-volume`
backups volume. It was imported with `railway config pull` on 26 Sep 2026 and
then edited (Batch 287, Decision #355).

**Railway does not read this folder during deploys.** It takes effect only when
someone runs `railway config apply`. It was applied on 27 Sep 2026 and
`railway.toml` was removed the same day, so the settings below now live in each
service's own configuration and nothing in the repository overrides them.

## What it states

- Every service builds the repo-root `Dockerfile` (`DOCKERFILE` builder). The
  Dockerfile's `CMD` runs `alembic upgrade head` before uvicorn, and pinning
  the builder stops Railway detecting the monorepo root as a Node project.
- `api`: health check `/api/v1/health` with a 300 s timeout, restart policy
  `ON_FAILURE` with 3 retries, `sleepApplication: false` (the API runs the
  in-process scheduler), the `/data/backups` volume mount and its Railway domain.
- `weekly-review` and `trend-narratives`: their cron schedules and start
  commands, restart policy `NEVER`, no health check.
- Every variable is `preserve()`: the value stays in Railway and none is in git.

## Before you plan or apply

- Node 22.6 or newer (the CLI runs this file with `--experimental-strip-types`).
- The SDK, pinned in `package.json` / `package-lock.json` here:
  `npm ci --prefix .railway`, from the repository root.

## Commands (from the repository root)

```bash
railway config plan --detailed-exit-code --verbose
```

```bash
railway config apply
```

`plan` changes nothing. `apply` shows the same plan and asks before changing
anything.

## One rule to keep

This file manages the whole project, and Railway's own guidance is that a
whole-project apply **can delete a resource the file omits**. Add a new service
or volume to this file before (or instead of) creating it in the Railway
console, and read the plan's "to destroy" count before every apply — it must be
0 unless you mean to delete something.

## Two things that look wrong and are not (found at the apply, 27 Sep 2026)

- **Every plan shows one change on `api`**: `deploy.restartPolicyType`
  (null → "ON_FAILURE") and `deploy.sleepApplication` (null → false). Railway
  stores a setting equal to its default as unset, and the plan compares the
  file's explicit value with that. Both are what runs: the API's deployment
  manifest reads `ON_FAILURE` with 3 retries and `sleepApplication: false`.
  Applying again changes nothing. The file keeps both stated because the API
  must never sleep (it runs the in-process scheduler), and before this apply its
  deployments ran with sleeping **on**.
- **The API's `serviceInstance` query still reports `builder: RAILPACK`.** That
  field is a legacy view. The environment's own config (`environment.config`),
  which deployments are built from, says `DOCKERFILE` for all three services,
  and every deployment's manifest confirms it.
