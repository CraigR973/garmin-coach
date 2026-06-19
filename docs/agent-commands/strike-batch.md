---
description: Mark a batch as shipped in docs/phase-batches.md (architecture phases, M-batches, and ad-hoc U-batches — "Polish / UX snags" section), docs/polish-batches.md (planned, multi-item U-batches), docs/review-batches.md (R-batches), or docs/env-batches.md (E-batches), and push to staging.
---

You are striking through a completed batch.

## Argument & mode

The user invokes this as `/strike-batch N` (architecture phases), `/strike-batch MN` (multi-league batches), `/strike-batch RN` (pre-launch review batches), `/strike-batch UN` (premium polish batches), or `/strike-batch EN` (env/ops batches), e.g. `/strike-batch 2`, `/strike-batch M1`, `/strike-batch R1`, `/strike-batch U3`, `/strike-batch E1`.

`$ARGUMENTS` contains the batch identifier. Trim whitespace, then:

- If it matches `^\d+$` → **phase mode**. Set `$FILE = /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md`.
- If it matches `^M\d+$` (case-sensitive `M`) → **multi-league mode**. Set `$FILE = /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md` (same file as phase mode; M-rows live in the "Multi-league (v1)" section).
- If it matches `^R\d+$` (case-sensitive `R`) → **review mode**. Set `$FILE = /Users/craigrobinson/wc_2026_predictor/docs/review-batches.md`.
- If it matches `^U\d+$` (case-sensitive `U`) → **polish mode**. U-numbering is a single sequence split across TWO files — determine `$FILE` dynamically:
  ```bash
  grep -nE "^\| ~~?$ARGUMENTS~~? " /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md
  grep -nE "^\| ~~?$ARGUMENTS~~? " /Users/craigrobinson/wc_2026_predictor/docs/polish-batches.md
  ```
  Set `$FILE` to whichever file matched (ad-hoc single-row batches live in `docs/phase-batches.md`'s "Polish / UX snags" section; larger pre-planned batches with a full `## U<N>` section live in `docs/polish-batches.md` — it is still actively used, not legacy). If neither matches, report not found. If both match, stop and ask the user — the same id should never exist in both files.
- If it matches `^E\d+$` (case-sensitive `E`) → **env mode**. Set `$FILE = /Users/craigrobinson/wc_2026_predictor/docs/env-batches.md`.
- Otherwise reject with `"Invalid batch id '$ARGUMENTS' — expected a positive integer, M<integer>, R<integer>, U<integer>, or E<integer>"`.

Throughout the steps below, use `$FILE` for the file path and `$ARGUMENTS` for the literal row identifier (which is `2` or `R1`).

## Steps

1. Read `$FILE`.

2. Find the row that begins with `| $ARGUMENTS |` (the unstriked form) **or** `| ~~$ARGUMENTS~~ |` (already striked).

   - If no match: report `"Batch $ARGUMENTS not found in $FILE"` and stop.
   - If already striked (`~~$ARGUMENTS~~`): report `"Batch $ARGUMENTS is already marked as shipped — nothing to do"` and stop.

3. Replace the row's cells with their struck-through form, keeping every cell
   (phase mode is 4 columns; ad-hoc "Polish / UX snags" U-rows are 5 columns —
   Batch | Model | Description | Commits | Status; planned `docs/polish-batches.md`
   U-rows are also 5 columns — Batch | Model | Effort | Items | Status). Strike
   every cell except the final status cell, which becomes `✅ Shipped to staging
   YYYY-MM-DD` (use today's UTC date). Preserve original spacing. In polish mode
   on `docs/polish-batches.md`, only the summary-table row is struck — leave the
   `## U<N>` section body untouched (no shipped marker is added there).

4. Commit and push to `staging`:

   ```bash
   git -C /Users/craigrobinson/wc_2026_predictor add $FILE
   git -C /Users/craigrobinson/wc_2026_predictor commit -m "docs: mark Batch $ARGUMENTS shipped"
   git -C /Users/craigrobinson/wc_2026_predictor push origin staging
   ```

   Promotion to `main`/production is not part of this skill — that's a
   separate, explicitly-gated `/ship-prod` call made by the user.

5. Report back with the new commit hash and the next un-struck batch. In polish
   mode, check **both** files (the next U-batch may live in either one) and
   report whichever has the lowest un-struck `U<N>`:
   ```bash
   grep -nE "^\| ([MRUNE]?[0-9]+) " /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md | head -1
   grep -nE "^\| U[0-9]+ " /Users/craigrobinson/wc_2026_predictor/docs/polish-batches.md | head -1
   ```
   In every other mode, just check `$FILE` (run `grep -nE "^\| ([MRUNE]?[0-9]+) " $FILE | head -1` — the regex covers `| 2 `, `| M1 `, `| R3 `, `| U4 `, and `| E1 `).

## Rules

- **Phase mode only** (numeric IDs): never strike a batch whose phases are not all marked ✅ in `wc2026-architecture.md`. Before step 3, verify by greping each phase ID in the row — if any phase is missing its `✅ YYYY-MM-DD` suffix, stop and report which one. **Skip this rule entirely in multi-league, review, polish, and env mode** — those items do not live in `wc2026-architecture.md`; for multi-league/review/polish the "shipped" signal is the feature branch merged to `staging`; for env mode the "shipped" signal is all acceptance criteria verified via CLI. (Multi-league acceptance criteria live in `docs/multi-league-architecture.md`; env acceptance criteria live in `docs/env-batches.md`.)
- Never run with tracked changes other than `$FILE`. Unrelated untracked scratch
  files may be ignored only when they are clearly outside the batch; never stage
  them. If `git status --short` shows modified/staged files other than `$FILE`,
  stop and report.
