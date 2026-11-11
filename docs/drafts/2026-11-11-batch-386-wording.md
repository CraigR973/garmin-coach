# Batch 386 — the words for the brief's call sentence and the app's words (DRAFT, for Craig's sign-off)

**Signed off 11 Nov (Craig, "Yes, as recommended"): option (a), sections 1–4, gate option C, effect ranges dropped; built into v71 (Decision #502).**

Built 11 Nov 2026 on `feat/batch-386-call-sentence-and-app-words`. The words below are now in the morning
prompt (v71); see Decision #502 for the eval. Every figure and example below is invented; the counts are measured read-only over stored
briefs and reads (no text is committed).

## What is built already (code only, in the draft PR)

- `brief_check` flags a call whose "Because…" sentence has no main clause (`call_sentence`); the
  one repair call is asked to finish that sentence, and kept only if the check then passes.
- The engine-word check also finds the app's phrases (below), as phrases.
- Room temperatures are carried to one decimal in the packet (`services/coach_sections.py`).

**The check cannot ship alone.** Run over v70's stored briefs it finds a phrase in 42 of the 43 briefs
since 1 Oct (13 of 13 since 30 Oct), so on today's words nearly every morning would cost a repair
call. It is meant to go live with the reworded rules below, as the backstop for what they miss.

## 1. The call's "Because…" sentence (option a, recommended; option b for comparison)

Today `TODAYS_CALL_INSTRUCTION` asks for "one sentence that begins "Because" and says why in his
words". Nothing asks what that means for the session, so 2 of the 13 briefs since 30 Oct (1 and 11 Nov,
both Green-light mornings) stop after the why.

**(a) Draft A, one clause added to the instruction** (the rest unchanged):

> one sentence that begins "Because", says why in his words, and ends with what that means for
> today's session (for example "…, the ride stands as planned"), never "domain" or "autonomic";

Cost: one clause in the prompt; the model writes the half, as it does the rest. The check is the
backstop (measured below). **(b)** the app writes the half from `todaysCall.line`
(`services/todays_call.py`), as it places the readiness line: the sentence could then never be
missing, but it is a larger change to words he sees and the model's "Because" would have to stop
before it. Recommended: (a).

**The repair call's ask** (already in code as a draft; it never reaches Mark unless the brief came
out unfinished):

> In the "Today's call" section, the sentence that begins "Because" has no main clause: it says why
> and stops. Finish that same sentence, after a comma, with what it means for today's session, as
> the rest of the brief already says it (for example "the ride stands as planned"). Add no figure.

## 2. Thermal rule: say what happened, not what the app recorded

Today (`morning_analysis.py`, the thermal rule): "when flags contains `precool_credited`, explicitly
credit that cooling and do not call the pre-cool a miss merely because it stopped above
targetPreCoolC." The brief copies it: "credited" in 28 of 43, "a miss" in 20 of 43.

> When flags contains `precool_credited`, tell him the cooling before bed worked, in plain words
> ("the room cooled well before bed"), even though it stopped above targetPreCoolC. Never say
> "credited", "credit" or "a miss" about it.

When the pre-cool was short of target and not credited, the rule is unchanged ("missed" there is
ordinary English).

## 3. Held-morning rule

Today: "on a held morning (verdict.held) the fallback is to ride it as planned with its targets
held, not to soften it." "targets held" reached 6 of 43 briefs and 1 of 16 weekly reviews.

> on a held morning (verdict.held) the fallback is to ride it as planned, at its planned power and
> length, not to soften it.

## 4. Severity words ("marked off")

The prompt's graded-verdict rule says "one marked or two mild"; the engine's own sentences say "a
little off". The brief's "nothing marked off" is the two meeting (3 of 43).

> When no domain is flagged, say that nothing is flagged or nothing is out of the ordinary; never
> "marked off".

(One sentence added after the rule's "never count a domain the packet does not flag".)

## 5. "Gate": where it comes from, and three ways to fix it

"gate" is in 26 of 43 briefs (30 with "gated"). It reaches the brief from four places, all about the
collagen experiment, whose kind is "gate":

1. the evaluation's own reasons (`experiment_evaluation.py`: "…gate not yet met", "the gate is met"),
   which the prompt and the experiment section's instruction tell the brief to quote ("state the
   first supplied reason");
2. the evidence keys `gateNights`, `gateMet`, `gateFloor`, `meetsGateFloor`;
3. the prompt's "every conclusion is human-gated";
4. the experiment section's instruction, "including the supplied reason and evidence still needed".

Options:

- **A. A sentence in the prompt:** "Never say 'gate' or 'gated' about an experiment; say what it
  needs, for example 'it needs 7 clean nights in a row at 74 or above'." Smallest; the model still
  sees the word in its input.
- **B. Reword the evaluation's reasons.** Fixes it at the source for every reader of the reasons
  (the brief, the coach chat), but changes stored evaluation text and several tests.
- **C. Give the brief what the Experiments page says.** Batch 385 already builds one plain sentence
  per experiment (`experiment_plain_words.plain_evaluation`, signed off). Put that sentence in the
  brief's packet and tell the brief to use it for the experiment line. This removes "gate" and the
  effect ranges together (the figures stay behind "Show the figures" on the page). More code than A,
  no change to stored evaluations. Recommended if Craig wants the ranges out (decision 3).

## 6. Effect ranges in the experiment lines

The lines print effect ranges in words ("both ranges still include no effect"): 18 of the 43 briefs
since 1 Oct say "no effect", 6 of the 7 since 5 Nov. Keep them (Mark sees the evidence) or drop them
(the page keeps them behind "Show the figures"). Option C above drops them; with A or B they stay.

## 7. The app phrases the check finds (built; the repair names each as written)

As phrases, never bare words: "credited" within a sentence of "pre-cool", "cool-down" or "cooling";
"not / than / called / as a miss" and "pre-cool miss"; "targets held"; "marked off"; "the / a / your /
retry / readiness gate", "gate is / needs / not…", "still gated"; "rearrange proposal"; "in this
read"; "targets-held". Not matched on purpose: "missed" about REM or HRV ("REM missed its age norm"),
"credit" far from cooling ("age credit"), "power target held" in a ride read.

**False hits, measured read-only over every stored read (11 Nov):**

| Reads | Stored | With a phrase | Ordinary English |
|---|---|---|---|
| Morning briefs | 153 | 120 | 0 found |
| Post-ride reads | 159 | 3 | 1 ("the gate for Monday's plan") |
| Strength, walk, flexibility | 101 | 0 | 0 |
| Weekly reviews | 16 | 1 | 0 |

The post-ride reads are not checked by this code (the brief's check is), so that one hit costs
nothing today; it is recorded in case the phrases are later added to the read check. An "age credit"
word (4 briefs, 1 to 18 Oct) is the app's too and was left out of the list; say if it should join.
A call sentence flagged by the new check: 2 of 38 briefs with a call, the two named above, none else.

## What Craig decides

1. The call fix: (a) or (b).
2. These words (sections 1–4, and 5's option).
3. Whether the experiment lines keep effect ranges (section 6).
4. The eval: one paid pass, about $1 (384's cost $0.93), cases to include 1 and 11 Nov and a morning
   with a credited pre-cool.
