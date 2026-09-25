# Reply to Mark — 25 Sep 2026

**Status:** drafted 25 Sep for Craig to send. It answers Mark's WhatsApp messages of
25 Sep (the holiday he couldn't set, the "Light reset" button, and the over-cutting). It
supersedes the 22 Sep draft and the 24 Sep chat draft, whose fixes have since shipped or
changed. The question at the end sets Batch 269's thresholds (group G3).

---

Mark — thanks, all useful, and no rush on any of it.

Holiday: the July one had never been closed properly, because the app didn't end a holiday by itself. I've cleared it, so you can add your new one now as normal. I've also fixed it: a holiday now ends by itself on its last day, so you don't need to press anything when you're back. If you come home early, Resume just brings back the sessions the holiday had skipped.

Light reset: that's the deload button you asked for in July. It turns the rest of that week's rides into steady Zone 2 at 65% FTP, keeps your strength sessions, updates Zwift, and tells the app the lighter load is on purpose. "Restore week" puts the week back as it was.

The cuts: you're right, and it isn't just telling you what you want to hear. On Wednesday and Thursday the only thing wrong was Garmin's 7-day HRV average sitting a point under its floor. Your overnight readings, resting heart rate and recovery time were all normal, and the app still cut Wednesday's ride by a third and Thursday's to half the time at 60%. I'm changing it so the size of any cut depends on how far off your numbers are, and on whether more than one of them agrees. A small dip on its own will do little or nothing. How little is your call:

On a day like Thursday (7-day HRV just under the floor, everything else normal), would you want:
a) the full session as planned
b) the full session, capped at the top of its zone
c) a shorter, easier day

And which of these should be enough on its own to ease a hard session: resting heart rate up, low readiness, a poor night's sleep, or you feeling rough?

The other two slips you spotted are being fixed too. The strength read will compare your heart rate with your own usual range for that workout, and the coach will see each session as the morning actually left it.

---

**Updated 25 Sep after Batch 290 shipped (PR #320):** the holiday paragraph now describes the
fix as live, rather than warning him off Resume.
