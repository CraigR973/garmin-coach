import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { AuthProvider } from '@/contexts/AuthContext';
import { TopBar } from '@/components/TopBar';

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>{children}</button>
  ),
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
}));

const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({
  id: 'p1',
  displayName: 'Alice',
  role: 'player',
  timezone: 'UTC',
});

function stubAuth() {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => {
      if (k === 'wc2026_player') return STORED_PLAYER;
      if (k === 'wc2026_access') return FAKE_JWT;
      return null;
    },
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  });
}

function renderTopBar() {
  stubAuth();
  vi.stubGlobal('fetch', () => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<TopBar />} />
            <Route path="/about" element={<div>About route</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TopBar avatar menu', () => {
  it('includes a one-tap About entry in the avatar dropdown', () => {
    renderTopBar();

    fireEvent.click(screen.getAllByRole('button', { name: /account menu/i })[0]);
    fireEvent.click(screen.getAllByRole('link', { name: /about \/ how it works/i })[0]);

    expect(screen.getByText('About route')).toBeTruthy();
  });

  it('uses the larger compact logo size in the top bar only', () => {
    const { container } = renderTopBar();

    // The compact brand mark is now an inline themed SVG (was a navy-tile <img>).
    const brandIcons = Array.from(container.querySelectorAll('svg[width="46"]'));

    expect(brandIcons.length).toBeGreaterThan(0);
    brandIcons.forEach((icon) => {
      expect(icon).toHaveAttribute('width', '46');
      expect(icon).toHaveAttribute('height', '46');
    });
  });

  it('adds extra iPhone safe-area clearance on the mobile header', () => {
    const { container } = renderTopBar();

    const header = container.querySelector('header');
    const mobileBrandLink = container.querySelector('a[aria-label="Home"].absolute');
    const navRow = container.querySelector('header > div');

    expect(header?.className).toContain('pt-[calc(env(safe-area-inset-top,0px)+1rem)]');
    expect(navRow?.className).toContain('h-16');
    expect(mobileBrandLink?.className).toContain('inset-y-0');
  });
});
