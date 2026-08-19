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
   - **an explicit instruction to re-verify the row's factual claims against
     current code and deployed state before building** — `file:line`
     references, measurements, counts, and "reuse X, which already does Y"
     pointers all decay between authoring and build, and a spec that names the
     wrong pattern will be followed faithfully into a broken result (see
     `batch-start.md` step 4)
   - instruction to avoid `/closeout` until explicitly requested
5. Include any known previous-session notes from `STATUS.md` that affect the
   batch.
6. Do not modify code or docs unless the user separately asks for edits.

## Output shape

Return only the prompt plus a short note naming the selected batch.
