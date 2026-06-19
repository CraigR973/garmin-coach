/**
 * Converts a verbose WC2026 placeholder string (e.g. "Winner of Match 73",
 * "Runner-up Group A", "2nd Place Group F") to a short display code
 * ("W73", "RU-A", "2F"). Already-short codes like "1A", "2B" pass through
 * unchanged. The full text is retained for title/tooltip use.
 */
export function shortPlaceholder(s: string | null | undefined): string {
  if (!s) return 'TBD';

  // Already a compact code (no whitespace, ≤ 6 chars) — return as-is
  if (!/\s/.test(s) && s.length <= 6) return s;

  // "Winner [of] Group A" → "WA"  (must check group before match-number)
  const winnerGroup = s.match(/winner[^A-L]*group\s+([A-L])/i);
  if (winnerGroup) return `W${winnerGroup[1].toUpperCase()}`;

  // "Winner [of] Match 73" → "W73"
  const winnerMatch = s.match(/winner\D+(\d+)/i);
  if (winnerMatch) return `W${winnerMatch[1]}`;

  // "Runner-up [of] Group A" → "RU-A"
  const runnerUp = s.match(/runner.{0,4}up[^A-L]*group\s+([A-L])/i);
  if (runnerUp) return `RU-${runnerUp[1].toUpperCase()}`;

  // "2nd [Place/in] Group F" / "1st Place Group F" → "2F" / "1F"
  const posGroup = s.match(/^(\d+)(?:st|nd|rd|th)[^A-L]*group\s+([A-L])/i);
  if (posGroup) return `${posGroup[1]}${posGroup[2].toUpperCase()}`;

  // Fallback: first letter of each word, max 5 chars
  return s
    .split(/\s+/)
    .map((w) => w[0] ?? '')
    .join('')
    .toUpperCase()
    .slice(0, 5);
}
