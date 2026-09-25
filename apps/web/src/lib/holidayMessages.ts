/** Batch 290: resume restores the skipped sessions; it no longer builds a new block. */
export function resumeMessage(restoredCount: number, cancelled: boolean): string {
  if (cancelled) return 'Holiday cancelled — your plan is back as it was.';
  if (restoredCount > 0) {
    const sessions = restoredCount === 1 ? '1 session' : `${restoredCount} sessions`;
    return `Welcome back — your plan is back on, with ${sessions} restored.`;
  }
  return 'Welcome back — your plan is back on.';
}

