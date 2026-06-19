---
description: Start a tracked batch on a clean feature branch. Works for architecture, multi-league, review, polish, and env batch IDs.
---

# /batch-start

Use this before implementing a batch. It exists to prevent accidental work on
`staging` or `main` and to make `/phase-closeout` boring.

Examples:

```text
/batch-start U43
/batch-start 14
/batch-start M11
/batch-start R6
```

## Argument parsing

`$ARGUMENTS` is required.

- `^\d+$` → architecture batch from `docs/phase-batches.md`
- `^M\d+$` → multi-league batch from `docs/phase-batches.md`
- `^R\d+$` → review batch from `docs/review-batches.md`
- `^U\d+$` → polish batch. U-numbering is a single sequence split across TWO files — check both `docs/phase-batches.md`'s "Polish / UX snags" section (ad-hoc, single-row batches) and `docs/polish-batches.md` (larger, pre-planned batches with a full `## U<N>` section — still actively used, not legacy) for a row matching the id; use whichever one has it
- `^E\d+$` → env batch from `docs/env-batches.md`

Reject anything else.

## Steps

1. Verify the working tree has no tracked changes:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor status --porcelain
   ```

   If tracked changes exist, stop and ask the user whether to commit, stash, or
   continue by making a branch that carries the current work. Ignore unrelated
   untracked scratch files only when the user explicitly says they are scratch.

2. Verify the current branch is `staging`:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor symbolic-ref --short HEAD
   ```

   If not on `staging`, stop and report the current branch. Do not nest
   feature branches unless the user explicitly asks. Feature branches start
   from `staging`, never `main` — `main` auto-deploys to production and only
   ever receives already-soaked work via the separate, gated `/ship-prod`
   command.

3. Update `staging`:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor fetch origin
   git -C /Users/craigrobinson/wc_2026_predictor pull --ff-only origin staging
   ```

4. Find the batch row/heading and derive a short slug:

   - Architecture / M: `docs/phase-batches.md`
   - Review: `docs/review-batches.md`
   - Polish: whichever file matched in Step argument-parsing —
     `docs/phase-batches.md` ("Polish / UX snags" section — flat rows, no
     `## U<N>` heading; derive the slug from the row's Description cell) or
     `docs/polish-batches.md` (has a `## U<N> — Title` heading; derive the
     slug from the title)
   - Env: `docs/env-batches.md`

   Use the section heading if present (`## U43 — Title`), otherwise derive from
   the row's rationale/status text. Lowercase, replace non-alphanumeric runs
   with `-`, trim to roughly 40 chars.

5. Create the branch:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor checkout -b feat/u43-short-slug
   ```

   Prefixes:
   - `feat/` for feature/polish/multi-league/env work
   - `fix/` for review batches that are explicitly bugfixes
   - `chore/` only for docs/tooling-only batches

6. Print the batch source and the close-out reminder:

   ```text
   Started feat/u43-short-slug for U43.
   Source: docs/phase-batches.md, "Polish / UX snags" row U43.
   Do not commit to staging or main directly. After implementation and
   verification, push this branch and run /phase-closeout U43 (merges to
   staging; promotion to main/prod is a separate /ship-prod call).
   ```

## Optional helper

Agents may use:

```bash
/Users/craigrobinson/wc_2026_predictor/scripts/agent/batch-start.sh U43
```

The helper creates the branch but still expects the agent to read the batch
spec and acceptance criteria.
