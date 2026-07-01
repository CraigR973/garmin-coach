import type { bedroomOvernightSchema } from '@coach/shared';

type Overnight = typeof bedroomOvernightSchema._type;
type TemperaturePoint = Overnight['temperature'][number];
type FanPoint = Overnight['fan'][number];

/** The loop's overnight cadence (services/fan_control.INTERVAL_MIN), in ms. */
export const INTERVAL_MS = 15 * 60 * 1000;

/** Fan ticks where the loop could not (or chose not to) act — charted as gaps. */
const MUTED_ACTIONS = new Set(['auto_off', 'unreachable']);

const MUTED_LABEL: Record<string, string> = {
  auto_off: 'Autopilot off',
  unreachable: 'Fan unreachable',
};

export interface ChartPoint {
  /** Epoch ms — a numeric time axis spaces ticks correctly across gaps. */
  t: number;
  /** Room temperature °C, or null at a fan-only timestamp (line connects across). */
  c: number | null;
  /** Effective fan speed (0 when off), or null where the fan was not read (muted). */
  speed: number | null;
}

export interface MutedSpan {
  start: number;
  end: number;
  action: string;
  label: string;
}

/**
 * Merge the temperature and fan series onto one numeric time axis (Batch 31).
 *
 * The Hive poll and the fan loop fire at *different* 15-min offsets, so points are
 * placed at their own real timestamps and the temperature line bridges fan-only
 * times with `connectNulls` — a nearest-time read alignment, not exact-timestamp.
 * Fan speed is 0 when off; `null` for auto_off / unreachable ticks so those read
 * as an explained gap (the muted span draws the explanation), not "off, cold".
 */
export function buildChartSeries(
  temperature: TemperaturePoint[],
  fan: FanPoint[],
): ChartPoint[] {
  const byTime = new Map<number, ChartPoint>();
  const at = (t: number): ChartPoint => {
    let point = byTime.get(t);
    if (!point) {
      point = { t, c: null, speed: null };
      byTime.set(t, point);
    }
    return point;
  };
  for (const tp of temperature) {
    at(new Date(tp.t).getTime()).c = tp.c;
  }
  for (const fp of fan) {
    const point = at(new Date(fp.t).getTime());
    point.speed = MUTED_ACTIONS.has(fp.action) ? null : fp.on ? (fp.speed ?? 0) : 0;
  }
  return [...byTime.values()].sort((a, b) => a.t - b.t);
}

/**
 * Contiguous runs of muted fan ticks (autopilot off / cloud unreachable), as
 * `[start, end]` epoch-ms spans for a faint background `ReferenceArea` that
 * *explains* a gap rather than leaving it blank.
 */
export function mutedSpans(fan: FanPoint[]): MutedSpan[] {
  const spans: MutedSpan[] = [];
  let current: MutedSpan | null = null;
  for (const fp of fan) {
    const t = new Date(fp.t).getTime();
    if (MUTED_ACTIONS.has(fp.action)) {
      if (current && current.action === fp.action) {
        current.end = t + INTERVAL_MS;
      } else {
        if (current) spans.push(current);
        current = {
          start: t,
          end: t + INTERVAL_MS,
          action: fp.action,
          label: MUTED_LABEL[fp.action] ?? fp.action,
        };
      }
    } else if (current) {
      spans.push(current);
      current = null;
    }
  }
  if (current) spans.push(current);
  return spans;
}
