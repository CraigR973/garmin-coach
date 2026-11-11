# Batch 386 — where a check-in question is answered (DRAFT, for Craig's sign-off)

Drafted 11 Nov 2026 after the paid eval held 5 of 6 cases (Decision #502). **Nothing here is built
or in the prompt.** Every example is invented; no stored text is quoted.

## What went wrong

The eval's 7 Nov case carries a question in the check-in. The prompt asks for the answer "under a
short **Your question** heading near the top of the read" and the call's instruction says it "comes
straight after this section". Both mean a bold line, not a heading, so the model wrote it straight
under "Today's call" and the brief check, which counts every word up to the next heading, counted
the answer as part of the call: 337 words against a cap of 120. The call itself was well within it.
v70's recording passed this case only because that answer happened to be short.

The app already treats a real "Your question" heading as its own part: the readiness line is placed
after it (`place_readiness_line`), and a heading ends the call for the length check. A bold line
does neither.

## The words (option A, recommended): a real heading, outside the call

Three edits, all in text the brief is sent. No change to code or to the check.

1. **The question rule** (morning prompt). Today: `Put the answer under a short "**Your question**"
   heading near the top of the read.` becomes:

   > Put the answer under its own "## Your question" heading straight after "## Today's call",
   > never inside it, so the call stays short.

2. **The tomorrow rule's reference** (same prompt). Today: `under the same "**Your question**"
   heading` becomes:

   > under the same "## Your question" heading

3. **The call's instruction** (`TODAYS_CALL_INSTRUCTION`, its last sentence). Today: `If he asked a
   question, the Your question answer comes straight after this section; everything else goes in
   the sections below.` becomes:

   > If he asked a question, its answer goes straight after this section under its own
   > "## Your question" heading, never inside this section; everything else goes in the sections
   > below.

What Mark sees: the same answer, as a page heading like the other sections instead of a bold line.
Briefs already stored keep their bold line and display as they do now.

Side effect, an improvement: on a morning with a question and the readiness line due, the line is
placed after the answer's heading, as the code already intends; with a bold line it was not found.

## Option B (not recommended): leave the words, change the check

Make the call's length check stop at a bold "Your question" line. Pure code, no new words. It
leaves the model free to put the answer inside the call heading, so Mark's page would still show it
there, and it changes what the check measures. Rejected unless you prefer no prompt change.

## Option C (not included): also cap the answer's length

The rule says "directly and briefly" and no more. A number ("in about 80 words") would be new
behaviour for Mark; left out unless you want it.

## What happens on sign-off

1. Make the three edits; the prompt text changes under v71 (no new version: v71 has not shipped and
   the recording is pinned to the text), the Batch 308 byte-for-byte test gets one more entry, and a
   test pins the three sentences.
2. One paid pass of the same six mornings, about $0.91, same cap; a stop if the estimate is higher.
3. If the gate holds: full local gates, both CI waves, merge outside 06:00–11:00 London, production
   verified. If it fails again: stop and report; no further pass without your word.
