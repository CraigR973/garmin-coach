import { MemoryRouter } from 'react-router-dom';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TabBar } from '@/components/TabBar';
import { TopBar } from '@/components/TopBar';

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    player: { id: '1', displayName: 'Mark', role: 'player', timezone: 'Europe/London' },
    logout: vi.fn(),
  }),
}));

vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ resolved: 'dark', setMode: vi.fn() }),
}));

function renderAt(path: string, ui: React.ReactElement) {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

describe('primary navigation (Batch 49)', () => {
  it('TabBar renders Home / Week / Sleep as the primary tabs', () => {
    renderAt('/', <TabBar />);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getByText('Home')).toBeTruthy();
    expect(within(nav).getByText('Week')).toBeTruthy();
    expect(within(nav).getByText('Sleep')).toBeTruthy();
    expect(within(nav).queryByText('Plan')).toBeNull();
    expect(within(nav).queryByText('Trends')).toBeNull();
  });

  it('TabBar marks Sleep active on /sleep', () => {
    renderAt('/sleep', <TabBar />);
    const sleepLink = screen.getByRole('link', { name: /sleep/i });
    expect(sleepLink.getAttribute('aria-current')).toBe('page');
  });

  it('TabBar "More" lights active for a re-tiered secondary path', () => {
    renderAt('/trends', <TabBar />);
    const moreButton = screen.getByRole('button', { name: /more/i });
    expect(moreButton.getAttribute('aria-current')).toBe('page');
  });

  it('TabBar opens the More sheet with the re-tiered, de-jargoned groups', async () => {
    const user = userEvent.setup();
    renderAt('/', <TabBar />);
    await user.click(screen.getByRole('button', { name: /more/i }));

    expect(await screen.findByText('For you')).toBeTruthy();
    expect(screen.getByText('Coaching')).toBeTruthy();
    expect(screen.getByText('Setup')).toBeTruthy();
    expect(screen.getByText('Reviews')).toBeTruthy();
    expect(screen.getByText('Trends')).toBeTruthy();
    expect(screen.getByText('New training block')).toBeTruthy();
    expect(screen.getByText('Experiments')).toBeTruthy();
    expect(screen.getByText('Coach memory')).toBeTruthy();
    expect(screen.getByText('Handover')).toBeTruthy();
    expect(screen.getByText('Settings')).toBeTruthy();
    // De-jargoned: no raw "Tests", "Plan builder", or "Coach state" labels remain.
    expect(screen.queryByText('Tests')).toBeNull();
    expect(screen.queryByText('Plan builder')).toBeNull();
    expect(screen.queryByText('Coach state')).toBeNull();
  });

  it('TopBar desktop nav mirrors the primary tabs and "More" dropdown mirrors MoreMenu', async () => {
    const user = userEvent.setup();
    renderAt('/', <TopBar />);
    expect(screen.getAllByTestId('logomark').length).toBeGreaterThanOrEqual(2);
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(within(nav).getByText('Home')).toBeTruthy();
    expect(within(nav).getByText('Week')).toBeTruthy();
    expect(within(nav).getByText('Sleep')).toBeTruthy();

    await user.click(within(nav).getByText('More'));
    expect(await screen.findByText('For you')).toBeTruthy();
    expect(screen.getByText('Coaching')).toBeTruthy();
    expect(screen.getByText('Setup')).toBeTruthy();
    expect(screen.getByText('New training block')).toBeTruthy();
  });
});
