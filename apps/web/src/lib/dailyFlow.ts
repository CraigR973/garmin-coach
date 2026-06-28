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
