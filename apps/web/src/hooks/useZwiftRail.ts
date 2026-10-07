import { useDailyLoop } from '@/hooks/useDailyLoop';
import type { ZwiftRail } from '@/lib/zwiftRail';

/**
 * Batch 326: today's reading of the intervals.icu account, from the day the app already
 * holds. It never fetches the day itself: fetching it issues the week's REM action, which
 * only Home and the brief page should do. Before the day has loaded (or from an older
 * server) it is undefined, and the words stay as they were.
 */
export function useZwiftRail(): ZwiftRail | null | undefined {
  return useDailyLoop(undefined, { enabled: false }).data?.data.zwiftRail;
}
