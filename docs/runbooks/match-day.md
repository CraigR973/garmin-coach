# Runbook — Match day operations (phone-first)

Cold-read reference for operating the league from your phone during a live match.
Pairs with `prod-monitor.md` (the detection/response system) — this page is the
**human judgement** layer: is it actually an incident, which lane fixes it, and
the one check no monitor can do for you.

The pipeline being exercised: **result-sync → scoring trigger → leaderboard
snapshot → push notifications.** Opening weekend is its first live test.

---

## 30-second triage — is this even an incident?

Before reacting to anything, check it against this. Most "problems" mid-match are
expected behaviour of the free-tier data feed.

| You see… | Normal? | Why |
|---|---|---|
| Live match shows **no score / null scoreline** | ✅ **Normal** | football-data free tier only writes the score at **full-time**. No live feed. Provisional "if it stands" points stay hidden until then (U54). |
| No points moving **during** a match | ✅ **Normal** | Scoring runs on the **final** result, not live. |
| Players **can't change a pick** after kickoff | ✅ **Correct** | Server-side lock (`predictions.py`, 409 `PREDICTION_LOCKED`), keyed on `kickoff_utc`. Working as designed. |
| Others' picks **hidden** until kickoff | ✅ **Correct** | Reveal gate uses the same lock — privacy invariant. |
| Result **not in within minutes** of full-time | 🟡 **Wait** | Sync runs every ~5 min; the monitor only flags a *finished* match as late after its threshold. Give it a cycle. |
| Result still missing **well after** full-time, or monitor opened an issue | 🔴 **Act** | See lanes below. |
| Result is in but **points/leaderboard didn't move** | 🔴 **Act** | Monitor flags this as `unscored_predictions` / `leaderboard_stale` (critical). Code-fix lane. |
| Points moved but the **numbers look wrong** | 🔴 **Act — only a human catches this.** | See "Scoring spot-check" below. |

If the monitor hasn't opened an issue and the row above says Normal/Wait — **do
nothing.** Inventing a fix for non-broken behaviour mid-match is the bigger risk.

---

## Two response lanes — pick the right one

| | **Lane A — ChatOps (data/ops)** | **Lane B — @claude (code bug)** |
|---|---|---|
| **For** | Result missing, sync stalled, manual result entry, DB snapshot | The code is wrong — scoring miscomputed, pipeline didn't fire, a real bug |
| **How** | Reply a slash-command on the monitor issue | Comment `@claude <describe it>` on an issue |
| **Speed** | Executes on the next monitor run (≤15 min), replies with the result | Investigates → opens a **draft PR** → you review + merge to deploy |
| **From phone** | One line, done | Must read a diff and merge — harder on mobile, slower |

**Rule of thumb:** try Lane A first. Only escalate to Lane B when the data is fine
but the *logic* is wrong. Don't reach for `@claude` when `/sync` or
`/enter-result` solves it.

### Lane A commands (you must be repo OWNER)
- `/sync` — re-run the result sync (safe; also auto-tried by the monitor)
- `/status` — fetch current sync status
- `/backup` — take a DB snapshot
- `/enter-result <match_id> <home>-<away> [et] [pens] [winner=<team_uuid>]` — manual result
- `/resolve` — close the issue

### ⚠️ Manual `/enter-result` is SILENT — no push to players
Only **auto-sync** queues push notifications. If you enter a result by hand,
scores and the leaderboard update but **the league gets no notification.** If it
matters, tell players yourself (WhatsApp/etc.). This is known, documented behaviour.

---

## Scoring spot-check — the one thing only you can do

The monitor verifies scoring **ran** (`unscored_predictions`, `leaderboard_stale`).
It does **not** verify the numbers are **right** — a trigger edge case (a draw,
ET/pens, the exact-score bonus, bracket advancement) would score everyone and
advance the leaderboard while being wrong, and show all-green.

**So: after the FIRST match scores this weekend, hand-verify one player once.**
Once the trigger is proven on one piece of real data, trust it for the rest.

### Group / knockout match points (per match, max 10)
Applied to the **90-minute** result. ET/pens decide advancement only — a 1-1
that goes to penalties is scored as a **1-1 draw** for prediction points.

| Criteria | Points |
|---|---|
| Correct **combined total goals** (pred 2-1 vs actual 3-0 → both = 3) | 2 |
| Correct **result** (W/D/L, ignoring score) | 3 |
| **Exact scoreline** (both goals correct) | 5 |
| **Max per match** | **10** |

These stack: an exact scoreline (5) is also a correct result (3) and usually a
correct total (2) → **10**. A correct result with wrong score and wrong total → **3**.

**Worked example — actual result 2-1** (3 goals total, home win):
- Predicted **2-1** → exact ✓ (5) + result/win ✓ (3) + total 3=3 ✓ (2) = **10**
- Predicted **1-0** → result/win ✓ (3) + total 1≠3 ✗ (0) + not exact (0) = **3**
- Predicted **3-0** → result/win ✓ (3) + total 3=3 ✓ (2) + not exact (0) = **5**

The full breakdown is stored per prediction in `predictions.points_breakdown` —
if a number looks off, read that column first; it shows which criteria fired.

### Knockout winner picks (separate system, per round)
R32 = 5 · R16 = 10 · QF = 15 · SF = 20 · 3rd-place = 10 · Final = 25.

### Specials
Awarded at **tournament end**, not during the weekend — ignore for now.

---

## Hard rules (don't break these on your phone)
- **Never admin-bypass CI** to merge a fix. If `@claude`'s PR is red, it doesn't ship.
- **Kickoff freeze** — don't merge/deploy while a match window is active. Each
  issue/PR shows whether one is open.
- **Don't add new code mid-weekend** to "validate" scoring — the human spot-check
  above is the right tool. Untested code in the critical path is the bigger risk.

---

## Manual instant health check
Don't wait for the 15-min cron. **Actions → prod-monitor → Run workflow** for an
instant read. Use `dry_run: true` to see intended actions without any writes.

## Coverage backstops (already wired)
- **Layer 0** — UptimeRobot on `/api/v1/health/ready` (independent of GitHub).
- **Dead-man's-switch** — `prod-monitor.yml` pings Healthchecks.io on every
  successful run; if the monitor dies silently, Healthchecks pages you (~20 min).

## After the match
A quick manual monitor run confirms: result synced, predictions scored,
leaderboard advanced, no failed pushes. Then you're clear until the next kickoff.
