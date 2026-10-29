# Batch 319 — progress has a signal (for Craig's sign-off)

**Draft, not signed off.** The weekly review now reads his fitness only from rides at a
fixed power in ERG (his heart rate at the same watts, the last four weeks against the four
before), stops proposing an FTP from every ride, and adds one note when he looks ready for
more. Nothing changes his FTP or his plan. `apps/api/tests/test_batch_319_progress_signal.py`
holds the note to this file.

**Measured, read-only, on production (29 Oct):** at about 184 W in ERG, his heart rate
averaged 111 beats a minute in the four weeks to 28 Oct against 113 in the four before
("steady"; 7 and 8 rides). The note would not have appeared on any Sunday in October: each
run of three hard sessions had a cautious morning after at least one.

## 1. The note (319.3)

**Where:** the weekly review, word for word, only when his last three hard sessions each
landed at least nine in ten work intervals on target and the morning after each was not
cautious.

> Your last three hard sessions all landed on target, and you woke up fresh after each. You look ready for a little more: a ramp test, or one small step up in your next hard session. Nothing changes unless you choose it.

**Replaces:** nothing; nothing ever suggested more.

## 2. The fitness line (319.2)

**Where:** the weekly review, one sentence the model writes from the numbers, for example
"At about 184 W your heart rate is steady: 111 beats a minute these four weeks against 113
the four before."

**Replaces:** an FTP the review proposed from watts per heartbeat across every ride (295 W
on 29 Jun, 272 W on 31 Aug), which moved with the mix of sessions. Only the ramp test sets
his FTP.

## Questions for Craig

1. The note's numbers (three sessions in a row, nine in ten on target, a fresh next
   morning) are provisional. Keep them?
2. The ramp test currently counts as a hard session (it scores 0 on target, so it resets
   the run). Leave it out?
