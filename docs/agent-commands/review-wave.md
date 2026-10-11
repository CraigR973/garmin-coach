# Command: review-wave

Run a full-app audit wave (a panel of expert passes, a synthesis, a roadmap) as a set of
separate, resumable batches, one session each. Written after wave #5 (Batches 327–333,
7–10 Oct 2026) and adopted by Craig on 10 Oct (Decision #391). Wave #5 launched five passes
in parallel at top effort; usage limits stopped it four times, lost the first run outright,
and turned a 6–8 hour job into about 2.5 days. This procedure exists so that cannot recur.

## Inputs

- The kickoff brief (the questions, the passes and their lenses, the hard rules). Earlier
  briefs live in session transcripts (memory note "Review kickoff prompts"); the wave #5
  scope note `docs/reviews/BATCH_327-333_AUDIT_SCOPE.md` is the best template.
- Craig's answers at check-in: which passes, read-only production access, a paid-call cap,
  and the reserved batch numbers (one per pass, the next free block in the ledger).

**In Claude Code** the user-level skill `/review-wave` runs these steps (`start`, `next`,
`panel`, `checkin`, `pack`, `pass <id>`, `synth`, `rows`, `delta`), keeps a state file in
`scratchpad/<wave>/STATE.md`, and holds the lens catalogue shared across Craig's projects. This
file is the repo's copy, so any agent can follow the same steps without the skill.

## Cadence (Decision #392)

```
Always on    standing checks in CI and scheduled jobs (the guards)
Monthly      delta review: only what shipped, 2–3 lenses chosen by what changed
Occasional   full panel: after a major phase, or every 6–8 weeks
```

## The shape

```
P. Panel           the app profile and the expert panel; Craig confirms
0. Check in        plan + three questions to Craig; wait for his go
1. Review pack     one session: frozen SHA + data snapshot, digest, follow-through
2. Pass batches    one session per pass, at most two running at once
3. Fast lane       a confirmed live defect gets its own fix batch at once
4. Synthesis       one session: short roadmap and guards, ledger rows on Craig's go, the page
```

## Step P — The panel

Before any plan, profile the app from its docs, code and live data (its user and their job;
the decisions it makes for them; what it changes outside itself; its data and how sensitive;
whether it calls models; where it runs; what has gone wrong before). Then propose the panel:
the core lenses (code and architecture; data, security and ops; product and UX with the user
scorecard; AI and LLM if it calls models) and the domain lenses the profile calls for (the
integrity of its core decision; the user's wellbeing or protection; any specialist its claims
depend on). Each lens names the harm only it would catch; about seven at most. For garmin-coach
the domain lenses have been the endurance coach, the strength and fitness coach, and the
sports-medicine doctor with a sleep scientist. Craig confirms the panel before Step 0.

## Hard rules (every step)

- **Read-only.** No change to code, production data, Railway, Vercel, Supabase or Sentry;
  no device token minted (it is a production write); nothing sent to Mark. The only writes
  are the review's own files on its `chore/` branch.
- **No paid Anthropic call** beyond Craig's cap; `count_tokens` is free; stored
  `coach.analyses` rows first. Log every paid call.
- **Evidence labels** on every finding (`observed`, `computed`, `proved`, `implemented`,
  as in `COACHING_INTEGRITY_AUDIT.md`); unverified ideas under Hypotheses. A ledger row,
  close-out note or STATUS line is a claim, not evidence.
- **Settled decisions** are cited by number under "For reconsideration", never silently
  re-argued. A queued or parked row that covers a problem is re-verified (`batch-start.md`
  step 4), not re-reported.
- **The repo is public:** Mark only in short phrases; no screenshots, captures or extracts
  committed (they stay in the gitignored `scratchpad/`).
- Production SQL through the Supabase MCP, `coach` schema, column-projected and windowed;
  any `railway run` that opens a transaction has a `faulthandler` watchdog and rolls back.
- `git rev-parse --abbrev-ref HEAD` before every commit; other sessions share the checkout.

## Step 0 — Check in

Fast-forward `main`, record the SHA and confirm production serves it, list open PRs and
other sessions' branches (touch none), check live state (the last few mornings, the plan,
`job_runs` failures, database size). Post the plan in 15 lines or fewer and ask Craig the
three remaining questions (production access, paid cap, batch numbers) as clickable choices. Wait for his go. Then write the scope note
(`docs/reviews/BATCH_<first>-<last>_AUDIT_SCOPE.md`) and commit it.

## Step 1 — The review pack (one session; Sonnet 5.5 · high)

Build once what every pass would otherwise re-read. Wave #5's passes each re-read STATUS,
ARCHITECTURE, DECISIONS and about 3,000 lines of the ledger, an estimated third of their
tokens. Write to `scratchpad/<wave>/pack/` (gitignored, persistent; **never** the session's
`/private/tmp` scratchpad, which was wiped mid-wave):

- `DIGEST.md`, at most about 400 lines: the architecture map as it is, the decisions since
  the last wave (one line each, with numbers), the batches shipped since (one line each),
  the queued and parked rows, the open "Needs Craig" items.
- `LIVE.md`: the live-state snapshot taken at check-in, with the SHA and the date. Passes
  judge this snapshot; later drift is noted, not chased.
- `followthrough.md`: every finding of the last wave and of the reviews since, with status
  and evidence. Passes correct only the rows in their own lens.
- `data/`: the extracts several passes need (for example the plan draft, the stored
  mornings' calls, `job_runs` per job), so each is pulled once.

Commit nothing from the pack; the scope note links to it by path.

## Step 2 — One pass, one batch

Each pass has its own reserved batch number, its own session and a brief file
(`scratchpad/<wave>/lenses/R<n>.md`) that holds its lens, report path, model and effort.
Start it with: read the common brief, then the pack, then the lens; nothing else up front.

**Order.** At most two passes running at once. Run the mechanism passes before the passes
that build on them:

| First (any two together) | Then | Last |
|---|---|---|
| Code · AI · Ops | Coaching (needs AI) · Health · Fitness | UX and the scorecard (needs all) |

**Model and effort** (Craig may overrule per pass):

| Pass | Model · effort |
|---|---|
| Code, AI, Coaching, Health | Opus 5.5 · high |
| Ops, Fitness | Opus 5.5 · high |
| UX screen walk, repo sweep, follow-through table | Sonnet 5.5 · high |
| Synthesis | Opus 5.5 · xhigh |

**Report outline, findings first, written to disk section by section:**

1. Summary in five lines with a grade.
2. Findings, at most ten, Highs first: ID (`<PREFIX><batch>-<nn>`), severity, evidence
   label, the evidence, what Mark or Craig experiences, the fix and its cost, where it goes.
3. Corrections to the pack's follow-through rows in this lens.
4. Queued and parked rows in this lens, re-verified.
5. For reconsideration · Hypotheses · Limitations · Probe log (paid calls with cost).

About 200 lines. If a stop interrupts it, the next session reads the report and the pass's
scratch folder and continues; it never restarts a pass whose findings are already on disk.

**At the end of each pass:** commit the report on the review branch, and send Craig a
one-screen note: the grade, each High in one line, anything for the fast lane.

## Step 3 — The fast lane (Decision #391)

When a pass confirms a defect that is affecting Mark now (wave #5's case: an eased ride
carried across three days, which recurred while the review ran), the orchestrator re-checks
it against production at once and messages Craig with the evidence and one recommended
action. If the fix only adds caution (a stopgap such as withholding an offer), it may be
authored as its own small batch and shipped mid-review on Craig's one-tap yes, through the
normal batch gate, even inside a trial window. Anything that removes caution, changes a rule
of a running trial, or touches money, auth or data waits for the roadmap. The review itself
stays read-only; the fast-lane batch is ordinary build work in its own session.

## Step 4 — Synthesis (one session; Opus 5.5 · xhigh)

Re-verify every High and every headline number against production or the shipped code. Then
write `docs/reviews/BATCH_<first>-<last>_REMEDIATION_ROADMAP.md`, short enough to read on a
phone (about 250 lines), in this order: the verdict in five lines and a scorecard; happening
now; how the app works now (a small diagram, and where `ARCHITECTURE.md` disagrees with the
code); the work packages; the coverage check (every finding mapped); decisions for Craig,
numbered with a recommendation and a cost each. It also names **the guards**: which findings
become standing checks (CI tests, scheduled jobs, alerts), so the next review need not
rediscover them. The full follow-through table and the draft
ledger rows go in companion files. Open a PR (not merged until Craig says), publish the
roadmap as a private page (never the coaching-integrity report or Mark's scorecard), prepend
one dated line to STATUS's log. Ledger rows and `/batch-group` groups only after Craig's go,
written from the roadmap, with a model and effort for each step.

## Lessons from wave #5 that this procedure encodes

- Five Opus passes in parallel at `xhigh` exhausted the plan's limit within minutes; at most
  two at once, at `high`.
- A wiped temp folder lost the first follow-through table; persistent scratch only.
- Reports written at the end lost work at every stop; findings first, written as you go.
- Three passes traced the same bug; the fast lane takes a live defect out of the passes.
- Seven re-reads of the same documents; one pack.
- About 5,000 lines of output for one reader on a phone; capped findings and a short roadmap.

## The delta review (monthly)

Everything merged since the last review's SHA, plus the live state. Map the changed paths to
lenses and run the 2–3 with the most change or risk, in one session (two if large). Re-run the
guards and note any missing. One short report (`docs/reviews/<date>-delta-review.md`): what
changed, at most ten findings, the last review's open items, new guards, decisions. Escalate to
a full panel if it finds a High in a lens it did not run, or if the change touched the rules of
the core decision.
