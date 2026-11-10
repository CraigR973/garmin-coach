# Batch 385 — the Experiments page in plain words: the words (for Craig's sign-off)

**Signed off by Craig on 10 Nov 2026** ("Yes, as recommended"), with one change: the "not yet" sentence for the sleep-score target ends "the target is 7 nights in a row." (section 1). Every sentence in section 1 is built by `experiment_plain_words.plain_evaluation`
and held to this file by `apps/api/tests/test_batch_385_experiments_plain_words.py`. Every
example, name and figure here is invented; Mark's real experiments stay in the git-ignored
`scratchpad/batch-385-plain-words/`.

The page shows an evaluation only after Mark taps "Evaluate evidence". Until now it printed the
evaluation's own reasons, which quote a correlation as `r=`, a range, a measured driver's key
(`bedroom_peak_fan_speed`), a threshold, "Standardised effect", and a status key
(`insufficient_history`). It now shows a badge, one or two sentences, and a closed "Show the figures" list (kept, Craig, 10 Nov).

## 1. The sentences (this is what Mark reads)

Where a figure a sentence needs is missing, the page shows no sentence at all, never the
technical line. The verdict sentences (the met gate, the supported and refuted overnight
disruption, the weeks averages and the lever figures) are the ones Craig signed off for the
experiment notice (Batch 382), unchanged apart from section 4. The rest are new, including the
"not yet" sentences, which the notice never sends (it is sent only for a supported or refuted
verdict), so Craig's 10 Nov change to the "not yet" sentence moves the page only.

**Sleep-score target (collagen)**

- Met: *Your age-adjusted sleep score has stayed at or above 75 for 7 nights in a row, which meets the 7-night target.*
- Not yet: *Your age-adjusted sleep score has stayed at or above 75 for 3 nights in a row so far; the target is 7 nights in a row.*
- Below the floor now: *Your age-adjusted sleep score is below 75 at the moment; the target is 7 nights in a row at or above it.*

**Overnight disruption (what lines up with disturbed nights)**

- Supported: *Fan speed moves closely with the disturbed nights, so it looks like a trigger.*
- Refuted: *Nothing I can measure lines up closely enough with the disturbed nights to be a trigger.*
- Real but weak: *Fan speed moves with the disturbed nights, but only weakly, so it isn't strong enough to call a trigger.*
- Unclear: *I can't yet tell whether fan speed or anything else I measure lines up with the disturbed nights.*
- Unclear, no driver named: *I can't yet tell whether anything I measure lines up with the disturbed nights.*

**Recovery weeks against build weeks**

- Any outcome, the averages: *Your overnight HRV averaged 36.4 ms in recovery weeks against 48.4 ms in build weeks.*
- Unclear, gap looks big: *…build weeks. The gap looks big enough to matter, but there isn't enough data yet to be sure it is real.*
- Unclear, gap small: *…build weeks. That gap is too small to count as a real difference.*

**A lever tried against nights without it (REM)**

- Any outcome, the figures: *On the nights you tried it, REM was 2.4 percentage points higher and you were awake 12 minutes less than on the nights you didn't.*
- Unclear: *…than on the nights you didn't. That is too small, or too uncertain, to call either way.*
- Nights fall in different seasons: *…than on the nights you didn't. The nights you tried it fall in different weeks of the year, so the season could explain the difference.*
- Not enough nights: *There aren't enough nights yet to compare the nights you tried it with the nights you didn't. I need at least 7 of each.*

**Too early, any experiment**

- One side only: *I have only 4 nights I can compare so far, which is too few to judge.*
- Weeks: *I have 2 nights from recovery weeks and 3 nights from build weeks so far, which is too few to compare yet.*

**No automatic check**

- *I can't check this one automatically, so it is for you to judge from your own notes.*

## 2. The badge, the footer and the messages

| Where | Today | Now |
|---|---|---|
| Badge, a verdict | supported / refuted / inconclusive | unchanged |
| Badge, too few nights | `insufficient_history` | *too early to tell* |
| Badge, nothing to check it | `no_evaluator` | *no automatic check* |
| Footer | *Based on 10 samples. Advisory only — concluding is always your call.* | *Based on 10 nights. Advisory only — concluding is always your call.* (the count is dropped when it is 0) |
| Message, too few nights | *Not enough history yet to evaluate this hypothesis.* | *It's too early to tell: there aren't enough nights yet.* |
| Message, nothing to check it | *No automatic evaluator applies to this experiment.* | *I can't check this one automatically.* |

Left alone on purpose: the "Conclude as supported / refuted" button, the experiment's own
status badge (active, paused, concluded), the title and the question, which are Mark's own words.

## 3. The detail view (kept, Craig, 10 Nov)

A closed "Show the figures" control sits under the sentence, and opens a two-column
list of plain labels. Nothing in it uses `r=`, a range, a key, or a threshold in notation.
It shows only the figures that exist for that evaluation.

| Kind | Label → value (invented) |
|---|---|
| Sleep-score target | Nights in a row at or above 75 → 3 · Target → 7 nights in a row · Latest night's score → 78 · Recent trend → rising |
| Overnight disruption | Closest match → Fan speed · How closely it moves with the disturbed nights → weak, moderate or strong · Nights compared → 10 · Not measured from your synced data → alcohol, late snack |
| Weeks | Recovery weeks, average → 36.4 ms over 7 nights · Build weeks, average → 48.4 ms over 7 nights · Recovery weeks against build weeks → 12.0 ms lower · A gap counts from → 3 ms |
| Lever | Nights you tried it → 8 · Nights you didn't → 8 · REM sleep on those nights → 2.4 points higher · Time awake on those nights → 12 minutes less |

Two of those are new information the page did not carry in words before: how many nights stand
behind each side, and the figures the experiment could not measure (alcohol, a late snack).

## 4. One correction to the signed-off notice sentence (Batch 382)

The weeks sentence in section 1 is the notice's own, from the same code. Its real metric label is
"overnight HRV" (the sign-off draft used "HRV"), and the code lower-cased the whole label, which
printed "overnight hrv", and printed the stored two decimals ("36.43 ms"). It now lower-cases only
the first letter and prints one decimal. No other word changed.
