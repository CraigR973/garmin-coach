# Command: next-batch-prompt

Generate the prompt for the next unshipped batch.

## Inputs

- Optional batch id. If omitted, use the first unshipped row in
  `docs/phase-batches.md`.

## Procedure

1. Read `STATUS.md`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`, and
   `docs/phase-batches.md`.
2. Select the requested batch or first unshipped batch.
3. Confirm its tier and include the model map:
   - `🔴 High`: Claude Opus or Codex GPT-5.5
   - `🟢 Mid`: Claude Sonnet or Codex GPT-5.4
4. Produce a copy-ready prompt containing:
   - repo path `/Users/craigrobinson/garmin-coach`
   - batch id/title/tier
   - phases, goal, and full acceptance criteria
   - required first reads
   - test commands relevant to the batch
   - gotchas from `STATUS.md`
   - instruction to avoid `/closeout` until explicitly requested
5. Include any known previous-session notes from `STATUS.md` that affect the
   batch.
6. Do not modify code or docs unless the user separately asks for edits.

## Output shape

Return only the prompt plus a short note naming the selected batch.
