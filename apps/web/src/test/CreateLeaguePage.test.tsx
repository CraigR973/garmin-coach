import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CreateLeaguePage } from '@/pages/CreateLeaguePage';

// Far-future exp so apiFetch's ensureFreshToken never tries to refresh.
const FAKE_JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwMSIsImV4cCI6OTk5OTk5OTk5OX0.fake';
const STORED_PLAYER = JSON.stringify({ id: 'p1', displayName: 'Alice', role: 'player', timezone: 'UTC' });

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

/** Stub fetch, capturing the parsed body of the create-league POST. */
function stubCreate(): { get: () => Record<string, unknown> | null } {
  let captured: Record<string, unknown> | null = null;
  vi.stubGlobal('fetch', (url: string, init: RequestInit) => {
    if (url.includes('/api/v1/leagues')) {
      captured = JSON.parse(init.body as string) as Record<string, unknown>;
      return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ slug: 'my-league' }) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
  return { get: () => captured };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={['/leagues/new']}>
      <QueryClientProvider client={qc}>
        <CreateLeaguePage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  stubAuth();
});

describe('CreateLeaguePage — privacy payload maps to backend enum', () => {
  it('sends "public_open" by default (not the legacy "open" that 422s)', async () => {
    const req = stubCreate();
    renderPage();
    fireEvent.change(screen.getByLabelText(/league name/i), { target: { value: 'My League' } });
    fireEvent.click(screen.getByRole('button', { name: /create league/i }));
    await waitFor(() => expect(req.get()).not.toBeNull());
    expect(req.get()?.privacy).toBe('public_open');
  });

  it('maps the Request option to "public_request"', async () => {
    const req = stubCreate();
    renderPage();
    fireEvent.change(screen.getByLabelText(/league name/i), { target: { value: 'My League' } });
    fireEvent.change(screen.getByLabelText(/privacy/i), { target: { value: 'public_request' } });
    fireEvent.click(screen.getByRole('button', { name: /create league/i }));
    await waitFor(() => expect(req.get()).not.toBeNull());
    expect(req.get()?.privacy).toBe('public_request');
  });
});
