# Agent commands

Tool-agnostic procedures, written as plain markdown so **any** agent (Claude
Code, Codex, …) executes identical steps. Each tool may add a thin wrapper that
just points here (e.g. a Claude slash-command in `.claude/commands/`), but the
real procedure lives in this folder — never duplicate the steps into a wrapper.

| Command | Purpose |
|---|---|
| `batch-start.md` | Start an implementation batch from `docs/phase-batches.md` |
| `batch-verify.md` | Check a batch against acceptance criteria before closeout |
| `closeout.md` | Explicit reviewed batch closeout: commit, CI, merge, deploy, docs, strike row |
| `handoff.md` | End-of-session handoff: update STATUS + DECISIONS, commit |
| `next-batch-prompt.md` | Generate a copy-ready prompt for the next batch |

Keep the real procedures here, not in any one tool's config.
