/**
 * Batch 290: resume restores the sessions the holiday skipped; it no longer builds
 * a new block. Wording approved by Craig, 25 Sep 2026: "Welcome back — your plan is
 * back on, with 3 sessions restored." With nothing to restore (or a holiday cancelled
 * before it began) the approved line is used without its clause.
 */
export function resumeMessage(restoredCount: number): string {
  if (restoredCount > 0) {
    const sessions = restoredCount === 1 ? '1 session' : `${restoredCount} sessions`;
    return `Welcome back — your plan is back on, with ${sessions} restored.`;
  }
  return 'Welcome back — your plan is back on.';
}
