import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MedicinesAskCard } from './MedicinesAskCard';
import {
  MEDICINES_ASK,
  MEDICINES_NO,
  MEDICINES_SAVE,
  MEDICINES_THANKS_NEW,
  MEDICINES_THANKS_NONE,
  MEDICINES_WHICH,
  MEDICINES_YES,
} from '@/lib/medicinesAsk';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => apiFetchMock(...args) }));
// The envelope's shape is the server's; the card only needs the call to succeed.
vi.mock('@coach/shared', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@coach/shared')>();
  return { ...actual, dailyLoopEnvelopeSchema: { parse: (value: unknown) => value } };
});

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('MedicinesAskCard (Batch 370.3)', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({ data: {}, meta: {}, errors: [] });
  });

  it('shows nothing until the quarter is up', () => {
    const { container } = render(wrap(<MedicinesAskCard due={false} subjectDate="2027-01-04" />));
    expect(container.textContent).toBe('');
  });

  it('answers "no" in one tap and says when it will ask again', async () => {
    const user = userEvent.setup();
    render(wrap(<MedicinesAskCard due subjectDate="2027-01-04" />));
    expect(screen.getByText(MEDICINES_ASK)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: MEDICINES_NO }));
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/daily-loop/2027-01-04/medicines', {
      method: 'POST',
      body: JSON.stringify({ answer: 'none' }),
    });
    expect(await screen.findByText(MEDICINES_THANKS_NONE)).toBeTruthy();
  });

  it('asks which on a yes, sends his words, and tells him to mention it to Craig', async () => {
    const user = userEvent.setup();
    render(wrap(<MedicinesAskCard due subjectDate="2027-01-04" />));
    await user.click(screen.getByRole('button', { name: MEDICINES_YES }));
    await user.type(screen.getByPlaceholderText(MEDICINES_WHICH), 'amlodipine 5 mg');
    await user.click(screen.getByRole('button', { name: MEDICINES_SAVE }));
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/daily-loop/2027-01-04/medicines', {
      method: 'POST',
      body: JSON.stringify({ answer: 'new', words: 'amlodipine 5 mg' }),
    });
    expect(await screen.findByText(MEDICINES_THANKS_NEW)).toBeTruthy();
    expect(MEDICINES_THANKS_NEW).toContain('mention it to Craig');
  });
});
