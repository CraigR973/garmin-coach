---
description: Run the full phase close-out workflow — push, poll CI, merge to staging, tick the architecture doc (architecture phase mode only), append a lean session-log entry, strike the batch row. Supports architecture phases (X.Y), multi-league batches (MN), pre-launch review batches (RN), premium polish batches (UN), and explicit dirty-trunk recovery. Promotion of staging to main/production is a separate, explicitly-gated `/ship-prod` step — never part of close-out.
---

You are running close-out. The user invokes this as one of:

```
/phase-closeout 7.1                  # single architecture phase
/phase-closeout 6.1,6.2,6.3,6.4      # multi-phase architecture batch
/phase-closeout M1                   # multi-league batch
/phase-closeout R1                   # pre-launch review batch
/phase-closeout U3                   # premium polish batch
```

This is the canonical tool-agnostic command. Claude Code wrappers, Codex, and
other agents should read this file directly and follow it literally.

## Argument parsing & mode

`$ARGUMENTS` may be:

- **Phase mode** — comma-separated list of IDs matching `^\d+\.\d+$` (e.g. `7.1` or `6.1,6.2,6.3,6.4`). Trim whitespace, split on commas, validate each. Reject if any ID is malformed or if the list is empty.
- **Multi-league mode** — a single token matching `^M\d+$` (e.g. `M1`). Multi-league batches tracked in `docs/phase-batches.md` "Multi-league (v1)" section; acceptance criteria in `docs/multi-league-architecture.md` § 8. Reject if combined with other IDs.
- **Review mode** — a single token matching `^R\d+$` (e.g. `R1`). Reject if combined with phase IDs.
- **Polish mode** — a single token matching `^U\d+$` (e.g. `U3`). Frontend-only polish batches use a single shared numbering sequence split across TWO files: lightweight ad-hoc fixes are flat rows in `docs/phase-batches.md`'s "Polish / UX snags" section; larger pre-planned batches use the full `## U<N>` format in `docs/polish-batches.md` (still actively used — do not assume it's legacy). Check both for the batch id before editing either. Reject if combined with other IDs.

Set `$MODE` to `phase`, `multi-league`, `review`, or `polish` based on the input shape. Many steps below behave differently per mode — read the per-step notes.

## Pre-conditions

Before doing anything, verify:

1. Determine the current branch with old-Git-compatible commands:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor symbolic-ref --short HEAD
   ```

   Do not use `git branch --show-current`; this checkout has older Git in some
   environments.

2. Preferred path: feature work is already **committed and pushed** to a
   feature branch (not `main`, not `staging`). Run:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor status --porcelain
   git -C /Users/craigrobinson/wc_2026_predictor log @{u}.. --oneline
   ```

   There must be no tracked worktree changes and no unpushed commits. Unrelated
   untracked scratch files may be ignored only when they are clearly outside the
   batch. If the branch is not a feature branch but there are uncommitted batch
   changes, stop unless the user explicitly asks you to commit them.

3. Recovery path: if the current branch is `main` or `staging` and the user
   explicitly says **"do it for me"**, **"recover it"**, or equivalent, the
   agent may create the feature branch and continue instead of stopping. Use
   this only for the current batch's files; never stage unrelated
   scratch/untracked files.

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor checkout -b feat/<batch-slug>
   git -C /Users/craigrobinson/wc_2026_predictor add <explicit batch files only>
   git -C /Users/craigrobinson/wc_2026_predictor commit -F /tmp/msg.txt
   git -C /Users/craigrobinson/wc_2026_predictor push -u origin feat/<batch-slug>
   ```

   After pushing, resume this command at Step 1. If you cannot confidently tell
   which files belong to the batch, stop and ask.

4. **Phase, multi-league, and review mode:** Tests, ruff, ruff format, and mypy all passed locally. Ask the user to confirm `"Did you run the full pytest + ruff + mypy locally and all green? (y/N)"`. If anything other than `y`/`yes`, stop. **Skip this confirmation in polish mode** — polish batches are frontend-only (pnpm test + typecheck), which CI already verified.

## Steps

### Step 1 — Poll CI for the feature branch tip

Per the CI-polling rule in `AGENTS.md`: **do not foreground-loop**. Pattern:

1. Get the tip SHA: `git -C /Users/craigrobinson/wc_2026_predictor rev-parse HEAD`.
2. Source the GitHub token: `source /Users/craigrobinson/wc_2026_predictor/.env` and then use `$GITHUB_TOKEN`.
3. One immediate check: `curl -s -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/CraigR973/wc2026-predictor/actions/runs?head_sha=$SHA"` and parse the first workflow_run's `status` and `conclusion`.
4. If `status` is `completed` and `conclusion` is `success`: continue to Step 2.
5. If `status` is `completed` and `conclusion` is anything else: stop and report which check failed — let the user fix and re-run.
6. If `status` is `in_progress` or `queued`: schedule one background shell poll that sleeps ~180 seconds, then runs the same curl. On notification, re-evaluate. Repeat at most twice (so max ~6 min wait). If still not done after that, ask the user how to proceed.

Never write more than ~3 polling lines into the conversation total.

### Step 2 — Merge to staging (NOT main)

Close-out lands work on `staging`, never `main`. `main` auto-deploys to
production (Vercel + Railway), so pushing there directly would skip the
staging soak and bypass `/ship-prod`'s safety gates (kickoff-freeze window
during the live tournament, SHA verification, CORS check). Promotion to
`main` is always a separate, explicit `/ship-prod` call made by the user —
never an implicit part of close-out, regardless of mode.

```bash
BRANCH=$(git -C /Users/craigrobinson/wc_2026_predictor symbolic-ref --short HEAD)  # store BEFORE checkout
git -C /Users/craigrobinson/wc_2026_predictor fetch origin
git -C /Users/craigrobinson/wc_2026_predictor checkout staging
git -C /Users/craigrobinson/wc_2026_predictor pull --ff-only origin staging
git -C /Users/craigrobinson/wc_2026_predictor merge --no-ff "$BRANCH" -m "merge: $BRANCH -> staging"
git -C /Users/craigrobinson/wc_2026_predictor push origin staging
```

Note: capture the feature branch name BEFORE the `checkout staging` step.

If `pull --ff-only origin staging` fails (local staging has diverged from
origin), stop and report — do not force. Resolve merge conflicts by
stopping and reporting; never auto-resolve.

The push to `staging` also triggers the `deploy-staging` CI job (ships to
`wc2026-staging.vercel.app`), so staging CI runs longer (~4–7 min) than a
feature-branch run — poll accordingly, same non-blocking pattern as Step 1.

### Step 3 — Tick the architecture doc for every phase ID

**Phase mode only.** Skip this step entirely in multi-league, review, and polish mode (those items do not live in `wc2026-architecture.md`). For multi-league mode specifically: `docs/multi-league-architecture.md` § 8 was written without ✅ markers by design — the "shipped" signal is the struck-through row in `docs/phase-batches.md`.

For each phase ID in `$ARGUMENTS`:

1. Grep for the heading: `grep -n "Phase X.Y:" /Users/craigrobinson/wc_2026_predictor/wc2026-architecture.md`.
2. If the line already ends with `✅ YYYY-MM-DD`, skip — don't double-tick.
3. Otherwise, edit the file to append ` ✅ YYYY-MM-DD` (today's UTC date) to the matching line.

Do NOT read the whole architecture doc — grep first, then use Edit with the precise line as the unique anchor.

### Step 4 — Append a lean session-log entry

Append a NEW section to the bottom of `/Users/craigrobinson/wc_2026_predictor/session-log.md` using the lean template defined in `AGENTS.md`. Pull commit hashes from `git log staging --oneline -<N>` where N covers the work just shipped (typically the last 1–3 commits before the docs commit you're about to make). Note in the entry that the batch is shipped to `staging` only, pending a separate `/ship-prod` promotion.

**Phase mode** — multi-phase batches get ONE section with all phase IDs in the title and all commit hashes on the Commits line:

```
---

## Phase X.Y[, X.Z] — Title[s]
**Commits:** <hash>[, <hash>] · CI ✅

### Key facts for future sessions
- <only non-obvious gotchas a future session can't discover by reading code or git log>
- <max ~6 bullets across the whole batch>

**Next:** Phase X.Z — Title (model tag)   ← use /next-batch-prompt logic to find this
```

**Multi-league mode** — title is the batch ID plus the section heading title from `docs/multi-league-architecture.md` § 8 (everything after `### M<n> · `, stripped of the trailing model emoji + tag):

```
---

## Multi-league batch M<n> — <Title from § 8 heading>
**Commits:** <hash>[, <hash>] · CI ✅

### Key facts for future sessions
- <only non-obvious gotchas a future session can't discover by reading code or git log>
- <max ~6 bullets>

**Next:** Multi-league batch M<n+1> — <Title> (model tag)   ← use /next-batch-prompt to find this
```

**Review mode** — title is the batch ID plus the batch name (read it from the `docs/review-batches.md` row's "Rationale" column or its `## R<N>` section heading):

```
---

## Review batch R<N> — <Title from review-batches.md row>
**Commits:** <hash>[, <hash>] · CI ✅

### Key facts for future sessions
- <only non-obvious gotchas a future session can't discover by reading code or git log>
- <max ~6 bullets>

**Next:** Review batch R<N+1> — <Title> (model tag)   ← use /next-batch-prompt review to find this
```

**Polish mode** — title depends on which file the batch's row was found in (see the mode-detection note above): if it was an ad-hoc row in `docs/phase-batches.md`, the title is the batch ID plus a short title summarizing the row's Description cell; if it was a planned batch in `docs/polish-batches.md`, use the batch ID plus the `## U<N> — <Title>` heading's title verbatim.

```
---

## Polish batch U<N> — <short title summarizing the batch>
**Commits:** <hash>[, <hash>] · CI ✅

### Key facts for future sessions
- <only non-obvious gotchas a future session can't discover by reading code or git log>
- <max ~6 bullets>

**Next:** Polish batch U<N+1> — <Title> (model tag)
```

Keep the entry under ~15 lines. Do NOT include "Files modified" or "What shipped" — they're recoverable from `git show --stat`.

### Step 5 — Commit the docs changes

**Phase mode:**

```bash
git -C /Users/craigrobinson/wc_2026_predictor add wc2026-architecture.md session-log.md
git -C /Users/craigrobinson/wc_2026_predictor commit -m "docs: close out phase(s) $ARGUMENTS — arch doc tick + session log"
git -C /Users/craigrobinson/wc_2026_predictor push origin staging
```

**Multi-league mode** (no arch doc to tick — session-log only):

```bash
git -C /Users/craigrobinson/wc_2026_predictor add session-log.md
git -C /Users/craigrobinson/wc_2026_predictor commit -m "docs: close out multi-league batch $ARGUMENTS — session log"
git -C /Users/craigrobinson/wc_2026_predictor push origin staging
```

**Review mode** (no arch doc to tick — session-log only):

```bash
git -C /Users/craigrobinson/wc_2026_predictor add session-log.md
git -C /Users/craigrobinson/wc_2026_predictor commit -m "docs: close out review batch $ARGUMENTS — session log"
git -C /Users/craigrobinson/wc_2026_predictor push origin staging
```

**Polish mode** (no arch doc to tick — session-log only):

```bash
git -C /Users/craigrobinson/wc_2026_predictor add session-log.md
git -C /Users/craigrobinson/wc_2026_predictor commit -m "docs: close out polish batch $ARGUMENTS — session log"
git -C /Users/craigrobinson/wc_2026_predictor push origin staging
```

### Step 6 — Strike the batch row

**Phase mode:** invoke `/strike-batch N` where N is the batch number that contains these phase IDs in `docs/phase-batches.md` (grep the file for a row whose 3rd column lists them).

**Multi-league mode:** invoke `/strike-batch $ARGUMENTS` directly — `$ARGUMENTS` is already the M-batch identifier (e.g. `M1`). The skill handles the file routing (`docs/phase-batches.md`, "Multi-league (v1)" section).

**Review mode:** invoke `/strike-batch $ARGUMENTS` directly — `$ARGUMENTS` is already the R-batch identifier (e.g. `R1`). The skill handles the file routing.

**Polish mode:** invoke `/strike-batch $ARGUMENTS` directly — `$ARGUMENTS` is already the U-batch identifier (e.g. `U3`). The skill checks both `docs/phase-batches.md` ("Polish / UX snags" section) and `docs/polish-batches.md` for the row and strikes whichever one has it.

The result is one more docs commit on `staging`. Promotion to `main`/production
is not part of close-out — that's a separate `/ship-prod` call, made when the
user is ready.

### Step 7 — Report

Output a short summary to the user:

**Phase mode:**
- Phase(s) closed: X.Y[, X.Z]
- Feature commit(s): <hashes>
- Docs commits: <2 hashes>
- Batch row struck: Batch N
- CI: ✅
- Next batch hint: run `/next-batch-prompt` to get the prompt for the next session

**Multi-league mode:**
- Multi-league batch closed: M<n>
- Feature commit(s): <hashes>
- Docs commits: <1–2 hashes>
- Batch row struck: M<n>
- CI: ✅
- Next batch hint: run `/next-batch-prompt` to get the prompt for the next session (the skill auto-detects whether the next un-struck row is architecture or multi-league)

**Review mode:**
- Review batch closed: R<N>
- Feature commit(s): <hashes>
- Docs commits: <1–2 hashes>
- Batch row struck: R<N>
- CI: ✅
- Next batch hint: run `/next-batch-prompt review` to get the prompt for the next session

**Polish mode:**
- Polish batch closed: U<N>
- Feature commit(s): <hashes>
- Docs commit: <hash>
- Batch row struck: U<N> in `docs/phase-batches.md` ("Polish / UX snags" section) or `docs/polish-batches.md`, whichever held it
- CI: ✅
- Next batch hint: run `/next-batch-prompt polish` to get the prompt for the next session

That's it.

## Rules

- Never use `git push --force` or `git push --no-verify`.
- Never amend a previous commit — always create new commits.
- Never write to `permissions.deny` or skip pre-commit hooks.
- If anything fails mid-flow, stop and report the exact failure. Don't try to clean up — let the user decide.
