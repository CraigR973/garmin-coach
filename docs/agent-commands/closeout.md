# Command: closeout

Explicitly close out a reviewed batch. This is never automatic.

## Inputs

- Batch id, for example `1` or `Batch 1`.

## Procedure

1. Read `STATUS.md`, `AGENTS.md`, `ARCHITECTURE.md`, `DECISIONS.md`,
   `docs/phase-batches.md`, and `docs/runbooks/deploys-ongoing.md`.
2. Confirm the user explicitly requested closeout for the batch.
3. Confirm the batch row is not already struck through and not marked `Shipped`.
4. Confirm the branch contains only the intended batch work.
5. Commit any reviewed implementation changes using Conventional Commits.
6. Push the branch and poll GitHub CI until it is green.
7. Confirm any required preview review is complete. Vercel previews are staging;
   Railway is main-only unless a separate backend environment is added later.
8. Merge to `main` using the repo's normal GitHub path or an equivalent
   non-interactive merge that preserves reviewed commits.
9. Wait for production deploys:
   - Railway backend auto-deploys from `main`.
   - Vercel frontend auto-deploys from `main`.
10. Verify production, not only HTTP 200:
    - `/api/v1/health` is healthy and reflects the expected deployed commit when
      the endpoint exposes a commit SHA.
    - The production web URL loads.
    - A non-mutating smoke check for the closed batch passes.
11. Update durable docs on `main`:
    - `STATUS.md`: current state, next step, gotchas, dated log entry.
    - `DECISIONS.md`: append only if the batch made or changed a durable
      decision.
    - `ARCHITECTURE.md`: tick or revise roadmap/spec items touched by the batch.
    - `docs/phase-batches.md`: strike through the batch title and set status to
      `Shipped`.
12. Commit the closeout docs with a Conventional Commit message.
13. Push `main`.
14. Wait for the docs-only production redeploy if auto-deploy starts another run,
    then re-check `/api/v1/health` and the web URL.
15. Report the closed batch, commits, CI result, deploy verification, and next
    unshipped batch.

## Guardrails

- Do not close out a batch with failing CI, unreviewed preview changes, or
  uncommitted work.
- Do not silently reverse decisions; append a new decision if course changes.
- Never use shell `cd`; use absolute paths and `git -C`.
