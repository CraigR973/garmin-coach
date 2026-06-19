---
description: Commit + push the current feature branch, merge into staging, push, watch CI, verify the deploy on wc2026-staging.vercel.app. Handles the full iteration loop without manual steps.
---

You are running the staging-ship loop. The user invokes this as:

```
/ship-staging                                  # all changes already committed
/ship-staging "feat(ui): tighten dashboard"    # commit any pending work with this message first
```

`$ARGUMENTS` is the optional commit message. It is REQUIRED if the working
tree has uncommitted changes; otherwise it is ignored.

## Pre-conditions

Stop and report (do not proceed) if any of these fail:

1. `git rev-parse --abbrev-ref HEAD` returns a branch matching
   `^(feat|fix|chore)/` — refuse to ship from `main`, `staging`, or any
   other branch. Suggest the user check out a feature branch first.
2. `git status --porcelain` is empty OR `$ARGUMENTS` is non-empty. If
   there are uncommitted changes and no `$ARGUMENTS`, refuse — tell the
   user to either pass a commit message or commit manually first.
3. There are no merge conflicts pending. (`git status` would show them.)
4. `~/Library/Application Support/com.vercel.cli/auth.json` exists
   (Vercel CLI logged in) and `.env` exposes a `GITHUB_TOKEN` we can use
   for polling. If either is missing, stop and tell the user what to add.

Track progress with a single TodoWrite list. Update statuses as you go.

## Step 1 — Verify, commit (if needed), push the feature branch

If `git status --porcelain` shows changes:

1. Use the project's standard test pattern from `AGENTS.md`:
   ```
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir apps/web typecheck
   PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH" pnpm --dir apps/web test
   ```
   Run tests in the background. If either fails, dump the failing-test
   output (last 30 lines) and stop. Do NOT commit failing code.
2. Stage modified files explicitly (`git add` listing each path — never
   `git add .` or `git add -A`).
3. `git commit -F /tmp/ship-staging-commit.txt` with the commit body
   built from `$ARGUMENTS` followed by the standard
   Use a file-based message to avoid heredoc/backtick escaping issues.
4. `git push origin <feature-branch>`.

If `git status --porcelain` is empty, skip to step 2 (no commit needed).
Still run `git push origin <feature-branch>` in case there are unpushed
commits.

## Step 2 — Merge feature branch into staging and push

1. Remember the current branch name as `$FEATURE`.
2. `git fetch origin`.
3. `git checkout staging`.
4. `git pull --ff-only origin staging` — if this fails (staging has
   local-only commits diverging from origin), stop and report. Do not
   force.
5. `git merge --no-ff "$FEATURE" -m "merge: $FEATURE -> staging"`.
   Resolve conflicts by stopping and reporting; do not auto-resolve.
6. `git push origin staging`.
7. `git checkout "$FEATURE"` — return the user to their working branch.

## Step 3 — Watch the CI run on staging

The push triggers the `CI` workflow on the `staging` branch, which runs
all jobs PLUS the `deploy-staging` job that ships to
`wc2026-staging.vercel.app`.

1. Get the run id for the staging push:
   ```bash
   source /Users/craigrobinson/wc_2026_predictor/.env
   curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
     "https://api.github.com/repos/CraigR973/wc2026-predictor/actions/runs?branch=staging&per_page=1" \
     | python3 -c "import sys,json; print(json.load(sys.stdin)['workflow_runs'][0]['id'])"
   ```
2. Poll until `status` == `completed` using a background bash command
   with an `until` loop (per the harness Bash conventions — never chain
   sleeps from the main turn). Use 25-second polls.
3. When the run completes, fetch job-level statuses.

CI typically takes 4–7 minutes (the Playwright smoke is the slow job).

## Step 4 — Report outcome

### If the run conclusion is `success`

1. Verify the deployment landed at `https://wc2026-staging.vercel.app`:
   - `curl -sI https://wc2026-staging.vercel.app` should return HTTP 200.
   - Curl the served HTML, extract the `index-*.js` chunk filename, fetch
     it, and grep for one or two strings the user would expect from the
     change (let the user tell you, or default to "Still Email?" and
     "sss_theme" which are stable markers).
2. Report a short summary with:
   - The staging URL (active link).
   - The commit SHA that was deployed.
   - The bundle fingerprint (entry chunk filename).
   - The list of CI jobs (all ✅).
3. Suggest the user reload the PWA on iPhone (no cache-bust needed — SW
   has `skipWaiting + clientsClaim`).

### If the run conclusion is `failure`

1. Identify the failing job(s) via the jobs API.
2. Fetch the failing job's logs (`/actions/jobs/{id}/logs`, follow
   redirects with `-L`).
3. Show the last ~30 lines of the log focusing on `Error|error|FAIL|##\[`
   patterns.
4. Summarise the likely cause in one or two sentences and propose the
   next step (`/ship-staging` again after fixing, or revert).

## Bash discipline

- Never `cd` (`AGENTS.md`). Use absolute paths or `git -C`.
- The repo root is `/Users/craigrobinson/wc_2026_predictor`.
- For long polls, use a background shell command with an `until` loop that
  exits on the terminal state. You'll get one completion notification.
- Don't dump full CI logs into the conversation — grep / tail.

## End-of-turn summary

Two sentences max:
- What state staging is in now (URL + SHA), or what failed (job name).
- What the user should do next (test on iPhone, OR fix the failing job).
