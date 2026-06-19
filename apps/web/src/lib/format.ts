/**
 * Humanise an average prediction submission time.
 * Input: minutes before kickoff (positive = submitted early).
 * Output: "Xd Yh before", "Xh Ym before", "Xm before", etc.
 */
export function formatSubmitTime(mins: number): string {
  const totalMins = Math.round(Math.abs(mins));
  const totalHours = Math.floor(totalMins / 60);
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const remainingMins = totalMins % 60;

  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h before` : `${days}d before`;
  }
  if (totalHours >= 1) {
    return remainingMins > 0
      ? `${totalHours}h ${remainingMins}m before`
      : `${totalHours}h before`;
  }
  return `${totalMins}m before`;
}
