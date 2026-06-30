export function hm(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  const mins = Math.round(seconds / 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

export function friendlyDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** The next `n` calendar days after `fromIso`, as timezone-safe ISO dates with a
 *  short human label (e.g. "Wed 1 Jul") — used by the Today card's Swap picker. */
export function nextDays(fromIso: string, n: number): Array<{ iso: string; label: string }> {
  const base = new Date(`${fromIso}T00:00:00`);
  const out: Array<{ iso: string; label: string }> = [];
  for (let i = 1; i <= n; i += 1) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
      d.getDate(),
    ).padStart(2, '0')}`;
    const label = d.toLocaleDateString(undefined, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    });
    out.push({ iso, label });
  }
  return out;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Not synced';
  const d = new Date(value);
  if (d.getTime() > Date.now() + 24 * 60 * 60 * 1000) return 'Sync error';
  return d.toLocaleString();
}

export function remContext(remSeconds: number | null | undefined): string | null {
  if (remSeconds === null || remSeconds === undefined) return null;
  const mins = Math.round(remSeconds / 60);
  if (mins < 65) return 'below your 65–90 min range';
  if (mins > 90) return 'above your 65–90 min range';
  return 'in your 65–90 min range';
}

export interface FanState {
  autoEnabled: boolean;
  mode: string;
  isOn: boolean | null;
  speed: number | null;
  respondingToC: number | null;
}

export interface OvernightGlanceSummary {
  minTempC: number | null;
  maxTempC: number | null;
  fanRanMinutes: number;
  peakSpeed: number | null;
}

/** The one-line last-night glance for the Home bedroom card (Batch 31).
 *  Returns null when there's no room data to summarise yet. */
export function overnightGlanceText(summary: OvernightGlanceSummary | null | undefined): string | null {
  if (!summary || summary.minTempC == null || summary.maxTempC == null) return null;
  const range = `${Math.round(summary.minTempC)}→${Math.round(summary.maxTempC)} °C`;
  if (summary.fanRanMinutes <= 0) return `Last night: ${range}, fan didn't run`;
  const hours = (summary.fanRanMinutes / 60).toFixed(1);
  const peak = summary.peakSpeed != null ? ` (peak speed ${summary.peakSpeed})` : '';
  return `Last night: ${range}, fan ran ${hours} h${peak}`;
}

/** A plain-language one-liner for the bedroom-fan autopilot's current intent. */
export function fanStatusText(fan: FanState): string {
  if (!fan.autoEnabled) return 'Manual control';
  if (fan.mode === 'idle') return 'Auto · standing by until tonight';
  if (fan.mode === 'winddown') return 'Auto · winding down for the morning';
  if (fan.isOn === null) return 'Auto · waiting for a room temperature';
  const temp = fan.respondingToC != null ? fan.respondingToC.toFixed(1) : null;
  if (fan.isOn) {
    const speed = fan.speed != null ? ` at speed ${fan.speed}` : '';
    return `Auto · on${speed}${temp ? `, responding to ${temp}°C` : ''}`;
  }
  return `Auto · off, room is cool enough${temp ? ` (${temp}°C)` : ''}`;
}
