---
description: Generate the next-batch paste-prompt. No-arg or `phase` → docs/phase-batches.md (numeric architecture phases AND M-batches; acceptance pulled from wc2026-architecture.md or docs/multi-league-architecture.md depending on the batch id). `review` → docs/review-batches.md (acceptance inline). `polish` → docs/phase-batches.md "Polish / UX snags" section (ad-hoc; spec is the row's Description cell — there is usually no pre-queued batch to find, since U-batches are named when the user is ready, not picked off a backlog). `env` → docs/env-batches.md (acceptance inline). Mechanical, no hallucination.
---

You are generating the copy-paste prompt for the next batch. Follow these steps **literally** — do not skip, do not infer.

## Mode

`$ARGUMENTS` selects the source:

- empty or `phase` → **phase mode**: `docs/phase-batches.md`. The first un-struck row determines the **sub-mode**:
  - row id matches `^\d+$` (e.g. `13`) → **architecture sub-mode**: acceptance from `wc2026-architecture.md`
  - row id matches `^M\d+$` (e.g. `M1`) → **multi-league sub-mode**: acceptance from `docs/multi-league-architecture.md` (§ 8 `### M<n> ·` headings)
- `review` → **review mode**: `docs/review-batches.md` only (acceptance criteria live in the per-batch sub-sections of that same file)
- `polish` → **polish mode**: U-numbering is a single sequence shared across TWO files — check both:
  - `docs/phase-batches.md` "Polish / UX snags" section — lightweight, single-row, ad-hoc batches (Batch | Model | Description | Commits | Status). The Description cell IS the spec; no separate section or Acceptance block.
  - `docs/polish-batches.md` — heavier, pre-planned multi-item batches with a `## U<N> — <Title>` section, numbered `**U<N>.<M>**` sub-items, and an explicit **Acceptance:** block. Still actively used for substantial batches (not legacy/dead — confirm by checking for a `Pending` row before assuming otherwise).
  Whichever file holds the lowest-numbered un-struck `U<N>` row is the next batch; read/write only that file for it.
- `env` → **env mode**: `docs/env-batches.md` only (spec and acceptance live inline per `## E<N>` section; no code commits or CI involved)

Reject any other value with `"Unknown mode '$ARGUMENTS' — use empty/phase, 'review', 'polish', or 'env'"`.

Per-step notes call out where the modes (and phase sub-modes) diverge.

## Step 1 — Find the next batch

**Polish mode:**

```bash
grep -nE "^\| (U|OPS-)[0-9]" /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md
grep -nE "^\| U[0-9]" /Users/craigrobinson/wc_2026_predictor/docs/polish-batches.md
```

Both patterns only match **unstruck** rows (struck rows begin `| ~~U...~~ |`, so the literal `U`/`OPS-` right after `| ` never appears once struck — no separate tilde check needed). Collect every match from both files and take the row with the **lowest** `U<N>` (the numbering is one shared sequence across both files — e.g. `docs/phase-batches.md` may be struck through up to U59 while `docs/polish-batches.md` separately has a pending U60). That row's file determines the format:

- **Row found in `docs/phase-batches.md`** (ad-hoc): extract the **Batch id**, **Model tag**, and the full **Description** cell — that cell IS the spec, no separate Acceptance block.
- **Row found in `docs/polish-batches.md`** (planned): extract the **Batch id**, **Model tag**, **Effort**, and **Items range** (e.g. `U60.1–U60.6`) from the summary-table row. Continue to Step 2 to pull the full `## U<N>` section.

If no unstruck `U`/`OPS-` row exists in either file, report: "No pending polish batch in `docs/phase-batches.md` or `docs/polish-batches.md`." and stop. Do not invent a batch.



**Phase mode:**

```bash
grep -nE "^\| [0-9~M]" /Users/craigrobinson/wc_2026_predictor/docs/phase-batches.md
```

The first row whose batch id is NOT wrapped in `~~...~~` (i.e. not struck through) is the next batch. Extract:
- **Batch id** (e.g. `2` or `M1`) — set sub-mode by regex match (`^\d+$` → architecture, `^M\d+$` → multi-league)
- **Model tag** (`🟢 Sonnet` or `🔴 Opus`)
- **Phase IDs** (architecture sub-mode: comma-separated, e.g. `7.2, 7.4`; multi-league sub-mode: a single `M<n>` id, e.g. `M1`)

If every row is struck through, report "All batches complete — consult `wc2026-architecture.md` and `docs/multi-league-architecture.md` for any remaining unticked phases" and stop.

**Review mode:**

```bash
grep -nE "^\| R[0-9~]" /Users/craigrobinson/wc_2026_predictor/docs/review-batches.md
```

The first row whose batch id is NOT wrapped in `~~...~~` is the next review batch. Extract:
- **Batch id** (e.g. `R1`)
- **Model tag** (`🟢 Sonnet` or `🔴 Opus`) and reasoning hint (e.g. `(extended thinking)`)
- **Effort** (e.g. `~2 h`)
- **Items range** (e.g. `R1.1–R1.5`)

If every row is struck through, report "All review batches shipped" and stop.

**Env mode:**

```bash
grep -nE "^\| E[0-9~]" /Users/craigrobinson/wc_2026_predictor/docs/env-batches.md
```

The first row whose batch id is NOT wrapped in `~~...~~` is the next env batch. Extract:
- **Batch id** (e.g. `E1`)
- **Model tag** (`🟢 Sonnet` or `🔴 Opus`)
- **Effort** (e.g. `~20 min`)
- **Items range** (e.g. `E1.1–E1.5`)

If every row is struck through, report "All env batches shipped" and stop.

## Step 2 — Pull acceptance criteria verbatim

**Phase mode — architecture sub-mode** (numeric IDs like `7.2`): for each phase ID extracted in Step 1, run:

```bash
grep -n -A 8 "Phase X.Y:" /Users/craigrobinson/wc_2026_predictor/wc2026-architecture.md
```

(Substitute `X.Y` for the actual ID.) If any grep returns no match, **STOP** and tell the user: "Phase `X.Y` does not exist in the architecture doc. Check `docs/phase-batches.md` for a typo." Do not invent acceptance criteria.

Copy the bullets verbatim, including the **Acceptance:** line. Do not paraphrase.

**Phase mode — multi-league sub-mode** (IDs like `M1`): for the M-id extracted in Step 1, run:

```bash
grep -n -A 14 "^### M<n> ·" /Users/craigrobinson/wc_2026_predictor/docs/multi-league-architecture.md
```

(Substitute `<n>` for the actual digit.) The section bullets are the work; the `- **Acceptance:**` sub-block lists the gate. If grep returns no match, **STOP** and tell the user: "Batch `M<n>` does not exist in `docs/multi-league-architecture.md` § 8. Check `docs/phase-batches.md` for a typo." Do not invent acceptance criteria.

Copy the heading title (everything after `### M<n> · `) and all bullets verbatim. The model tag is at the end of the heading line — confirm it matches the row's model tag and stop if they disagree.

**Review mode:** acceptance criteria live INLINE in `docs/review-batches.md`. Read the `## R<N> — <Title>` section of that file for the batch you identified in Step 1. Capture:
- The section title (the part after `— `)
- The one-line summary of each item (lead clause before the first `(` or `.`)
- The **Acceptance:** paragraph at the end of the section

Do **not** grep `wc2026-architecture.md` in review mode — review items are not in it. If the section is missing, stop and report.

**Env mode:** spec and acceptance live INLINE in `docs/env-batches.md`. Read the `## E<N> — <Title>` section for the batch identified in Step 1. Capture:
- The section title (the part after `— `)
- The one-line summary of each `### E<N>.<M>` sub-section heading
- The entire **Acceptance:** block at the end of the section

Do **not** grep architecture docs in env mode. If the section is missing, stop and report.

**Polish mode — ad-hoc (row in `docs/phase-batches.md`):** the spec is the row's **Description cell**, captured verbatim in Step 1 — there is no separate section to grep. Skip the rest of this step.

**Polish mode — planned (row in `docs/polish-batches.md`):** spec and acceptance live INLINE in that file. Read the `## U<N> — <Title>` section for the batch identified in Step 1. Capture:
- The section title (the part after `— `)
- The one-line summary of each numbered item (the `**U<N>.<M>**` lead clause)
- The entire **Acceptance:** block at the end of the section

Do **not** grep `wc2026-architecture.md` in either polish sub-case.

## Step 3 — Anchor with recent commit hashes

Run:

```bash
git -C /Users/craigrobinson/wc_2026_predictor log --oneline -10
```

Identify the commits for the most-recently-shipped phase (the immediately preceding batch). You will reference those hashes in the PREVIOUS SESSION NOTES so the future session can run `git show <hash>` instead of grepping.

## Step 4 — Pull non-obvious gotchas from the previous batch's session-log entry

Run:

```bash
grep -nE "^## (Phase|Multi-league batch|Review batch|Polish batch)" /Users/craigrobinson/wc_2026_predictor/session-log.md | tail -3
```

Read the most recent 1–2 entries (use `Read` with `offset` + `limit` based on the line numbers from the grep). Their `### Key facts for future sessions` bullets are candidates for the new PREVIOUS SESSION NOTES, but only carry forward those that are still relevant to the upcoming batch. Skip anything specific to the just-shipped work.

## Step 5 — Emit the prompt

Output the prompt in this exact format (no preamble, no commentary, just the prompt inside a fenced code block so the user can copy it).

**Phase mode — architecture sub-mode** (numeric IDs):

````
```
Batch N: Phases X.Y → X.Z — back-to-back, single <model> session.

**STEP 1 before anything else:** make sure `staging` is up to date and create
the feature branch:

    git fetch origin && git checkout staging && git pull --ff-only origin staging
    git checkout -b feat/b<N>-<slug>     ← slug derived from the batch title

Do not commit to `staging` or `main` directly under any circumstance.
`/phase-closeout` will merge this branch into `staging` once CI is green.
(Promotion of `staging` to `main`/production is a separate, later
`/ship-prod` call — not part of this batch.)

Close each phase fully before starting the next.   ← include this line only if batch has 2+ phases

Phase X.Y: <Title> <model emoji + tag>
- <acceptance bullet verbatim>
- <acceptance bullet verbatim>
- Acceptance: <acceptance line verbatim>

Phase X.Z: ...   ← repeat per phase in the batch

PREVIOUS SESSION NOTES:
- <non-obvious gotcha, anchored to a commit hash when useful>
- <max ~6 bullets>
- <stop if you cannot think of >3 genuinely non-obvious things — better short than padded>
```
````

**Phase mode — multi-league sub-mode** (`M<n>` IDs):

````
```
Batch M<n>: <Title from § 8 heading> — single <model emoji + tag> session.

**STEP 1 before anything else:** make sure `staging` is up to date and create
the feature branch:

    git fetch origin && git checkout staging && git pull --ff-only origin staging
    git checkout -b feat/m<n>-<slug>     ← slug derived from the batch title

Do not commit to `staging` or `main` directly under any circumstance.
`/phase-closeout` will merge this branch into `staging` once CI is green.
(Promotion of `staging` to `main`/production is a separate, later
`/ship-prod` call — not part of this batch.)

The M-series batch acceptance criteria live in `docs/multi-league-architecture.md` § 8 (NOT in `wc2026-architecture.md`). Skim § 2.2 (decision rationale), § 3 (data model + DDL), § 4 (auth flow), and § 7 (migration plan) before touching code — they were written specifically for this implementer.

Phase M<n>: <Title> <model emoji + tag>
- <bullet verbatim from § 8>
- <bullet verbatim from § 8>
- Acceptance:
  - <acceptance bullet verbatim>
  - <acceptance bullet verbatim>

PREVIOUS SESSION NOTES:
- <non-obvious gotcha, anchored to a commit hash when useful>
- <include the design-doc commit hash so the implementer can run `git show <hash>` for context>
- <max ~6 bullets — stop if you cannot think of >3 genuinely non-obvious things>
```
````

**Review mode:**

````
```
# Batch R<N> — <Title>

You're starting a fresh session for the World Cup 2026 Prediction League
pre-launch fixes. Read `AGENTS.md` in the repo root for project conventions
(branch naming, commit format, test discipline, bash patterns).

**STEP 1 before anything else:** make sure `staging` is up to date and create
the feature branch:

    git fetch origin && git checkout staging && git pull --ff-only origin staging
    git checkout -b fix/r<n>-<slug>     ← slug derived from the batch title

Do not commit to `staging` or `main` directly under any circumstance.

This batch implements **<items range>** from `docs/review-batches.md`. Open
that file and read the entire **R<N> — <Title>** section before starting —
it has the exact file paths, line numbers, and per-item acceptance criteria.
Don't infer the spec from this prompt; the source of truth is the doc.

**Model & effort:** sized for <model emoji + tag>, <effort>. <reasoning hint
verbatim from the batch row, e.g. "Standard thinking — nothing in this
batch needs extended reasoning." or "Extended thinking ON — race/transaction
reasoning matters.">. If you're not on the named model, ask the user before
continuing.

Items to ship (full spec in the doc):
- R<N>.1 — <one-line summary>
- R<N>.2 — <one-line summary>
- ...

**Acceptance gate before you stop:**
- All items done per the R<N> section of `docs/review-batches.md`
- New tests added per the doc's acceptance bullets
- `PYTHONPATH=/Users/craigrobinson/wc_2026_predictor/apps/api /Users/craigrobinson/wc_2026_predictor/apps/api/.venv/bin/python -m pytest /Users/craigrobinson/wc_2026_predictor/apps/api/tests` green (or frontend equivalent if the batch is frontend-only)
- `ruff check` and `mypy src` green (backend); `pnpm test` green (frontend)
- Push the branch (`git push -u origin fix/r<n>-<slug>`) and confirm CI green — use the cached endpoint or one background poll, do NOT foreground-poll (see `AGENTS.md` bash discipline)

**Do not merge.** Stop after CI is green. The user will run `/phase-closeout
R<N>` to merge to `staging`, append the session-log entry, and strike the row
in `docs/review-batches.md`. (Promotion of `staging` to `main`/production is
a separate, later `/ship-prod` call — not part of this batch.)

PREVIOUS SESSION NOTES:
- <non-obvious gotchas from the most recent review-batch session-log entry,
  anchored to a commit hash when useful — max ~6 bullets, or omit the whole
  block if this is R1 or there are no genuinely non-obvious items>
```
````

**Polish mode — ad-hoc** (row found in `docs/phase-batches.md`):

````
```
# Batch <batch-id> — <short title derived from the Description cell>

You're starting a fresh session for the World Cup 2026 Prediction League
PWA. Read CLAUDE.md in the repo root for project conventions (branch
naming, commit format, test discipline, bash patterns).

**STEP 1 before anything else:** make sure `staging` is up to date and
create the feature branch:

    git fetch origin && git checkout staging && git pull --ff-only origin staging
    git checkout -b fix/<batch-id-lowercase>-<slug>     ← slug derived from the description

Do not commit to `staging` or `main` directly under any circumstance.

This batch is row **<batch-id>** in `docs/phase-batches.md`'s "Polish / UX
snags" section:

<--- paste the row's Description cell verbatim here --->

**Model:** <model emoji + tag> per the row. If you're not on the named
model, ask the user before continuing.

**Acceptance gate before you stop:**
- The description above is fully implemented
- Tests added/updated as appropriate; `pnpm test` + `pnpm typecheck` green
  (frontend) or pytest + ruff + mypy green (backend) — whichever side(s)
  this batch touches
- Push the branch and confirm CI green — one check + at most one
  background poll, do NOT foreground-poll (see CLAUDE.md bash discipline)

**Do not merge.** Stop after CI is green. The user will run
`/phase-closeout <batch-id>` to merge into `staging`, append the
session-log entry, and strike the row in `docs/phase-batches.md`.
(Promotion of `staging` to `main`/production is a separate, later
`/ship-prod` call — not part of this batch.)

PREVIOUS SESSION NOTES:
- <non-obvious gotchas from the most recent polish-batch session-log entry,
  anchored to a commit hash when useful — max ~6 bullets, or omit the
  whole block if there are no genuinely non-obvious items>
```
````

**Polish mode — planned** (row found in `docs/polish-batches.md`):

````
```
# Batch <batch-id> — <Title from the ## U<N> heading>

You're starting a fresh session for the World Cup 2026 Prediction League
PWA. Read CLAUDE.md in the repo root for project conventions (branch
naming, commit format, test discipline, bash patterns).

**STEP 1 before anything else:** make sure `staging` is up to date and
create the feature branch:

    git fetch origin && git checkout staging && git pull --ff-only origin staging
    git checkout -b feat/<batch-id-lowercase>-<slug>     ← slug derived from the title

Do not commit to `staging` or `main` directly under any circumstance.

This batch implements **<items range>** from `docs/polish-batches.md`. Open
that file and read the entire `## <batch-id> — <Title>` section before
starting — it has the full per-item spec. Don't infer the spec from this
prompt; the source of truth is the doc.

**Model & effort:** sized for <model emoji + tag>, <effort>.

Items to ship (full spec in the doc):
- <batch-id>.1 — <one-line summary>
- <batch-id>.2 — <one-line summary>
- ...

**Acceptance gate before you stop (verbatim from the doc's Acceptance: block):**
- <acceptance bullet verbatim>
- <acceptance bullet verbatim>
- ...

**Do not merge.** Stop after CI is green. The user will run
`/phase-closeout <batch-id>` to merge into `staging`, append the
session-log entry, and strike the row in `docs/polish-batches.md`.
(Promotion of `staging` to `main`/production is a separate, later
`/ship-prod` call — not part of this batch.)

PREVIOUS SESSION NOTES:
- <non-obvious gotchas from the most recent polish-batch session-log entry,
  anchored to a commit hash when useful — max ~6 bullets, or omit the
  whole block if there are no genuinely non-obvious items>
```
````

**Env mode:**

````
```
# Batch E<N> — <Title>

You're running an **ops-only** env-variable batch for the World Cup 2026 Prediction League. No code changes — this is all Railway CLI and Vercel CLI/dashboard work.

Open `docs/env-batches.md` and read the entire **E<N> — <Title>** section before starting. The per-item instructions there are authoritative; don't infer the spec from this prompt.

**Model & effort:** sized for <model emoji + tag>, <effort>. If you hit a missing CLI permission or unexpected output, stop and ask rather than guessing.

Items to complete (full spec in `docs/env-batches.md`):
- E<N>.1 — <one-line summary from ### heading>
- E<N>.2 — <one-line summary>
- ...

**Acceptance (from `docs/env-batches.md`):**
- <acceptance bullet verbatim>
- <acceptance bullet verbatim>
- ...

**No feature branch. No commits. No CI. No `/phase-closeout`.** When all acceptance criteria pass, report back and the user will run `/strike-batch E<N>`.

PREVIOUS SESSION NOTES:
- <non-obvious gotchas from the most recent env-batch session-log entry — max ~4 bullets, or omit entirely if this is E1>
```
````

After emitting the prompt, on a new line, remind the user: "Paste into a fresh **<model>** session. After it starts, run `/strike-batch <id>` (or edit the batches doc manually) to mark this batch in-flight." The `<id>` is `N` in phase mode architecture sub-mode, `M<n>` in phase mode multi-league sub-mode, `R<N>` in review mode, `U<N>` in polish mode, and `E<N>` in env mode.

## Rules

- Never include "Files modified" or "What shipped" sections.
- Never include date, model tag, or commit hashes as a metadata header — those belong in session-log entries, not the next-batch prompt.
- Never propose a model different from what's in the batch row.
- Never quote acceptance criteria from memory — always grep them fresh from the source doc (architecture sub-mode → `wc2026-architecture.md`; multi-league sub-mode → `docs/multi-league-architecture.md`; review mode → `docs/review-batches.md`; polish mode → whichever of `docs/phase-batches.md` or `docs/polish-batches.md` actually holds the next un-struck `U<N>` row — check both, never assume one is dead).
- If anything looks inconsistent (architecture sub-mode: struck-through row but phase not ✅ in arch doc, or vice versa; multi-league sub-mode: batch row's model tag disagrees with the § 8 heading's model tag), stop and ask the user.
