import type { CoachOriginKind } from '@coach/shared';

/**
 * Which surface the coach was opened from (Batch 179.4).
 *
 * The origin *seeds* the conversation — "we're talking about last night's
 * sleep" — without fencing it: Mark can still ask about anything from
 * anywhere. Only the kind travels to the server, never a free-text label, and
 * an unrecognised route simply falls back to `general`.
 */
const ROUTE_ORIGINS: Array<[string, CoachOriginKind]> = [
  ['/brief', 'morning_brief'],
  ['/sleep', 'sleep'],
  ['/delivery', 'week'],
  ['/trends', 'trends'],
  ['/reviews', 'reviews'],
  ['/environment', 'environment'],
  ['/check-in', 'check_in'],
];

export function originForPath(pathname: string): CoachOriginKind {
  if (pathname === '/') return 'home';
  const match = ROUTE_ORIGINS.find(
    ([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  return match ? match[1] : 'general';
}

/** What the launcher tells Mark it will talk about, for each origin. */
export const ORIGIN_PROMPTS: Record<CoachOriginKind, string> = {
  general: 'Ask your coach anything',
  home: 'Ask about today',
  morning_brief: "Ask about this morning's brief",
  sleep: 'Ask about your sleep',
  week: 'Ask about your week',
  workout: 'Ask about this session',
  trends: 'Ask about your trends',
  reviews: 'Ask about your review',
  weekly_review: 'Reply to your weekly review',
  environment: 'Ask about your bedroom',
  breathwork: 'Ask about your breathwork',
  strength: 'Ask about your strength work',
  walking: 'Ask about your walking',
  check_in: 'Ask about your check-in',
};
