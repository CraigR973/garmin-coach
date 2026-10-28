# Batch 346 — the words Mark sees (for Craig's sign-off)

**Signed off by Craig as drafted, 28 Oct.** Batch 346, Decision #448.

Craig's answers, about 09:30 on 28 Oct, verbatim:

- Q: "Coach memory (346): sign off its words? Each memory reads in the third person ("Mark does his bodyweight session every Saturday."), Home shows three at a time, and it adds one empty database column." A: "Sign off as drafted (Recommended)". The option read: Keep "Mark does …": the same sentence goes into the coach's own memory, where "you" would read as the coach.
- Q: "Coach memory's first paid read: about $0.25 (at most about $0.30), then up to about $0.09 a night with chat, roughly $2–3 a month. Go?" A: "Go, after two free fixes (Recommended)". The option read: Measure the real input with the free token counter, and raise the output limit from 4,096 to 8,192 tokens (adds at most about 6p), so it can't fail and pay again.
- Q: "Raise coach memory's output limit to 16,384 tokens?" A: "Yes, 16,384" (about 09:35). The button read: Raise coach memory's output limit to 16,384 tokens, so the first read can't run out and pay again. Worst case about $0.34.

Batch 346 makes the coach read Mark's chat each night and ask him, on Home, whether to
remember anything he keeps saying. He answers in one tap, and he can take any memory back on
Coach memory. These are every new Mark-facing line, word for word, and the one line that is
replaced. Nothing about the day's call changes. `apps/web/src/lib/coachMemory.ts` holds every
line below, and its tests read them from there.

## 1. Home: the ask (only when something is waiting)

Card title:

> Should the coach remember this?

Then, for each waiting memory (three at most), the coach's wording of it, then where it came
from, with the date and his own words:

> Mark does his bodyweight session every Saturday.
>
> You said on 10 Jun: “I do my bodyweight session every Saturday”

Two buttons:

> Yes, remember it

> No

After a tap, a short message at the bottom of the screen:

> The coach will remember that.

or

> The coach will leave that out.

When more than three are waiting:

> 2 more are waiting on Coach memory.

(“1 more is waiting on Coach memory.” for one.)

A link at the foot of the card:

> See everything the coach remembers

The card shows nothing at all when nothing is waiting, or if the list cannot be loaded.
A proposed experiment never asks here; it stays on Coach memory, as now.

## 2. Coach memory: the card's introduction (replaces the current line)

Now:

> The coach proposes standing facts and preferences from your chats and notes. Nothing is
> remembered until you accept the evidence-bound wording, and learned memory can never change
> the verdict rules.

Proposed:

> Each night the coach reads what you have told it and asks to remember anything you keep
> saying. Nothing is kept until you say yes, and nothing here changes how the coach makes the
> day’s call.

## 3. Coach memory: taking a memory back

Under each confirmed memory, one button:

> Forget this

After the tap:

> The coach has forgotten that.

The memory leaves the coach's context from his next question. A forgotten memory is not
proposed to him again.

If he asks the coach where its memory came from, the coach may describe a version written by
this button in these words (the same list already says "added from something you confirmed
with the coach" for a confirmed one):

> updated when you removed something the coach remembered

## Unchanged, for context

Coach memory keeps its existing words for a waiting proposal ("Accept memory", "Reject",
"Waiting for confirmation", the locked-wording line) and the "Look for new memories" button.

## Questions for Craig (answered above: keep the third person; three at a time)

1. **The coach's wording is in the third person.** The extractor writes each memory as
   "Mark does …" (its prompt, `conversation-learning-v3-2026-09-27`, unchanged here). On
   Home he would read "Mark does his bodyweight session every Saturday." under "Should the
   coach remember this?". Keep it (no prompt change), or change the extractor to write "You
   …" (a prompt bump, a separate small change)? Recommendation: keep it for the first run and
   decide on what it actually proposes.
2. **Three at a time on Home.** The first read may propose up to 12. Recommendation: three,
   with the rest on Coach memory.

## The first paid read (Craig's go, 28 Oct)

The first 01:30 run after the merge reads everything since 18 Jul in one call. Measured on
28 Oct with the free `count_tokens` call, on production data, read-only, with the exact request
the job sends: **485 sources** (283 chat questions, 177 notes, 25 corrections), 4 memories
already known, **89,867 input tokens**. The output limit is now **16,384 tokens** (was 4,096; Craig
chose 16,384 over 8,192 because Sonnet 5 has thought 9,000–15,000 tokens on one brief), room
for 12 proposals plus thinking, so a long read cannot run out, fail and pay again each
night.

At Sonnet 5's rate as the app records it ($2 in / $10 out per million tokens) the first read
costs **at most about $0.34** (input $0.18, plus $0.16 if it used every output token). At the
older $3 / $15 rate this draft first priced it at, the ceiling would be $0.52. After that, each
night with a new chat question reads the newest 60 sources of 30 days: roughly 11,000 input
tokens, so about $0.03–0.05 a night and at most about $0.19, about $1–3 a month if he
chats most days. A night with no question costs nothing.

Not measured: the nightly figure scales the first read's tokens per source; the price is the
published rate, not a Console figure.
