# Command: batch-start

Start an implementation batch from `docs/phase-batches.md`.

## Inputs

- Batch id, for example `1` or `Batch 1`. If omitted, use the first unshipped
  row in `docs/phase-batches.md`.

## Procedure

1. Read, in order: `STATUS.md`, `AGENTS.md`, `ARCHITECTURE.md`,
   `DECISIONS.md`, and `docs/phase-batches.md`.
2. Identify the requested batch and restate:
   - tier and model map (`🔴 High` = Opus/GPT-5.5, `🟢 Mid` = Sonnet/GPT-5.4)
   - phases included
   - goal
   - acceptance criteria
3. Confirm the batch is not already struck through and is not marked `Shipped`.
4. Sync from remote without changing production:
   - Fetch `origin`.
   - Start from the current reviewed base branch unless the user specified a
     different branch.
   - Create a conventional branch such as `feat/batch-1-data-model` or
     `chore/batch-workflow`.
5. Build only the phases in the batch. Do not start later batches.
6. Keep work evidence in the repo:
   - Update `STATUS.md` during handoff.
   - Append `DECISIONS.md` only for new or changed durable decisions.
   - Update `ARCHITECTURE.md` only when the spec/roadmap/data model changes.
7. Run the tests/lint/type checks required by the touched code.
8. Commit and push the branch when the batch implementation is ready for review.
9. Stop before promotion. Do not run `/closeout` unless the user explicitly asks.

## Guardrails

- Never use shell `cd`; use absolute paths and `git -C`.
- Use real Garmin/Hive sample JSON from `~/garmin-spike/out/` and
  `~/garmin-spike/out_hive/`, not inherited football shapes.
- Do not touch hosting configuration unless the batch explicitly requires it.
- Tests ship with every change.
