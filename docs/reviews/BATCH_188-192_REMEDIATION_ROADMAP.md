# Batch 188–192 remediation roadmap

**Date:** 2026-08-06
**Author:** triage pass over the five diagnose-only wave-2 reviews (188 coach
conversation, 189 code, 190 data/security/ops, 191 coaching integrity, 192 UX)
**Status:** proposal for Craig's approval — no code changed, no ledger row added,
no batch/DECISIONS numbers allocated

## Purpose

The wave-2 audit produced **67 findings (12 High, 33 Medium, 22 Low)** with
review-local IDs (`CC188-*`, `CR189-*`, `DS190-*`, `CI191-*`, `UX192-*`) and
remediation *stubs*, but no ordering and no allocated work. This doc converts them
into a sequenced set of **proposed** batches, one disposition per finding, so the
roadmap can be approved before any code starts. It follows the pattern of
[`BATCH_153-156_REMEDIATION_ROADMAP.md`](BATCH_153-156_REMEDIATION_ROADMAP.md),
whose nine slots all shipped as Batches 157–166.

**Count correction.** Batch 188's own summary line and the `STATUS.md` entry that
copied it both read "2 High, 8 Medium, 7 Low" (17). The document actually carries
`CC188-01…20` — **2 High, 10 Medium, 8 Low**. The wave total is 67, not 64. All 20
are mapped below.

**Numbering discipline:** the `W1…W13` labels are roadmap-local sequence slots,
**not** ledger batch numbers. Real batch numbers and DECISIONS numbers get assigned
when each is kicked off via `/batch-start` — pre-assigning has collided with
concurrent sessions twice.

**Verdict-engine safety rule** (carried from wave 1) applies to **W2, W9 and W13**:
a change may only ever *harden* the deterministic Green/Amber/Red light, never
soften it, and the light stays computed in Python, never model-set.

## Disposition legend

- **Do now** — schedule as a batch in the order shown.
- **Fold** — ships inside a parent slot (same files/surface), not its own batch.
- **Decision-gated** — ready, but Craig decides *whether/when* to trigger.
- **Defer** — real but low value at current 1–2-user scale; revisit on a trigger.

## Model guidance

Each slot names a suggested **coding-agent model** — the model that *writes* the
batch, separate from the app's runtime coaching model (Sonnet 4.6).

- **Opus 5** — subtle correctness, safety-critical, concurrency, or multi-file
  design work where a wrong-but-plausible change is costly.
- **Sonnet 5** — well-scoped implementation against a clear pattern or spec.
- **Haiku 4.5** — mechanical, low-ambiguity edits.

Starting points, not rules.

## At a glance (proposed order)

| Slot | Proposed batch | Findings | Max sev | Model | Size | Migration | Why here |
|---|---|---|---|---|---|---|---|
| **W0** | Migration 022 backfill audit | CR189-06 | 🟠 Med | Sonnet 5 | XS | No | Read-only prod query, not a batch — answers whether Mark's real history holds a mislinked read or a resurrected skip |
| **W1** | The coach actually reaches Mark | UX192-01/02/03/04/06, CR189-01 *(gate: UX192-10)* | 🔴 High ×4 | Sonnet 5 | S–M | No | **Only findings broken in production right now**; the Sunday 09 Aug weekly review lands on all of them |
| **W2** | A Red cannot be talked away | CI191-01, CI191-03 | 🔴 High | Opus 5 | M | No | Live inversion of the audit's founding invariant; switched off a real deload on 05 Aug |
| **W3** | Jobs that fail say so | CR189-02, DS190-02, DS190-04, CR189-20; DS190-01 *(gated)* | 🔴 High ×3 | Opus 5 | M | No | A poisoned Session can cost Mark a whole day's verdict and log one useless line |
| **W4** | A backup you have actually restored | DS190-03 | 🔴 High | Sonnet 5 | M | No | Free-plan Supabase has no managed backup — this dump is the only one, and it is alertless |
| **W5** | Unprompted speech agrees with the brief | CC188-01/02/08/10/20, CR189-09 | 🔴 High ×2 | Opus 5 | M | No | Blocked behind W1 (nothing is delivered yet), but must land before the rail carries traffic |
| **W6** | The unprompted writer is safe to run twice | CR189-03/04/07/16, CC188-17/19 | 🟠 Med | Sonnet 5 | S–M | Maybe | Same file as W5 — fold if you'd rather touch `state_change_coach.py` once |
| **W7** | Floors that can actually fail | CC188-04/05/06/07/11/14/18, CI191-04 | 🟠 Med | Opus 5 | M | No | The safety audit currently passes an inverted Red/VO2 rule; the guard is the product |
| **W8** | Contrast and touch where they render | UX192-05, UX192-08 | 🟠 Med | Sonnet 5 | M | No | `UX156-03` re-opened past the batch meant to close it; Mark is 60-plus on a phone outdoors |
| **W9** | Verdict-ladder residuals | CI191-05/06/07 | 🟠 Med | Opus 5 | M | No | Credit ceiling guards the Green line but not the Red line; load still relaxes below the cap |
| **W10** | Chat context tells the truth about itself | CC188-03/09/12/13/15/16, CI191-08 | 🟠 Med | Sonnet 5 | M | No | Packet honesty + prompt hygiene; the 11k-char self-embedded prompt is the big one |
| **W11** | Correctness cleanup | CR189-05/08/10/14/15/17/18/19 | 🟠 Med | Sonnet 5 | M | No | Independent small backend fixes; can ship as one batch or split |
| **W12** | Security hygiene | DS190-07/08/09, CR189-11/13 | 🟠 Med | Sonnet 5 | S–M | No | Posture, no live exploit — sequence after user-facing work |
| **W13** | The day's record means one thing | CI191-02 | 🔴 High | Opus 5 | L | **Yes** | Architectural; the largest single item in the wave — decision-gated deliberately |
| — | **Defer** | DS190-05, DS190-06, UX192-07, UX192-09, CR189-12 | 🟠 Med | — | — | — | See *Deferred* below |

---

## W0 — Migration 022 backfill audit *(Do now — a query, not a batch)*

**Findings:** CR189-06 (Medium)
**Source:** [Batch 189](BATCH_189_CODE_REVIEW.md#cr189-06)
**Model:** Sonnet 5 — a read-only SQL pass with a clear question.

Not a batch. Migration `022` ran in production on 2026-07-26 and paired activities
to planned workouts by `row_number()` over **two unrelated v4-UUID orderings**, then
set `status = 'completed'` on the matched workouts with no exclusion for `skipped`.
On any day with two same-kind sessions the pairing was a coin flip, and a workout
Mark explicitly skipped could have been flipped to completed.

The migration is not to be amended. The open question is *retrospective*: does
Mark's history now contain a mislinked read or a resurrected skip?

- **Scope:** a read-only production query listing days with ≥2 same-kind
  post-activity analyses, comparing each `analyses.planned_workout_id` against the
  time-ordered pairing; plus any `planned_workouts` whose status moved to
  `completed` on the migration date while an `action_audit` row records a skip.
- **Why first:** it is cheap, it is read-only, and if it finds something the repair
  belongs inside W2's data pass rather than a separate later batch.

## W1 — The coach actually reaches Mark *(Do now — first)*

**Findings:** UX192-01 (High), UX192-02 (High), UX192-03 (High), CR189-01 (High),
UX192-04 (Medium), UX192-06 (Medium) · **gate:** UX192-10 (Low)
**Source:** [Batch 192](BATCH_192_UX_LIVE_APP_REVIEW.md#ux192-01) ·
[Batch 189](BATCH_189_CODE_REVIEW.md#cr189-01)
**Model:** Sonnet 5 — clear frontend patterns against measured evidence; no
ambiguity about what correct looks like.

**The only findings broken in production right now**, and they compound on one
surface. Four Highs on one component:

- **UX192-01:** `CoachLauncher.tsx:126` passes `'fixed … relative'` to `cn()`;
  tailwind-merge keeps the last position utility and **discards `fixed`**. The
  launcher computes `position: relative; left: -16px`, renders in normal flow at
  the end of the layout (`rect.y` 2176 on a 2300 px page in an 844 px viewport) and
  is clipped 16 px off the left edge. Introduced by Batch 185's own commit
  `368ef69`; live in the deployed bundle, desktop included.
- **UX192-02:** the thread opens at `scrollTop: 0` of a 28,380 px pane in a 388 px
  window — the newest turn is **27,992 px below the fold**, and the 60-message
  window already truncates a real 82-message history with no "load older".
- **UX192-03:** a failed thread fetch renders as *"Nothing here yet. Ask whatever's
  on your mind."* — 82 messages read as deleted, with an invitation to start over.
  The inline read chat is worse: no copy at all.
- **CR189-01 / UX192-04:** the unread predicate hard-codes
  `originKind === 'weekly_review'`, so a `state_change` turn lights nothing. Three
  vocabularies disagree (backend 15 kinds, shared schema 14, client 14).
- **UX192-06** folds in: no optimistic user turn and no thinking affordance, so a
  multi-second Anthropic call reads as "it didn't send".

**Why first:** the Sunday weekly review is scheduled for **2026-08-09**, the first
ever produced. Every one of these sits on its delivery path — it would arrive on a
button Mark cannot see, in the one part of the pane never on screen, and any
transient failure would render the whole history as absent. This also
retro-unblocks Batches 184–187, whose entire proactive-coaching output is currently
undeliverable.

- **Scope:** separate positioning from the dot anchor (a `fixed` element is already
  a containing block, so the redundant `relative` can simply go); scroll to the
  newest turn on open and after each reply, and decide what the 60-message ceiling
  means to a reader; give `CoachConversation` an explicit status input with three
  distinct presentations and a retry; widen the unread rule to role-and-recency (or
  an explicit complete allowlist) behind a shared constant in `packages/shared`;
  bring `coachOriginKindSchema` + `ORIGIN_PROMPTS` up to `ORIGIN_KINDS`; append the
  user's turn optimistically.
- **Size / migration / tests:** S–M · no migration · **assert the rendered DOM, not
  the class string** — `getComputedStyle(button).position === 'fixed'` and in-viewport
  on a long page; rendered copy per status; a test that fails when the backend gains
  an origin kind the client does not know.
- **Gate (UX192-10):** before closing, force one weekly review into a disposable
  context and confirm the whole chain — turn written → dot lit → launcher visible →
  sheet opens on the new turn → week-ahead prose present and readable. Batch 186's
  week-ahead guidance has no other outlet and has never been exercised in front of
  a user.
- **Split option:** W1a = UX192-01/02/03 (the three Highs, one file); W1b =
  CR189-01/UX192-04/UX192-06 (vocabulary + unread rule + pending state).

## W2 — A Red cannot be talked away *(Do now — coaching safety)*

**Findings:** CI191-01 (High), CI191-03 (Medium)
**Source:** [Batch 191](BATCH_191_COACHING_INTEGRITY_REFRESH.md#ci191-01)
**Model:** Opus 5 — this is the deterministic protection rail, and the fix has to
restore an invariant without introducing a new way to over-escalate.

**CI191-01 inverts the property the original audit was built on.** Batch 182's Red
qualification removes a Red from the chronic cluster if *any* single check-in phrase
matches — uncapped, undecaying, with no physiology check. Two of the five categories
are not acute events at all: `training_load` matches "hard training", "back-to-back",
"3-day block"; `deliberate_rest` matches "deload", "recovery week". A Red caused by
training load is the signal, not the noise.

Observed live, not hypothetical: on 05 Aug both of Mark's Reds became
`explained_by_check_in` (07-31 `training_load`, 08-01 `alcohol`), `redMorningCount`
fell 2 → 0, and a live seven-day deload escalation switched off — with 08-01's
resting HR at 48 against its own ceiling of 45. The more honestly he attributes a
Red to training, the less the app escalates.

**CI191-03 folds in** because it is the same escalation's tail: when that escalation
was withdrawn, its two undecided proposals for **08-08 and 08-09 stayed `proposed`**.
On Saturday Mark's brief will say no chronic action is warranted while the Week view
offers him a "Seven-day chronic deload" for that same session.

- **Scope:** separate acute exogenous causes (alcohol, illness, travel) from
  endogenous training causes and stop `training_load`/`deliberate_rest` excusing a
  Red at all; bound the remaining exclusion — physiology may contradict it, cap how
  many of the last N Reds may be excluded, decay the tag's power; expire undecided
  chronic-origin proposals when `chronicAction.triggered` goes false, with an audit
  row saying why (already-pushed sessions stay).
- **Size / migration / tests:** M · no migration expected · a regression on the real
  07-31/08-01 shape proving those Reds now count; proof a habitual annotation cannot
  permanently silence the rail; proof the change only ever *hardens*.
- **Craig's call, this week and separate from the batch:** the 08-08/08-09 proposals
  are still standing in production. Batch 191 deliberately left them because
  retracting them is your decision. They expire on their own by Sunday.

## W3 — Jobs that fail say so *(Do now — reliability)*

**Findings:** CR189-02 (High), DS190-02 (High), DS190-01 (High, **half gated**),
DS190-04 (Medium), CR189-20 (Low, **fold**)
**Source:** [Batch 189](BATCH_189_CODE_REVIEW.md#cr189-02) ·
[Batch 190](BATCH_190_DATA_SECURITY_OPS_REVIEW.md#ds190-01)
**Model:** Opus 5 — transaction-boundary correctness plus a job-result contract
that has to degrade the right things.

- **CR189-02:** every per-step handler in the morning pipeline catches, logs and
  continues **on the same `AsyncSession`**. SQLAlchemy invalidates a Session after a
  failed flush, so everything downstream raises `PendingRollbackError` — confirmed by
  execution. Batch 180 widened the daily sync from one date to four, so one bad row
  on D-2 poisons D-3, then `_sync_morning_inputs`'s `commit()` raises *outside* any
  per-step handler and unwinds past morning analysis, the brief-ready push, Amber
  regeneration, chronic deload and the driver cache. **Mark gets no verdict that
  day, and the log emits one line naming neither the profile nor the step.**
- **DS190-02 + CR189-20:** each coroutine swallows its own exception and the runner
  exits 0 regardless, so Railway/GitHub cron cannot alert from exit state. A failed
  weekly review or backup looks exactly like a successful one.
- **DS190-04:** deploy freshness is human-only. Decision #258's dropped-webhook
  incident produced no failed deployment — production silently served a stale SHA.

- **Scope:** `await session.rollback()` in every per-step handler that can follow a
  DB write (matching the three that already do); give `_sync_morning_inputs`'s
  commits their own guard so a commit failure degrades the *inputs*, not the
  verdict; a typed job result/failure contract with non-zero exit in external mode
  and a persisted per-job run row (window, timestamps, status, reason, counters); a
  post-merge monitor polling both health paths to the expected SHA with a bounded
  timeout, alerting on mismatch.
- **Size / migration / tests:** M · likely a small run-log table · a test that a
  poisoned step does not cost the verdict; a job-failure test asserting non-zero
  exit; a simulated stale-SHA alert.
- **Decision-gated half (DS190-01):** the API is sleep-enabled and still hosts 10 of
  11 scheduled workloads. Making execution genuinely always-on versus creating
  external run-to-completion services for every job is a hosting-cost and
  architecture call, not an implementation detail. **Do not flip the in-process
  scheduler off until each external job has proved successful.**

## W4 — A backup you have actually restored *(Do now — High)*

**Findings:** DS190-03 (High)
**Source:** [Batch 190](BATCH_190_DATA_SECURITY_OPS_REVIEW.md#ds190-03)
**Model:** Sonnet 5 — a clear ops task; bump only if the off-site design gets
complicated.

The mechanics now pass — durable `api-volume` mounted at `/data/backups`, three
7.7–7.8 MB PostgreSQL 17 custom archives surviving deploys, owner-only modes,
correct scope. What does not pass: **seven production failure rows paged nobody**,
and **no full restore has ever been performed**. A syntactically valid archive can
still fail on ownership, extensions, migration state or data constraints at the
moment you urgently need it.

This is sharper than the finding text alone suggests: the Supabase free plan has
**no managed backups and no PITR**, so this dump is not a second line of defence —
it is the only one. A base-image regression already erased the recovery window for
five silent nights once.

- **Scope:** alert outside the end-user profile model (provider log alert,
  operator-only channel, or external monitor); a scheduled disposable restore with
  row/schema invariants, recording the result; an encrypted off-site cadence with a
  stated RPO/RTO.
- **Size / migration / tests:** M · no migration · the restore drill *is* the test;
  assert the alert fires on a simulated failure.

## W5 — Unprompted speech agrees with the brief *(Do now, after W1)*

**Findings:** CC188-01 (High), CC188-02 (High), CC188-08 (Medium),
CC188-10 (Medium), CR189-09 (Medium), CC188-20 (Low, **fold**)
**Source:** [Batch 188](BATCH_188_COACH_CONVERSATION_REVIEW.md#cc188-01)
**Model:** Opus 5 — the failure modes are all "plausible but wrong", which is
exactly where a cheaper model produces a confident regression.

Sequenced after W1 because until the launcher works, nothing here is delivered
anyway — but it must land before the rail carries real traffic.

- **CC188-01:** the seven-day budget is checked *before* candidates are computed and
  fires on **any** `state_change_coach` row regardless of kind. A trivial
  weekly-mix heads-up on Monday permanently silences a chronic deload transition
  that appears on Tuesday — not "until the budget frees up", but never, because the
  comparison baseline moves independently of delivery.
- **CC188-02:** the coach recomputes "current" state with **different parameters**
  from the brief Mark read that morning — weekly mix forced to
  `verdict_status="Green"`, chronic without `current_verdict` — and compares against
  *yesterday's* packet, even though the 11:00 backstop guarantees today's read
  before the 11:45 job. It can announce a bucket "has quietly gone at risk" an hour
  after the brief already said so and offered the swap. **This also closes
  CI191-07's rail half.**
- **CC188-08:** an absent previous morning read makes every `previous_value` `None`,
  so a fortnight-old standing state is announced as *"Something changed"* — which is
  exactly what happens on the first day back from a holiday.
- **CC188-10:** no holiday guard at all, and the weekly-mix lane has no suppression,
  so a bucket mechanically flips to at-risk as a holiday week progresses and the
  coach posts a heads-up about a week there is nothing to fix.
- **CR189-09 / CC188-20:** the one DB test **subclasses the service and overrides
  `_candidates`** — the entire detection layer, which is Decision #268's central
  design claim, is never executed under test. Every finding above would have been
  caught by a single end-to-end test.

- **Scope:** evaluate candidates first and apply the budget as a *ranked* spend
  (allow a strictly higher-ranked transition to pre-empt a lower-ranked one, at most
  one pre-emption per window) or scope it per `TransitionKind`; read *today's*
  stored morning packet as the "current" snapshot instead of recomputing — which
  deletes both parameter asymmetries and removes three service calls per profile per
  day; treat "no previous packet" as *unknown*, not "different"; apply the
  weekly-review job's holiday check before candidate generation.
- **Size / migration / tests:** M · no migration · DB tests that seed a real
  previous-morning packet and run `_candidates` **unstubbed**: standing state → no
  message, genuine flip → message, missing previous read → no message.

## W6 — The unprompted writer is safe to run twice *(Do now — Medium)*

**Findings:** CR189-03, CR189-04, CR189-07 (Medium) · CR189-16, CC188-17,
CC188-19 (Low, **fold**)
**Source:** [Batch 189](BATCH_189_CODE_REVIEW.md#cr189-03)
**Model:** Sonnet 5 — a clear lock/commit pattern already established elsewhere in
the codebase.

Everything here is in `state_change_coach.py`. **Fold into W5 if you would rather
touch that file once** — the reason to keep it separate is that W5 changes
behaviour and W6 does not.

- **CR189-03:** `run()` reads the budget, computes candidates, re-reads, then
  inserts — with no lock, and `analyses` has no unique constraint. `ReviewService.run`
  takes an advisory lock *specifically* for the cron/in-process overlap; the
  state-change coach shipped two batches later onto the same rail with neither.
- **CR189-04:** `_experiment_candidates` calls `ExperimentEvaluationService.run(commit=False)`
  purely to read a recommendation — and that call **inserts** an audit row. The
  `already_delivered` exit never commits, so those rows land in a *later* profile's
  transaction or are discarded.
- **CR189-07:** an unbounded scan of every historical evaluation packet, each with a
  full JSONB payload, filtered in Python — once per active experiment, every run.
- **CR189-16 / CC188-17 / CC188-19** fold in: the runbook omission is currently
  *protective* and should become an explicit note rather than a row; the
  `already_delivered` idempotency path is 48 lines of unreachable code; and
  DECISIONS should record that a dropped transition is dropped *permanently*.

- **Scope:** `pg_advisory_xact_lock` as the first statement in `run()`, mirroring
  `reviews.py`; a read-only detection path via the existing pure
  `ExperimentEvaluationService.evaluate`; push the `experimentId` predicate into SQL
  with `.limit(1)`; delete the dead branch; runbook note.
- **Size / migration / tests:** S–M · a partial unique index would make the property
  structural rather than procedural — decide at kickoff · **a real two-session
  concurrency test** modelled on `test_auth.py:131`, not two sequential calls on one
  session (see CR189-10 in W11).

## W7 — Floors that can actually fail *(Do now — Medium, safety-adjacent)*

**Findings:** CC188-04, CC188-05, CC188-06, CC188-07, CC188-11, CI191-04 (Medium) ·
CC188-14, CC188-18 (Low, **fold**)
**Source:** [Batch 188](BATCH_188_COACH_CONVERSATION_REVIEW.md#cc188-04) ·
[Batch 191](BATCH_191_COACHING_INTEGRITY_REFRESH.md#ci191-04)
**Model:** Opus 5 — the guard *is* the product here; a plausible-looking regex that
still fails open is the exact failure mode.

The floors audit is the mechanism that stops the most safety-critical rule in the
system from silently regressing. It currently does not work:

- **CC188-04:** `missing_floors("On a Red day, VO2 intervals are absolutely fine.",
  ("never_vo2_on_red",))` returns `()` — **verified by execution**. The audit passes
  an exactly inverted rule, because the pattern matches topic adjacency, not the
  prohibition. Same for `no_skipped_as_live` against "Do not say skipped."
- **CC188-05:** the audit is closed-world — it asserts a hand-written dict equals
  itself. A new user-facing prompt is never forced in, and the pattern has repeated
  five times (walk, strength, flexibility, reviews, trends).
- **CC188-07:** `local_clock_times` is registered, stated to Mark verbatim, and
  audited against **zero** prompts — it is reported missing from all eight, because
  the morning read enforces it with wording ("local clock time") the pattern cannot
  see.
- **CC188-06:** the app-state block asserts *"this block is the current truth"* and
  *"a direction stated here is evidence"* — contradicting the Batch 181 floor in the
  same prompt. Which instruction wins is undetermined and untested.
- **CI191-04:** none of the five deterministic protections built by the F1–F4
  remediation (`trainingLoadCap`, `sleepCreditCeiling`, `cumulativeEscalation`,
  `readinessBaselineTrend`, `chronicAction`) is in `FLOORS`. Deleting them would not
  fail CI, and the chat inherits none of them — on the first day the load cap ever
  fired, the chat called it *"probably more conservative than the situation actually
  requires"*, a sentence the morning read is forbidden to write.
- **CC188-11:** `verdictImpact: "none"` is a literal the test asserts is *present*,
  not a property anything verifies. True today by construction; the exact string a
  reviewer would grep to confirm the boundary.
- **CC188-14 / CC188-18** fold in: version and stamp `conversation_learning` (the
  only unversioned LLM prompt, and the only one writing into persistent memory), and
  record in `coach_policy.py`'s docstring *why* the deterministic template surfaces
  are out of scope.

- **Scope:** require the prohibition inside the same clause as the subject, and add
  a **negative control per floor** — an inverted sentence must be reported missing;
  discover prompt surfaces by enumerating modules that call `generate_anthropic_text`
  rather than listing them, with a commented opt-out list; widen the
  `local_clock_times` pattern and add it to the three entries that own it; restate
  the two `chat_context` strings in record vocabulary; promote the five
  deterministic sub-verdicts to `FLOORS` with the narrow rule *explain a
  deterministic ceiling, never argue it down*; replace the declaration assertions
  with a shared helper proving no plan/verdict row was written.
- **Size / migration / tests:** M · no migration · prompt-version bumps required.

## W8 — Contrast and touch where they render *(Do now — Medium)*

**Findings:** UX192-05, UX192-08 (Medium)
**Source:** [Batch 192](BATCH_192_UX_LIVE_APP_REVIEW.md#ux192-05)
**Model:** Sonnet 5 — clear frontend patterns; the token swaps alone are
Haiku-4.5-tier if split out.

**This is `UX156-03` still open after Batch 163, the batch that was meant to close
it.** 75 light-mode text nodes fail AA across 13 of 15 routes — including the
**active bottom-tab label at 3.55:1**, the Home workout-type chips, and the sleep
table's own "below the healthy range for your age" warning. Dark mode is clean on
all 15.

Batch 163 shipped the *right* tokens (`--primary-text: #047857` etc., all passing).
They are simply not used at these sites, which still reference the decorative fill
tokens. And `lib/semanticTextContrast.test.ts` stays green because it reads nine
tokens out of a CSS file and **never renders a page**.

UX192-08 folds in the same shape at the touch layer: seven controls sit under the
app's own declared 44 px floor, including the **16 px feel-score slider** — the one
interaction Mark performs every single day — and the 16 px back link. Batch 163
raised buttons; links, switches, range and text inputs were outside that scope.

- **Scope:** replace decorative-fill tokens used as text at the 75 measured sites,
  starting with the tab bar, Home chips and sleep table; fix `--text-muted` on
  `--surface-elevated` (4.35:1) or stop pairing them; extend the 44 px floor to the
  slider, inline nav links, switches and form inputs.
- **Size / migration / tests:** M · no migration · **a rendered-DOM contrast
  assertion over a representative page set in both themes**, and a rendered
  hit-area assertion across the primary daily path — per-property, not per-component,
  because scope-shaped tests are what let this through the first time.

## W9 — Verdict-ladder residuals *(Do now — Medium)*

**Findings:** CI191-05, CI191-06, CI191-07 (Medium)
**Source:** [Batch 191](BATCH_191_COACHING_INTEGRITY_REFRESH.md#ci191-05)
**Model:** Opus 5 — verdict core. The only-harden rule applies.

Three residuals left by Batches 167/170, all in the same ladder:

- **CI191-06:** Batch 170 stopped the age credit carrying a night across the
  **Green** line. Nothing tests the **Red** line. A raw 53/POOR night earns the full
  +12, lands at 65, and with clean corroboration can resolve Green — a
  full-intensity day off a night the device called poor. Latent today only because
  Mark's readiness centre (50) sits below the anchor; 07-23 already lifted a night
  out of Red into Amber this way.
- **CI191-07 (load half):** between "load present" and "load high" there is a band
  where load can only *relax*. Readiness LOW + clean recovery + ACWR 1.20 reads
  `load_driven` → Green; the cap only bites at ACWR ≥1.5. F2's original instance is
  closed only above the threshold. *(The rail half of this finding is closed by W5's
  CC188-02 fix.)*
- **CI191-05:** a 115% VO2 interval eases to 98% FTP — so an Amber day turns a VO2
  session into threshold intervals at 98% for 75% of the duration. HIT is genuinely
  removed and the duration cut is real, but 4×4 at 98% is still a quality session on
  a day the engine judged compromised, and the generic wording says *"remove HIT/VO2
  work"*, which reads as "the hard session is off".

- **Scope:** apply the `crossedGreenThreshold` treatment to the Red line; make the
  `load_driven` escape symmetric with the cap (require load to be genuinely benign,
  e.g. ACWR ≤ 1.3, not merely present); consider whether an Amber set *by the load
  cap* should ease differently from one set by recovery, and align the
  plan-adjustment wording with what the transform actually produces.
- **Size / migration / tests:** M · no migration · the combined-matrix pattern Batch
  170 used, proving every changed outcome is equally or more cautious.

## W10 — Chat context tells the truth about itself *(Do now — Medium)*

**Findings:** CC188-03, CC188-09, CC188-12 (Medium) · CC188-13, CC188-15,
CC188-16, CI191-08 (Low, **fold**)
**Source:** [Batch 188](BATCH_188_COACH_CONVERSATION_REVIEW.md#cc188-03)
**Model:** Sonnet 5 — well-scoped against a clear spec.

- **CC188-09** is the substantial one: all eight read packets store `prompt.system`
  = the module's full `SYSTEM_PROMPT` **verbatim** (morning: 11,254 characters),
  and the generation call passes the same prompt separately — so every morning
  generation pays for ~2.8k duplicated tokens. Worse for integrity, an anchored chat
  turn receives the morning read's *entire instruction set* in user-prompt position,
  labelled as Mark's information, with nothing saying those are a record rather than
  instructions to follow.
- **CC188-03:** `subjectDateWorkoutsClosedSinceRead` filters on **current status
  alone** with no timestamp comparison, so a post-workout read reports the very ride
  it is about as a change since itself.
- **CC188-12:** the propose button is attached on **question keywords alone** — the
  model's answer is never consulted, and the list includes `"harder"`. "Am I strong
  enough to go harder next block?" attaches *"Propose this adjustment"* to today's
  ride; "can we knock twenty minutes off tonight?" gets no button.
- **CC188-13/15/16** fold in: anchor the activity delta on ingest time rather than
  ride time; name field truncations in `omittedForLength`; document the char budget
  as best-effort and log when the trim exits above it.
- **CI191-08** folds in: extend the effective weight/VO2max resolution to the
  morning packet, so a metrics question is answered from the app's own dated figures
  (a live weight on 59 of the last 67 days, VO2max on 30) rather than from numbers
  Mark supplies in the chat.

- **Scope:** stop storing `prompt.system`, keep `prompt.version` (which is what
  currentness actually keys on) and a hash if forensics wants it; timestamp the
  closure comparison or rename the field honestly; require both a keyword *and* a
  structured marker from the model before attaching the propose affordance.
- **Size / migration / tests:** M · no migration · `PlannedWorkout` has no
  status-change timestamp, so CC188-03's honest minimum is the rename — adding one
  is a migration, decide at kickoff.

## W11 — Correctness cleanup *(Do now — Medium)*

**Findings:** CR189-05, CR189-08, CR189-10 (Medium) · CR189-14, CR189-15,
CR189-17, CR189-18, CR189-19 (Low)
**Source:** [Batch 189](BATCH_189_CODE_REVIEW.md#cr189-05)
**Model:** Sonnet 5 — independent small backend fixes; can ship as one batch or
split into three.

- **CR189-05:** two definitions of "VO2 today" — the morning read matches the
  workout *type name*, the safety layer matches *intensity* (≥106% FTP). A
  `bike_threshold` session manually overridden to 115% makes the read say
  `hasVo2WorkoutToday: false` on a Red morning, so the narrative never mentions VO2 —
  and then `blocks_red_vo2` refuses the push, with nothing connecting the two for
  Mark.
- **CR189-08:** Batch 180's coverage guard reaches three call sites; five more
  consumers read the same columns raw, feeding partial rows into rolling baselines
  and weekly averages. Not a verdict risk — but the current split is the state that
  drifts.
- **CR189-10:** every idempotency test calls the service twice **on one session**,
  which passes identically whether the advisory lock exists or not. The project
  already has the real pattern at `test_auth.py:131`.
- **Low folds:** `safetyRulesApplied` lists a rule that was not applied; a
  prompt-version bump mid-Sunday yields two review turns (dedupe on the week, not
  the row); the failure turn dedupes on exact string equality, so a copy edit breaks
  it; push dedupe is a read-then-write; `_activity_local_date` now exists in **four**
  files, so a timezone fix has four places to land.

- **Size / migration / tests:** M · no migration · compute `has_vo2` from the IR
  where one is buildable, falling back to the type name — the pattern
  `_verdict_adjustment_packet` already uses.

## W12 — Security hygiene *(Do now — Medium, after user-facing work)*

**Findings:** DS190-07, CR189-11 (Medium) · DS190-08, DS190-09, CR189-13 (Low)
**Source:** [Batch 190](BATCH_190_DATA_SECURITY_OPS_REVIEW.md#ds190-07) ·
[Batch 189](BATCH_189_CODE_REVIEW.md#cr189-11)
**Model:** Sonnet 5 — posture work with no live exploit.

- **DS190-07:** egress has no budget control, and the 5.5 GB organisation-wide cap
  was already blown on 2026-08-04. Capture the provider usage meter daily, alert at
  staged thresholds, document only the scoped dump command.
- **CR189-11:** the RLS guard test reads each migration's `RLS_TABLES` tuple and
  **never inspects the `upgrade()` body**. A migration declaring a table but omitting
  `ENABLE ROW LEVEL SECURITY` passes the suite — the exact gap the docstring says it
  prevents. Worth keeping (it catches the forgotten table); it just is not evidence
  RLS is on. Add a `pg_class.relrowsecurity` assertion after `alembic upgrade head`.
- **Lows:** return the same 404 for absent and foreign anchors (the 403/404 split
  confirms a read exists); add `BriefMessage.user_id` to the inline-history query
  rather than relying on a write invariant; add the missing `Analysis.user_id`
  predicate to `_sources`, which its sibling join already carries.

## W13 — The day's record means one thing *(Decision-gated High)*

**Findings:** CI191-02 (High)
**Source:** [Batch 191](BATCH_191_COACHING_INTEGRITY_REFRESH.md#ci191-02)
**Model:** Opus 5 — a data-model decision with consequences for every retrospective
consumer.

`daily_metrics` is **one mutable row per day**, overwritten by the evening sync
(`recorded_at_utc` 19:00–21:30 on 12 of 14 days checked) while the verdict is
computed at wake. The packet's readiness exceeds the surviving row on 11 of 18
mornings and its recovery clock is lower on 12 of 18. Every retrospective consumer
reads the evening value. Three consequences compound: Batch 182's
`expected_training_debt` exclusion tests against a clock that day's training
inflated (so the harder Mark trains, the likelier his Red is excused); the personal
baselines the floors key off are built from evening readings while the daily
comparison uses a morning one — an apples-to-oranges bias toward a *lower* floor,
which is why Batch 168's anchor binds on 12/12 mornings; and a stored verdict is
mutable (2026-07-05 reads `Amber@07:23 → Green@22:03`, and the later row is the one
counted).

**Why decision-gated:** this is the largest single item in the wave, it needs a
migration, and the fix has at least two viable shapes — an as-of column preserving
the morning observation, or repointing retrospective consumers at the stored morning
packet, which already holds the figures. It also partially overlaps W2 and W9: the
Red qualification and the readiness baseline should at minimum agree with each other
about which time of day they mean. Worth deciding *after* W2 lands, because W2 may
change how much of this still bites.

---

## Deferred / accept-and-close

- **DS190-05 (Medium) — RLS does not constrain the app owner.** 28/28 tables have
  RLS, none has `FORCE RLS`, and FastAPI connects as the owning role. This is the
  same call wave 1 deferred as DS154-06's second half. RLS here protects against
  PostgREST/client-role exposure, not application authorization defects — which is
  the correct reading of what it is for. **Revisit trigger:** a genuine second user,
  or any move to a least-privilege application login.
- **DS190-06 (Medium) — shared public app in the blast radius.** No live
  cross-schema object or grant reaches `coach`; the residual is shared ownership,
  quota and maintenance with a co-resident 27-table public app. Moving `coach` to
  its own Supabase project (preferably its own organisation) is real work with a
  rehearsed cutover. **Do now, separately and cheaply:** route that app's advisor
  WARNs to its owner.
- **UX192-07 (Medium) — two conversations on one page.** Genuinely confusing —
  `/brief` shows "Ask about this read" beside a launcher headed "Ask about this
  morning's brief", membership is one-way, and a launcher question asked while
  standing on `/brief` can never appear in that brief's inline chat. But the fix is
  a **product decision** (anchor launcher questions to the current route, or state
  the relationship and link to the full thread), not a defect with one right answer.
  **Needs Craig/Mark input before it can be specced.**
- **UX192-09 (Low) — cold time-to-content.** `/api/v1/daily-loop` is 5.4 s and
  275 KB, dominating a 7.4 s median cold load. Batch 62 already persists the query
  to `localStorage`, so this affects first open after a cache bust or install, not
  every launch. **Revisit trigger:** Mark reports slowness, or the payload grows.
- **CR189-12 (Low) — advisory lock held across a 60-second model call.** Recorded
  as a known cost, not a defect. It is the correct trade at one user. **Revisit
  trigger:** connection-pool pressure on the Supabase pooler.

## Coverage check (all 67 mapped)

- **High (12):** UX192-01/02/03 → W1 · CR189-01 → W1 · CI191-01 → W2 ·
  CR189-02 → W3 · DS190-01/02 → W3 · DS190-03 → W4 · CC188-01/02 → W5 ·
  CI191-02 → W13
- **Medium (33):** CC188-03 → W10 · CC188-04/05/06/07 → W7 · CC188-08 → W5 ·
  CC188-09 → W10 · CC188-10 → W5 · CC188-11 → W7 · CC188-12 → W10 ·
  CR189-03/04 → W6 · CR189-05 → W11 · CR189-06 → W0 · CR189-07 → W6 ·
  CR189-08 → W11 · CR189-09 → W5 · CR189-10 → W11 · CR189-11 → W12 ·
  DS190-04 → W3 · DS190-05/06 → Defer · DS190-07 → W12 · CI191-03 → W2 ·
  CI191-04 → W7 · CI191-05/06/07 → W9 · UX192-04/06 → W1 · UX192-05/08 → W8 ·
  UX192-07 → Defer
- **Low (22):** CC188-13 → W10 · CC188-14 → W7 · CC188-15/16 → W10 ·
  CC188-17 → W6 · CC188-18 → W7 · CC188-19 → W6 · CC188-20 → W5 ·
  CR189-12 → Defer · CR189-13 → W12 · CR189-14/15 → W11 · CR189-16 → W6 ·
  CR189-17/18/19 → W11 · CR189-20 → W3 · DS190-08/09 → W12 · CI191-08 → W10 ·
  UX192-09 → Defer · UX192-10 → W1 (verification gate)
- **Batch 191's Mark scorecard:** communication artifact — no work item.

## Zero-code decisions for Craig

These need a call and no implementation, and two of them expire this week:

1. **The 08-08/08-09 chronic deload proposals** are standing in production with
   their evidence withdrawn (CI191-03). Retract or let them ride — Saturday and
   Sunday.
2. **DS190-01's shape** — make the API genuinely always-on, or externalise every
   scheduled job. A hosting-cost decision that gates half of W3.
3. **W13's shape** — as-of column versus repointing consumers at the stored morning
   packet. Best decided after W2 lands.
4. **UX192-07** — is the launcher one app-wide conversation, or is it the current
   read's conversation when a read is on screen?

## How to execute (per the batch workflow)

1. Approve or adjust this ordering.
2. Per slot, at start: run `/batch-start`, which allocates the ledger batch number
   and any DECISIONS number, authors the spec into
   [`docs/phase-batches.md`](../phase-batches.md), and opens a `fix/`/`chore/`
   branch. Numbers are **not** taken here, to avoid concurrent-session collisions.
3. Build → `/batch-verify` → `/closeout` as normal.
4. **W1 is the recommended first kickoff** — the only slot broken in production, and
   the Sunday 09 Aug weekly review lands on it. W0 is a query that can run alongside.
   W2/W3/W4 are the remaining live-consequence Highs; W5–W12 follow; W13 and the
   deferred items sit until their trigger.

**One gotcha to carry into every slot in this wave.** Three separate findings here
(UX192-01, UX192-05, CR189-11) shipped past green tests because the assertion never
touched the thing it claimed to protect — a class string instead of a computed
style, a token in a CSS file instead of a rendered node, a declared tuple instead of
the SQL that ran. Where a slot's acceptance criterion is a *property*, assert the
property.
