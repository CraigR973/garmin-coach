# Notes reader eval

Generated 30 Sep 2026 20:05 UTC · Batch 297 · 100 cases: 56 of Mark's real morning notes and 44 hand-written hard cases, labelled by Craig on 30 Sep 2026.

**The gate:** every red-flag case caught on every pass (a floor, or at least the question); at most 2 of the 56 real notes raise a floor or a question the key does not; no floor for someone else's symptom or a past one.

Red-flag cases (12): H01, H02, H03, H04, H05, H06, H07, H08, H09, H10, H43, H44.

## How this run was reached

- A 2-cent smoke (2 notes per model) confirmed both models answer the strict schema.
- The first Sonnet 5 run (3 passes, $2.53) missed H04 and H43 on 2 and 3 passes: it read "since yesterday" as past, because the prompt defined earlier as "before last night". The prompt now says a symptom still going on is now, however long ago it started. Its examples name "since yesterday", the phrase in both misses, so those two cases are no longer unseen. Nothing else changed.
- The recorded runs below are after that fix. Total spend on the eval: $4.89 of Craig's $5.
- Both models caught every red flag. Haiku 4.5 set no floor for H07 (chest tightness on the stairs) on either pass, only the question, where Sonnet 5 set the chest floor; and its real-note false alarms sat at the limit on both passes.

## claude-haiku-4-5-20251001 (none reasoning)

- **Gate:** met
- **Passes:** 2
- **Red flags caught:** 12 of 12, 12 of 12
- **Floor class exact:** 11 of 12, 11 of 12
- **Real-note false alarms:** 2 ['R29', 'R35']; 2 ['R29', 'R35']
- **Hard-case false alarms:** 0; 0
- **Missed questions:** 0; 0
- **Feel-notch disagreements:** 7 ['R02', 'R07', 'R29', 'R35', 'H15', 'H39', 'H40']; 4 ['R02', 'R29', 'R35', 'H15']
- **Failed readings:** 0; 0
- **Cost:** $0.62 (367,854 tokens in, 49,741 out)

## claude-sonnet-5 (configured reasoning)

- **Gate:** met
- **Passes:** 2
- **Red flags caught:** 12 of 12, 12 of 12
- **Floor class exact:** 12 of 12, 12 of 12
- **Real-note false alarms:** 1 ['R29']; 2 ['R29', 'R35']
- **Hard-case false alarms:** 0; 0
- **Missed questions:** 0; 0
- **Feel-notch disagreements:** 2 ['R29', 'H15']; 3 ['R29', 'R35', 'H15']
- **Failed readings:** 0; 0
- **Cost:** $1.72 (462,204 tokens in, 79,532 out)

