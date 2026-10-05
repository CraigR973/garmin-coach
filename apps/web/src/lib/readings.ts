/**
 * Batch 313: how recovered he is, the engine's Green, Amber and Red in words. The
 * morning's own words come from the server with each call (`readingWords`); the calendar,
 * which reads only each day's reading, takes them from `readingWords.json`, a copy of the
 * server's `READING_WORDS` pinned to it by a parity test. This picks the chip's colour:
 * green, amber, and a calm blue for still recovering.
 */
export function readingBadgeVariant(
  reading: string | null | undefined,
): 'success' | 'warning' | 'recover' | 'muted' {
  if (reading === 'recovered') return 'success';
  if (reading === 'some_fatigue') return 'warning';
  if (reading === 'still_recovering') return 'recover';
  return 'muted';
}
