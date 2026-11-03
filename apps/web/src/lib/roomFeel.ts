/** Batch 376: the night's bedroom on Batch 366's lines, warm from 24 °C and cold below
 *  18 °C, never "critical" or a colour word. Drafts for Craig's sign-off
 *  (docs/drafts/2026-11-03-batch-376-wording.md). */
export type RoomFeel = 'comfortable' | 'warm' | 'cold';

export const ROOM_FEEL_LABEL: Record<RoomFeel, string> = {
  comfortable: 'Comfortable',
  warm: 'Warm',
  cold: 'Cold',
};

export function roomFeelVariant(feel: RoomFeel): 'success' | 'warning' {
  return feel === 'comfortable' ? 'success' : 'warning';
}

export function chartLinesLegend(coldC: number, warmC: number): string {
  return `Lines: ${coldC}° (cold below) · ${warmC}° (warm above)`;
}
