import { useQuery } from '@tanstack/react-query';
import { sleepCalendarVerdictsEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export type SleepCalendarVerdictsEnvelope = typeof sleepCalendarVerdictsEnvelopeSchema._type;
export type SleepCalendarVerdictsData = SleepCalendarVerdictsEnvelope['data'];

export async function fetchSleepCalendarVerdicts(fromDate: string, toDate: string) {
  const query = `?from=${encodeURIComponent(fromDate)}&to=${encodeURIComponent(toDate)}`;
  const response = await apiFetch<unknown>(`/api/v1/sleep/verdicts${query}`);
  return sleepCalendarVerdictsEnvelopeSchema.parse(response);
}

export function useSleepCalendarVerdicts(fromDate: string, toDate: string) {
  return useQuery({
    queryKey: ['sleep-calendar-verdicts', fromDate, toDate],
    queryFn: () => fetchSleepCalendarVerdicts(fromDate, toDate),
  });
}
