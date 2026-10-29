# Batch 319 — progress has a signal (for Craig's sign-off)

**Signed off by Craig on 29 Oct 2026** ("All as recommended"): the thresholds as drafted, and the ramp test left out of the run. Figures below are made up, so the repo carries none of Mark's readings. The weekly review now reads his fitness only from rides at a
fixed power in ERG (his heart rate at the same watts, the last four weeks against the four
before), stops proposing an FTP from every ride, and adds one note when he looks ready for
more. Nothing changes his FTP or his plan. `apps/api/tests/test_batch_319_progress_signal.py`
holds the note to this file.

**Measured, read-only, on production (29 Oct):** at his ERG Zone 2 power his heart rate
was steady (under 3 beats a minute of change; 7 and 8 rides in the two windows). The note would not have appeared on any Sunday in October: each
run of three hard sessions had a cautious morning after at least one.

## 1. The note (319.3)

**Where:** the weekly review, word for word, only when his last three hard sessions each
landed at least nine in ten work intervals on target and the morning after each was not
cautious.

> Your last three hard sessions all landed on target, and you woke up fresh after each. You look ready for a little more: a ramp test, or one small step up in your next hard session. Nothing changes unless you choose it.

**Replaces:** nothing; nothing ever suggested more.

## 2. The fitness line (319.2)

**Where:** the weekly review, one sentence the model writes from the numbers, for example
"At about 180 W your heart rate is steady: 110 beats a minute these four weeks against 112
the four before."

**Replaces:** an FTP the review proposed from watts per heartbeat across every ride (two different
figures two months apart), which moved with the mix of sessions. Only the ramp test sets
his FTP.

## Settled by Craig (29 Oct)

1. The note's numbers stand (three sessions in a row, nine in ten on target, a fresh next
   morning).
2. The ramp test is left out of the run: it runs to failure, so it scores 0 on target.
