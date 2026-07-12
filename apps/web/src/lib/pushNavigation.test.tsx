import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PushNavigationController } from '../components/PushNavigationController';
import {
  PUSH_NAVIGATION_MESSAGE_TYPE,
  buildPushNavigationMessage,
  focusOrOpenPushTarget,
  normalizePushNavigationUrl,
} from './pushNavigation';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

describe('push navigation helpers (Batch 99)', () => {
  it('normalizes same-origin deep-links and rejects cross-origin ones', () => {
    expect(normalizePushNavigationUrl('/check-in?from=push#today', 'https://coach.test')).toBe(
      '/check-in?from=push#today',
    );
    expect(normalizePushNavigationUrl('https://coach.test/brief', 'https://coach.test')).toBe('/brief');
    expect(normalizePushNavigationUrl('https://example.com/phish', 'https://coach.test')).toBe('/');
    expect(normalizePushNavigationUrl('', 'https://coach.test')).toBe('/');
  });

  it('posts the target URL to an already-open client', async () => {
    const focus = vi.fn(async () => undefined);
    const postMessage = vi.fn();
    const openWindow = vi.fn();

    await focusOrOpenPushTarget({
      windowClients: [{ focus, postMessage }],
      rawUrl: '/check-in',
      origin: 'https://coach.test',
      openWindow,
    });

    expect(focus).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({
      type: PUSH_NAVIGATION_MESSAGE_TYPE,
      url: '/check-in',
    });
    expect(openWindow).not.toHaveBeenCalled();
  });

  it('falls back to openWindow when no client is already open', async () => {
    const openWindow = vi.fn(async () => undefined);

    await focusOrOpenPushTarget({
      windowClients: [],
      rawUrl: '/brief',
      origin: 'https://coach.test',
      openWindow,
    });

    expect(openWindow).toHaveBeenCalledWith('/brief');
  });
});

describe('PushNavigationController', () => {
  const addEventListener = vi.fn();
  const removeEventListener = vi.fn();

  beforeEach(() => {
    addEventListener.mockReset();
    removeEventListener.mockReset();
    Object.defineProperty(window.navigator, 'serviceWorker', {
      configurable: true,
      value: { addEventListener, removeEventListener },
    });
    window.history.replaceState({}, '', '/');
  });

  it('routes the SPA when the service worker posts a deep-link message', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <PushNavigationController />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(addEventListener).toHaveBeenCalledTimes(1);
    const handler = addEventListener.mock.calls[0]?.[1] as ((event: MessageEvent<unknown>) => void) | undefined;
    expect(handler).toBeTypeOf('function');

    await act(async () => {
      handler?.({
        data: buildPushNavigationMessage('/check-in?from=push#today', window.location.origin),
      } as MessageEvent<unknown>);
    });

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/check-in'));
  });

  it('ignores unrelated service-worker messages', async () => {
    render(
      <MemoryRouter initialEntries={['/brief']}>
        <PushNavigationController />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const handler = addEventListener.mock.calls[0]?.[1] as ((event: MessageEvent<unknown>) => void) | undefined;

    await act(async () => {
      handler?.({ data: { type: 'other', url: '/check-in' } } as MessageEvent<unknown>);
    });

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/brief'));
  });
});
