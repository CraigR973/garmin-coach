import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { fetchDailyLoop, type DailyLoopData } from '@/hooks/useDailyLoop';
import { localTodayIso } from '@/lib/dailyFlow';

/**
 * Is the served daily-loop payload for a day other than local-today, and how do
 * you get a fresh one?
 *
 * Batch 138 built this inside `DashboardPage` and no other page inherited it
 * (UX241-11). The persisted React Query cache and the service worker's
 * NetworkFirst fallback can both paint an earlier day's payload on a cold or
 * slow open, so `/brief` could show yesterday's brief with yesterday's date in
 * small caps at the top and no route to a fresh read short of killing the app.
 * Mark was being asked to notice a date in order to avoid acting on the wrong
 * day's verdict.
 *
 * Batch 248 lifts it here so every consumer of `useDailyLoop` inherits it
 * instead of reimplementing it. Local-today is derived from the timezone the
 * *payload itself* carries, not from the browser and not from auth context: the
 * comparison is only meaningful against the timezone the backend built that
 * subject date in, and taking it from the payload keeps the check self-contained
 * — no provider, no second query, and correct either side of midnight UTC.
 */
export function useDailyLoopFreshness(
  data: DailyLoopData | undefined,
  options?: { isOnline?: boolean },
) {
  const queryClient = useQueryClient();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const isOnline = options?.isOnline ?? true;

  const isStale = isOnline && data != null && data.subjectDate !== localTodayIso(data.timezone);

  const refresh = async () => {
    setIsRefreshing(true);
    try {
      // `forceFresh` sends `cache: 'reload'`. A user-initiated refresh from the
      // banner must not re-serve the same day-old response the banner is warning
      // about, which is what a plain refetch through NetworkFirst would do.
      await queryClient.fetchQuery({
        queryKey: ['daily-loop', 'today'],
        queryFn: () => fetchDailyLoop(undefined, { forceFresh: true }),
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  return { isStale, isRefreshing, refresh };
}
