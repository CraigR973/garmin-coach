import { useQuery } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type;
export type DailyLoopData = DailyLoopEnvelope['data'];

export async function fetchDailyLoop(subjectDate?: string) {
  const query = subjectDate ? `?subject_date=${subjectDate}` : '';
  const response = await apiFetch<unknown>(`/api/v1/daily-loop${query}`);
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
