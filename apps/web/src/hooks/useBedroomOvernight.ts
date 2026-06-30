import { useQuery } from '@tanstack/react-query';
import { bedroomOvernightEnvelopeSchema } from '@coach/shared';
import { apiFetch } from '@/lib/api';

export type BedroomOvernightEnvelope = typeof bedroomOvernightEnvelopeSchema._type;
export type BedroomOvernightData = BedroomOvernightEnvelope['data'];

export async function fetchBedroomOvernight(night?: string | null) {
  const query = night ? `?date=${night}` : '';
  const response = await apiFetch<unknown>(`/api/v1/bedroom/overnight${query}`);
  return bedroomOvernightEnvelopeSchema.parse(response);
}

/** Fetch one night's temp × fan × sleep series. `night` omitted = last completed
 *  night (what the Home glance wants); pass a date to page back on /bedroom. */
export function useBedroomOvernight(night?: string | null) {
  return useQuery({
    queryKey: ['bedroom-overnight', night ?? 'default'],
    queryFn: () => fetchBedroomOvernight(night),
  });
}
