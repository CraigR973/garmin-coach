import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FtpTestCard } from './FtpTestCard';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));
const toastSuccess = vi.fn();
vi.mock('sonner', () => ({ toast: { success: (m: string) => toastSuccess(m), error: vi.fn() } }));

// His 20 Oct test, as if it were still waiting: Garmin's best minute 353 W.
const TEST = {
  plannedWorkoutId: 'test-row',
  testDate: '2026-10-20',
  bestMinuteWatts: 353,
  ftpWatts: 265,
  currentFtpWatts: 280,
  ownNumberMin: 239,
  ownNumberMax: 291,
};

function renderCard(ftpTest: typeof TEST | null | undefined) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FtpTestCard ftpTest={ftpTest} />
    </QueryClientProvider>,
  );
}

// Batch 336.1 (CI330-02): the ramp test sets his FTP, in the app and in Zwift alike.
describe('ramp test FTP card', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    toastSuccess.mockReset();
  });

  it('renders nothing without a result waiting', () => {
    const { container } = renderCard(null);
    expect(container.textContent).toBe('');
  });

  it('gives the number, how it was worked out, and names Zwift’s own FTP setting', () => {
    renderCard(TEST);
    expect(screen.getByText('Your ramp test: FTP 265 W')).toBeTruthy();
    expect(
      screen.getByText(
        'Your best minute on 20 Oct was 353 W, and your new FTP is three-quarters of it: 265 W. Your FTP in the app is 280 W now.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Zwift sets your trainer from its own FTP setting, and the app grades your rides from this one, so they need the same number. If Zwift gave you a different number for this test, use Zwift's.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Keep 280 W' })).toBeTruthy();
  });

  it('sets the app’s number in one tap', async () => {
    apiFetchMock.mockResolvedValue({ data: { ftpWatts: 265 } });
    renderCard(TEST);
    fireEvent.click(screen.getByRole('button', { name: 'Set my FTP to 265 W' }));
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "Your FTP is now 265 W. Check Zwift's FTP setting says 265 W too.",
      ),
    );
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/ftp-test/decision', {
      method: 'POST',
      body: JSON.stringify({ plannedWorkoutId: 'test-row', choice: 'set' }),
    });
  });

  it('takes Zwift’s own number inside the range only', async () => {
    apiFetchMock.mockResolvedValue({ data: { ftpWatts: 267 } });
    renderCard(TEST);
    fireEvent.click(screen.getByRole('button', { name: 'Zwift gave a different number' }));
    expect(screen.getByText('Between 239 and 291 W.')).toBeTruthy();
    const field = screen.getByLabelText("Zwift's FTP (W)");
    const save = screen.getByRole('button', { name: 'Set this FTP' }) as HTMLButtonElement;
    fireEvent.change(field, { target: { value: '300' } });
    expect(save.disabled).toBe(true);
    fireEvent.change(field, { target: { value: '267' } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls[0][1].body).toBe(
      JSON.stringify({ plannedWorkoutId: 'test-row', choice: 'set', ftpWatts: 267 }),
    );
  });

  it('keeps his FTP', async () => {
    apiFetchMock.mockResolvedValue({ data: { ftpWatts: 280 } });
    renderCard(TEST);
    fireEvent.click(screen.getByRole('button', { name: 'Keep 280 W' }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Your FTP stays 280 W.'));
  });
});
