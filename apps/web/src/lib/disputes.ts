import { disputeEnvelopeSchema, type Dispute } from '@coach/shared';
import type { DisputeFormCopy } from '@/components/DisputeForm';
import { apiFetch } from '@/lib/api';

/**
 * Batch 274 — Mark's disputes. The server snapshots the working the app showed for
 * a contested figure from the stored read, so the client sends only which read,
 * which figure, and why.
 *
 * Mark-facing wording, signed off by Craig on Mark's behalf on 27 Sep 2026.
 */
export const FIGURE_CONTEST_COPY: DisputeFormCopy = {
  trigger: 'This looks wrong',
  prompt: "What's wrong with it?",
  placeholder: 'e.g. that reading is from the afternoon, not my night',
  submit: 'Send to Craig',
  sent: "Sent to Craig. It doesn't change the figure; he'll look into it.",
};

export const VERDICT_DISSENT_COPY: DisputeFormCopy = {
  trigger: "I disagree with today's call",
  prompt: 'What does the app have wrong about today?',
  placeholder: 'e.g. my HRV was only a point under a floor Garmin had just moved',
  submit: 'Record it',
  sent: "Recorded. It won't change today's call, and it will show in your weekly review.",
};

export async function contestFigure(analysisId: string, figure: string, reason: string): Promise<Dispute> {
  const response = await apiFetch<unknown>('/api/v1/disputes/figures', {
    method: 'POST',
    body: JSON.stringify({ analysisId, figure, reason }),
  });
  return disputeEnvelopeSchema.parse(response).data;
}

export async function dissentFromVerdict(subjectDate: string, reason: string): Promise<Dispute> {
  const response = await apiFetch<unknown>('/api/v1/disputes/verdicts', {
    method: 'POST',
    body: JSON.stringify({ subjectDate, reason }),
  });
  return disputeEnvelopeSchema.parse(response).data;
}
