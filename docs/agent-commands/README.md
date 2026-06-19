# Agent commands

Tool-agnostic procedures, written as plain markdown so **any** agent (Claude
Code, Codex, …) executes identical steps. Each tool may add a thin wrapper that
just points here (e.g. a Claude slash-command in `.claude/commands/`), but the
real procedure lives in this folder — never duplicate the steps into a wrapper.

| Command | Purpose |
|---|---|
| `handoff.md` | End-of-session handoff: update STATUS + DECISIONS, commit |

Add more as real workflows emerge (e.g. `deploy.md`, `new-migration.md`) — keep
them here, not in any one tool's config.
