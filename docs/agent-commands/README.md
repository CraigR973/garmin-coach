# Agent Commands

These docs are the canonical command workflows for both Claude Code and Codex.
Slash-command wrappers may live in tool-specific folders such as `.claude/`,
but the source of truth is here.

## Normal Batch Flow

```text
/next-batch-prompt polish
/batch-start U43
<implement the batch>
/batch-verify U43
/phase-closeout U43
```

The key invariant: implementation happens on a feature branch, not directly on
`main`. `/phase-closeout` can recover from dirty `main` only when the user
explicitly asks the agent to do that recovery.

## Commands

- `batch-start.md` — update `main`, create the feature branch, print the batch source.
- `batch-verify.md` — run local lint/typecheck/build/tests before close-out.
- `next-batch-prompt.md` — generate the next implementation prompt from batch docs.
- `phase-closeout.md` — push, poll CI, fast-forward merge, session-log, strike row.
- `strike-batch.md` — mark a batch row shipped.
- `ship-staging.md` — ship a feature branch to staging.
- `ship-prod.md` — promote staging to production.
