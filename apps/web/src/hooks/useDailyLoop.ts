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
  return useQuery({ queryKey: ['daily-loop'], queryFn: fetchDailyLoop });
}
