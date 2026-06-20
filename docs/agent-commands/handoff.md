# Command: handoff

Run at the end of any work session so the next agent (Claude or Codex) starts
from a known state. Keeps the repo the single source of truth.

## Steps
1. **Update `STATUS.md`:**
   - Overwrite the **Now** block: current phase, what's done, the concrete next step(s).
   - Refresh **Gotchas** (anything that would trip up the next session).
   - Prepend a dated one-liner to the **Log**.
2. **Update `DECISIONS.md`:** if any architectural decision was made or changed,
   append an entry (the decision + *why*). Don't silently reverse a prior decision.
3. **Update `ARCHITECTURE.md`** if the spec/data-model/roadmap changed.
4. **Commit and push the current branch** with a Conventional Commit message; keep it small and descriptive
   (`git log` is itself a handoff).

## Don't
- Don't leave durable state only in a tool's private memory (Claude memory is a
  cache; Codex can't read it).
- Don't end a session with uncommitted, unexplained working-tree changes.
- Don't push directly to `main` unless the user explicitly wants production
  auto-deploy to move.
