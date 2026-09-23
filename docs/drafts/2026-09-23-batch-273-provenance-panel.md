# Batch 273 — the provenance panel: copy and layout for Craig

**Status: nothing here has been shown to Mark, and no UI has been built.**
The packet side of Batch 273 is built and green on PR #308, which is **not
merged**. 273.2 is explicit — *"Mark-facing UI and copy: draft it, do not ship it
unreviewed"* — so this file is the draft, and the panel waits on it.

---

## 1. What exists after this PR, and what does not

**Built (packet side, invisible to Mark):** every covered figure now carries its
own structured derivation beside the number — which rows, over which window, under
which rule, against which threshold. A contract test fails CI if a covered figure
stops carrying it.

**Not built:** the panel itself. Nothing on any screen changes.

This split is deliberate and is what makes the panel cheap to add later: the API
already serves the data, so the panel is a rendering job rather than a
re-derivation, and it cannot drift from the number it explains.

---

## 2. What is covered, and what is not (273.3 — the decision)

Full coverage of every derived figure is large and most of it has never been
disputed, so **coverage starts with the figures that have actually caused
arguments**:

| figure | the dispute it settles |
|---|---|
| bedroom peak overnight | 7–13 Sep: a 21.4 °C "overnight" reading that was a 14:07 afternoon sample |
| average bedroom peak, weekly review | the same figure, rolled up |
| nights the bedroom disrupted sleep | the count Mark said was wrong, and was |
| acute personal HRV floor | "where are you getting that number" — it is his own median minus 1.5 SD, not Garmin's band |
| work intervals on target | 8 Sep: five "under" calls he checked against Garmin and found above 350 W at peak |

**Deferred, with the reason recorded in the code** (`DEFERRED_FIGURES`) rather
than only here:

- **sleep-credit ceiling** — its inputs are the age-norm credit model, a table of
  population bands rather than a window of rows. That is a different provenance
  shape, and Mark has questioned its *conclusion* rather than its arithmetic.
  Worth covering once the panel has shown which figures he actually presses.
- **readiness effective floor** — derived from a baseline centre that already
  publishes its own window, and never disputed. Covering it now would be coverage
  for its own sake.
- **Trends narratives** — model prose over rollups. Cover the rollups first.

> **Craig: is that the right five to start with?** The list is drawn from real
> disputes, not from the backlog, which is what 273.3 asked for.

---

## 3. Draft panel — the bedroom peak, 8–9 September

The worst case is the useful one, because it is the one that was wrong.

> ### Bedroom peak overnight — 21.4 °C
>
> **How this was worked out**
>
> - **Readings used:** 17 from your bedroom sensor
> - **Window:** 14:07 on 8 Sep → 06:00 on 9 Sep — *a clock window, not your sleep*
> - **Rule:** the highest reading inside the window. No sleep times were recorded
>   for this night, so the window falls back to the clock and **may include hours
>   you were awake**.
> - **Compared against:** 20.0 °C, your disruption threshold
>
> ⚠️ **The first reading in this window is from 14:07** — an afternoon sample,
> not part of your night.

And the same panel on a night that was measured properly:

> ### Bedroom peak overnight — 19.1 °C
>
> - **Readings used:** 16 from your bedroom sensor
> - **Window:** 22:00 → 06:00 — *the night you actually slept*
> - **Rule:** the highest reading between sleep onset and wake
> - **Compared against:** 20.0 °C, your disruption threshold

**Wording notes for Craig:**

1. *"a clock window, not your sleep"* is the line doing the real work. It is
   deliberately blunt. Softer alternative: *"an estimated window"* — but that
   hides exactly what needs showing.
2. The ⚠️ line is generated only when the window's first reading falls outside
   plausible sleep hours. It could also be dropped entirely and left to the reader.
3. "Readings used" vs "Readings available" — the packet carries both. The draft
   shows only the first. Showing both would say *"17 used, 41 available"*, which
   is more honest and more cluttered.

---

## 4. Draft panel — the HRV floor

This one is worth showing because the number **already** had its working; it just
had nowhere to appear.

> ### Acute personal HRV floor — 39.6 ms
>
> - **Nights used:** 47 of your own overnight readings
> - **Window:** the 84 days before this morning, excluding it
> - **Rule:** your own median (46.0 ms) minus 1.5 standard deviations of it.
>   **This is your own floor, not a population band and not Garmin's.**
> - **This morning:** 36 ms — below it

**Craig's call:** the last line of the rule — *"not a population band and not
Garmin's"* — is a direct answer to a thing Mark has asked more than once. It also
reads slightly defensive. Keep or cut.

---

## 5. Draft panel — interval grading

> ### Work intervals on target — 11 of 16
>
> - **Boundaries:** the planned-duration clock (Garmin supplied no usable step
>   laps, so a boundary can be out by a few seconds)
> - **Rule:** a sustained effort is graded on **the average power it held across
>   its window, not its peak**. A short effort is graded on its peak and can never
>   be "over". An interval that recorded below the recovery next to it is a
>   segmentation failure, so its grade is withheld rather than counted.
> - **This session:** 11 on target, 2 over, 3 under, 0 ungraded

**Why this wording:** on 8 Sep Mark checked five "under" calls against Garmin and
found every one above 350 W at its peak. **Both readings were right.** The panel
has to say which statistic was used, in a sentence, or the same argument recurs.

---

## 6. Layout — the one open design question

The panel needs a home. Three options, in order of my preference:

1. **A collapsed "how this was worked out" line under each figure**, expanding in
   place. Closest to where the dispute happens; costs the most layout work.
2. **One panel per screen**, listing every covered figure on that brief or review.
   Cheapest; the reader has to find the figure they care about.
3. **A separate page.** Cheapest of all and almost certainly unused.

> **Craig: pick one.** The packet shape supports all three unchanged.

---

## 7. What to do with this file

1. Confirm the five covered figures (§2).
2. Edit §3–5 copy in place, or say "fine as is".
3. Pick a layout (§6).
4. Then PR #308 can merge and the panel becomes a rendering job.

**Batch 274 must branch from a `main` that already contains 273** —
`batch-group.md` forbids stacking branches, so 274 has not been started.
