# Batch 383 — words, version and what each option does to the coach

Sanitised: sizes and invented examples only. Not signed off. Written at the batch's
one stop (9 Nov, Decision #493); nothing here is built.

## Which options change what the coach is told

| Option | Changes words the coach reads? | Chat version |
|---|---|---|
| A. Compact JSON separators | No. Same data, fewer spaces. | stays v32 |
| D1. Drop the four verbatim copies in the knowledge base (chat only) | No. The prompt and the section's meaning never name them; the same content stays in `sections`. | stays v32 |
| B2. Slim the nested copy of a moved session in the week ahead's change entries (chat only) | No. Keeps who, when, from/to and the summary; drops the repeated session body. | stays v32 |
| F. Budget 62,500 to 66,000 | No. | stays v32 |
| G. Trim recent sessions oldest-first before dropping the list | One new omission label (below). The omission note's wording is unchanged. | stays v32 |
| D3. Send remembered facts once (quoted, fenced), not twice | Optional one sentence (below). | v32, or v33 if the sentence is used |
| C1. Fewer trend months by design | Yes: an omission note is needed (below), or the coach would read the missing months as "no data". | v33 |

Chat is unfiltered in `prompt_artifacts`, so no version bump withdraws or regenerates
a stored answer. A bump to v33 would end the v32 evidence window Batch 380's
acceptance is judged on: Mark's natural answers on v32 would stop at the deploy, and
380 would need the same review again on v33. Options that leave the version at v32
change the block the v32 answers see, so the deploy time splits the v32 answers into
"before" and "after" for that review.

## Draft words (only if Craig chooses the option)

**G — label only.** `recentActivities(oldest)` is added to the fetchable omissions with
`get_activities`, so the existing sentence applies unchanged: "Trimmed to fit the
prompt, not absent from the app. Fetch items with a named lookup."

**D3 — optional sentence added to the knowledge-base meaning:**
"Remembered facts come as quoted statements only; where a statement came from is not in
front of you here."

**C1 — omission note when trend months are cut by design:**
"Trends here cover the latest four months. Earlier months exist in the app but are not in
front of you here; say so rather than saying there was no trend."

## What is not touched

Floors, the answer guard, pass-on, propose/approve, answer-first and length, the model,
effort and tokens, the morning prompt and its packet, and the knowledge-base shape the
morning brief reads.
