# Batch 362 — UX and the live app, with Mark's scorecard (wave #6, pass R7)

**Pass R7** · reviewed SHA `083e012` (production serves `caae3c4`, docs only) · lens: product designer · read-only · paid calls: **none ($0)**.
Run 1 Nov 2026, from 16:15 GMT. **Status: done (main part 16:15–16:40 GMT; weekly-review resume 18:55–18:58 GMT).** The first v14 weekly review (stored 1 Nov 18:00:57 London) is read and rendered in §12; R8's §11 and R4's §9 are read and agree with it.
Companion: `BATCH_362_MARK_SCORECARD.md` (never published). Predecessors: `BATCH_333_UX_LIVE_APP_REVIEW.md` (B−), `BATCH_241_…`.

## 1. Summary

**Grade B (settled after the weekly review; wave #5 was B−).** Screen by screen it is the best the app has been, and the failure states wave #5 graded D are fixed and proved. What a product designer would not leave alone: (1) on a morning with no overnight data the app told Mark "something went wrong while writing" and nothing else, for eight and a half hours; (2) he gets about 6.4 pushes a day and can only switch all of them off; (3) the tired-morning card says "pick below", hides the pick until he opens the brief, then shows a second control for the same ride; (4) a line he questioned twice (the readiness slide) came back unchanged on five mornings.

| Question | In this lens |
|---|---|
| 1. Correct and safe? | The screens say what the engine decided; one live ride line checked, none wrong. A no-call morning shows no caution (UX362-01); the no-plan fix has a hole (UX362-09). |
| 2. Honest with Mark? | Yes on every number I traced; wording drifts: three REM yardsticks on one morning, "median" again on 1 Nov, a pattern card that says "repeatedly missed" the morning after a good night (UX362-04, -06). |
| 3. Doing its job? | The call leads, the plain-words cards (FTP, memory, next plan) read well. The brief page is still about 1,150 words (7–8 phone screens), the check-in page asks seven things (UX362-05, -06). |
| 4. Failure noticed? | By Mark: yes, in words, every state I forced (8 of 8). By the app or Craig: no. The 1 Nov outage text names the wrong cause (UX362-01). |
| 5. Cheap to run and change? | Yes. 502 KB gzip JavaScript (476 KB in wave #5), Home ready in 0.4–0.7 s on the mock, no contrast or target failures that matter. Fixes below are hours each, mostly copy. |

**Counts:** 0 High · 1 Med-High · 5 Medium · 4 Low (10 findings). **Weekly review (§12):** the first v14 review reads well (546 words, his words, honest on the sleep habit) but ends with "ready for a little more: a ramp test, or one small step up" straight after "no training changes needed" for the recovery week (R4's CI359-02, R8's ST363-02) and says "median" twice (UX362-04); it changes no grade. **Before Tue 10 Nov** (first full VO₂ of the build): UX362-01's wording with R4's CI359-01. Everything else can wait for a normal batch.

## 2. What optimal looks like

One moment, one story; every state in words *with its real cause*; one decision, one control; the app asks for as little as it needs and says each thing once. Mark is a 57-year-old on an Android phone reading half awake, so: the call first (already true), notifications he can tune, and a brief a third the length it is now.

**Near-optimal, leave alone:** failure and drift states (§4); the "On Zwift: …" ride line (UX333-01, §3 table); Home's call hero; the FTP offer, the memory ask and the next-plan card (short, plain, one tap each); dark and light contrast; speed and bundle; the Week tab's counts.

## 3. Findings (Highs first; none High)

### UX362-01 — Med-High · The 1 Nov no-data morning: Home blamed the writing, said nothing of the missing night, and left a full 120-minute ride "Already in Zwift"
**Evidence: observed + proved + implemented.**
- *Observed (1 Nov):* Garmin refused the app's login 00:25–12:01 GMT (R2's DS357-01). Mark had checked in by 10:15 (the stored entry is stamped 10:15; R3 saw the held check-in at 09:46); no morning row was stored; the brief appeared at 12:04–12:05 after his "Try again"; his ride started at 11:59, six minutes earlier, 104 minutes long. `good_morning_nudge` count that day: **0**; pushes all day: 3 (two "check in and I'll read it" ride nudges and the brief at 12:05).
- *Proved (the shipped bundle on the real 1 Nov envelope, fields removed to match the outage):* **before his check-in** Home shows "Say good morning — Check in and I'll sync your overnight data before I read your day" and a button, over the ride card "Long Z2 · 120 min … Already in Zwift, ready to ride". **After it** Home shows "Couldn't finish your brief — Something went wrong while writing today's brief. Your check-in is saved. Try again". `/brief` shows only that card. No screen names the cause (no night of data), says it is not his fault, says anyone is fixing it, or says what to do if he rides before it lands.
- *Implemented:* the state is picked from `briefGeneration.status` alone; the reason (`inputs`) reaches the page but is not read, and "writing" is the only wording for `failed` (`BriefFailedCta`). "Try again" re-runs the same check-in, which cannot succeed while the login is refused. The failure is filed `inputs`, which raises no alert (R3's AI358-02).
- *Story with the other passes:* R3 AI358-01 (no call is written; the coach said "ride as prescribed"), R4 CI359-01 (the engine's own missing-data rule never runs; the full session stays on Zwift), R2 DS357-01/-02 (nobody was told). R7 adds what he saw while it happened.
**What Mark experienced.** Eight and a half hours (03:30–12:04) with either a promise to sync or an error in the wrong words; at least one "Try again" (11:34, per the orchestrator's check) that could not work; no caution on the ride. He waited, then started the ride six minutes before the brief. Today's ride was easy endurance, so the harm was small.
**Fix.** Wording by reason, caution only: for `inputs`, "Your watch data hasn't reached me yet, so I can't read your day. If you ride before it does, keep it easy and stop if anything feels wrong. I'll tell you the moment it arrives." For any failure, keep "Your check-in is saved." Pair with R4's code-only call so Home can show an actual call. **Cost:** copy and one branch, under half a day; wording needs Craig's sign-off (Mark-facing). **Where:** ride with CI359-01; before Tue 10 Nov.

### UX362-02 — Medium · About 6.4 pushes a day, six evenings with two "critical" bedroom pushes in an hour, and no way to tune them
**Evidence: observed + computed + implemented.**
- *Computed (`coach.analyses` push rows, 7–31 Oct, 25 days):* **161 pushes, 3–10 a day, mean 6.4.** By kind: bedroom alert 42, ride "check in and I'll read it" 43, good-morning 22, brief-ready 25, evening nudge 17, stale-source 7 (Hive outage), weekly review 3, other 2. Bedroom alert graded critical on **13 days**, evening nudge critical on **8**, both on **6** days (the 31 Oct pair: 19:00 "20.5C, above the 20C disruption threshold", 20:00 "Start the pre-cool earlier…").
- *Implemented:* Settings → Notifications offers enable, send a test, disable. The API has a global mute and quiet hours (`/notifications/preferences`); **no web file calls it**. Nothing lets him keep the brief and the ride read and drop the bedroom pair.
- *Observed:* the ride nudge is sent per synced activity: on 1 Nov two went out for a 12-minute circuit and a 17-minute walk synced after the outage, a third for the ride.
**What it teaches.** A nightly "critical" that R6 shows is graded from the early-evening reading (HS361-01, High) and R8 shows rests on a weak link (ST363-01) is a push Mark will learn to swipe; the day a real symptom or a stale source needs his eye, it sits in the same stream. (His own quilt note on 1 Nov shows warmth is a real worry for him; the fix is fewer, better-graded pushes, not none.)
**Fix, smallest first.** (a) R6's grade fix (one evening bedroom push, graded on the sleep-window forecast). (b) One ride nudge per day, not per activity, and none for a walk or a circuit under 20 minutes. (c) A Settings switch per kind (three: brief and ride reads, bedroom, reviews), using the existing mute and quiet hours. **Cost:** (a) is R6's; (b) an hour; (c) half a day. **For reconsideration:** the 25 Oct push settings design (inherited global mute); no decision number cited, none found.

### UX362-03 — Medium · The tired-morning card: "pick … below" with nothing to pick, then two controls for one ride, and a default that is the opposite of the headline
**Evidence: observed + implemented + proved.**
- *Proved (31 Oct 09:30 envelope through the bundle):* Home's headline reads "Easy or tempo — your call … pick easy Zone 2 or tempo below". While the "Your morning brief is ready" strip is unread, the card shows no Easy/Tempo buttons (the code hides today's actions until he opens the brief); the ride card shows "Coach's suggested change … Approve & upload / Ignore". After he opens the brief, Home shows the pick ("Easy Zone 2 / Tempo") **and** the same "Approve & upload / Ignore" further down: two controls for one decision (the class of UX333-02, narrower). `/brief` shows the pick card only.
- *Observed:* the pick card says "If you pick neither, the planned session stays on Zwift"; Zwift held the full session with its 185% sprints (`liveRide` as planned, 58 min). He picked neither, rode it (RPE 3, feel 9). The headline said "the hard efforts are off today".
- *Observed (chat, 31 Oct 09:34–09:38):* he asked whether the app can see "the two alternative" rides and which of the three is best; the coach answered the app does not rank them. A short exchange, but it is the decision the app handed him and did not help with.
**What Mark experiences.** A call that tells him to choose, a card that looks as if "Approve & upload" is the choice, and the hard ride on his trainer unless he acts.
**Fix.** One control: show the pick on Home the moment the brief exists (not behind "Read it"), drop "Approve & upload / Ignore" while a pick is open, and say in the card which is the default: "No pick: the planned ride stays." Whether the engine should itself pick (easy Zone 2 as default, tempo on request) is R4's coaching call; as UX, a three-way "your call" with no recommendation costs a 57-year-old a decision on a bad-sleep morning. **Cost:** half a day. **Cross-lens → R4.**

### UX362-04 — Medium · The readiness-slide line: questioned on 28 and 29 Oct, repeated unchanged on five mornings, "median" every time
**Evidence: observed + implemented; numbers are R8's.**
- *Observed:* Mark's chat messages on 28 and 29 Oct (six in all) quote the line back, say "median", and ask whether the holiday and the days after it explain the slide. The brief carried the same paragraph on 28, 29, 30, 31 Oct and 1 Nov (63 against 74 on the last two); the 1 Nov brief again says "median" twice and does not mention the holiday.
- *Implemented:* the warning's text comes from `readiness_baseline_trend` ("the recent 42-day median … below the prior 42-day median") with no holiday allowance; the prompt orders the model to state it every day it triggers. R8 (ST363-08b): the fall holds without the holiday fortnight (−7 instead of −11) and is not a build-block effect. **So he is partly right and the app never said so.**
- *Observed, 1 Nov 18:00 (weekly review):* the stored v14 review says "median" twice in its two "usual range" brackets, against its own plain-words rule (R8 ST363-09 notes the same). The word has now reached a second Mark-facing surface.
**What Mark experiences.** The coach raises a worry he has twice answered with a reasonable question, in a word the app promised not to use (Decisions #440–#442), and says nothing new. Repeated warnings that never change are the brief's version of alert fatigue.
**Fix.** Say it once, plainly, with his point in it: "Your readiness has run lower for six weeks (63, against 74 before). It still shows when the holiday weeks are left out (67)." Then only on a change, or weekly. Feed the model plain figures, not `firstHalfMedian`. **Cost:** an hour plus Craig's sign-off; with R8's ST363-08b and R3's AI358-03.

### UX362-05 — Medium · The check-in is seven questions under "A few taps", and the two newest asks are the least used
**Evidence: observed + implemented.**
- *Proved (render, 1 Nov):* the page holds feel (a score and five words), symptoms (four options), "Anything to flag?", **last night's advice: did you manage it?** (Batch 320), **last night's REM focus** (two items, three answers each, plus "Unknown stays unknown…"), a free-text box, last night's setup, and a folded "More" (blood pressure, supplements, food). Height about 2,350 px, three phone screens.
- *Observed:* the advice question has **one** answer in its three live mornings (1 Nov); R1 had counted none in 309 earlier rows. The free-text note is used on 22 of 25 days (1–4 a day), so the free-text box is the channel he uses.
**What Mark experiences.** The same two REM actions daily ("pre-cool to 17°C" is one), most unanswered. A daily form teaches him to skip.
**Fix.** Show the REM questions on the day the app issues or reviews the experiment, not daily; fold "did you manage it?" into one tap above the note; keep symptoms first. **Cost:** a few hours. **Where:** with the notes-reader work; copy sign-off.

### UX362-06 — Medium · The brief page is about 1,150 words with the same REM story twice, and three REM yardsticks in one morning
**Evidence: observed.**
- *Observed:* the 31 Oct and 1 Nov briefs run **1,182 and 1,137 words** (page 6,150–6,500 px, seven to eight screens; wave #5: "about eight"). The call itself is short (97 words on 1 Nov, 117 on 31 Oct), so v65's call-length miss (R3, R8) is not what Mark feels; the sections below it are. REM appears in the sleep section, in "metrics vs baselines", in an experiment line and in "chronic pattern actions".
- *Observed (one morning, three yardsticks):* 31 Oct Home says "REM 28m, below 65–90"; the Sleep table gives 7.0–13.4% (his own) and 15–23% (age); the brief gives both percentages. On 1 Nov Home says "REM 70m, in 65–90", the Sleep table "1.4 above", and the brief "just below the healthy band … a genuinely good night for you", while the chronic card still says "repeatedly missed" (R8 ST363-07: true by construction on 80% of nights).
**What Mark experiences.** Different words for one number depending on the screen, a worry card on a good night, and a long page whose top is right. He has called this REM line "muddled and flawed" before (UX333-07).
**Fix.** One REM yardstick (his own, in minutes and percent), one place for it in the brief, the age band once a month at most (R6 HS361-03, R8 ST363-07); fold the experiment block into a single weekly line. **Cost:** a day with R6/R8's changes; Craig's sign-off.

### UX362-07 — Low · Home's call is a morning instruction that stays up all day, including after the ride
**Evidence: observed (render).** 31 Oct 19:00, ride "Completed": Home still reads "Good evening, Mark … pick easy Zone 2 or tempo below", pointing at a pick that no longer exists. 1 Nov 16:30, ride completed: "Good afternoon, Mark. You're recovered. Today's session is on as written." Both are true of the morning and stale by the evening. **Fix:** once the day's key session is logged, replace the call line with the plain result ("Done. Long Z2 logged.") and keep the colour and reason. Under half a day; copy sign-off.

### UX362-08 — Low · The watch route lives on Week only, and one live-ride card contradicts itself
**Evidence: observed + implemented + proved.**
- Home's dumbbell card says "Non-bike session — nothing to upload to Zwift" while the 31 Oct strength read tells him to set that dumbbell workout up on his watch; the only button ("Put this week's dumbbells on your watch") is in Week's header, never changes state after a tap (a toast only) and leaves no record (R5's FC360-07).
- *Proved:* with the live ride forced to "not this day" the card prints "Already in Zwift, ready to ride." and, two lines lower, "On Zwift: … That is not the ride planned for this day." plus "Put the planned ride on Zwift". The first line is wrong in that state.
**Fix.** Show the watch button, with its state ("on your watch since Sat"), on Home's dumbbell card; drop "Already in Zwift" when a live-ride line is present. An hour each. (`liveOrigin` has no reader in the web app, as R1's CR356-05 says; the screens use `liveRide`, so delete it rather than read it.)

### UX362-09 — Low · "No plan loaded" is shadowed by "Rest is still the plan today" on any day he logged something
**Evidence: proved (render) + implemented.** With the plan removed and the day's strength read present, Home's day card says "Rest is still the plan today — I've got what you logged below." The no-plan branch sits after the logged-activity branch, so Batch 343's fix (UX333-06) only shows on a day with nothing logged. Mark logs a circuit or a walk most days, so this is the usual path if he lets Plan No. 3 end on 17 Jan without accepting the next one. The Today strip and Week badge do say "No plan loaded". **Fix:** one reordered condition and a test; 15 minutes. Not urgent (11 weeks out; the next-plan card asks first).

### UX362-10 — Low · Leftovers: a raw timestamp, third-person memory, a statistics table and hypotheses written as facts
**Evidence: observed (render).**
- Coach memory page: "Generated 01/11/2026, 16:19:45" (Batch 343 fixed Home and the brief, not this page) and items in the third person ("Mark prefers…") on Mark's own screen with "Forget this".
- Handover page: a "Metric baselines" table headed Mean, Median, Min, Max, n (Decision #442's words are Home's and the brief's; this page is a reference page and Mark can reach it from More).
- Experiments page: cards state the hypothesis as the finding ("Reintroducing collagen disrupts sleep") above an "Evaluate evidence" button.
**Fix.** A date helper, "you" in the memory lines, plain words in the table, "We're testing whether…" on experiments. A couple of hours; copy sign-off.

## 4. Every state in words (headline question 2)

All run through the shipped bundle at 390 × 844 (touch, en-GB, Europe/London, fresh context per job) against a read-only mock; states are transforms of the real 1 Nov envelope, labelled.

| State | What Mark sees | Verdict |
|---|---|---|
| Brief writing | Call and plan shown; "Writing…" card | good |
| Brief failed, billing | Call shown; "Couldn't finish your written brief. Today's call and your plan above are complete without it. Your check-in is saved. Try again" | good (Batch 302) |
| Brief failed, no night of data | "Couldn't finish your brief … while writing" | wrong cause (UX362-01) |
| No check-in yet | "Say good morning … I'll sync your overnight data" | promise it cannot keep on 1 Nov |
| Server 500 on daily loop | "Today's brief couldn't load. We couldn't load this right now. Your saved data is safe. Try again" | good |
| 502 HTML body | same words | good |
| Network down | same words | good (no cached call shown) |
| Week schedule 500 / field missing | "Plan couldn't load … Try again", rest of Week stays | good |
| Missing top-level field (thermal; sleep + plan flag) | Home renders fully | good (one field no longer blanks Home) |
| Unknown field, unknown brief status "queued" | Home renders fully | good |
| No plan, nothing logged | "No plan loaded" with "Make the next plan" | good; shadowed when something is logged (UX362-09) |

**UX333-03 is fixed and proved:** 0 raw JSON, 0 "Internal Server Error", in 8 of 8 forced failures, and the UX333 hypothesis (a PWA left open overnight showing raw JSON) does not hold for the daily loop or Week. R1 agrees from the code (stale cached PWA unlikely to break). Not tested: a failure while a chat message sends, and the offline page (renders "You're offline" text only).

## 5. One moment, one story — Sat 31 Oct and Sun 1 Nov

Amber, Z2 + Neuromuscular completed, Dumbbells B planned (31 Oct).

| Surface | What it said | Agrees? |
|---|---|---|
| Home call | "Easy or tempo — your call"; hard efforts off | — |
| Zwift | the full 58-minute ride with 185% sprints (never changed; he picked neither) | **no** with the headline (UX362-03) |
| Week | Z2 done; "+ Strength · 14 min"; B "To do" | yes (the circuit is not counted as B, matching the v8 read) |
| Strength read | circuit was maintenance, "doesn't tick off the dumbbell session you still owe" | yes with Week |
| Week, 26 Oct | "Dumbbells A (legs and back)" Done | **no** with what he did (R5 FC360-01, High) |
| Push 13:25 | "Your ride is synced — check in and I'll read it" | yes |
| Push 19:00 and 20:00 | bedroom critical, evening nudge critical | in tension with a sleep-window mean under 20 °C on 11 of 12 such nights (R6) |
| Sleep, Home, brief | REM given in three yardsticks | **no** (UX362-06) |
| Chat | consistent with the call; says the app does not rank easy vs tempo | yes, unhelpful |
| Home, 1 Nov afternoon | "Today's session is on as written", ride completed | stale (UX362-07) |

New since wave #5, read as Mark reads them: Home's one-line reason (short, true, plain); "On Zwift: …" (right, UX333-01 fixed); FTP card ("Set my FTP to N W / Zwift gave a different number": plain, answers what he asked on 20 Oct); memory ask and "See everything the coach remembers" (plain; page itself UX362-10); "did you manage it?" (UX362-05); "No plan loaded" (UX362-09); next-plan card (the 12 Oct text is plain); Week's dumbbell button (UX362-08); symptom notices (not re-rendered; R6 owns the words).

## 6. Mark's own words since wave #5 (counts and short phrases)

81 chat messages on 14 days since 10 Oct; a check-in note on 22 of 25 days. Of the eight asks I could trace since 18 Oct:

| Ask | Status |
|---|---|
| The temperature link ignores the holiday and the next-morning date (18–19 Oct, 7 messages) | **partly**: the card now counts away nights ("3 of 22"); the date-offset point never answered on screen; R8 says the link is weak this autumn |
| Use Zwift's own ramp test (20 Oct) | **fixed**: "Zwift gave a different number" on the FTP card; the preference is in memory |
| Friday is a rest day, not "unstructured" (22 Oct) | **fixed**: in confirmed memory |
| Give me the A and B dumbbell sets I was given on 15 Oct (24 Oct, 6 messages, "not sure why you can't understand") | **partly**: the plan rows carry the sets and can go to the watch; the chat still cannot find the old thread |
| Readiness slide vs holiday, "median" (28–29 Oct, 6 messages) | **not**: unchanged on 1 Nov (UX362-04) |
| Is the daily bodyweight circuit good or not (28 Oct) | **partly**: the first answer gave only the caution; he asked for the benefit |
| Which of the three rides is best (31 Oct) | **not**: "the app does not rank" (UX362-03) |
| "Which are the two alternative workouts" (31 Oct) | same finding: the pick was hidden on Home |

3 fixed, 3 partly, 2 not. The pattern: he asks the same question until the answer lands; the app answers in chat and does not change the screen.

## 7. Accessibility, speed, size

- **Contrast (computed, 15 routes × dark and light):** 0 misses in dark; light has 3 at 3.77–3.78:1 (a "Resumed" label and two Trends axis labels). Wave #5: none.
- **Targets under 44 px:** 0 on Home, Week and Settings; 3 disclosure rows on the brief (16–20 px tall), 1 on Sleep, 1 on Check-in.
- **Text size:** body 14 px; 11–12 px text on Home (20 elements), Week (63) and Sleep (70). Text scaling: only Sleep has fixed-size small labels (13, the clock times).
- **Speed/size:** 81 JavaScript files, **502 KB gzip** (476 KB in wave #5), CSS 10 KB; the daily-loop payload **51–68 KB** (41 KB in wave #5). Home ready in 0.4–0.7 s on the mock (instant server); not re-measured on the throttled phone profile (wave #5: 2.65 s).
- **Dark mode:** renders everywhere; headings and buttons clear.

## 8. Follow-through corrections (rows of the pack's table in this lens)

| Row | Pack says | R7 finds |
|---|---|---|
| UX333-01 | fixed, implemented | **confirmed, proved**: "On Zwift: …, 58 min, up to 75% FTP" and the "not this day" variant render with the one-tap fix; a small wording clash (UX362-08) |
| UX333-02 | fixed (claimed) | **partly**: the swap offer withdrawal was not re-driven here; the tired-morning pick now has the two-control problem (UX362-03) |
| UX333-03 | fixed, implemented | **confirmed, proved** (§4) |
| UX333-04 | fixed (claimed) | not re-checked (the builder rendered only "Plan No. 3 is in your plan"); stays claimed |
| UX333-05 | fixed, implemented | not re-checked this pass |
| UX333-06 | fixed (claimed) | **partly, proved**: Today strip and Week badge say it; the day card does not when anything is logged (UX362-09) |
| UX333-07 | fixed (claimed) | the daily REM check-in is plainer but still two items every day (UX362-05, -06) |
| UX333-08 | fixed (claimed) | **confirmed**: the denied-notifications line carries no iPhone text (rendered on a non-iOS profile; the Android profile itself not emulated) |
| UX333-09 | fixed (claimed) | **partly**: Home and brief fixed; the Coach memory page still prints "Generated 01/11/2026, 16:19:45" (UX362-10) |
| UX333-10 | fixed (claimed) | Week carries the rail warning in code; not rendered (rail "ok" in the fixture) |
| DV-4 | fixed (claimed) | Home's one-line reason is present and plain ("Your numbers are all within your usual range.") |
| UX241-03 | fixed, implemented | = UX333-03, confirmed |

## 9. Queued / parked rows re-verified

- **337** (alerts reach Craig): still deferred; today's outage is its live example, and my finding UX362-01 needs only its wording half, not the Sentry half.
- **338, 345, 209:** nothing in my lens; no screen depends on them.

## 10. For reconsideration

- **Decision #300** (no no-data brief): the UX cost is UX362-01; R3's and R4's code-only "insufficient data" call is the alternative.
- **Decisions #440–#442** (plain words): the "median" leak on 1 Nov is the rule being missed by the model, not the rule being wrong; R3 owns the check.
- **The Home hide-until-read rule** (Batch 96, "an unviewed brief outranks every action card"): it is what hides the pick on a tired morning (UX362-03).

## 11. Hypotheses (not verified)

- The ride nudge per activity probably trains him to ignore the nudge that matters (a missing check-in after a hard ride). Needs a count of ignored nudges; no read signal is stored.
- A Home that stops the morning call after the ride is logged would cut re-opens; no usage data.
- Mark's reading time on the brief page is unknown; I assumed he reads the call and scrolls. Ask him which sections he opens.

## 12. The first v14 weekly review, as Mark meets it (read 1 Nov 18:55–18:58 GMT)

**Evidence:** observed (stored row `reviews-v14-2026-10-29`, 3,086 characters, generated 18:00:57 GMT; the page rendered through the read-only mock at 390 px wide, light and large-text dark, with the review text injected into a copy of the real envelope; nothing stored or copied into this folder). Numbers are R8's §11 and R4's §9; this section is the screen and the words.

**Verdict: reads well, with one instruction that contradicts the next.** Grade unchanged at B.

| Check | What Mark meets | Verdict |
|---|---|---|
| Length | 546 words in five blocks (bottom line, trends, wins, worth watching, recommendations); about 3.7 phone screens of text under four number cards | Inside the v11 baseline of 457–615 words. The cards above it (Sleep, Recovery, Training load, Strength) make the written review start about 40% of the way down a 4.4-screen page |
| Opening | One sentence: mornings, sleep, key sessions all good, counts in his own words ("5 recovered · 2 some fatigue · 0 still recovering"), no colours | Good. Alone it would do; the push carries the same sentence (242 characters) |
| Plain words | Mostly: "fatigue", "protect", "wind down". Not: "median 78" and "median 67.5" (the review's own rule forbids it), "69.75–83" to two decimals, "ms", "bpm", "VO2", "20 °C disruption threshold", "settle date", "sleep-window habit" | One rule broken twice (UX362-04's word, second surface); the rest is cyclist's language he uses himself |
| What it asks of him | Five things: confirm whether Dumbbells B got done; keep logging the sleep habit; cool the bedroom before a warm night; wind down on Monday evening; choose between a ramp test or one small step up. Every one is optional ("Nothing changes unless you choose it") | One too many for a Sunday evening; the first is admin for the app, not for him |
| The recovery-week contradiction | The third recommendation says "No training changes needed … lighter targets … by design"; the last says "you look ready for a little more: a ramp test, or one small step up in your next hard session" | **The one real fault.** "Your next hard session" is Tuesday's 3 × 2 min VO₂ Light. A ramp test on a recovery week is not what the plan wants, and he has no way to ask which instruction wins. Same defect as R4's CI359-02 (the engine's note) and R8's ST363-02 (it equals three Greens); from the screen it is two opposite instructions in one list. Opt-in, nothing moves (Decision #459), so Medium here |
| Warm bedroom | "hit or crossed 20 °C on 3 of the 7 nights (average peak 19.9 °C)" then "cool the bedroom down beforehand — three nights this week crossed the 20 °C mark" | A reader sees "19.9 on average" and "20 on three nights" in one line. Two of the three were brief touches (R8); the advice repeats HS361-01 and ST363-01's lever. Said twice (worth watching and recommendations) |
| Sleep "rose through the week" | 74 → 77.8, "about 4 points higher" | Half a standard error (R8 ST363-09). He cannot tell; it is written as a fact, then used for "keep whatever you did" |
| Strength item | "Saturday's second strength session … is still showing as planned … just confirm whether that one got done" | Possibly already done: R4 saw a strength read stored on 1 Nov. If so, the review asks him to confirm something the app holds. Not checked further (R5/R2 lead) |
| Layout | Headings and bullets render cleanly; "Was this right?" buttons (Spot on / A bit off / Way off) and Regenerate sit at the foot; no contrast or target failures; three 20-px summary rows (the "How these numbers were worked out" disclosure and two thermal details) are the only small targets, same as wave #5 | Fine |

**What Mark will do with it.** Probably read the bottom line, the wins and "no training changes needed", and ride the recovery week as planned. The last bullet is the line he may act on in the wrong week, which is why the fix belongs with CI359-02 (one line, "Your next chance for a step up is the week of 9 Nov").

**Fix for the review's wording (copy only).** Drop "median" and the decimals ("usually 70 to 83"), say the bedroom point once, and keep the progress note off the recovery week. **Cost:** an hour with R4's and R8's changes; Craig's sign-off for Mark-facing copy. No new finding: it folds into UX362-04 (the word) and R4's CI359-02 (the note); the report stays at ten.

## 13. Limitations

- Headless Chromium is not his phone: no Android text scaling, no installed-PWA chrome, no real push; a mock answers instantly (no server time). The fixtures were dumped at 16:19 GMT, after the 1 Nov brief, so the 31 Oct and 1 Nov outage views are the real envelope transformed, not a capture from the day.
- Not rendered: the chat panel (messages checked in SQL), the builder beyond its first state, the Week page with no plan, symptom and chest notices, the chat panel's reply to the weekly review, the memory ask with a pending proposal, the FTP offer card (wording read in code).
- The first CSS build was wrong (Tailwind config not found from another working directory); every capture used for layout or audits was rerun on the corrected build. Text-only reads were unaffected.

## 14. Probe log

| When (GMT, 1 Nov) | What | Result |
|---|---|---|
| 16:15–16:20 | read brief, lens, state, scope, seven reports; usage 40% / 49% | — |
| 16:16–16:27 | `vite build` of the scratch copy of `083e012`'s `apps/web` (Node 24.21); rebuilt with the right working directory for CSS | 81 JS files, 502 KB gzip |
| 16:16–16:20 | `railway run --service api` → in-process FastAPI on a read-only connection (`default_transaction_read_only = on`, `SET TRANSACTION READ ONLY`, rolled back, user override, outbound hosts blocked, 240 s watchdog), 34 GET routes | 34 envelopes (35 files with the log); one GET that writes (notification preferences) refused by the read-only connection; two 422s (wrong query values) |
| 16:20–16:50 | mock server on 127.0.0.1:4329 (405 on every non-GET; log checked: one non-GET, my own smoke test, refused 405); Playwright, 390 × 844, fresh context per job, every non-GET aborted in the browser, every other host refused | 15 routes × 2 themes, 10 outage jobs, 24 story/state jobs, 0 refused calls |
| 16:25–16:40 | Supabase SELECTs (`coach` schema, projected, windowed): push counts by kind and day; check-in counts and answer counts; the chat messages since 18 Oct (read, not copied); activity start times 1 Nov; weekly-review sizes; two pushes' text | counts as cited |
| — | paid calls | **none** |
| 16:50 | processes stopped: mock, browser (see end of file) | — |
| 18:55–18:58 | Supabase SELECT: the one stored v14 weekly review row (3,086 characters, read, not copied) and its push (242 characters); read R8 §11 and R4 §9; started the read-only mock again (one process), rendered `/reviews` with the review text injected (two captures, scratchpad only); mock stopped (no listener, no browser left) | as cited in §12 |

**End of file:** the mock server, headless browser and dev build from 16:15–16:50 and 18:55–18:58 are all stopped (no listener on the mock's port, no browser process). Captures and the injected review text sit only in this session's scratchpad.
