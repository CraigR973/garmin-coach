# Batch 375 — Dumbbells B's "harder version" line: the words (for Craig's sign-off)

**Signed off by Craig on 2 Nov 2026** ("yes", relayed by the orchestrator session). Batch 368's week-7 dose line named A's moves for both
sessions, so Dumbbells B (shoulder press, reverse-grip row, floor press, pullover, curl,
triceps extension, step-up, dead bug) was told to raise his rear foot on a lunge it does not
have. `apps/api/tests/test_batch_375_dumbbells_b_harder_line.py` holds the app's line to
this file.

## 1. Week 7's Dumbbells B (3 × 8)

**Where:** Dumbbells B's description in the plan (Week, the session card, the watch), from
the next plan the app writes, and on Plan No. 3's Sat 5 Dec row. **Replaces** "the harder
version of each move you can (rear foot raised on the lunge, one leg on the deadlift); 2
reps in reserve" on B only. Dumbbells A keeps that line.

> the harder version of each move you can (one arm at a time on the presses and the row); 2 reps in reserve

"The presses" are the shoulder press and the floor press. Working one arm at a time keeps
his 5 and 10 kg dumbbells and makes each move harder by making his trunk hold him steady
(Decision #462 (7): progress by harder variants within his kit).

## 2. The other weeks

No other week's dose line names a move. Week 10's "the harder versions, lowering over 3
seconds" refers back to week 7's line, so on B it now means B's harder versions.

## 3. Plan No. 3's Sat 5 Dec row

After the merge, row `9c36855d` (Dumbbells B, Sat 5 Dec, v2) has the bracket in its step
target and its summary replaced with the line above: text only, in one `UPDATE`, rehearsed
first in a rolled-back transaction (2 Nov, 18:02 GMT: one row changed, date, version, status,
minutes and dose unchanged). Thu 3 Dec's Dumbbells A keeps its line. No session moves.
