# Batch 236–241 — full-app audit wave (wave #4)

**Opened 2026-09-01.** Scope, decisions and constraints agreed with Craig before
any pass ran. This is the fourth audit wave; the previous three were Batches
153–156, 188–192 and 211. Coaching integrity currently stands at **A−** (moved
from B+ at Batch 211).

## The six passes

| Batch | Pass | Lens | Deliverable |
|---|---|---|---|
| 236 | Code & architecture | Software engineering | `BATCH_236_CODE_REVIEW.md` |
| 237 | Data, security & ops | Software engineering | `BATCH_237_DATA_SECURITY_OPS_REVIEW.md` |
| 238 | AI / LLM engineering | AI engineering | `BATCH_238_AI_ENGINEERING_REVIEW.md` |
| 239 | Coaching integrity (4th refresh) | Cycling coaching | new section in `COACHING_INTEGRITY_AUDIT.md` |
| 240 | Health & sleep science | Health / sleep science | `BATCH_240_HEALTH_SCIENCE_REVIEW.md` |
| 241 | UX / live app + Mark scorecard | Product | `BATCH_241_UX_LIVE_APP_REVIEW.md`, `BATCH_241_MARK_SCORECARD.md` |

Synthesis afterwards into `BATCH_236-241_REMEDIATION_ROADMAP.md`, following the
Batch 188–192 roadmap's format: finding IDs, severity, disposition legend
(fix now / decision-gated / defer-with-trigger / accept-and-close), a coverage
check that every raw finding is mapped, and a "zero-code decisions for Craig"
section. Ledger rows are authored from the roadmap, not from the passes.

## Decisions taken at scoping

1. **All six passes**, not a subset.
2. **Production access approved**, read-only.
3. **Anthropic spend approved, ~$1–2.** Prefer free `count_tokens` and stored
   `analyses` rows over live generation wherever a stored row will answer it.
4. **Batches 236–241 reserved.** DECISIONS.md numbers are assigned at
   `/batch-start`, never when authoring a spec.
5. **Subagent fan-out**, one agent per pass.

## Live constraints at the time of the audit

- **Supabase egress cap is on until 2026-09-21** (the 2026-08-30 incident,
  34.784 GB against a 5 GB cap). Every production read must be
  column-projected and windowed. Do not `select *` over a history window, and
  never select a JSONB payload column you are not going to read — JSONB is
  stored TOAST-compressed and sent uncompressed (Batch 235).
- **The Anthropic spend cap reset at 2026-09-01 00:00 UTC.** Spend is available
  again but is a shared budget across all six passes.
- Production serves `2178381` (`docs: close out batch 233`) on Railway direct
  and Vercel same-origin; local `main` is at the same SHA.

## Guardrails

- **Read-only throughout.** No writes to Mark's data, no brief regeneration, no
  schema change, no code change. The passes produce findings; the roadmap
  produces rows; a later batch builds.
- **Settled decisions are not re-litigated.** If a pass disagrees with a
  `DECISIONS.md` entry, it appends a new one with the evidence rather than
  reopening the old.
- **Label evidence honestly** — `observed` / `proved` / `implemented`, the
  convention the coaching-integrity audit already uses. Nothing is stated more
  strongly than its evidence supports.
- **Verify deployed state by the SHA `/api/v1/health` serves**, never by what a
  local run produced (Decision #309).

## Pre-audit finding — logged before any pass, because it gates several

**The first production brief on Sonnet 5 is 43% of its predecessor's length and
is silently dropping whole sections that shipped batches deliberately added.**

Batch 233 merged with 233.8 — the prose comparison — explicitly **blocked, not
skipped**, and STATUS recorded that "whether a 3,806-character brief still
carries what Mark needs is a product judgement nobody has made". The 2026-09-01
brief is the first real one. It answers the question, and the answer is that the
shorter brief is **lossy**.

Measured from stored `coach.analyses` rows, same prompt version
(`morning-analysis-v40-2026-08-28`) on both sides:

| | 2026-08-31 (Sonnet 4.6) | 2026-09-01 (Sonnet 5) |
|---|---|---|
| `output_chars` | 8,482 | **3,646** |
| `output_tokens` | 2,305 | 1,360 |
| `thinking_tokens` | *(field absent)* | **0** |
| `input_tokens` | 20,102 | 29,118 |
| verdict | Green | Green |

Prior five 4.6 briefs ran 6,966–11,475 chars (mean ≈ 8,470), so 3,646 is not
day-to-day variation.

**What the 09-01 brief no longer contains:**

- **The entire `🔬 Experiment Updates` section.** All four running experiments
  are absent — REM intervention rotation, the collagen reintroduction gate, the
  04:00 waking pattern, and recovery-week sleep disruption. The experiment loop
  (`experiment_tracker` / `experiment_evaluation` / `experiment_loop`) still
  runs; Mark simply is not told any of it.
- **The `🔁 Chronic REM Pattern` section**, including its two carried actions
  (protect the final 90-minute cycle; hold the room cool into the back half of
  the night). A REM bullet survives; the actions do not.
- **Most of the sleep-stage detail.** 09-01 reports REM and deep only — no
  light, no awake, no restless. **Batch 230's denominator statement**, shipped
  to close a factual error, is reduced to a parenthetical `(deep+light+REM+awake)`
  rather than the explicit basis sentence 230 specified.
- **Respiration, SpO₂, VO₂max, Body Battery charged.**
- **The data-quality corrections acknowledgement** — the surface where the app
  admits its own prior errors to Mark.

**Two things to establish, not assume.** (1) `thinking_tokens: 0` on a run
configured `adaptive` / `medium`: adaptive genuinely lets the model decline to
think, so zero may be legitimate on an easy packet — but Batch 233 measured
5,280 output tokens *with* thinking at `medium` on the 08-31 packet, and 1,360 /
0 is much closer to the measured `low` profile (1,317, no thinking block). The
deployed SHA is correct and `morning_analysis.py:457-458` resolves both from
settings, so if this is a defect it is not in that wiring. (2) Whether the loss
is caused by the model, by `morning_analysis.py:229`'s *"Return concise markdown
with…"* holdover directive that 233.8 predicted Sonnet 5 would take literally,
or by both.

**Disposition:** seeded into Batch 238 (AI) as its first lead, and flagged to
239 and 240 because the dropped sections are coaching and health content, not
formatting. Severity is provisionally **High** — several shipped batches'
user-visible output regressed silently on a model swap, and nothing in the
system noticed.
