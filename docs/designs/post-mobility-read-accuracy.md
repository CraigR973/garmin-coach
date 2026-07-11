# Batch 90 — Post-mobility read accuracy

Status: Implemented on `feat/batch-90-post-mobility-read`; not shipped. Decision #163.

## Problem

The post-mobility read could derive the wrong weekday, cite a template ride that
had been skipped for a holiday, and treat Mark's normal daily mobility habit as
extra training load. Its packet also referenced an unseeded `analysis_rules`
knowledge-base section and omitted the seeded training schedule.

## Kickoff decisions

- Supply `subjectWeekday` to every direct LLM read (morning, ride, walk,
  strength, mobility), and explicitly forbid deriving it from the date.
- Give the mobility reader a 14-day, data-driven planned-workout horizon plus
  overlapping holiday windows. Each workout is annotated with
  `insideHolidayWindow` and `isLive`; a skipped/holiday workout is never live.
- Model daily mobility in the packet and prompt over the existing observed
  consistency signal. Do not re-seed or reinterpret the cycling plan/weekly
  rhythm.
- Repair `analysisRules` systemically in ride/walk/strength/mobility packets by
  exposing the real `data_quality_rules` and `coaching_protocol` sections.

## Packet contract

The mobility packet adds `subjectWeekday`, `holidayContext`, `mobilityBaseline`,
the 14-day `plannedWorkouts` view, and `knowledgeBase.trainingSchedule`.
`mobilityBaseline` says the cadence is daily, the cycling weekly rhythm is not a
mobility budget, and the habit does not count as recovery load. The prompt keeps
the one next step within mobility and preserves `advisoryOnly` plus
`neverFeedsRecoveryDecision`.

## Boundaries

No migration, KB re-seed, verdict change, delivery write, or frontend/shared
contract change. Decisions #133 and #135 and Red-never-VO2 are untouched.

## Verification

Packet tests cover a known Saturday, an upcoming holiday containing a skipped
VO2 row, baseline-habit framing, the training schedule, non-empty rules, and the
advisory-only output rule. Sibling packet tests cover authoritative weekdays and
real rules. Full backend pytest, ruff, format, and mypy are required.
