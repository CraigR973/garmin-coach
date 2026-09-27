import { provenanceEntrySchema, type ProvenanceEntry } from '@coach/shared';

/**
 * Batch 273.2 — the words for "How these numbers were worked out".
 *
 * Each covered figure's packet carries its working (`services/provenance.py`):
 * which readings, over which window, by which rule, against which threshold. This
 * turns that structure into the copy Mark signed off (Part 2 of the 24 Sep sheet,
 * `docs/drafts/2026-09-24-wording-sign-off.md`), in the second person. The words
 * are composed here from the structured fields rather than taken from the packet's
 * own `rule` text, which is written for the model and speaks of Mark as "he".
 */

export interface ProvenanceLine {
  label: string;
  text: string;
}

export interface ProvenanceRow {
  figure: string;
  title: string;
  lines: ProvenanceLine[];
  warning?: string;
}

/** Parse an envelope's provenance list one entry at a time: a malformed entry is
 *  dropped, so it can cost a row but never the page. */
export function provenanceEntries(raw: unknown): ProvenanceEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    const parsed = provenanceEntrySchema.safeParse(item);
    return parsed.success ? [parsed.data] : [];
  });
}

function oneDecimal(value: number): string {
  return value.toFixed(1);
}

function count(sources: Record<string, unknown>, key: string): number | null {
  const value = sources[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** The packet writes naive UTC timestamps (no offset); read them as UTC. */
function utcDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) || !value.includes('T') ? value : `${value}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function clock(date: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: timeZone || undefined,
  }).format(date);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "14:07 on 8 Sep". Months are spelled here because en-GB's ICU data now writes
 *  "Sept", and the app writes dates as "8 Sep". */
function clockOnDay(date: Date, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'numeric',
    timeZone: timeZone || undefined,
  }).formatToParts(date);
  const day = Number(parts.find((part) => part.type === 'day')?.value ?? '0');
  const month = Number(parts.find((part) => part.type === 'month')?.value ?? '0');
  return `${clock(date, timeZone)} on ${day} ${MONTHS[month - 1] ?? ''}`.trimEnd();
}

function minutesOfDay(date: Date, timeZone?: string): number {
  const [hours, minutes] = clock(date, timeZone).split(':').map(Number);
  return hours * 60 + minutes;
}

/** A clock-window reading taken while Mark would normally be up (09:00–21:30)
 *  is named, because that is what the 7–13 Sep argument was about. */
function daytimeSample(date: Date, timeZone?: string): string | null {
  const minute = minutesOfDay(date, timeZone);
  if (minute < 9 * 60 || minute >= 21 * 60 + 30) return null;
  if (minute < 12 * 60) return 'a morning sample';
  if (minute < 18 * 60) return 'an afternoon sample';
  return 'an evening sample';
}

function thresholdLine(entry: ProvenanceEntry, what: string): ProvenanceLine | null {
  const against = entry.threshold?.comparedAgainst;
  if (typeof against !== 'number') return null;
  return { label: 'Compared against', text: `${oneDecimal(against)} °C, ${what}` };
}

function bedroomPeak(entry: ProvenanceEntry, timeZone?: string): ProvenanceRow | null {
  if (entry.value === null) return null;
  const rows = count(entry.sources, 'rowsInWindow');
  const measured = entry.window?.kind === 'sleep';
  const lines: ProvenanceLine[] = [];
  if (rows !== null) {
    lines.push({ label: 'Readings used', text: `${rows} from your bedroom sensor` });
  }
  let warning: string | undefined;
  if (measured) {
    const start = utcDate(entry.window?.startUtc);
    const end = utcDate(entry.window?.endUtc);
    lines.push({
      label: 'Window',
      text:
        start && end
          ? `${clock(start, timeZone)} → ${clock(end, timeZone)} — the night you actually slept`
          : 'the night you actually slept',
    });
    lines.push({ label: 'Rule', text: 'the highest reading between sleep onset and wake' });
  } else {
    const first = utcDate(entry.sources.firstReadingUtc as string | null | undefined);
    const last = utcDate(entry.sources.lastReadingUtc as string | null | undefined);
    lines.push({
      label: 'Window',
      text:
        first && last
          ? `${clockOnDay(first, timeZone)} → ${clockOnDay(last, timeZone)} — a clock window, not your sleep`
          : 'a clock window, not your sleep',
    });
    lines.push({
      label: 'Rule',
      text:
        'the highest reading inside the window. No sleep times were recorded for this night, ' +
        'so the window falls back to the clock and may include hours you were awake.',
    });
    const sample = first ? daytimeSample(first, timeZone) : null;
    if (first && sample) {
      warning = `The first reading in this window is from ${clock(first, timeZone)} — ${sample}, not part of your night.`;
    }
  }
  const threshold = thresholdLine(entry, 'your disruption threshold');
  if (threshold) lines.push(threshold);
  return {
    figure: entry.figure,
    title: `Bedroom peak overnight — ${oneDecimal(entry.value)} °C`,
    lines,
    warning,
  };
}

function hrvFloor(entry: ProvenanceEntry): ProvenanceRow | null {
  if (entry.value === null) return null;
  const nights = count(entry.sources, 'nightsUsed');
  const days = count(entry.sources, 'windowDays');
  const median = count(entry.sources, 'medianMs');
  const spread = count(entry.sources, 'stddevsBelowMedian');
  const lines: ProvenanceLine[] = [];
  if (nights !== null) {
    lines.push({ label: 'Nights used', text: `${nights} of your own overnight readings` });
  }
  lines.push({
    label: 'Window',
    text:
      days !== null
        ? `the ${days} days before this morning, excluding it`
        : 'the days before this morning, excluding it',
  });
  lines.push({
    label: 'Rule',
    text:
      `your own median${median !== null ? ` (${oneDecimal(median)} ms)` : ''} minus ` +
      `${spread !== null ? spread : 1.5} standard deviations of it. ` +
      "This is your own floor, not a population band and not Garmin's.",
  });
  const morning = entry.threshold?.comparedAgainst;
  if (typeof morning === 'number') {
    const relation =
      morning < entry.value ? 'below it' : morning > entry.value ? 'above it' : 'right on it';
    lines.push({ label: 'This morning', text: `${morning} ms — ${relation}` });
  }
  return {
    figure: entry.figure,
    title: `Acute personal HRV floor — ${oneDecimal(entry.value)} ms`,
    lines,
  };
}

const BOUNDARIES: Record<string, string> = {
  actual_laps: "Garmin's lap boundaries from the ride itself",
  actual_trace:
    'the target-power changes in your ride trace (Garmin supplied no usable step laps)',
  planned_durations:
    'the planned-duration clock (Garmin supplied no usable step laps, so a boundary can be out by a few seconds)',
  none: 'none — no planned interval structure was available',
};

function intervalGrading(entry: ProvenanceEntry): ProvenanceRow | null {
  const total = count(entry.sources, 'workIntervals');
  if (entry.value === null || !total) return null;
  const over = count(entry.sources, 'over') ?? 0;
  const under = count(entry.sources, 'under') ?? 0;
  const ungraded = count(entry.sources, 'ungraded') ?? 0;
  const kind = entry.window?.kind ?? '';
  return {
    figure: entry.figure,
    title: `Work intervals on target — ${entry.value} of ${total}`,
    lines: [
      {
        label: 'Boundaries',
        text: BOUNDARIES[kind] ?? entry.window?.label ?? 'not recorded',
      },
      {
        label: 'Rule',
        text:
          'a sustained effort is graded on the average power it held across its window, not its peak. ' +
          'A short effort is graded on its peak and can never be "over". An interval that recorded below ' +
          'the recovery next to it is a segmentation failure, so its grade is withheld rather than counted.',
      },
      {
        label: 'This session',
        text: `${entry.value} on target, ${over} over, ${under} under, ${ungraded} ungraded`,
      },
    ],
  };
}

function nightsLine(entry: ProvenanceEntry, label: string): ProvenanceLine | null {
  const withPeak = count(entry.sources, 'nightsWithAPeak');
  const inPeriod = count(entry.sources, 'nightsInPeriod');
  if (withPeak === null || inPeriod === null) return null;
  return { label, text: `${withPeak} of the ${inPeriod} in this period` };
}

function windowSplitLine(entry: ProvenanceEntry): ProvenanceLine | null {
  const measured = count(entry.sources, 'nightsFromSleepWindow');
  const fallback = count(entry.sources, 'nightsFromClockFallback');
  if (measured === null || fallback === null) return null;
  return {
    label: 'Window',
    text: `${measured} measured over your real sleep window, ${fallback} over a clock window`,
  };
}

function reviewAveragePeak(entry: ProvenanceEntry): ProvenanceRow | null {
  if (entry.value === null) return null;
  const lines = [
    nightsLine(entry, 'Nights used'),
    windowSplitLine(entry),
    {
      label: 'Rule',
      text: "the average of each night's highest reading; a night with no readings is left out rather than counted as cold",
    },
  ].filter((line): line is ProvenanceLine => line !== null);
  return {
    figure: entry.figure,
    title: `Average bedroom peak — ${oneDecimal(entry.value)} °C`,
    lines,
  };
}

function reviewDisruptionNights(entry: ProvenanceEntry): ProvenanceRow | null {
  if (entry.value === null) return null;
  const lines = [
    nightsLine(entry, 'Nights measured'),
    windowSplitLine(entry),
    {
      label: 'Rule',
      text: "a night counts when its peak reaches the threshold; a night without a measured peak can't count either way",
    },
    thresholdLine(entry, 'your disruption threshold'),
  ].filter((line): line is ProvenanceLine => line !== null);
  return {
    figure: entry.figure,
    title: `Nights warm enough to disrupt sleep — ${entry.value}`,
    lines,
  };
}

/** One panel row per covered figure; `null` when there is nothing to explain. */
export function describeProvenance(entry: ProvenanceEntry, timeZone?: string): ProvenanceRow | null {
  switch (entry.figure) {
    case 'environment.thermalReview.indoorPeakC':
      return bedroomPeak(entry, timeZone);
    case 'verdict.acutePhysiology.hrvAcuteFloorMs':
      return hrvFloor(entry);
    case 'execution.onTargetCount':
      return intervalGrading(entry);
    case 'review.thermal.avgIndoorPeakC':
      return reviewAveragePeak(entry);
    case 'review.thermal.disruptionNights':
      return reviewDisruptionNights(entry);
    default:
      // A figure the panel has no words for yet shows the packet's own working.
      if (entry.value === null) return null;
      return {
        figure: entry.figure,
        title: `${entry.label.charAt(0).toUpperCase()}${entry.label.slice(1)} — ${entry.value}${
          entry.units ? ` ${entry.units}` : ''
        }`,
        lines: [
          ...(entry.window?.label ? [{ label: 'Window', text: entry.window.label }] : []),
          { label: 'Rule', text: entry.rule },
        ],
      };
  }
}
