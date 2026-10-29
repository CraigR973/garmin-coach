# Batch 322 — record what he rode and how it went (for Craig's sign-off)

**Signed off by Craig on 29 Oct 2026** ("All as recommended"): no extra monthly fixed-power ride. Batch 322 records, with each ride's read, whether he rode the
morning's call, a clean 0–10 effort and his legs, and the ride's fixed-power check (his
heart rate at a steady Zone 2 power); each morning keeps Garmin's readiness factors. Only
the check-in's two labels are new words for Mark.

**Measured, read-only, on production (29 Oct):** 126 post-ride check-ins give an effort,
all on the 0–10 scale (none on another scale, so the 6 Oct concern is about the "Legs"
field's meaning, not the numbers); 38 of 105 ride reads hold a steady Zone 2 block of 20
minutes or more (for example, made up: 55 minutes at 180 W, heart rate 110); all 40 daily
rows of the last 30 days carry Garmin's six readiness factors.

## 1. The ride check-in (322.2)

**Where:** "How did it feel?" after a ride, on Home.

> **Effort (0–10)** — placeholder "0 easy, 10 all-out"

> **Legs** — placeholder "0 dead, 10 fresh"

**Replaces:** "RPE" with no scale, and "Legs" with "1-10". The app now refuses an effort
above 10.

## 2. Not Mark-facing

- **The call against what he rode:** each ride's read stores the morning's action for that
  ride and whether he rode it ("tookTheCall"): riding the eased version he was sent after
  an easing morning counts; riding the planned session the call had eased does not.
- **The version he was sent:** rides have been graded against the version on Zwift since
  Batches 152 and 335; the read already stores which (`gradingTarget`).
- **Readiness factors:** sleep, recovery time, load ratio, HRV, sleep history and stress
  history, as Garmin gave them, kept with each morning.
- **The fixed-power check:** every Zone 2 ride in ERG with a steady block of 20 minutes or
  more records its power, heart rate and drift. Batch 319 reads his fitness drift from
  these rides only.

## Question for Craig

1. The row asked for "a monthly fixed-power check". His mid-week Zone 2 ride already is
   one (a steady Zone 2 block in ERG, most weeks), so no extra session is added.
   Keep it that way, or add a dedicated 20-minute check once a month?
