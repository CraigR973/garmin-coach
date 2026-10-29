/**
 * Batch 343 (UX333-08): how to turn blocked notifications back on, by the phone he holds.
 * Mark has used Android Chrome since 16 Sep 2026, and the only line was the iPhone's.
 * Draft for Craig's sign-off (docs/drafts/2026-10-29-batch-343-wording.md).
 */
export const BLOCKED_ANDROID =
  'Notifications are blocked for CheckMark. In Chrome, tap the three dots › Settings › Site settings › Notifications, allow CheckMark, then come back here.';
export const BLOCKED_IPHONE =
  'Notifications are blocked for CheckMark. Turn them back on in iPhone Settings › Notifications › CheckMark, then come back here.';
export const BLOCKED_OTHER =
  "Notifications are blocked for CheckMark. Allow them in your browser's site settings, then come back here.";

export function notificationsBlockedLine(userAgent: string): string {
  if (/android/i.test(userAgent)) return BLOCKED_ANDROID;
  if (/iphone|ipad|ipod/i.test(userAgent)) return BLOCKED_IPHONE;
  return BLOCKED_OTHER;
}
