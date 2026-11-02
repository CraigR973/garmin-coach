import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { STRENGTH_ON_WATCH_BUTTON, isDumbbellSessionToDo } from '@/lib/strengthOnWatch';
import { StrengthOnWatchButton } from './StrengthOnWatchButton';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => apiFetchMock(...args) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// Batch 368.5 (UX362-08): the watch button sits on Home on a dumbbell day, as on Week.
describe('the watch button', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('shows only for a Dumbbells A or B session still to do', () => {
    expect(isDumbbellSessionToDo({ title: 'Dumbbells A (legs and back)', status: 'planned' })).toBe(true);
    expect(isDumbbellSessionToDo({ title: 'Dumbbells B (upper body)', status: 'completed' })).toBe(false);
    expect(isDumbbellSessionToDo({ title: 'Z2', status: 'planned' })).toBe(false);
  });

  it('asks the server to put the week on his watch, once per tap', async () => {
    apiFetchMock.mockResolvedValue({ data: { placed: [], alreadyThere: [], failed: [] } });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <StrengthOnWatchButton />
      </QueryClientProvider>,
    );
    await userEvent.setup().click(screen.getByRole('button', { name: STRENGTH_ON_WATCH_BUTTON }));
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/plan-actions/strength-on-watch', {
      method: 'POST',
    });
  });
});
