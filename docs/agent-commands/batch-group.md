# Command: batch-group

Run a defined group of batches end to end, each one through the full
`batch-start` → `batch-verify` → `closeout` cycle, sequentially, without
returning to the user between them.

## Inputs

- A group id, for example `A` or `Group A`. Groups are defined in
  `docs/phase-batches.md` under **"Batch groups"**.
- Optionally an explicit batch list, for example `242,248` — a sub-run of a
  group, used when a group was interrupted and is being resumed.

## What this command is, and what it overrides

The standing rule in the user's global instructions is that closeout is
**explicit, never automatic** — the agent stops after `batch-start` and waits.
**This command is the user's explicit, standing authorisation to run closeout
for every batch in the named group**, given once at group level instead of
thirteen times at batch level. That is the entire point of the command.

It does **not** authorise anything else. Every guardrail in `batch-start.md`,
`batch-verify.md` and `closeout.md` still applies in full, and the stop
conditions below are absolute.

## Procedure

1. Read `STATUS.md`, `AGENTS.md`, `DECISIONS.md`, `docs/phase-batches.md`, and
   the group's definition under **"Batch groups"**.
2. Restate the group: its batches in order, each one's tier, and the group's
   **pre-flight blockers**. If a pre-flight blocker is unresolved, **stop and
   ask** — do not begin.
3. Confirm `main` is clean and matches `origin/main`, and that
   `/api/v1/health` serves that SHA. A group run that starts from a divergent
   base compounds across every batch in it.
4. For each batch in the group, in the stated order:
   1. Run the full `batch-start` procedure, **including step 4's spec
      re-verification**. Branch from freshly-merged `main`, not from the
      previous batch's branch.
   2. Build only that batch's phases.
   3. Run the full `batch-verify` procedure against the row's acceptance
      criteria.
   4. Run the full `closeout` procedure: commit, push, poll CI to green, merge,
      wait for both deploys, verify production on the exact merge SHA, update
      `STATUS.md` / `DECISIONS.md` / `ARCHITECTURE.md`, strike the ledger row,
      push `main`.
   5. Post a short progress line to the user — batch, PR, squash SHA, gate
      results — then continue to the next batch **without waiting for a reply**.
5. After the last batch, report the group: every batch closed, its PR and squash
   SHA, the CI result, the production verification, and the next group.

## Stop conditions — absolute

Stop the group, report what has landed and what has not, and wait for the user:

- **CI is not green.** Never merge and never proceed to the next batch. A red
  gate in batch *n* invalidates the base every later batch would build on.
- **Production verification fails** — the health SHA does not match the merge
  SHA, the web root does not return 200, or the batch's own smoke check fails.
- **`batch-start` step 4 finds a spec fact that is wrong in a way that changes
  what the batch should build.** Correcting a stale `file:line` and continuing is
  normal and expected; discovering the batch should do something materially
  different is a stop. Batch 216 is the case that earned this rule.
- **The batch would delete or overwrite production data**, including the
  `activity_timeseries` retention step in Batch 247. See below.
- **A decision gate is reached** that the group definition did not pre-answer.
- **The working tree contains work that is not this batch's.** This repository is
  shared with concurrent sessions and has twice had another session's
  uncommitted work found in it (Batches 232, 235). A single clean `git status`
  is not proof — check `git log --all --not --remotes` for parked branches
  before starting a group.
- **Anything requires a credential, a password, or a hosting-console change.**
  Report it and let the user do it.

## Hard stop: destructive data operations

A batch phase that **deletes production data is never run as part of an
unattended group**, regardless of group authorisation. Batch 247.2 is the known
instance: 90-day `activity_timeseries` retention removes roughly 465,000 rows
and about 247 MB, the table is **excluded from every backup by design**, and the
deletion is irreversible.

For such a phase: build it, test it, verify the retention window and both
readers, then **stop before executing against production** and ask for explicit
confirmation naming the row count. The rest of the batch may close out; the
destructive step is its own approval.

## Guardrails

- Groups are sequential by construction. Each batch branches from the `main`
  that the previous batch's closeout produced — never run two batches of a group
  in parallel, and never stack branches.
- Do not reorder batches within a group. The orders are dependency-derived and
  the reasons are recorded per group.
- Do not merge batches together to save a cycle. One batch, one PR, one squash,
  one production verification — the ledger's audit trail depends on it.
- If a batch bumps a prompt version, `closeout.md` step 10's orphan check is
  mandatory before moving to the next batch. Batch 227 is the case that earned
  it.
- Assign `DECISIONS.md` numbers at each batch's `/batch-start`, never in advance
  for the whole group — pre-assigning collides with concurrent sessions.
- Never use shell `cd`; use absolute paths and `git -C`.
- Tests ship with every change.
