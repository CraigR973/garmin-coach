import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { HolidayPage } from './HolidayPage';

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

const noHoliday = {
  data: {
    windows: [],
    activeWindow: null,
  },
  meta: { generatedAtUtc: '2026-07-01T06:00:00Z' },
  errors: [],
};

const activeHoliday = {
  data: {
    windows: [
      {
        startDate: '2026-07-14',
        endDate: '2026-07-21',
        pausedAtUtc: '2026-07-13T20:00:00',
        resumedAtUtc: null,
        isActive: true,
      },
    ],
    activeWindow: {
      startDate: '2026-07-14',
      endDate: '2026-07-21',
      pausedAtUtc: '2026-07-13T20:00:00',
      resumedAtUtc: null,
      isActive: true,
    },
  },
  meta: { generatedAtUtc: '2026-07-14T06:00:00Z' },
  errors: [],
};

const pauseResponse = {
  data: {
    window: {
      startDate: '2026-07-14',
      endDate: '2026-07-21',
      pausedAtUtc: '2026-07-13T20:00:00',
      resumedAtUtc: null,
      isActive: true,
    },
    skippedCount: 3,
  },
  meta: { generatedAtUtc: '2026-07-13T20:00:00Z' },
  errors: [],
};

const resumeResponse = {
  data: {
    window: {
      startDate: '2026-07-14',
      endDate: '2026-07-21',
      pausedAtUtc: '2026-07-13T20:00:00',
      resumedAtUtc: '2026-07-22T06:00:00',
      isActive: false,
    },
    continuationLabel: 'Build2',
    regeneratedCount: 5,
  },
  meta: { generatedAtUtc: '2026-07-22T06:00:00Z' },
  errors: [],
};

function renderPage(queryClient?: QueryClient) {
  const qc = queryClient ?? new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HolidayPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HolidayPage', () => {
  it('shows the pause form when no active holiday', async () => {
    apiFetchMock.mockResolvedValue(noHoliday);
    renderPage();
    expect(await screen.findByText('Set holiday dates')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Pause plan/ })).toBeTruthy();
  });

  it('pauses the plan and shows confirmation toast', async () => {
    const qc = new QueryClient();
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/holiday/pause') {
        return Promise.resolve(pauseResponse);
      }
      return Promise.resolve(noHoliday);
    });

    renderPage(qc);
    await screen.findByText('Set holiday dates');

    await user.type(screen.getByLabelText('First day of holiday'), '2026-07-14');
    await user.type(screen.getByLabelText('Last day of holiday'), '2026-07-21');

    const pauseBtn = screen.getByRole('button', { name: /Pause plan/ });
    await user.click(pauseBtn);

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/holiday/pause',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('shows resume button when holiday is active', async () => {
    apiFetchMock.mockResolvedValue(activeHoliday);
    renderPage();
    expect(await screen.findByText('Holiday active')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Resume plan/ })).toBeTruthy();
  });

  it('resumes the plan and shows continuation label in toast', async () => {
    const { toast } = await import('sonner');
    const user = userEvent.setup();

    apiFetchMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST' && path === '/api/v1/holiday/resume') {
        return Promise.resolve(resumeResponse);
      }
      return Promise.resolve(activeHoliday);
    });

    renderPage();
    await screen.findByText('Holiday active');

    await user.click(screen.getByRole('button', { name: /Resume plan/ }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        expect.stringContaining('Build2'),
      );
    });
  });
});
