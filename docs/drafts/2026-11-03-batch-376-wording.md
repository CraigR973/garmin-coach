# Batch 376 — The Home badge and the Bedroom chart on 366's lines: the words (for Craig's sign-off)

**Awaiting Craig's sign-off.** After Batch 366 the bedroom pushes judge the room warm from
24 °C and cold below 18 °C, but the badge beside last night's room still read **Red** after
60 minutes above 20 °C, and the Bedroom chart labelled 20 °C **"critical"**. Batch 376 puts both
on 366's lines. `apps/web/src/lib/roomFeel.test.ts` holds the app's lines to this file.

## 1. The badge (Home's "Last night" line and the Bedroom/Sleep chart card)

**Replaces** "Green", "Amber" and "Red". A night is Warm or Cold only after an hour past a line
(the longer side wins a night with both); otherwise Comfortable.

> Comfortable

> Warm

> Cold

On Mark's October nights (room 18.2–20.9 °C at night) the badge reads Comfortable where it read
Red or Amber.

## 2. The chart's lines

**Replaces** "Lines: fan on 19.5° · critical 20.0°", and the two lines move from 19.5 and 20 °C
to 18 and 24 °C (the warm line amber, the cold line grey; no red line).

> Lines: 18° (cold below) · 24° (warm above)
