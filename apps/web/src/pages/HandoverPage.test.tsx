import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { HandoverPage } from './HandoverPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function envelope(withNarrative: boolean) {
  return {
    data: {
      subjectDate: '2026-06-23',
      packet: { packetType: 'handover_export' },
      markdown: '# CheckMark — Handover Document\n\n## Athlete profile\n- **Name:** Mark',
      export: withNarrative
        ? {
            generatedAtUtc: '2026-06-23T08:00:00Z',
            modelName: 'claude-sonnet-4-6',
            promptVersion: 'handover-v1',
            markdown: '# Handover\n\nMark is a 57-year-old endurance athlete.',
          }
        : null,
    },
    meta: { generatedAtUtc: '2026-06-23T08:00:00Z' },
    errors: [],
  };
}

describe('HandoverPage', () => {
  it('renders the deterministic export and generates a narrative', async () => {
    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/handover/run') {
        return Promise.resolve(envelope(true));
      }
      if (path === '/api/v1/handover') {
        return Promise.resolve(envelope(false));
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HandoverPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // The briefing is shown first, with no written summary yet.
    expect(await screen.findByText('Full briefing for a new AI chat')).toBeTruthy();
    expect(screen.getByText(/Athlete profile/)).toBeTruthy();
    expect(screen.queryByText('Written summary')).toBeNull();

    await user.click(screen.getByRole('button', { name: /Write summary/ }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/handover/run',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    expect(await screen.findByText(/57-year-old endurance athlete/)).toBeTruthy();
  });
});
