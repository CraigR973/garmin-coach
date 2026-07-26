# Batch 153–156 remediation roadmap

**Date:** 2026-07-26
**Author:** triage pass over the four diagnose-only reviews (153 code, 154
data/security, 155 Mark scorecard, 156 UX/live-app)
**Status:** proposal for Craig's approval — no code changed, no ledger row added,
no batch/DECISIONS numbers allocated

## Purpose

The audit wave produced **21 findings (4 High, 14 Medium, 3 Low)** with
review-local IDs (`CR153-*`, `DS154-*`, `UX156-*`) and remediation *stubs*, but
no ordering and no allocated work. This doc converts them into a sequenced set of
**proposed** batches, one disposition per finding, so the roadmap can be approved
before any code starts. [Batch 155](BATCH_155_MARK_SCORECARD.md) is a Mark-facing
communication artifact (grade B+) with no findings — nothing to action.

**Numbering discipline:** the `R1…R9` labels below are roadmap-local sequence
slots, **not** ledger batch numbers. Real batch numbers and DECISIONS numbers get
assigned when each one is kicked off via `/batch-start` (pre-assigning has
collided with concurrent sessions before). Each slot's spec is authored per-batch
at kickoff; the row lands in [`docs/phase-batches.md`](../phase-batches.md) then.

## Disposition legend

- **Do now** — schedule as a batch in the order shown.
- **Fold** — ships inside a parent slot (same files/surface), not its own batch.
- **Decision-gated** — ready, but Craig decides *whether/when* to trigger.
- **Defer** — real but low value at current 1–2-user scale; revisit on a trigger.

## Model guidance

Each slot names a suggested **coding-agent model** — which Claude model to run the
implementation session on, tiered by reasoning difficulty. (This is the model that
*writes* the batch; it's separate from the app's runtime coaching model, which
stays Sonnet 4.6 per the Anthropic-API decision.)

- **Opus 5** *(flagship; the Opus 4.8 in use is equivalent-tier)* — subtle
  correctness, security-critical, distributed-concurrency, or multi-file design
  work where a wrong-but-plausible change is costly.
- **Sonnet 5** — well-scoped implementation against a clear pattern or spec.
- **Haiku 4.5** — mechanical, low-ambiguity edits (dependency bumps, token/value
  swaps, config).

Starting points, not rules: drop a tier when the spec is tight and the pattern is
obvious, bump one when a slot proves subtler than expected.

## At a glance (proposed order)

| Slot | Proposed batch | Findings | Max sev | Model | Size | Migration | Why here |
|---|---|---|---|---|---|---|---|
| **R1** | Coach-memory public contract | UX156-01 | 🔴 High | Sonnet 5 | S | No | **Only finding broken in prod right now**; blocks the shipped learning proposal-review surface |
| **R2** | Delivery-rail atomicity & observability | CR153-01, CR153-08 | 🔴 High | Opus 5 | M | No | Coaching-safety adjacent — wrong workout can land on Zwift; silent skips invisible |
| **R3** | Completed-session reads (non-ride + states) | CR153-02 | 🔴 High | Opus 5 | M | Unlikely | Shipped surface says "no read" when a strength/flex/walk read exists |
| **R4** | Auth Phase 3 | DS154-01 | 🔴 High | Opus 5 | L + destructive | Yes | Closes the oldest open High + a secret-log violation; runbook already exists |
| **R5** | Concurrency, idempotency & workload budgets | UX156-02, CR153-04, DS154-05 | 🟠 Med | Opus 5 | M | Maybe | One lease/idempotency design fixes three symptoms |
| **R6** | Learning-memory integrity | DS154-02, DS154-07 | 🟠 Med | Opus 5 | M | Unlikely | Protect the flagship learning feature's narrative safety + close the test gap |
| **R7** | Mobile a11y & responsive | UX156-03, UX156-04, UX156-05, UX156-06 | 🟠 Med | Sonnet 5 | M | No | Shared-system fix; high real value for Mark (contrast, touch, readability) |
| **R8** | Security / ops hygiene | DS154-03, DS154-04, DS154-06 | 🟠 Med | Sonnet 5 | M | Partial | Posture hardening, no live exploit — sequence after user-facing work |
| **R9** | Small correctness cleanup | CR153-03, CR153-05, CR153-07 | 🟠 Med | Sonnet 5 | S–M | Maybe | Independent small backend fixes; can ship as one batch or split |
| — | **Defer** | CR153-06 | 🟠 Med | Sonnet 5 | — | — | N+1 tolerable at current volume; revisit if scheduler latency grows |

---

## R1 — Coach-memory public contract *(Do now — first)*

**Findings:** UX156-01 (High)
**Source:** [Batch 156](BATCH_156_UX_LIVE_APP_REVIEW.md#ux156-01)
**Model:** Sonnet 5 — a clear three-layer contract/DTO fix; bump to Opus 5 only if
you want extra caution on the shared closed enum that other pages also consume.

The one thing actually broken in production. `GET /api/v1/coach-memory` returns a
KB row with `section="holiday_windows"` (and `generated_block` also exists
internally); the closed client enum `knowledgeBaseSectionSchema` rejects it, so
`coachingStateEnvelopeSchema.parse` fails and the page renders the raw Zod issue
array on Mark's phone. The whole Coach-memory route — **including the Batch
150/151 proposal-review surface** — is unreachable.

- **Scope:** define an explicit public Coach-memory DTO; filter internal sections
  server-side (or intentionally add + render them); replace raw error text with
  user-safe copy + retry. Keep any admin editor contract separate.
- **Size / migration / tests:** S · no migration · backend+shared+frontend
  contract tests incl. a production-shaped row set that proves one unexpected row
  can't blank the page.
- **First action at kickoff:** reproduce against prod data (still live — the
  review was diagnose-only) before touching the contract.

## R2 — Delivery-rail atomicity & observability *(Do now)*

**Findings:** CR153-01 (High) · CR153-08 (Low, **fold**)
**Source:** [Batch 153](BATCH_153_CODE_REVIEW.md#cr153-01)
**Model:** Opus 5 — subtle transaction/commit-boundary correctness plus
reconciliation-retry reasoning; top tier is warranted for a safety-adjacent rail.

CR153-01: on an intervals.icu failure, `replace_event` calls `session.commit()`
even when the caller passed `commit=False`, persisting the new
pointer/version while Zwift still holds the old workout — then pointer/version
equality makes reconciliation decide there's nothing to retry. Mark could approve
one interval structure and receive another. Same pre-repoint pattern exists in
`_resync_event`, so it's a delivery-rail issue, not interval-editor-only.

CR153-08 folds in: `_deliver_one` swallows an `HTTPException` and returns `None`,
indistinguishable from an intentional no-op — no audit row, alert, or structured
log. Same files, same "delivery failure that isn't surfaced" theme.

- **Scope:** make `commit=False` never commit the surrounding unit of work;
  persist the pointer/version only after the cloud write succeeds (or restore on
  failure); stop treating pointer/version alone as proof cloud content is current;
  distinguish malformed-bike-data skips from intentional no-ops with a durable
  signal.
- **Size / migration / tests:** M · no migration · **DB-backed** full-service
  test for failure → persisted state → successful retry, across interval-edit and
  generic resync; malformed-IR / missing-FTP / intentional-no-op tested
  separately.

## R3 — Completed-session reads: non-ride + states *(Do now)*

**Findings:** CR153-02 (High)
**Source:** [Batch 153](BATCH_153_CODE_REVIEW.md#cr153-02)
**Model:** Opus 5 for the shared-seam refactor across four categories plus the
state contract; a strong Sonnet 5 is viable if the spec is tight.

Batch 152 promised the completed-Week read works for strength/flexibility/walk
and renders distinct absent / generating / failed states. But only
`PostWorkoutAnalysisService` writes `planned_workout_id`; the strength/flex/walk
generators never link it, so their completed reads can't be returned — the UI
says "no read" when one exists — and there's no generation-state source, so
absent/in-flight/failed all collapse to one state.

- **Scope:** move planned-workout completion/linking to a shared post-activity
  seam for all categories; constrain the read selector to supported post-session
  analysis types + verify caller ownership; add a reliable generating/failed state
  (reuse `brief_generation_status` if it fits rather than a new table).
- **Size / migration / tests:** M · likely no migration (existing
  `planned_workout_id` column; reuse status table) · positive+negative DB tests
  for every post-* type, no-read, generating, failed, foreign-user; frontend state
  tests.
- **Coupling note:** while you're inside the post-* services here, consider
  pulling **CR153-05** (R9) forward — same three files.

## R4 — Auth Phase 3 *(Decision-gated High)*

**Findings:** DS154-01 (High)
**Source:** [Batch 154](BATCH_154_DATA_SECURITY_REVIEW.md#ds154-01) · runbook:
[auth-simplification-plan.md](auth-simplification-plan.md)
**Model:** Opus 5 — destructive, security-critical auth surgery; highest stakes
even with a runbook in hand.

The legacy name + 4-digit-PIN fallback still has **no durable lockout** (the
schema fields exist but login never reads/writes them; only an in-memory SlowAPI
bucket guards it) and `POST /pin/reset-request` **logs the live reset bearer JWT
at INFO** — a confirmed secret-log + account-takeover path. This is the
long-standing P1-1/P3-3 from [v1-v2-review.md](v1-v2-review.md); the accepted plan
was always to delete this machinery in Auth Phase 3, not polish it.

- **Why decision-gated:** not new, and mitigated (private deployment + rate
  limiter). The call is *whether to trigger Phase 3 now* vs keep deferring. If
  deferring, at minimum stop logging the reset JWT.
- **Scope:** Phase 3 removes PIN/JWT/reset/change endpoints + helpers, revokes
  PIN-era tokens; Phase 4 drops `pin_hash`/`failed_login_count`/`locked_until` and
  the two JWT secrets. Runbook is written.
- **Size / migration / tests:** L + destructive · yes (Phase 4 column/secret
  drops) · replace PIN auth tests with device-token activate/verify/revoke; prove
  PIN routes unavailable in prod mode and no bearer reaches logs.

## R5 — Concurrency, idempotency & workload budgets *(Do now — Medium)*

**Findings:** UX156-02, CR153-04, DS154-05
**Source:** [156](BATCH_156_UX_LIVE_APP_REVIEW.md#ux156-02) ·
[153](BATCH_153_CODE_REVIEW.md#cr153-04) ·
[154](BATCH_154_DATA_SECURITY_REVIEW.md#ds154-05)
**Model:** Opus 5 — distributed-concurrency reasoning (atomic compare-and-set,
leases, idempotency identity without breaking Decision #219's history).

Three symptoms of one gap — a supposedly-bounded operation runs twice/unbounded:

- **UX156-02:** activation exchange reads `used_at IS NULL` then updates
  non-atomically → a code redeemed twice; the review saw **two device rows per
  activation** and orphan long-lived credentials.
- **CR153-04:** rapid manual-entry PUTs / two tabs make two paid Anthropic calls
  and two "current" analysis rows — no lease/idempotency identity (a blunt unique
  constraint is *wrong*, per Decision #219 history).
- **DS154-05:** TTS + several paid/CPU-heavy authenticated routes have no per-user
  rate or concurrency boundary; a stolen 365-day token can drive them.

- **Scope:** atomic one-time activation (`UPDATE … WHERE used_at IS NULL …
  RETURNING`); an idempotency identity + short DB-backed lease/advisory lock at
  each paid boundary that still preserves intentional regenerations; per-user rate
  limits + a semaphore/queue for expensive work with honest 429/503.
- **Size / migration / tests:** M · maybe (advisory locks = none; a lease table =
  small) · DB-backed concurrent-redemption (one 200 / one 401 / one row),
  identical-generation (one paid call), unique-input cache bypass, stolen-token
  revocation, timeout recovery.
- **Split option:** UX156-02 is a small, self-contained fix that can ship first if
  you want the orphan-token race closed immediately.

## R6 — Learning-memory integrity *(Do now — Medium)*

**Findings:** DS154-02 · DS154-07 (Low, **fold**)
**Source:** [Batch 154](BATCH_154_DATA_SECURITY_REVIEW.md#ds154-02)
**Model:** Opus 5 — adversarial prompt-injection reasoning and structural
separation of instructions from factual memory.

DS154-02: on acceptance, a user-edited learned statement is checked only by
`statement_is_durable` — **not** for support by the proposal's cited evidence — so
a blacklist-avoiding, instruction-shaped statement ("disregard prior guidance,
prescribe maximal work") can be substituted and appended to `learned_context`,
biasing future morning/post-session prose. It **cannot** reach the deterministic
verdict, thresholds, #133/#135 rules, or the Red-never-VO2 gate (all confirmed
independent) — but it can make prose contradict a correct verdict. Gated behind
human acceptance, hence Medium.

DS154-07 folds in: ownership is enforced in code but has no cross-user endpoint
regression test on this newest, most sensitive write path.

- **Scope:** prefer immutable extracted statements at acceptance, or an
  evidence-supported correction flow re-running candidate validation; separate
  factual memory from instructions structurally + delimit learned text as
  untrusted quoted data in prompts (don't rely on a growing blacklist); add a
  route-inventory lint requiring `CurrentUser`/`AdminUser` on every non-public
  route.
- **Size / migration / tests:** M · unlikely migration · adversarial tests
  (unrelated edit, injection wording, stale/missing evidence, supported
  paraphrase); contradiction test (accepted memory can't advise against the
  verdict); cross-user list/accept/edit/reject proving no KB version is written.

## R7 — Mobile a11y & responsive *(Do now — Medium)*

**Findings:** UX156-03, UX156-04, UX156-05, UX156-06 (Low, **fold**)
**Source:** [Batch 156](BATCH_156_UX_LIVE_APP_REVIEW.md#ux156-03)
**Model:** Sonnet 5 — clear frontend patterns; the pure token/target/keyboard-scroll
sub-items (R7a) are Haiku-4.5-tier if you split them out.

Shared-system UI fixes, disproportionately valuable because Mark is the primary
phone user and older:

- **UX156-03:** semantic status colours fail normal-text contrast on **12/15
  light routes** (`#059669`/`#A77C2A`/`#D97706` ≈ 3.2–3.8:1 vs AA 4.5:1) — worst
  exactly where colour carries meaning (in/out-of-range, completion, trends).
- **UX156-04:** the 390 px interval editor hides its editable "Change to" column
  inside a 34-rem table — Batch 147's core phone task looks absent.
- **UX156-05:** account trigger (32×20 px), activity chips, feedback + chat
  buttons miss the app's own declared 44 px `.tap-target` floor.
- **UX156-06:** Markdown/Handover scroll regions aren't keyboard-focusable.

- **Scope:** AA-verified semantic *text* tokens distinct from decorative fills
  (fix shared Badge first); stacked/2-row interval rows below the small
  breakpoint; enforce 44 px hit areas via a mobile-safe primitive; `tabIndex` +
  label + focus style on overflowing scroll containers.
- **Size / migration / tests:** M · no migration · automated contrast coverage per
  badge variant + representative rows in both themes; 390 px DOM-size + reach-every-
  field interaction tests; keyboard-scroll tests.
- **Split option:** R7a = cross-app primitives (UX156-03/05/06); R7b = interval-
  editor layout (UX156-04, co-locate with any future Batch-147 work).

## R8 — Security / ops hygiene *(Do now — Medium)*

**Findings:** DS154-03, DS154-04, DS154-06
**Source:** [Batch 154](BATCH_154_DATA_SECURITY_REVIEW.md#ds154-03)
**Model:** Sonnet 5 base — Haiku 4.5 for the dependency/CI/permissions bumps;
bump to Opus 5 if you take on the React Router 7 migration or the RLS role change.

Posture hardening — no confirmed live exploit today, so it sequences after
user-facing work:

- **DS154-03:** committed JS lockfile has 1 High (`postcss`) + 3 Moderate
  (`react-router*`) advisories; CI audits only Python; Python runtime isn't pinned
  reproducibly. None currently reachable, but the localStorage 365-day token makes
  a future XSS costly.
- **DS154-04:** Garmin/Hive bootstrap scripts print bearer blobs by default /
  write without `0600`; the daily `pg_dump` writes unbounded plaintext with no
  `--schema=coach` filter (shared Supabase!) or retention.
- **DS154-06:** RLS is a Data-API backstop only (FastAPI connects as `postgres`
  owner, bypasses RLS by design); legacy policies are under-specified; invariants
  can drift silently.
- **Size / migration / tests:** M · partial — PostCSS bump + CI JS audit + hashed
  Python lock (no DB); script/backup perms; **DS154-06 splits**: the cheap
  read-only CI drift-check (fail if a `coach` table loses RLS / roles gain grants)
  is worth doing now, but moving FastAPI to a least-privilege role + `FORCE RLS` is
  a larger architectural decision — **likely defer** that half.
- **Note:** the React Router 7 migration inside DS154-03 is the biggest sub-item
  and can be split to its own batch.

## R9 — Small correctness cleanup *(Do now — Medium)*

**Findings:** CR153-03, CR153-05, CR153-07
**Source:** [Batch 153](BATCH_153_CODE_REVIEW.md#cr153-03)
**Model:** Sonnet 5 — small, well-scoped fixes; the timezone-grouping fix on its
own is Haiku-4.5-tier.

Three independent small backend fixes — one batch, or split into three tiny PRs:

- **CR153-03:** user + assistant chat turns share an identical `created_utc` and
  queries order only by it → nondeterministic user/assistant order; and the
  universal prompt promises a confirmable adjustment that post-session reads
  deliberately withhold. Fix ordering (sequence value or composite order) + build
  the prompt from an explicit per-read capability flag.
- **CR153-05:** strength/flex/walk `_analysis_covers_activity_checkin` compares
  only the check-in timestamp, so a prompt-version bump is ignored for unchanged
  activities; handover returns latest-for-date before checking prompt version.
  (Pull forward into **R3** if convenient — same files.)
- **CR153-07:** Plan Week groups activities by `start_utc.date()` (UTC), not
  profile-local — during BST a 00:00–01:00 activity lands on the wrong day.
- **Size / migration / tests:** S–M · maybe (CR153-03 could add a `brief_messages`
  sequence column, or avoid it with a composite order — decide at kickoff) ·
  same-timestamp ordering test; old-prompt/changed-input tests for
  strength/flex/walk/handover; GMT+BST midnight-boundary grouping test.

---

## Deferred / accept-and-close

- **CR153-06 (Medium) — N+1 in learning + pending-read scans.** The review itself
  notes current volume keeps wall time tolerable; on a 1–2-user app the ~60 extra
  queries from one learning action aren't worth a batch now. **Revisit trigger:**
  scheduler latency becomes noticeable or the user count grows. If R5/R6 touch
  these scans, fold the bulk-fetch opportunistically. **Model when picked up:**
  Sonnet 5 (a bounded bulk-fetch refactor).
- **DS154-06 least-privilege-role half (Medium).** As above — do the cheap CI
  drift-check in R8; defer the `postgres` → dedicated-role + `FORCE RLS` migration
  as a standalone architectural decision unless a second unrelated user is
  onboarded.

## Coverage check (all 21 mapped)

- **High (4):** UX156-01 → R1 · CR153-01 → R2 · CR153-02 → R3 · DS154-01 → R4
- **Medium (14):** CR153-03/05/07 → R9 · CR153-04 → R5 · CR153-06 → Defer ·
  DS154-02 → R6 · DS154-03/04/06 → R8 · DS154-05 → R5 · UX156-02 → R5 ·
  UX156-03/04/05 → R7
- **Low (3):** CR153-08 → R2 (fold) · DS154-07 → R6 (fold) · UX156-06 → R7 (fold)
- **Batch 155:** communication artifact — no work item.

## How to execute (per the batch workflow)

1. Approve/adjust this ordering.
2. Per slot, at start: run `/batch-start`, which allocates the ledger batch
   number + any DECISIONS number, authors the spec into
   [`docs/phase-batches.md`](../phase-batches.md), and opens a `fix/`/`chore/`
   branch. Numbers are **not** taken here to avoid concurrent-session collisions.
3. Build → `/batch-verify` → `/closeout` (commit, CI, merge, tick docs, session
   log) as normal.
4. R1 is the recommended first kickoff (live-broken); R2–R4 are the remaining
   Highs; R5–R9 the Mediums; the two deferred items sit until their trigger.
