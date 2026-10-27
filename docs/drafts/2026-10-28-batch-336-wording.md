# Batch 336 — the words Mark sees (for Craig's sign-off)

**Not signed off yet.** Built 28 Oct 2026 under Craig's go of 27 Oct; nothing merges until
Craig signs off these words.

Batch 336 makes his ramp test set his FTP in the app, and makes a test something he rides as
planned or moves, never eases. These are every new Mark-facing line, word for word.
`apps/web/src/components/FtpTestCard.test.tsx` and `apps/api/tests/test_batch_336_test_moved.py`
hold the app's lines to this file.

Figures below are his 20 Oct test as if it were still waiting: Garmin's best minute 353 W, so
the app's number is 265 W (Zwift's own result was 267 W, which Craig set on 20 Oct, so this
card will not appear for that test).

## 1. After a ramp test: the FTP card on Home (336.1)

Shown for 7 days after a ramp test he has ridden, until he decides. Never shown again for a
test once decided.

Heading:

> Your ramp test: FTP 265 W

Then:

> Your best minute on 20 Oct was 353 W, and your new FTP is three-quarters of it: 265 W. Your FTP in the app is 280 W now.

> Zwift sets your trainer from its own FTP setting, and the app grades your rides from this one, so they need the same number. If Zwift gave you a different number for this test, use Zwift's.

Two buttons:

> Set my FTP to 265 W

> Keep 280 W

And a link under them:

> Zwift gave a different number

which opens a box labelled

> Zwift's FTP (W)

with the line

> Between 239 and 291 W.

and a button

> Set this FTP

After he taps, a short message:

> Your FTP is now 265 W. Check Zwift's FTP setting says 265 W too.

or, if he kept it:

> Your FTP stays 280 W.

**Questions for Craig:**
1. Zwift usually sets its own FTP when its ramp test ends, so the second line asks him to
   match the app to Zwift rather than the other way round. If you would rather the app's
   number led ("set Zwift to 265 W"), say so.
2. "Zwift's FTP setting" names the setting without a menu path; I could not confirm Zwift's
   current menu wording. Add the path if you know it.

## 2. A test on a morning that is not a clean Green (336.2)

When the morning would have eased, held or offered a pick for a test (Amber, a tired morning,
Green with one reading a touch off, or a planned light week), the test now stays as planned on
Zwift and the morning offers a move instead.

Today's call (a new call, state 18):

> **Test day — fresh or move it**
>
> A test needs you fresh, and you're not quite there today. Move it to a fresher day this week if you can; if not, ride it as planned. Don't ride it eased.

The plan line under the brief:

> Move FTP Ramp Test to a fresher day this week if there is one; if not, ride it as planned. A test ridden tired or eased gives a low FTP, and your sessions are set from it.

The existing swap offer ("Move … Apply") appears with it when the week has a better day, as
it does for any hard session today.

The written brief is told the same thing (prompt v61): name the move first, never suggest
riding the test eased or holding back in it.

Unchanged: a Red morning still makes the test an easy spin and says "The hard session will do
more for you on a fresher day — today, rest or an easy spin."; the health warnings still
take him off the bike.

## How often he will see these

Plan No. 3 has one ramp test (20 Oct, already decided), so neither part shows again until his
next plan's test, about mid-January. The replay over every stored morning (read-only, 28 Oct)
changes none.
