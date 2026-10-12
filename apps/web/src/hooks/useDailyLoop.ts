import { useQuery } from '@tanstack/react-query';
import { dailyLoopEnvelopeSchema, dailyLoopSchema, dailyLoopThermalStateSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';
import { reportClientError } from '@/lib/queryClient';
import { briefOnItsWay } from '@/lib/storedMorning';

/** Batch 302: how often a screen showing the day re-reads it while a brief is on its way. */
export const BRIEF_ON_ITS_WAY_POLL_MS = 5000;

export type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type & {
  unavailableFields?: Array<'thermalState' | 'briefGeneration' | 'sleep' | 'dailyMetrics' | 'plannedWorkouts'>;
};
export type DailyLoopData = DailyLoopEnvelope['data'];

/** A bad section is unavailable; other validated sections of the day can still render. */
export function parseDailyLoopResponse(response: unknown): DailyLoopEnvelope {
  const strict = dailyLoopEnvelopeSchema.safeParse(response);
  if (strict.success) return strict.data;
  if (!response || typeof response !== 'object' || !('data' in response) ||
      !response.data || typeof response.data !== 'object') throw strict.error;

  const data: Record<string, unknown> = { ...response.data };
  const fallbacks = {
    thermalState: dailyLoopThermalStateSchema.parse({}),
    briefGeneration: null,
    sleep: null,
    dailyMetrics: null,
    plannedWorkouts: [],
  } as const;
  const unavailableFields: NonNullable<DailyLoopEnvelope['unavailableFields']> = [];
  for (const key of Object.keys(fallbacks) as Array<keyof typeof fallbacks>) {
    if (!dailyLoopSchema.shape[key].safeParse(data[key]).success) {
      data[key] = fallbacks[key];
      unavailableFields.push(key);
    }
  }
  if (unavailableFields.length === 0) throw strict.error;
  const recovered = dailyLoopEnvelopeSchema.safeParse({ ...response, data });
  if (!recovered.success) throw strict.error;
  reportClientError(strict.error);
  return { ...recovered.data, unavailableFields };
}

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
  return parseDailyLoopResponse(response);
}

export function useDailyLoop(subjectDate?: string, options?: { enabled?: boolean }) {
  // Batch 62.1: a small staleTime lets a hydrated brief render immediately on a
  // quick reopen while a stale one still background-refetches (never blocking).
  return useQuery({
    queryKey: ['daily-loop', subjectDate ?? 'today'],
    queryFn: () => fetchDailyLoop(subjectDate),
    staleTime: 60_000,
    enabled: options?.enabled ?? true,
    // Batch 302: the colour is stored a little after the check-in and the brief about a
    // minute after that. Home and the brief page showed "Writing your brief" until he
    // next refocused the app; they now keep looking while a brief is on its way. The
    // server turns a wait that outlives its limit into a failure, which ends this.
    refetchInterval: (query) =>
      briefOnItsWay(query.state.data?.data) ? BRIEF_ON_ITS_WAY_POLL_MS : false,
  });
}
