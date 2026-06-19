const STORAGE_KEY = 'sss_firstrun_launchpad_seen';

export function markFirstRunLaunchpadSeen(): void {
  try { localStorage.setItem(STORAGE_KEY, '1'); } catch { /* ignore */ }
}

export function isFirstRunLaunchpadSeen(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }
}
