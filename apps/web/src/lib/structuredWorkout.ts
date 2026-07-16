// Shared read model for a bike workout's structured steps.
//
// Batch 135: the free-form editor (StructuredWorkoutSheet) and the read-only
// detail sheet (WorkoutDetailSheet) both need to interpret the same
// `structuredWorkout` JSON blob (an ordered `steps` list) and render the same
// ride shape. This module holds that shared interpretation — the segment shape,
// the blob→segments parser, the segments→power-bars expander, and a read-only
// summariser — so there is one source of truth for both surfaces rather than a
// duplicated parser/renderer.

export type SegmentKind = 'ramp' | 'steady' | 'interval';

// A segment carries nullable numbers because the editor can hold a half-typed /
// cleared field; a parsed-from-storage segment always has its fields populated.
export interface WorkoutSegment {
  kind: SegmentKind;
  durationMin: number | null;
  startFtpPct: number | null;
  endFtpPct: number | null;
  ftpPct: number | null;
  repeats: number | null;
  workMin: number | null;
  workFtpPct: number | null;
  recoverMin: number | null;
  recoverFtpPct: number | null;
}

export interface PowerBar {
  durationMin: number;
  startPct: number;
  endPct: number;
}

export type Delivery = 'indoor' | 'outdoor';

export interface ParsedStructuredWorkout {
  delivery: Delivery;
  segments: WorkoutSegment[];
}

// A read-only, human-readable line for one segment (detail sheet list).
export interface SegmentSummary {
  title: string;
  detail: string;
}

export function blankSegment(kind: SegmentKind): WorkoutSegment {
  const base: WorkoutSegment = {
    kind,
    durationMin: null,
    startFtpPct: null,
    endFtpPct: null,
    ftpPct: null,
    repeats: null,
    workMin: null,
    workFtpPct: null,
    recoverMin: null,
    recoverFtpPct: null,
  };
  if (kind === 'ramp') return { ...base, durationMin: 10, startFtpPct: 45, endFtpPct: 75 };
  if (kind === 'steady') return { ...base, durationMin: 20, ftpPct: 65 };
  return { ...base, repeats: 4, workMin: 4, workFtpPct: 110, recoverMin: 4, recoverFtpPct: 55 };
}

// The editor's starting template when there is nothing to parse.
export const DEFAULT_SEGMENTS: WorkoutSegment[] = [
  blankSegment('ramp'),
  blankSegment('steady'),
  { ...blankSegment('ramp'), durationMin: 5, startFtpPct: 75, endFtpPct: 45 },
];

/**
 * Faithfully parse a stored `structuredWorkout` blob into segments. Unlike the
 * editor's template default, this returns an empty `segments` array when the
 * blob carries no real steps — so a read-only surface can tell "has structure"
 * from "no structure" rather than showing a fabricated default ride.
 */
export function parseStructuredWorkout(
  structuredWorkout: Record<string, unknown> | null | undefined,
): ParsedStructuredWorkout {
  if (!structuredWorkout) return { delivery: 'indoor', segments: [] };
  const delivery: Delivery = structuredWorkout.delivery === 'outdoor' ? 'outdoor' : 'indoor';
  const rawSteps = Array.isArray(structuredWorkout.steps) ? structuredWorkout.steps : [];
  const segments: WorkoutSegment[] = [];
  for (const rawStep of rawSteps) {
    const segment = segmentFromStep(rawStep);
    if (segment) segments.push(segment);
  }
  return { delivery, segments };
}

function segmentFromStep(rawStep: unknown): WorkoutSegment | null {
  if (typeof rawStep !== 'object' || rawStep === null) return null;
  const step = rawStep as Record<string, unknown>;
  const minutes = numberOrNull(step.minutes);
  const ramp = Array.isArray(step.ramp) ? step.ramp : null;
  const target = typeof step.target === 'string' ? step.target : '';
  const pattern = typeof step.pattern === 'string' ? step.pattern : '';

  if (ramp && ramp.length === 2 && minutes) {
    return {
      ...blankSegment('ramp'),
      durationMin: minutes,
      startFtpPct: Math.round(Number(ramp[0])),
      endFtpPct: Math.round(Number(ramp[1])),
    };
  }
  if (pattern) {
    const parsed = parsePattern(pattern, target);
    if (parsed) return parsed;
  }
  const pct = parsePower(target);
  if (minutes && pct !== null) {
    return { ...blankSegment('steady'), durationMin: minutes, ftpPct: pct };
  }
  return null;
}

function parsePattern(pattern: string, target: string): WorkoutSegment | null {
  const match = pattern.match(/(\d+)\s*x\s*(\d+)min\s*\/\s*(\d+)min\s*@(\d+)%/i);
  if (!match) return null;
  return {
    ...blankSegment('interval'),
    repeats: Number(match[1]),
    workMin: Number(match[2]),
    workFtpPct: parsePower(target) ?? 110,
    recoverMin: Number(match[3]),
    recoverFtpPct: Number(match[4]),
  };
}

function parsePower(value: string): number | null {
  const match = value.match(/(\d+(?:\.\d+)?)\s*%/);
  return match ? Math.round(Number(match[1])) : null;
}

/** Expand segments into flat power bars (intervals unrolled) for the profile SVG. */
export function expand(segments: WorkoutSegment[]): PowerBar[] {
  const bars: PowerBar[] = [];
  for (const segment of segments) {
    if (segment.kind === 'ramp') {
      if (positive(segment.durationMin) && isNum(segment.startFtpPct) && isNum(segment.endFtpPct)) {
        bars.push({ durationMin: segment.durationMin, startPct: segment.startFtpPct, endPct: segment.endFtpPct });
      }
    } else if (segment.kind === 'steady') {
      if (positive(segment.durationMin) && isNum(segment.ftpPct)) {
        bars.push({ durationMin: segment.durationMin, startPct: segment.ftpPct, endPct: segment.ftpPct });
      }
    } else if (
      positive(segment.repeats) &&
      positive(segment.workMin) &&
      isNum(segment.workFtpPct) &&
      positive(segment.recoverMin) &&
      isNum(segment.recoverFtpPct)
    ) {
      for (let rep = 0; rep < segment.repeats; rep += 1) {
        bars.push({ durationMin: segment.workMin, startPct: segment.workFtpPct, endPct: segment.workFtpPct });
        bars.push({ durationMin: segment.recoverMin, startPct: segment.recoverFtpPct, endPct: segment.recoverFtpPct });
      }
    }
  }
  return bars;
}

/**
 * A read-only one-line description of a segment. `index`/`total` let a leading
 * or trailing ramp read as "Warm-up" / "Cool-down" — matching the editor's own
 * ramp-role labelling.
 */
export function describeSegment(segment: WorkoutSegment, index: number, total: number): SegmentSummary {
  if (segment.kind === 'ramp') {
    const title = index === 0 ? 'Warm-up' : index === total - 1 ? 'Cool-down' : 'Ramp';
    return { title, detail: `${segment.durationMin} min · ${segment.startFtpPct}→${segment.endFtpPct}% FTP` };
  }
  if (segment.kind === 'steady') {
    return { title: 'Steady', detail: `${segment.durationMin} min · ${segment.ftpPct}% FTP` };
  }
  return {
    title: 'Intervals',
    detail: `${segment.repeats}× (${segment.workMin} min @ ${segment.workFtpPct}% / ${segment.recoverMin} min @ ${segment.recoverFtpPct}%)`,
  };
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function isNum(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function positive(value: number | null | undefined): value is number {
  return isNum(value) && value > 0;
}
