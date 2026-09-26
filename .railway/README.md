# Railway configuration as code

`railway.ts` in this folder is garmin-coach's Railway configuration: the three
services (`api`, `weekly-review`, `trend-narratives`) and the `api-volume`
backups volume. It was imported with `railway config pull` on 26 Sep 2026 and
then edited (Batch 287, Decision #355).

**Railway does not read this folder during deploys.** It takes effect only when
someone runs `railway config apply`. Until that has run, and been verified,
`railway.toml` at the repository root stays authoritative and must not be
deleted. Railway stops reading `railway.toml` on 1 Dec 2026.

## What it states

- Every service builds the repo-root `Dockerfile` (`DOCKERFILE` builder). Today
  they carry `RAILPACK` in their own settings and use the Dockerfile only
  because `railway.toml` overrides it.
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
