# Review — how the daily call is worked out, explained and used (6 Oct 2026)

Reviewed at `44274a1` (production health reported the same SHA on 6 Oct). Lenses: senior
software engineer, AI engineer, cycling coach for masters athletes, strength and fitness
coach, sports-medicine doctor. Read-only: no code, production, Railway, Vercel or Supabase
change; no paid model call (the free token counter only); nothing sent to Mark. Section F
(predictions for 7–20 Oct) was committed first, on 6 Oct, before his first morning back
(`a4836d3`), and is unchanged since.

**Evidence labels** (as in `COACHING_INTEGRITY_AUDIT.md` and the 1 Oct review):
*observed* (production rows, logs or CI), *computed* (arithmetic over production rows),
*proved* (the app's own code run on production inputs, or a test run that shows it),
*implemented* (read in the code, not run). Ideas not yet checked are under Hypotheses.

The repo is public: Mark is quoted only in short phrases, and his notes and chat are not
reproduced.

---

## A. The verdict

1. **The call is mostly right and safe.** The replay reproduces production on 5 of 5 graded
   mornings; across 33,000 probes a worse input never gave a less cautious colour; every
   floor held; hard sessions ridden on Green mornings went well (89% of intervals on target).
2. **It does not push him too hard.** The one safety gap is the morning after a chest or
   heart report, which is an ordinary day by Craig's call of 2 Oct (Decision #375).
3. **It is not helping him progress.** His fitness has been flat since July, his FTP has not
   been tested since 27 Jan, the engine can only hold or reduce, the block's two peak weeks
   were lost, and nothing is planned from Mon 19 Oct.
4. **The explanation is the weakest part.** Home leads with a clear call but never shows
   which of his numbers made it; the written brief does, but last, after about 5,000
   characters of sleep detail and engine jargon, with two different "usual" HRVs and a
   "fair night" called "clearly off".
5. **Recovery advice is generic and never measured.** No rewrite is needed: four small
   batches after 20 Oct, Plan No. 3 before 19 Oct, and one caution-only fix for Craig to rule on.

### Scorecard

| Question | Grade | In one line |
|---|---|---|
| 1. Is the call right? | **B+** | Sound, reproducible and monotone; its cautious calls track worse mornings, but readiness re-counts sleep and his normal drifts with his own dips |
| 2. Is it explained well? | **C+** | Home: clear call, no numbers. The written brief: call last, jargon, inconsistent numbers, no "what would change it". For Craig: §4 is an accretion with no single decision table |
| 3. Is it helping him progress? | **C** | Nothing measures or prompts progress; FTP 8 months untested; no plan after 18 Oct |
| 4. Does it ever push too hard? | **A−** | No sign of overreach on 106 mornings; one rare, serious gap after a chest or heart report |
| 5. Does it get the most from recovery? | **C** | Rest days now read well (313), but tonight's advice is generic and its effect is never measured |

---

## B. How today's call is worked out now

```
 Garmin night + check-in (+ note,
 + his answer to Home's question)
            │
 ① FLOORS (acute rail)
   chest/heart, fever → no training
   head cold → easy riding (Red)
   HRV ≤ illness line, or under
   floor + RHR +4 / symptom,
   or RHR +7 → off the bike
   day after fever / open chest
   question → hard → easy spin
            │
 ② RATE 4 DOMAINS vs his normal
   autonomic · sleep · load · feel
   (none / mild / marked; low
   readiness confirms 1 mild)
            │
 ③ COMBINE
   2 marked or Rough → Red
   1 marked or 2 mild → Amber
   1 mild → Green, held
            │
 ④ GUARDS  age credit · missing row
            │
 ⑤ ACTION for each session
   Red → spin / shorter Z2
   light week, nothing marked → hold
   tired Amber → pick / shorter
   Amber → ease hard a zone
   held + hard → move or hold
            │
 ⑥ TODAY'S CALL (17 states), stored
   before the paid brief
            │
 ⑦ Home · brief · chat · calendar ·
   weekly review · Zwift proposal
```

**In words.** Each morning the app reads last night's Garmin data, his check-in (a 0–10
feel, a symptom answer and a free-text note) and his plan. Claude reads the note once
(about 0.8 cents) and can only add caution. Then everything is deterministic:

1. **Floors first.** A reported or written symptom, an illness-grade HRV night (at or under
   max(median − 2.5 SD, 70% of median), about 34 ms for him), a low night (under median −
   1.5 SD, about 39 ms) with resting HR up 4 bpm or a symptom, or resting HR up 7 bpm. A floor
   always wins. Since Batch 303, the two mornings after a fever, and any morning with an
   unanswered possible chest mention and a hard session, turn the hard session into an
   easy spin.
2. **Four domains, each rated against his own last 84 days.** Autonomic: last night's HRV,
   his 7-day HRV mean (mild under his normal minus 0.5 SD; marked under 1 SD, or after three
   mornings under 0.5 SD, or with last night under his floor; back to mild in the week after
   a holiday once two nights are back), and resting HR (+4 mild, +5 marked). Sleep: score
   under 74 or 60 (age-adjusted), and short nights. Load: Garmin's load ratio (1.3, 1.5),
   Garmin's recovery time (24 h, 48 h), and a hard yesterday before a hard session. Feel:
   his tap against his own spread, plus one notch if his note says unwell or unusually
   tired. Low Garmin readiness turns one mild sleep or load domain into marked, on purpose
   (Decision #379).
3. **Combine.** Two clearly-off domains, or a Rough tap, is Red; one clearly-off or two
   a-little-off is Amber; one a-little-off is Green with the targets held.
4. **Guards.** The age credit is never the only thing between Amber and Green; a missing
   Garmin day or sleep row turns Green into Amber.
5. **Each session gets an action**, most consequential first (the order is in
   `_session_action`). Strength, mobility and walks are always "as planned" unless a
   symptom stops all training.
6. **Today's call** is one of 17 signed-off states chosen from those actions (`todays_call`),
   stored with the morning before the paid brief, so it stands if Anthropic is down.
7. **Every surface reads that stored call.** The paid brief is written from the same stored
   packet and told to open its "Today's call" section with the headline word for word.

**How much decides a morning** (*implemented*, counted from the code): 7 floors, 13 signal
lines over about 22 numeric thresholds, 3 modifiers (readiness, age credit, missing row), 1
combination rule, a 10-way session-action ladder, 3 rest-day reasons and 17 call states:
about 60 decision points before any downstream consumer (the VO₂ gate, two-Reds rule,
weekly mix, swaps, delivery rail). The ladder still runs beside it (logged only) until
Batch 308. `THRESHOLDS` holds the numeric lines of the domains; the acute rail's lines live
as constants in `morning_verdict.py`, and the combination, the session-action order and the
call's precedence exist only as code. **There is no single decision table.**

**What actually decides his mornings** (*proved*, replay of 106 mornings): the sleep score
(17 marked, 11 mild), the 7-day HRV and persistence (14 marked, 12 mild), readiness
confirmation (13 domains, 7 colours). Load is rare and nearly always the July return; feel
fires on 3 of 63 eligible mornings (his tap sits at 6–8, SD 0.94).

### Where ARCHITECTURE §4 disagrees with the code

| §4 says | The code does | Label |
|---|---|---|
| "Analysis engine (the heart — Claude generates it)" and "Green/Amber/Red workout verdict" | A deterministic engine decides; Claude explains. Mark has seen no colour since Batch 313 | implemented |
| The 296 summary: "a recovery-class block … holds the session" | Since Batch 300 only a morning with nothing marked holds; a marked domain eases (the 300 note further down says so; the summary does not) | implemented |
| "Missing data never makes the day better" | True only when a whole Garmin day or sleep row is missing. A row without an HRV reading or sleep score rates that signal as normal (3 of 107 mornings had no HRV) | implemented, computed |
| "Every line is in one table, `THRESHOLDS`" | The domain lines are. The acute rail's lines, the combination, the action order and the call's precedence are not | implemented |
| Load: "yesterday's load" | Counts only before a hard session since Batch 305 (stated further down, not in the summary) | implemented |
| The brief's metrics table reads `Metric · Last night · Status` | The 5 Oct brief's table reads `Metric · Today · Your usual (median) · Delta` | observed |
| (silent) | Readiness, which §4 says "confirms at most one mild domain", decided 7 of 106 colours, 3 of them Red | proved |

§4's verdict part is 7 summary bullets followed by 30 dated batch notes. It is accurate as
history and hard to use as a model.

---

## C. Findings, most severe first

Severity: **High** (misleads Mark, risks harm, or costs real training), **Medium**, **Low**.

### DV-1 · High · Nothing is planned after Sun 18 Oct, and nothing tells Mark

- **Evidence:** *observed* (plan_blocks end at W13 TAPER, 18 Oct; no later row; no generated
  draft) and *implemented* (`atBlockBoundary` is computed and in the shared schema, but no
  screen reads it; `todays_call` returns "No session planned" outside a plan week).
- **What Mark experiences:** from Mon 19 Oct every morning reads "No session planned · There's
  nothing in your plan for today yet", while the engine keeps grading his recovery for
  nothing. The coach stops coaching, two weeks after his plan's peak was lost (DV-2).
- **Fix:** Craig loads Plan No. 3 before 19 Oct, with an FTP test in its first week and two
  loaded, progressing strength sessions a week (no code). Then a small card on the block
  boundary ("Your plan ends Sun 18 Oct") from the flag that already exists.
- **Cost:** the plan is Craig's time; the card is about half a day of web work.

### DV-2 · High · Nothing measures or prompts progress, and the engine can only hold or reduce

- **Evidence:** *observed*: one FTP test on record (27 Jan 2026, 20 min 289 W); FTP 280 W in
  the knowledge base and on Zwift since April; Garmin VO₂max 53.5 (mid-Jun) to 55.6 (Sep),
  flat since early July; watts per heartbeat on steady Zone 2 rides flat Jun–Sep (1.58–1.66);
  heart rate at sweet-spot power unchanged (129.4 vs 128.8 bpm, like for like). *Implemented*:
  the graded actions are as planned, hold, move, ease, pick, shorter, spin, off the bike, no
  training; none progresses. The FTP-drift signal compares watts per heartbeat across every
  ride type, so it moves with the session mix: the weekly reviews told Mark to raise FTP to
  295 W (29 Jun) and to consider 272 W (31 Aug) (*observed*). The block generator, the only
  path that could raise FTP, has never run, and would not change Zwift's FTP if it did.
  *Computed*: Plan No. 2's two peak weeks (21 Sep–4 Oct) delivered none of their 2 VO₂
  sessions or 2 long rides (three ladder Reds, then the holiday).
- **What Mark experiences:** a coach that tells him when to ease off and never when he is
  ready for more; contradictory FTP advice in the reviews; a block that ends without its peak.
- **Fix, smallest first:** (1) an FTP or 20-minute test in Plan No. 3's first week (no code);
  (2) restrict the drift signal to fixed-power rides (heart rate at his Zone 2 and sweet-spot
  power), which ERG makes clean, and stop the reviews quoting a new FTP from it; (3) a
  "ready to progress" note when three hard sessions in a row hit at least 90% of intervals
  with normal next mornings.
- **Cost:** (1) none; (2) about half a day; (3) about a day, plus Mark-facing wording.

### DV-3 · High (rare, safety, caution-only) · The morning after a chest or heart report is an ordinary day, VO₂ included

- **Evidence:** *implemented* and decided (Craig, 2 Oct; STATUS "Needs Craig" 7; Decision
  #375 "Not chosen"). It has never happened (*observed*: no symptom answer other than None).
- **What Mark experiences:** he taps "Chest or heart" on Tuesday and is told to call 111 or
  his GP; on Wednesday, if he taps None and his numbers are fine, he reads "Green light ·
  Make it count" before a VO₂ session, and nothing asks whether he was checked.
- **Why it matters:** exertional chest pain, palpitations, faintness or unusual
  breathlessness in a 57-year-old lifelong endurance athlete warrant assessment before
  vigorous exercise resumes (the ESC 2020 sports-cardiology guideline, Pelliccia 2021; the
  IOC 2022 consensus's return-to-exercise checklist stops progression and sends the athlete
  to a doctor on chest pain, palpitations or breathlessness during or after exercise,
  Schwellnus 2022). Endurance athletes carry roughly two and a half to five times the
  atrial-fibrillation risk of non-athletes (Newman 2021; Abdulla 2009), rising with years and
  volume of training (Andersen 2013).
- **Fix (caution-only):** for the mornings after a "Chest or heart" answer, Home asks one
  question ("Have yesterday's chest or heart symptoms gone, and have you spoken to your GP or
  111?") and the hard session takes Batch 303's existing easing until he answers. No new
  machinery; one new question and its words.
- **Cost:** about half a day plus wording sign-off. **This is the only finding that may land
  before 21 Oct, and only on Craig's go** (decision 1 below).

### DV-4 · Medium · Home says what to do but not why; the written brief says why but last

- **Evidence:** *implemented*: Home's hero shows the call's headline, its generic line
  ("There's some fatigue about…") and the reading; the engine's own one-line reason with his
  numbers (`graded.summary`, e.g. "your 7-day HRV average has been below your usual for 6
  mornings running (43 ms against 47)", signed off in Batch 296) reaches no screen; it appears
  only inside the paid brief. `morning_output_contract` orders up to six sections and puts
  "Today's call" last. *Observed* (5 Oct, v57): 6,728 characters, about 1,050 words; the call
  starts after sleep stages, a metrics table, four experiments and chronic actions.
- **What Mark experiences:** Home tells him what to do in five seconds but not which of his
  numbers made the call; to find out he opens a 4–5 minute read whose action is at the
  bottom, explained in engine terms ("domain", "autonomic", "the marked weekly one",
  "standard deviation"); nothing says what would change the call; tonight's advice is one
  line ("a short wind-down breathwork session").
- **Target, against your five checks** (5 Oct, the only brief written under v57; the other
  13 of the last 14 were ladder Reds or holiday rest days written before 313):

  | Check | 5 Oct | Target |
  |---|---|---|
  | Leads with what to do | No (section 6 of 6) | First line |
  | The few numbers against his normal | Yes, but 11 table rows and two "usuals" | 2–3 numbers, one normal |
  | Why, and what would change it | Why: yes, in jargon. Change: no | One line each |
  | Tonight's recovery | One generic line | One specific line tied to today's reason |
  | Agrees with Home, chat, calendar, review | Headline and reading word for word: yes | Same, and checked (DV-9) |
  | Under a minute on a phone | No | The call section alone, under 120 words |

- **Fix, smallest first:** (1) show the stored one-line reason under Home's hero (web only;
  words already signed off); (2) move "Today's call" to the top of the brief with a fixed
  shape (the headline and reading; two or three numbers against his normal; one "because";
  one "this would change it"; one "tonight"), and fold the detail below it. Prompt bump;
  self-healing.
- **Cost:** (1) a couple of hours; (2) about a day, plus Mark-facing wording sign-off for
  the new lines.

### DV-5 · Medium · Two "usual" HRVs in one brief, and a fair night called "clearly off"

- **Evidence:** *observed* on 5 Oct: "below your usual 47 ms" (the acute rail's median) and
  "your usual 46.3 ms" (the engine's mean), and the metrics table's "Your usual" of 47 for the
  7-day average (Garmin's own 7-day baseline). *Observed* on 3 and 4 Oct: "Two things are
  clearly off: … and a fair night's sleep (score 68) (your readiness agrees)". *Proved* by
  probe: every readiness-confirmed fair night reads that way (181 of 3,000 random cases).
- **What Mark experiences:** numbers that do not quite agree, and a night called both fair and
  clearly off in one sentence, which reads as the app overstating.
- **Fix:** one HRV normal, the engine's, used by the rail, the table and the words; and a
  phrase for the confirmed case ("a fair night that your readiness says cost you more than
  usual").
- **Cost:** about half a day (the rail's median becomes a display choice), plus wording.

### DV-6 · Medium · Readiness confirmation decides 7 of 106 colours, 3 of the 7 Reds, and it re-counts sleep rather than HRV

- **Evidence:** *proved* (replay, 106 mornings): confirmation raised 13 domains and decided 7
  colours: 12 Aug, 21 Aug, 30 Aug and 4 Sep (Green held to Amber), and 28 Aug, 3 Oct and 4 Oct
  (Amber to Red). *Computed* (107 mornings): readiness correlates with his sleep score
  (r 0.68), Garmin's recovery time (r −0.70) and resting HR (r −0.55), but barely with his
  overnight HRV (r 0.17).
- **What Mark experiences:** three Reds came from a fair night counted twice. Only one session
  action changed (30 Aug, a long ride offered shorter), because most fell on rest days.
- **Why it matters now:** Batch 311's candidate (a), "readiness cannot confirm while Garmin's
  HRV status is below Balanced", aims at the HRV overlap, which his data says is small. The
  overlap that decides colours is with sleep.
- **Fix:** add to 311's replay a candidate (c), "readiness confirms load only", and (d),
  "readiness never confirms"; decide on the replay that includes his return. A change amends
  Decision #379.
- **Cost:** included in 311's replay (about half a day); building either is under half a day.

### DV-7 · Medium · His normal includes the week it judges, and a low holiday week lowers it for 12 weeks

- **Evidence:** *implemented*: both the acute rail and the 7-day rating take his normal from
  the 84 nights before this morning, this week's included. *Proved* by probe: a worse earlier
  night this week can lower his normal enough to lift an off-the-bike floor (9 of 3,000
  random cases; status never fell, actions did). *Computed*: with the holiday nights in it,
  his normal on 7 Oct is 46.05 ms (SD 5.13) against 46.71 ms (SD 4.82) without them, so both
  lines sit about 1 ms lower, and stay lower until the nights leave the window on 29 Dec.
- **What Mark experiences:** nothing visible; for twelve weeks after any low week the engine
  is slightly more lenient than his real normal. The trials set the normal from an
  undisturbed baseline (Vesterinen 2016 says it "should not be performed under extensive
  stress factors").
- **Fix:** take his normal from nights 8–91 days back (exclude the current week), and leave
  nights away out of it. Replay first; it changes colours, so after 20 Oct with 311.
- **Cost:** about half a day plus the replay.

### DV-8 · Medium · The load domain is the least informative, and its 1.3 line flags Garmin's "optimal"

- **Evidence:** *computed*: the five mornings made cautious by load alone were followed by a
  normal next morning four times (next-morning HRV +2.6 ms against his normal), against 5 of 21
  for autonomic or sleep cautious mornings. The ratio reached 1.3 on 7 mornings, all in the
  July return; recovery time over 24 h on 9, over 48 h never. No load-only morning had a hard
  session, so no ride has paid for it yet.
- **What Mark experiences:** "some fatigue" on mornings he is fine, mainly on easy days.
- **Fix:** 305's queued load-ratio line (mild from 1.5) is supported; also count recovery time
  only before a hard session, as 305 did for a hard yesterday.
- **Cost:** as queued, plus about an hour for the recovery-time line.

### DV-9 · Medium · Nothing checks the written brief against the call or the packet, and the brief has no eval

- **Evidence:** *implemented*: after the paid call the only check is a logged warning when a
  required heading is missing (`write_brief`). The notes reader has a pinned eval (Batch
  307); the morning brief has none. The graded system prompt still mentions
  "Green/Amber/Red verdict" in four places while `TODAYS_CALL_RULE` forbids colours.
- **What Mark experiences:** today, nothing wrong was seen (5 Oct opened word for word). A
  future prompt or model change could put a wrong number or a colour in front of him with no
  alarm.
- **Fix:** a deterministic post-check (the call section opens with the stored headline and
  reading; no colour words; each HRV, sleep and resting-HR number quoted is one the packet
  holds), sent through the existing `admin_alert` tag; and a small recorded eval of about
  ten stored packets, re-run only at prompt bumps (the 307 pattern).
- **Cost:** about a day; the eval's first paid run about $1–2, Craig's go.

### DV-10 · Medium · Strength is protected but never coached

- **Evidence:** *observed*: the plan repeats one 22-minute dumbbell session and one 15-minute
  bodyweight session every week for 13 weeks; loaded sessions fell to 2 in September while
  short bodyweight days rose to 19. *Implemented*: non-bike sessions are always "as planned"
  and add about 3–5 units of Garmin load, so they never count as load.
- **What Mark experiences:** the call never crowds out strength, which is right, but nothing
  progresses it. At 57 the evidence favours at least two weekly sessions that load the major
  muscle groups and progress, plus some impact or heavy work for bone, which cycling does not
  provide (WHO 2020; ACSM).
- **Fix:** Plan No. 3 content, two loaded, progressing sessions a week (no code).
- **Cost:** plan content only.

### DV-11 · Medium · Recovery advice is generic and its effect is never measured

- **Evidence:** *observed* (5 Oct: "a short wind-down breathwork session tonight"; the
  chronic REM levers; all four experiments "inconclusive"). *Implemented*: tonight's projection
  (Batch 46) is advisory and nothing records whether the advice was followed.
- **What Mark experiences:** the same kind of advice whatever made the morning cautious.
- **Fix:** tie tonight's line to today's reason (a sleep-marked morning: the sleep window and
  the room; an HRV-low week: alcohol, late meals and stress; a load morning: food and an
  earlier night), add a one-tap "did it" at the next check-in, and report next-morning change.
  Evidence for most of these levers is weak to moderate; say so in the words.
- **Cost:** one to two days.

### DV-12 · Low · Withholding a swap on an off-the-bike day has no test

- **Evidence:** *proved* locally: removing the rule (`morning_analysis.py`, swap withheld when
  bike rest applies) failed no test, and no test names it. The same defect shipped on 22 Sep
  (Batch 277). Two other surviving mutants are covered by Postgres tests (skipped on this Mac)
  or are near-equivalent.
- **Fix:** one test. **Cost:** under an hour.

### DV-13 · Low · A missing HRV reading or sleep score counts as normal

- **Evidence:** *implemented*; 3 of 107 mornings had no HRV reading.
- **Fix:** reword the claim in `THRESHOLDS` and §4, or carry the last rating for one morning.
- **Cost:** under an hour to reword; half a day to carry.

### DV-14 · Low · Three call lines say more than the engine knows

- **Evidence:** *proved* by probe. A head-cold morning with normal numbers reads "Recovery
  day · Your body's still recovering"; a missing-row Amber reads "There's some fatigue
  about"; a still-recovering day with only strength shows the green "go" look (Craig's 5 Oct
  line). None has happened on a real morning.
- **Fix:** a cold-specific line, and a "not enough data" line. Wording sign-off.
- **Cost:** under half a day.

### DV-15 · Low · ARCHITECTURE §4 no longer works as a model

- **Evidence:** *implemented* (the table in section B).
- **Fix:** with 308, rewrite §4's verdict part as the section-B diagram and one decision
  table (floors, domains, combination, actions, call precedence), with dated notes moved to
  DECISIONS.
- **Cost:** about half a day, docs only.

### DV-16 · Low · Cost and size are fine

- **Evidence:** *observed*: about 35,500 input and 2,000–8,000 output tokens per brief, no
  prompt caching, so about $0.10–0.15 a brief at $2/$10 per million tokens. *Proved*: the
  free counter gives 35,497 tokens for 5 Oct's request, exactly what production recorded; the
  system prompt is 8,935 of them; the largest packet sections are the verdict (13 KB), the
  experiment loop (11 KB) and the knowledge base (9 KB).
- **Fix:** none needed. Caching the system prompt would save about a fifth of input cost.

### C.1 Outcomes: did cautious calls come before worse outcomes?

All *computed* over the 106 replayed mornings, each scored by the graded engine as it would
have called it (the "graded" column; most mornings were shown the ladder's call, which
changed what he rode). Differences are cautious minus Green, with bootstrap 95% intervals.

| Outcome | Difference | 95% interval | n |
|---|---|---|---|
| Same-morning HRV against his 28-night mean (by construction) | −2.6 ms | −4.9 to −0.3 | 32 v 49 |
| Next-morning HRV | −0.9 ms | −3.1 to +1.4 | 32 v 49 |
| HRV two mornings later | +0.3 ms | −1.8 to +2.4 | 31 v 48 |
| Next-morning resting HR | **+0.9 bpm** | +0.3 to +1.5 | 32 v 52 |
| Next night's sleep score | −0.3 | −5.0 to +4.3 | 35 v 55 |
| Next morning's feel | −0.2 | −0.7 to +0.3 | 24 v 43 |
| Share of hard-session intervals on target (per session) | **−0.36** | −0.65 to −0.09 | 7 v 15 |

- **Cautious calls mark a real state, which mostly clears within a day.** Resting HR stays
  higher the next morning; HRV does not, except when the week was already low: with last
  night 4+ ms under his normal, cautious mornings were followed by −4.4 ms, other mornings by
  −0.6 ms (n 13 v 10).
- **By the domain that made the call:** autonomic or sleep cautious mornings were followed by
  a normal morning 5 of 21 times; load-only ones 4 of 5 (DV-8). For comparison, 25 of 49 Green
  mornings were followed by a normal morning.
- **Green and ridden went well:** 15 hard sessions on Green mornings, 89% of intervals on
  target (89 of 108), next-morning HRV −0.3 ms against normal, 8 of 14 next mornings normal.
- **Flagged and ridden went less well:** 7 sessions, 53% (per session; 62% without 23 Jun's
  30/30, graded before Batch 214's segmentation fix). Two of the seven (8 and 23 Jul) were
  ridden as something other than the plan, so the gap is directional only.
- **The known bad patches.** 16 Jul (33 ms, sleep 57): at the time shown Green; the graded
  engine now takes him off the bike that morning, with no earlier warning (14–15 Jul were
  Green). 28 Aug: Red on the day under both engines, nothing the days before, Green the day
  after. The late-September dip: graded Amber from its first low night (21 Sep) to Red on 27
  Sep. The holiday: Amber from the first low night (1 Oct). Pre-app, and illustrative only
  (HRV before the reliability date): a November–December 2025 episode would have been
  flagged on 24 Nov (resting HR +5), four days before resting HR +7 and eight before an
  illness-grade night.
- **False alarms.** 11 of 30 cautious mornings (not floors) were followed by a fully normal
  next morning (HRV within 2.5 ms, resting HR within 1 bpm, sleep 74+), against 25 of 49 Green
  mornings. Most of the 11 were load or single-signal mornings.
- **Too thin to say:** post-ride effort and feel (n 46 flagged, and some effort entries look
  like a different scale); anything about the graded engine's own calls on training days
  (none yet; the first is 7 Oct).

**What to record from now on, so this can be answered properly:**

1. Which version he rode for each session (planned, eased, picked, self-edited), linked to the
   proposal that was pushed; today only the planned prescription is graded.
2. One clean post-ride effort (0–10) and "legs" answer, the same scale every time.
3. Whether he followed the call (call against what he rode), stored with the morning.
4. A monthly fixed-power check (heart rate over 20 minutes at his Zone 2 power, in ERG) and a
   test each block, so fitness has a measure that ERG does not fix in advance.
5. Garmin's readiness breakdown (its HRV, sleep and recovery factors) with each morning, so
   311 and DV-6 can be settled on data.
6. His dissent taps (stored since 274; none yet).

### C.2 Progression

| Measure | June | Now | Label |
|---|---|---|---|
| FTP basis | 280 W, test of 27 Jan | 280 W, untested | observed |
| Garmin VO₂max | 53.5 | 55.6 (flat since early Jul) | observed |
| Chronic load | 714 | 741 at the September peak, 291 now (holiday) | observed |
| Watts per heartbeat, steady Z2 | 1.58 (n 3) | 1.62 in Sep (n 7) | computed |
| Drift on long Z2 rides | 5.2% (Jul) | 0.9% (Sep, n 5; season may explain it) | computed |
| Resting HR / HRV (monthly) | 44.8 bpm / 46.8 ms | 44.2 / 46.8 (Aug) | computed |
| Best efforts | ERG prescriptions only; cannot show change | — | observed |

**Stimulus cost** (*computed*, 15 Jun–26 Sep, 36 key sessions, holidays excluded): 11 (31%)
were moved, eased, cut or lost after an Amber or Red; 20 of 27 (74%) hard sessions were
ridden in full, the same ratio as Vesterinen 2016's HRV-guided group (13.2 against 17.7
sessions, 0.75). Long rides paid most: 4 of 9 changed. Since 30 Sep: 4 key sessions planned,
all holiday-skipped, so the graded engine has decided none (the first is Thu 8 Oct). The
replay says the graded engine would have changed fewer: of 42 key sessions, 26 as planned,
8 held or moved, 2 eased, 1 recovery, 1 off the bike, against the ladder's 12 cut.

**Does anything tell him to progress?** No morning ever suggested a harder session or a
test; one weekly review (29 Jun) told him to raise FTP, from the noisy drift signal (DV-2).

### C.3 Complexity

Counted in section B: about 60 decision points, two engines until 308, no single decision
table. **Dead or near-dead on his data** (*computed*): the 7-day 1 SD line (3 mornings,
all this week), recovery time over 48 h (never), resting HR +5 and +7 (never since the app
started), feel mild and marked (1 each), total sleep marked (1), the illness line (once, 16
Jul). **Duplicated:** "hard session" is defined four ways (the scaling rule's own test,
`todays_call`'s workout-type list for old mornings, the replay's list, and the
hard-yesterday thresholds); his "usual" HRV three ways (DV-5). **Contradictory:** none in
the decisions; two in the words (DV-5, DV-14). **Untested:** DV-12. **Tests:** the verdict
selection passes locally, 214 passed and 25 skipped (Postgres tests skip on this Mac); in a
scratch copy, removing each of 30 rules made a test fail for 27 (*proved*).

**Invariants, probed on the real functions** (*proved*, 3,000 seeded random mornings, about
11 one-input worsenings each, 33,000 comparisons):

- **Worse inputs never gave a less cautious colour.** Session actions were less cautious in
  two named cases: a light-week Zone 2 ride labelled "hold the targets" becomes "as planned"
  when something is clearly off (the same ride; Decision #373), and DV-7's baseline drift.
- **Floors always won** (chest, fever, head cold, off the bike): 0 failures.
- **The words never contradicted the colour**, with the three exceptions in DV-5 and DV-14.
- **The same stored packet always gave the same call**, and every surface reads that one
  stored call (Home, the brief page, chat, the calendar and the weekly review read
  `todaysCall` or its reading).

### C.4 The explanation as Mark reads it

Covered in DV-4 and DV-5. Of the last 14 mornings (22 Sep–5 Oct), six were ladder Reds
written under prompt v46, eight were holiday rest days, and only 5 Oct (regenerated after
313) carries today's call; no training morning has yet been graded and written under the
current words. Against your five checks: Home's hero leads with what to do, agrees with every
surface and has a Tonight section, but shows no numbers and no "why" beyond a generic line
(the numbers sit in the collapsed sleep table); the written brief has the numbers and the
why, but last, in jargon, and with no "what would change it".

### C.5 By lens, what is near-optimal

- **Software engineer:** the pipeline is pure where it matters, stored before the paid call,
  reproducible (5 of 5), and monotone in colour. Near-optimal; DV-7, DV-12 and DV-15 remain.
- **AI engineer:** Claude decides nothing about the call; the notes reader can only add
  caution and has a pinned eval; the brief is written from the stored packet. Missing: an
  output check and an eval for the brief (DV-9). Cost is fine (DV-16).
- **Cycling coach:** the HRV lines are faithful to the trials' threshold (0.5 SD of his daily
  readings, as Vesterinen 2016 defines it; raw against log values disagree on 0 of 83
  mornings, so raw is fine for him) and more lenient than them in three ways Craig chose: a
  dip under the line holds or moves for two mornings before easing, hard work resumes once
  back inside the band rather than at his mean, and only low readings count (the trials used
  both sides). For a 57-year-old building fitness, 74% of hard sessions in full matches the
  best trial; the cost is in long rides and in progression (DV-2).
- **Fitness coach:** non-bike work is protected; it needs load and progression (DV-10).
- **Doctor:** the floors are sound and rare (one off-the-bike morning in 106); return after
  fever is shorter than the IOC's graded return but has a floor; the gaps are DV-3, the
  medication question (no medication or medical history in the knowledge base, *observed*),
  and the SpO₂ dips (Hypotheses).

---

## D. The target, and the smallest path to it

**An optimal morning for Mark**, on one phone screen:

> **Take the edge off** · Some fatigue
> Your 7-day HRV is 41 ms against your usual 46, three mornings running. Ride Thursday's
> sweet spot in full, with the 30-minute block at 76% instead of 89%.
> *It would be a green light, targets held,* once two nights in a row are back above 44 ms.
> *Tonight:* no alcohol and lights out by 22:45; that is when your HRV has recovered fastest.

Behind it: one normal per signal, every number the engine used shown once against it, the
call checked against the packet after it is written, a record of what he rode and how it
went, and a monthly fixed-power check and a test each block so "is he fitter?" has an answer.

**The smallest path** (no rewrite; the engine is sound and a rewrite would discard 300
batches of pinned behaviour for no gain shown here):

1. Before 19 Oct, no code: Plan No. 3 with an FTP test in week 1 and two loaded strength
   sessions a week (DV-1, DV-2, DV-10).
2. Only on Craig's go, the caution-only fix in DV-3.
3. After 20 Oct, in the order of section E: the load line (DV-8), 311 widened (DV-6, DV-7),
   308 with §4 rewritten (DV-15), the brief leads with the call (DV-4, DV-5, DV-9), progress
   gets a signal (DV-2), tonight's advice from today's reason (DV-11), and the small fixes
   (DV-12 to DV-14).

---

## E. Proposed batches (draft ledger rows; not added to the ledger)

Ordered around what is queued: 305's load-ratio line → 311 → 308, Plan No. 3 before 19 Oct,
and nothing before 21 Oct except E0 on Craig's go.

| Batch (draft) | When | Goal | Acceptance criteria |
|---|---|---|---|
| **E0 — After a chest or heart report, ask before hard work** | Only on Craig's go; otherwise after 20 Oct | DV-3. The mornings after a "Chest or heart" answer ask one question and ease a hard session until he answers. Amends Decision #375 | The 303 easing applies after a chest answer until his one-tap reply; no change on any stored morning (none has a chest answer); wording signed off; replay unchanged on all 106 mornings |
| **Plan No. 3** (Craig, no code) | Before Mon 19 Oct | DV-1, DV-2, DV-10 | Plan blocks from 19 Oct; an FTP or 20-minute test in week 1; two loaded, progressing strength sessions a week |
| **305's load-ratio line**, as queued, plus recovery time only before a hard session | First after 20 Oct | DV-8 | The replay over every stored morning including 7–20 Oct lists the changed mornings; no hard session changes without being listed |
| **311, widened** | After the load line, before 308 | DV-6, DV-7. Add candidates: readiness confirms load only, or never; the normal excludes the current week and nights away | One replay with each candidate alone and together; Craig decides each; new decisions amend #379 and #366/#377 where they change |
| **308, and §4 rewritten as one decision table** | After 311 | DV-15 | The ladder deleted; §4's verdict part is the diagram and one table; dated notes live in DECISIONS |
| **The call says why, first** | After 308 | DV-4, DV-5, DV-9 | Home shows the stored one-line reason under the hero; the brief's call section comes first, under 120 words, with one HRV normal; a post-check alerts on a mismatch, a colour word or an unknown number; a recorded 10-packet eval; prompt bump, self-healing; wording signed off |
| **Progress has a signal** | Once Plan No. 3 is loaded | DV-2, and the block-end card from DV-1 | Drift from fixed-power rides only; the reviews stop proposing an FTP from it; a "ready to progress" note on three hard sessions at 90%+ with normal next mornings; the block-end card |
| **Tonight's advice from today's reason, measured** | After the above | DV-11 | Tonight's line names the reason; a one-tap "did it"; the weekly review reports next-morning change, labelled weak evidence |
| **Small fixes** | Any time after 20 Oct | DV-12, DV-13, DV-14 | A test for the swap on an off-the-bike day; the missing-data claim reworded; the cold and missing-data call lines signed off |

276 stays as it is (only if Mark contests a figure).

---

## F. Predictions for 7–20 Oct, written before the trial

### How they were made

The real engine was run read-only over Mark's real history to 6 Oct (every morning-phase
HRV and resting-HR row, sleep, check-in feel, baselines, plan blocks, the holiday window
and the plan rows for 7–20 Oct), with hypothetical nights appended from 7 Oct, through the
real acute rails (`_hrv_rail`, `_rhr_rail`), `grade()` and `todays_call()`. The script is
kept beside this review (`docs/reviews/2026-10-06-daily-verdict-review/predict.py`; it reads
only, and its session rolls back). Simplifications, each stated: resting HR, readiness,
sleep and feel are set per scenario; recovery time is 0 and yesterday's load is not hard;
the load ratio is a rough projection of Garmin's (proprietary) model, so it is varied
separately below.

What the engine does **given** a night is *proved*: it is the code's own output. Which
nights he will have is not knowable, so the scenarios bracket it, and the probabilities
in P1–P12 are my judgement, stated so they can be scored.

**Where he starts (observed, 6 Oct):** nightly HRV 38, 36, 39, 37, 38, 38 ms on 1–6 Oct
against a usual of about 46 (his lowest week on record); resting HR 44–47; readiness 50–60
against a lower quartile of 53.8; Garmin's chronic load 291 and falling about 27 a day;
acute load 8. His acute floor for a single night is about 39.3 ms and his illness line
about 34.2 ms. His highest night on record is 60 ms.

### The scenarios, through the real engine (*proved* on hypothetical inputs)

| Morning (plan) | A: nights back to 47 from 7 Oct | B: gradual 41, 43, 45, 47 | C: nights stay 40 to 13 Oct | D: as A, poor night before 8 Oct | E: fair night + readiness 50 on 7 Oct |
|---|---|---|---|---|---|
| Wed 7 (Z2 60) | As planned · Some fatigue | As planned · Some fatigue | As planned · Some fatigue | As planned · Some fatigue | **Short and easy · Still recovering** (Red) |
| Thu 8 (Sweet Spot 1×30 @ 89%) | **As planned — hold the targets** (310 fires) | Take the edge off (89% → 76%) | Take the edge off | **Easy or tempo — your call** (306's card) | As planned — hold the targets |
| Fri 9 (nothing) | Rest day · Recovered | Rest day · Some fatigue | Rest day · Some fatigue | Rest day · Recovered | Rest day · Recovered |
| Sat 10 (Easy Z2 45) | As planned — hold the targets | As planned — hold the targets | As planned · Some fatigue | As planned — hold the targets | As planned — hold the targets |
| Sun 11 (Easy Z2 90) | Green light | As planned — hold the targets | As planned · Some fatigue | Green light | Green light |
| Mon 12 (strength) | Green light | Green light | As planned · Some fatigue | Green light | Green light |
| Tue 13 (VO₂ primer 3×1 @ 120%) | Green light | Green light | **Take the edge off** (120% → 94%) | Green light | Green light |
| Wed 14 (Z2 45) | Green light | Green light | As planned · Some fatigue | Green light | Green light |
| Thu 15 (SS primer 1×12 @ 89%) | Green light | Green light | **Take the edge off** | Green light | Green light |
| Fri 16 (nothing) | Rest day | Rest day | Rest day · Some fatigue | Rest day | Rest day |
| Sat 17, Sun 18 (Z2 40, optional 45) | Green light | Green light | Green light | Green light | Green light |
| Mon 19, Tue 20 (no plan) | **No session planned** | No session planned | No session planned | No session planned | No session planned |

Load ratio sensitivity: with A's nights and a load ratio of 1.35 on 12–15 Oct, those four
mornings become "Green, targets held" and the VO₂ and sweet-spot primers are held at their
targets (no change to what he rides). With C's nights and 1.55 on 12–15 Oct, 12–15 Oct go
Red: the VO₂ primer and the sweet-spot primer become recovery spins and the Z2 is shortened.

### Deterministic predictions (the engine, given his nights)

- **E1. Wed 7 Oct cannot be "Recovered".** His normal for 7 Oct is 46.05 ms, SD 5.13
  (84 nights). His 7-day mean stays under the 1 SD line (40.9 ms) for any night under
  60.4 ms, and under the smallest-worthwhile-change line (43.5 ms), with a streak well past
  three mornings, for any night under 78 ms; his highest night on record is 60. So 7 Oct is
  at least "Some fatigue". The Z2 ride stays at full length unless a second domain is
  clearly off (a sleep score under 60, about 5.6 h or less, a fair night with readiness
  under 53.8, feel 4 or less, resting HR +5): then Red, "Short and easy", Z2 shortened.
- **E2. Thu 8 Oct's sweet spot turns on two nights.** If his HRV on the nights dated 7 and
  8 Oct is each at least about 43.5 ms and nothing else is clearly off, Batch 310 fires for
  the first time: "As planned — hold the targets", ridden at 89%, and the summary reads
  "your HRV is back to normal, but your 7-day average is still catching up after your
  holiday". If either night is under that line, the sweet spot is eased to 76% at full
  length ("Take the edge off"), or, after a poor night or a flat feel, Home shows the pick
  card for the first time ("Easy or tempo — your call").
- **E3. Fri 9 and Fri 16 read "Rest day"** with his reading, never "No session planned".
- **E4. Mon 19 and Tue 20 read "No session planned"** whatever his numbers, because no plan
  is loaded after 18 Oct. The reading chip still shows.
- **E5. The holiday catch-up can act only on 8–12 Oct** (the mornings whose 7-night week
  holds a night away). From 13 Oct a lagging 7-day mean is judged as any other dip: if his
  nights are slow to return (C), the taper's VO₂ and sweet-spot primers are eased on the
  average alone, with a "13 mornings running" streak that counts his holiday.
- **E6. In the taper (12–18 Oct) his HRV is judged against his recovery-week normal**
  (about 45.3 ms, not 46), so the lines sit about 0.8 ms lower.
- **E7. An off-the-bike morning needs a night at or under about 34 ms**, or under about
  39 ms with resting HR up 4 bpm or more, or a symptom. "No training" needs a symptom.

### Probabilistic predictions (my judgement, to be scored)

| # | Prediction | Probability |
|---|---|---|
| P1 | 0–2 Red mornings in 7–20 Oct | 80% |
| P2 | Any Red falls on 7–10 Oct and has readiness confirming a fair night, or a sleep score under 60 | 70% |
| P3 | 8 Oct's sweet spot is held at its targets by the holiday catch-up (E2) | 45% |
| P4 | Autonomic is clear (no HRV concern) on at least one morning by 12 Oct | 70% |
| P5 | 13 Oct's VO₂ primer and 15 Oct's sweet-spot primer are each "Green light" | 65% each |
| P6 | The load ratio never reaches 1.5 in 7–20 Oct, and changes no hard session's action | 85% |
| P7 | Ladder and graded disagree on 2–5 mornings, all one step, the ladder the more cautious; no two-step (ladder Red, graded Green) alert | 70% |
| P8 | The replay reproduces production on every morning he checks in | 95% |
| P9 | Every written brief's "Today's call" opens with the stored headline and reading | 95% |
| P10 | His nightly HRV is back at or above 44 ms on two nights in a row by 9 Oct | 60% |
| P11 | Hard sessions ridden at their targets on "Recovered" or held mornings hit at least 70% of work intervals on target (his norm is 72%) | 65% |
| P12 | No off-the-bike or no-training morning | 90% |

### What would show the engine is wrong, not just unlucky

- A "Recovered" call before a hard session he then fails (under 50% of intervals on target,
  or a post-ride feel 2 or more below his usual), followed by a worse next morning.
- An eased or picked session he rides as written and executes at or above his norm, with a
  normal next morning, two or more times: the caution cost stimulus.
- A Red that rests only on readiness confirming a fair night (311's double count) on a
  morning his own nights are back.
- Any surface (Home, brief, chat, calendar, weekly review) showing a call that differs from
  the stored `todaysCall`.

### The checks a short addendum after 20 Oct should run

1. Replay 7–20 Oct (`scripts/replay_verdicts.py --start 2026-10-07 --end 2026-10-20`):
   "reproduces production N of N", and the disagreements table in STATUS.md.
2. Score E1–E7 and P1–P12 above, one line each: right, wrong, or not tested (and why).
3. For each morning: the stored call, its domains, and which rule decided it (`--compare-without`
   for `hrv_holiday_catch_up` and `hrv_persistence`), so 311 is decided on his return.
4. For each hard session: the call, what he rode (power against target per interval), his
   post-ride feel and effort, and the next morning's HRV and resting HR.
5. Whether readiness confirmation decided any colour (311's question a).
6. Whether the stored brief, Home, chat and the calendar said the same call on every morning.

---

## G. Earlier findings, reconsideration, hypotheses and limits

### G.1 Earlier findings: fixed, open or superseded

Labels: *implemented* unless marked; "not re-checked" where this review did not look.

**1 Oct review** (`2026-10-01-batches-268-297-review.md`)

| Finding | Now | Evidence |
|---|---|---|
| SE-1 colour and floors need the paid brief | Fixed | 302: stored before the paid call |
| SE-2 weekly mix reads the colour | Fixed | 299 |
| SE-3 rail proposes rides on rest days | Fixed | 299 |
| SE-4 a re-save clears a note's symptom | Fixed | 303: only his answer to Home's question counts |
| SE-5 the rollback is not exact (notes reader still runs) | Open, superseded by 308 | STATUS rollback note |
| SE-6 chat sees a held day as plain Green | Fixed | 298 |
| SE-7 knowledge base states the ladder's Amber | Fixed | 298, 313 (`training_plan` v4, *observed*) |
| SE-8 `updated_at` microseconds before `created_at` | Open, cosmetic | not re-checked |
| SE-9 CI on Postgres 16, production 17 | Open | not re-checked |
| AI-1 ladder words beside the graded colour | Fixed | 298 |
| AI-2 readiness counts sleep and recovery twice | Open, labelled (305); now DV-6 | *proved*: decides 7 colours |
| AI-3 eval cannot catch a prompt change | Fixed | 307 |
| AI-4 a reading outlives a prompt change | Fixed | 307 |
| AI-5 recovery-week normal rests on three weeks | Open | now four light weeks; W13 will use it |
| AI-6 the replay cannot catch a live acute-rail fault | Open | it reuses the stored rail by design |
| AI-7 the chat extractor has never run | Not re-checked | |
| CO-1 light weeks hold on a clearly-off morning | Fixed | 300 |
| CO-2 a persistent HRV dip never escalates | Fixed | 304 (*proved*: 7 mornings change) |
| CO-3 Amber never shortens a ride | Fixed | 306 (offered) |
| CO-4 Amber turns VO₂ into 94% work | Fixed | 306 (his pick) |
| CO-5 planned training called "a little off" | Fixed | 305 (*proved*: 5 mornings change) |
| CO-6 load ratio 1.3 flags Garmin's "optimal" | Open, queued (305's line); DV-8 adds evidence | |
| MD-1 medical advice needs the model | Fixed | 301 |
| MD-2 no graded return after fever | Fixed (two easy mornings) | 303; shorter than the IOC's graded return, with a floor |
| MD-3 breathlessness missing | Fixed | 303 |
| MD-4 an unclear chest mention only asks | Fixed | 303 |
| MD-5 respiration never grades | Open | surveillance only; it restates HRV (r −0.61, *computed*) |
| MD-6 two-mornings RHR corroborates bike rest | Fixed | 305 |

**28 Sep review** (`verdict-grading-review-2026-09-28.md`): its six changes shipped (294–297).
Still open from it: MD-5 (a sudden HRV rise is not always good news: the bands are one-sided;
one night in 104 was 2 SD above his median, *computed*), MD-6 (sleep stages are the least
reliable measure: the 5 Oct brief now carries that caveat, *observed*, but still opens with
stage percentages) and AI-5 (a replay shows what changes, not whether it is better: this
review's C.1 is a first answer, and the recording list in C.1 is how to get a better one).

**29 Sep replay** (`verdict-replay-2026-09-29.md`): its outcome proxies are reproduced and
extended in C.1 (58% against 72% on target then; per-session 53% against 89% now, same
direction, same small sample).

**Batch 238 (AI)**: AI238-01 (stale four-item output contract) fixed by the derived contract;
AI238-02 (nothing inspects generated output) **open**, now DV-9; AI238-03 (alerts dormant)
fixed by 291, pending Craig's Sentry rule; the rest not re-checked.

**Batch 239 (coaching integrity)**: CI239-03, -04 and -05 fixed (243); CI239-06 (FTP can
never increase) gate fixed in code, **open in practice** (DV-2); CI239-07 (strength invisible
to load) partly fixed, open (DV-10); CI239-09 (the generator never produced a plan) **open**
(DV-1); CI239-11 (a blackout returns Green) fixed for whole missing rows, open for missing
fields (DV-13); CI239-02 (the planned session is the default on Zwift) unchanged by design
(an eased ride still needs his approval); the rest not re-checked.

**Batch 240 (health science)**: HS240-01 (RHR 40 above ceiling gives Green) fixed (the +7
floor); HS240-02 (an acute HRV collapse is invisible) fixed (246, 294); HS240-03 (SpO₂ and
respiration never evaluated) partly: a surveillance rail exists and has never fired
(Hypotheses); HS240-04 (no medical boundary) partly: the symptom notices carry GP, 111 and 999
lines, and a standing boundary line exists in code; HS240-05 (REM likely a device artefact)
partly: the caveat now reaches the brief; HS240-12 (one-sided bands) open; HS240-15
(self-recalibrating baselines) **open**, now DV-7; HS240-17 (flat age credit) superseded by
the age-credit guard.

**Deload escalation evidence** (`deload-escalation-evidence.md`): superseded in practice; the
two-Reds rule now fires rarely (one pair in 106 mornings under the graded engine, *proved*).

**Coaching-integrity audit**: grade was A− (Batch 211) and B+ (Batch 239). This review does
not re-grade the audit.

### G.2 For reconsideration (settled decisions, with new evidence)

- **Decision #375 (Craig, 2 Oct): after a chest or heart report nothing follows.** New
  evidence: the IOC 2022 return-to-exercise checklist and the ESC 2020 guideline both put
  chest pain, palpitations and breathlessness behind a medical check before hard exercise;
  Batch 303's easing already exists, so a caution-only follow-up is cheap (DV-3, E0).
- **Decision #379 (Craig, 3 Oct): readiness confirmation kept as deliberate extra weight.**
  New evidence: it decided 7 of 106 colours and 3 of 7 Reds (*proved*), and his readiness
  restates sleep (r 0.68) and recovery time (r −0.70), not HRV (r 0.17) (*computed*). 311's
  candidate (a) aims at the smaller overlap (DV-6).
- **Decision #366 / Batch 246: his normal is the 84 nights before the morning, this week
  included ("one definition of his normal").** New evidence: a worse earlier night can lift a
  floor (*proved*), and a low week lowers his lines by about 1 ms for 12 weeks (*computed*)
  (DV-7).

Not reconsidered, though they depart from the trials: the two-morning hold before a dip
eases, resuming hard work inside the band rather than at the mean, and Batch 310's catch-up.
Craig chose these knowingly (#377, #382) and the outcomes in C.1 show no harm from them yet.

### G.3 Hypotheses (not verified)

- **The Nov–Dec 2025 episode was an illness the current lines would have caught early.** HRV
  then predates the reliability date (11 Jun 2026), so this is illustrative only.
- **The repeated wrist SpO₂ dips (lowest under 88% on 15 of 108 nights, lowest 82%) may be
  measurement noise or sleep-disordered breathing.** Wrist oximetry overnight is unreliable;
  in men of his age sleep apnoea is common and linked to atrial fibrillation. A GP
  conversation, not the app, would settle it. Craig's call whether the app ever mentions it.
- **His medication, if any, would change how his heart rate and HRV should be read** (beta
  blockers lower both). The knowledge base records none (*observed*); whether that means
  "none" or "never asked" is unknown.
- **The fall in long-ride drift (5.2% to 0.9%) is the cooler season, not fitness.**
- **Heart rate at 249 W rising from 129 to 139 bpm through the August build was fatigue the
  morning call did not see**; heat or longer intervals are alternatives.
- **Showing the reason line on Home would answer most of Mark's "why" questions** (his
  24 Sep complaint was about a call he saw no reason for).

### G.4 Limitations

- **One man, about 100 mornings.** Every effect in C.1 is uncertain and stated with its
  interval; most mornings were shown the ladder's call, so what he rode followed the ladder.
- **The graded engine has decided no training morning yet.** All five graded mornings were
  holiday rest days; the trial from 7 Oct is the first real test (section F).
- **What he rode is not linked to what was planned**, so execution is graded against the
  plan even when he rode an eased or self-edited version (two of the seven flagged sessions).
- **Sources.** Read in full for this review: Vesterinen 2016 (accepted manuscript). Read in
  part: Schwellnus 2022 (the return-to-exercise checklists). Cited from the 1 Oct review's
  reading or abstracts: Plews 2013, 2014; Javaloyes 2019; Kiviniemi 2007; Saw 2016; Gabbett
  2016; Impellizzeri 2020; Abdulla 2009. Cited as standard recommendations, not re-read:
  Pelliccia 2021 (ESC), Newman 2021, Andersen 2013, WHO 2020; their DOIs are as I recall them and
  were not re-checked online for this review.
- **Process.** Three lens passes ran as subagents; the progression pass finished, and its
  headline numbers were re-checked here (FTP test date, VO₂max, the reviews' FTP advice, the
  unread block-end flag). The doctor-and-thresholds and engine passes stopped at a usage
  limit; their saved work (his distributions, the mutation runs, the Vesterinen and IOC
  texts) was re-checked and the rest done directly.
- **Not examined:** the BST-to-GMT change on 25 Oct (date boundaries), several check-ins in a
  day beyond what the code reads (the newest scored morning check-in), and the Zwift screen.
- **No clinician** reviewed the medical findings. This is not medical advice.
- **Tests run locally:** the verdict selection, 214 passed and 25 skipped (Postgres tests
  skip on this Mac); 475 passed and 84 skipped in the wider engine selection used for the
  mutation runs. CI's full suite was not run for this docs-only branch beyond its own checks.

### How to re-run

- Replay: `PYTHONPATH=apps/api railway run --service api apps/api/.venv/bin/python scripts/replay_verdicts.py` (add `--compare-without <rule>` for one rule's effect).
- Predictions: `docs/reviews/2026-10-06-daily-verdict-review/predict.py` through `railway run`
  (reads only; its session rolls back; a watchdog ends it after 4 minutes).
- The outcome join, the probes and the token count were scratch scripts outside the repo;
  their method is described in C.1, C.3 and DV-16.

### References

- Abdulla J, Nielsen JR. Is the risk of atrial fibrillation higher in athletes than in the general population? *Europace* 2009. doi:10.1093/europace/eup197
- Andersen K, Farahmand B, Ahlbom A, et al. Risk of arrhythmias in 52 755 long-distance cross-country skiers. *Eur Heart J* 2013. doi:10.1093/eurheartj/eht188
- Gabbett TJ. The training-injury prevention paradox. *BJSM* 2016. doi:10.1136/bjsports-2015-095788
- Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:chronic workload ratio: conceptual issues and fundamental pitfalls. *IJSPP* 2020. doi:10.1123/ijspp.2019-0864
- Javaloyes A, Sarabia JM, Lamberts RP, Moya-Ramon M. Training prescription guided by heart-rate variability in cycling. *IJSPP* 2019. doi:10.1123/ijspp.2018-0122
- Kiviniemi AM, Hautala AJ, Kinnunen H, Tulppo MP. Endurance training guided individually by daily heart rate variability measurements. *EJAP* 2007. doi:10.1007/s00421-007-0552-2
- Newman W, Parry-Williams G, Wiles J, et al. Risk of atrial fibrillation in athletes: a systematic review and meta-analysis. *BJSM* 2021. doi:10.1136/bjsports-2021-103994
- Pelliccia A, Sharma S, Gati S, et al. 2020 ESC Guidelines on sports cardiology and exercise in patients with cardiovascular disease. *Eur Heart J* 2021. doi:10.1093/eurheartj/ehaa605
- Plews DJ, Laursen PB, Stanley J, Kilding AE, Buchheit M. Training adaptation and heart rate variability in elite endurance athletes. *Sports Med* 2013. doi:10.1007/s40279-013-0071-8
- Plews DJ, Laursen PB, Le Meur Y, et al. Monitoring training with heart rate variability: how much compliance is needed for valid assessment? *IJSPP* 2014. doi:10.1123/ijspp.2013-0455
- Saw AE, Main LC, Gastin PB. Monitoring the athlete training response. *BJSM* 2016. doi:10.1136/bjsports-2015-094758
- Schwellnus M, Adami PE, Bougault V, et al. IOC consensus statement on acute respiratory illness in athletes, part 1: acute respiratory infections. *BJSM* 2022;56:1066–88. doi:10.1136/bjsports-2022-105759
- Vesterinen V, Nummela A, Heikura I, et al. Individual endurance training prescription with heart rate variability. *MSSE* 2016;48:1347–54. doi:10.1249/MSS.0000000000000910
- World Health Organization. Guidelines on physical activity and sedentary behaviour. 2020.
