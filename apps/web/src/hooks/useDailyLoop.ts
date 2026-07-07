import { useQuery } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type;
export type DailyLoopData = DailyLoopEnvelope['data'];

export async function fetchDailyLoop() {
  const response = await apiFetch<unknown>('/api/v1/daily-loop');
  return dailyLoopEnvelopeSchema.parse(response);
}

export function useDailyLoop() {
  // Batch 62.1: a small staleTime lets a hydrated brief render immediately on a
  // quick reopen while a stale one still background-refetches (never blocking).
  return useQuery({
    queryKey: ['daily-loop'],
    queryFn: fetchDailyLoop,
    staleTime: 60_000,
  });
}
