import { useQuery } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type;
export type DailyLoopData = DailyLoopEnvelope['data'];

export async function fetchDailyLoop(
  subjectDate?: string,
  options?: { forceFresh?: boolean },
) {
  const query = subjectDate ? `?subject_date=${subjectDate}` : '';
  const path = `/api/v1/daily-loop${query}`;
  // Batch 138: a user-initiated refresh from the stale-data banner must not just
  // re-serve the same day-old response the service worker's NetworkFirst cache is
  // being warned about — `cache: 'reload'` bypasses the browser HTTP cache and,
  // combined with NetworkFirst trying the network first, forces a genuinely fresh
  // read. Only that path passes an init; the normal fetch stays a single-arg
  // `apiFetch(path)` so it keeps the call signature every other caller/test relies on.
  const response = options?.forceFresh
    ? await apiFetch<unknown>(path, { cache: 'reload' })
    : await apiFetch<unknown>(path);
  return dailyLoopEnvelopeSchema.parse(response);
}

export function useDailyLoop(subjectDate?: string, options?: { enabled?: boolean }) {
  // Batch 62.1: a small staleTime lets a hydrated brief render immediately on a
  // quick reopen while a stale one still background-refetches (never blocking).
  return useQuery({
    queryKey: ['daily-loop', subjectDate ?? 'today'],
    queryFn: () => fetchDailyLoop(subjectDate),
    staleTime: 60_000,
    enabled: options?.enabled ?? true,
  });
}
