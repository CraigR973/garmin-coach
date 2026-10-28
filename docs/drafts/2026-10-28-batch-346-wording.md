# Batch 346 — the words Mark sees (for Craig's sign-off)

**Not yet signed off.** Draft PR for Batch 346, Decision #448 (provisional number).

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

## Unchanged, for context

Coach memory keeps its existing words for a waiting proposal ("Accept memory", "Reject",
"Waiting for confirmation", the locked-wording line) and the "Look for new memories" button.

## Questions for Craig

1. **The coach's wording is in the third person.** The extractor writes each memory as
   "Mark does …" (its prompt, `conversation-learning-v3-2026-09-27`, unchanged here). On
   Home he would read "Mark does his bodyweight session every Saturday." under "Should the
   coach remember this?". Keep it (no prompt change), or change the extractor to write "You
   …" (a prompt bump, a separate small change)? Recommendation: keep it for the first run and
   decide on what it actually proposes.
2. **Three at a time on Home.** The first read may propose up to 12. Recommendation: three,
   with the rest on Coach memory.

## The first paid read (needs Craig's go)

The first 01:30 run after the merge reads everything since 18 Jul in one call: about 485
sources (283 chat questions, 177 notes, 25 corrections, production count of 28 Oct), roughly
55,000–65,000 input tokens and at most 4,096 output tokens. At Sonnet's $3 / $15 per million
tokens that is **about $0.25 (at most about $0.30)**. After that, each night with a new chat
question reads the newest 60 sources of 30 days: about $0.03–0.09 a night, so up to about
$2–3 a month if he chats most days. A night with no question costs nothing.

Not measured: the token count is estimated from character counts, not from the free
`count_tokens` call, and the price is Sonnet's published rate, not a Console figure.
Risk: if the first read runs out of output room (12 proposals plus thinking within 4,096
tokens), it fails, raises the coach-memory alert, and tries again the next night, paying
again each time until it fits.
