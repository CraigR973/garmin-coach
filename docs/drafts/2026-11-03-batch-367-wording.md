# Batch 367.2–.5 — Progress and trend claims that pass a noise test: the words (for Craig's sign-off)

**Signed off by Craig on 3 Nov 2026** ("Yes, both", relayed by the orchestrator session, with the three decisions of the PR). Wave #6's statistics pass found the weekly review's claims
firing on noise (ST363-02 to -09). Batch 367.2–.5 makes each claim clear its own noise, tested
in CI on simulations with Mark's own spreads (each fires on noise less than one time in ten).
`apps/api/tests/test_batch_367_claims_pass_a_noise_test.py` holds the app's lines to this file.

## 1. The weekly review's progress note (367.2)

**When:** his last three key sessions (VO₂, threshold, sweet spot) each landed on target,
**each felt no harder than 7 out of 10 (his own check-in)**, he woke fresh after each, his heart
rate at fixed power is not slipping, and it is not a light week or within four weeks of a test.
Under ERG "on target" is automatic (55 of 55 intervals since Plan No. 3), so how hard it felt is
the part ERG cannot fake.

**Replaces** "Your last three hard sessions all landed on target, and you woke up fresh after
each. You look ready for a little more: a ramp test, or one small step up in your next hard
session. Nothing changes unless you choose it." It no longer offers a test or a step up: Plan
No. 3 already steps up, so the note says the plan's step looks right.

> Your last three hard sessions all landed on target, none felt harder than a 7 out of 10, and you woke up fresh after each. The plan's next step looks right for you.

## 2. What the review now says less often (367.3, no new words)

- **Fitness drift** (heart rate at the same watts): a change is called only past about 6 bpm
  with three rides a side (twice its standard error, his ride-to-ride spread 3.5 bpm), not 3 bpm.
  Noise called a change on one Sunday in seven; now under one in ten (simulated: about 1 in 20).
- **Sleep trend through the week:** called only past about 16 points half to half (7 points for
  a month). The first v14 review's "sleep rose through the week" (74.0 → 77.8, one 88 night) now
  reads steady. The old rule called a trend on 63% of shuffled weeks.

## 3. Behind the scenes (367.4, no new words)

- **Experiments** (the REM tips): judged once a month, on the nights to the end of the last whole
  month, not re-judged every morning. A tip with no effect got a direction on some morning in
  about a quarter of seasons; at fixed points it is under one in ten.
- **Sleep stress** is no longer a candidate cause of his early waking: it is measured from the
  same overnight heart signal his waking raises.
- **Tonight's advice** in the weekly review reports only the difference between the nights he
  followed it and the nights he did not (each side starts from a cautious morning, so both bounce
  back).
- The HRV "mild" line is described as more than a worthwhile change, not "real, not noise", and
  the "marked" line is recorded as set from his own first months. No call changes.
- The driver audit (Craig's record, not Mark's) prints the coefficient it ranks by, with its own
  sign, and only for a driver with 20 nights.

**Prompt version:** the weekly review moves v15 → v16 (its rules describe the new note and the
difference-only advice). Unfiltered: no stored review is withdrawn and nothing is regenerated;
Sunday 8 Nov's review is the first at v16.
