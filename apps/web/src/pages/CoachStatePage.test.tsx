import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CoachStatePage } from './CoachStatePage';

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    player: {
      id: '11111111-1111-4111-8111-111111111111',
      displayName: 'Mark',
      role: 'player',
      timezone: 'Europe/London',
    },
  }),
}));

describe('CoachStatePage', () => {
  it('shows the admin-only guard for non-admin players', () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CoachStatePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText('Admin access required')).toBeTruthy();
    expect(
      screen.getByText('This internal editor is only available to the seeded admin profile.'),
    ).toBeTruthy();
  });
});
