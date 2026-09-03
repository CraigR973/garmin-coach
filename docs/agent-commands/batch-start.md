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
4. **Re-verify the spec's factual claims before building anything.** A row is
   often authored days or weeks before it is built, so its `file:line`
   references, measurements, counts, and especially its "reuse X, which already
   does Y" pointers can be stale or simply wrong. Check every fact the phases
   depend on against current code and deployed state. If one is wrong, correct
   the row and say so *before* writing code — never build to a spec you have
   just found to be inaccurate. The intent of a row is durable; its facts decay.
   Two real cases:
   - Batch 216's spec instructed the build to reuse the `body_battery_charge`
     settled-row pattern. That path is itself the defect the batch exists to
     fix, so following the spec faithfully would have produced a second broken
     metric and a build that looked correct.
   - Batch 206 was graded Low on an assumption about payload size that
     measurement inverted — the deferred item turned out to be 96% of the
     endpoint.
   - Batch 217 named four facts to annotate; two had already been annotated by
     the very batches the row said to follow, and the convention it asked us to
     establish already existed four times in the codebase. **When a row says
     "land after X", check what X actually shipped before building — a
     sequencing note can change what the batch should build, not merely when.**

   **Two sources worth checking, both cheap and both routinely decisive:**
   - **`coach.brief_messages` holds Mark's verbatim challenges.** A targeted
     query ("where are you getting", "what prompted", "not sure why", "basis")
     returns what he actually disputed, in his words, alongside what the coach
     answered. Batch 217's real defect — a basis that is present but unquotable
     — was only visible there: the coach said it would be speculating while
     looking straight at the answer. A report relayed second-hand loses that.
   - **`coach.analyses.context_packet` is the exact input a read was written
     from.** Running a proposed check over the real stored packet from the day
     being fixed is the strongest before/after evidence available without
     deploying anything.
5. Sync from remote without changing production:
   - Fetch `origin`.
   - Start from the current reviewed base branch unless the user specified a
     different branch.
   - Create a conventional branch such as `feat/batch-1-data-model` or
     `chore/batch-workflow`.
6. Build only the phases in the batch. Do not start later batches.
7. Keep work evidence in the repo:
   - Update `STATUS.md` during handoff.
   - Append `DECISIONS.md` only for new or changed durable decisions.
   - Update `ARCHITECTURE.md` only when the spec/roadmap/data model changes.
   - Record any spec claim you found to be wrong, so the correction outlives the
     session that made it.
8. Run the tests/lint/type checks required by the touched code.
9. Commit and push the branch when the batch implementation is ready for review.
10. Continue into `/closeout` once the gate is green — close-out is automatic
    on this project (see `AGENTS.md`). Stop before promotion only if the gate is
    red or a close-out step needs Craig's judgement rather than a green gate.

## Guardrails

- Treat the batch row as a proposal to verify, not an instruction to execute. A
  green test suite cannot tell you the spec was right, only that you built what
  it said.
- Never use shell `cd`; use absolute paths and `git -C`.
- Use real Garmin/Hive sample JSON from `~/garmin-spike/out/` and
  `~/garmin-spike/out_hive/`, not inherited football shapes.
- Do not touch hosting configuration unless the batch explicitly requires it.
- Tests ship with every change.
