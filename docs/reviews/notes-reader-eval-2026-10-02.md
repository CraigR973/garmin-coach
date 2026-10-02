# Notes reader eval

Generated 2 Oct 2026 17:34 UTC · 125 cases: 56 of Mark's real morning notes, 59 hand-written hard cases, and 10 held out (written after the prompt was frozen). Labelled by Craig, 30 Sep 2026 (R01-R56, H01-H44) and 2 Oct 2026 (B01-B15, X01-X10).

**The gate:** every red-flag case caught on every pass (a floor, or at least the question); at most 2 of the 56 real notes raise a floor or a question the key does not; no floor for someone else's symptom or a past one.

Red-flag cases (22): H01, H02, H03, H04, H05, H06, H07, H08, H09, H10, H43, H44, B01, B02, B03, B04, B11, X01, X02, X03, X04, X05.

## How this run was reached

- **Batch 297, 30 Sep 2026: the v1 prompt.** A 2-cent smoke (2 notes per model) confirmed both models answer the strict schema.
- The first Sonnet 5 run (3 passes, $2.53) missed H04 and H43 on 2 and 3 passes: it read "since yesterday" as past, because the prompt defined earlier as "before last night". The prompt now says a symptom still going on is now, however long ago it started. Its examples name "since yesterday", the phrase in both misses, so those two cases are no longer unseen. Nothing else changed.
- The recorded runs below are after that fix. Total spend on the eval: $4.89 of Craig's $5.
- Both models caught every red flag. Haiku 4.5 set no floor for H07 (chest tightness on the stairs) on either pass, only the question, where Sonnet 5 set the chest floor; and its real-note false alarms sat at the limit on both passes.
- **Batch 303, 2 Oct 2026: the v2 prompt.** Breathlessness that is unusual for him joins the chest flag, with two rules for what is not one (his breathing exercises, and breathing hard in a hard effort). 25 cases were added and confirmed by Craig before the run: 15 on breathlessness (B01-B15) and 10 held out (X01-X10), written after the prompt was frozen.
- A 2-cent smoke (B02 and B08) confirmed the v2 prompt answers the schema. The recorded run is the first and only v2 run: Sonnet 5, 2 passes, $2.23. The prompt was not changed after it. Total spend on this re-run: $2.25 of Craig's $5.
- Every red flag was caught on both passes, the 10 new ones included. B03 (woke gasping in the night) set the chest floor on one pass and only asked on the other; since Batch 303 that question also eases a hard session until he answers. The two real notes that mention his breathing exercises (R33, R42) stayed quiet on both passes, and the real-note false alarms are the same two notes as under v1 (R29, R35).
- One held-out note raised a question it should not have, on one pass of two: X07, a stitch in his side on a walk, read as a possible chest symptom. The prompt was not changed to fit it. One tap of None on Home clears it.
- Haiku 4.5 was not re-run: it is not the production model. Its v1 recording is kept and named below, not scored.

## claude-sonnet-5 (configured reasoning)

- **Prompt:** `notes-reader-v2-2026-10-02`, SHA-256 `91945b356ba3`
- **Gate:** met
- **Passes:** 2
- **Red flags caught:** 22 of 22, 22 of 22
- **Floor class exact:** 21 of 22, 22 of 22
- **Real-note false alarms:** 1 ['R35']; 2 ['R29', 'R35']
- **Hard-case false alarms:** 1 ['X07']; 0
- **Missed questions:** 0; 0
- **Feel-notch disagreements:** 3 ['R29', 'R35', 'H15']; 3 ['R29', 'R35', 'H15']
- **Failed readings:** 0; 0
- **Held-out cases as keyed:** 9 of 10 ['X07']; 10 of 10
- **Cost:** $2.23 (625,964 tokens in, 98,252 out)

## Not re-run under this prompt

- claude-haiku-4-5-20251001: recorded under `notes-reader-v1-2026-09-30` on 2026-09-30T20:03:45Z, and not scored here. It answers a prompt the reader no longer sends.

