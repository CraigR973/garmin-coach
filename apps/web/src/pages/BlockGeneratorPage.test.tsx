import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { BlockGeneratorPage } from './BlockGeneratorPage';

const apiFetchMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const noDraft = {
  data: { draft: null, canGenerate: true },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const draft = {
  data: {
    draft: {
      status: 'draft',
      framework: '13-week 2121',
      startDate: '2026-08-03',
      endDate: '2026-11-01',
      ftpWatts: 280,
      athleteName: 'Mark',
      generatedAtUtc: '2026-07-01T06:00:00',
      lockedAtUtc: null,
      weeks: [
        {
          weekNumber: 1,
          blockType: 'build',
          label: 'Build1',
          focus: 'Progress aerobic capacity and quality bike work.',
          startDate: '2026-08-03',
          endDate: '2026-08-09',
          workouts: [
            {
              dayOffset: 1,
              workoutDate: '2026-08-04',
              title: 'VO2 Max 30/30',
              workoutType: 'bike_vo2',
              plannedDurationMin: 60,
              intensityTarget: '105-110% FTP',
              structuredWorkout: { format: 'bike', steps: [] },
            },
          ],
        },
      ],
    },
    canGenerate: false,
  },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const lockResponse = {
  data: {
    blocksCreated: 13,
    workoutsWritten: 65,
    startDate: '2026-08-03',
    endDate: '2026-11-01',
  },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

function renderPage(queryClient?: QueryClient) {
  const qc = queryClient ?? new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BlockGeneratorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('BlockGeneratorPage', () => {
  it('shows the generate form when no draft exists', async () => {
    apiFetchMock.mockResolvedValue(noDraft);
    renderPage();
    expect(await screen.findByText('Generate a new block')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Generate block/ })).toBeTruthy();
  });

  it('generates a block and shows a confirmation toast', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/generate') {
        return Promise.resolve(draft);
      }
      return Promise.resolve(noDraft);
    });

    renderPage();
    await screen.findByText('Generate a new block');
    await user.click(screen.getByRole('button', { name: /Generate block/ }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/block-generator/generate',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(toast.success).toHaveBeenCalled();
    });
  });

  it('renders the draft weeks and lock button', async () => {
    apiFetchMock.mockResolvedValue(draft);
    renderPage();
    expect(await screen.findByText('Week 1 · Build1')).toBeTruthy();
    expect(screen.getByText('VO2 Max 30/30')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Lock block/ })).toBeTruthy();
  });

  it('locks the block and reports the workout count', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/lock') {
        return Promise.resolve(lockResponse);
      }
      return Promise.resolve(draft);
    });

    renderPage();
    await screen.findByText('Week 1 · Build1');
    await user.click(screen.getByRole('button', { name: /Lock block/ }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('65 workouts'));
    });
  });

  it('refines a day through the inline editor', async () => {
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/block-generator/refine') {
        return Promise.resolve(draft);
      }
      return Promise.resolve(draft);
    });

    renderPage();
    await screen.findByText('Week 1 · Build1');
    await user.click(screen.getByRole('button', { name: /Edit VO2 Max 30\/30/ }));

    const titleInput = await screen.findByLabelText('Workout title');
    await user.clear(titleInput);
    await user.type(titleInput, 'Custom VO2');
    await user.click(screen.getByRole('button', { name: /^Save$/ }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/block-generator/refine',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
