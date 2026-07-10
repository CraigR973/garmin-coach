import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from './api';

vi.mock('./tokens', () => ({
  clearTokens: vi.fn(async () => {}),
  getAuthToken: vi.fn(() => null),
  getDeviceToken: vi.fn(() => null),
  getRefreshToken: vi.fn(() => null),
  getStoredPlayer: vi.fn(() => null),
  isAccessTokenExpiringSoon: vi.fn(() => false),
  storeTokens: vi.fn(),
}));

describe('apiFetch', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('surfaces FastAPI array detail as a readable message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [
            {
              loc: ['body', 'durationScalePct'],
              msg: 'Input should be less than or equal to 125',
            },
          ],
        }),
      })),
    );

    await expect(apiFetch('/api/v1/example')).rejects.toThrow(
      'durationScalePct: Input should be less than or equal to 125',
    );
  });

  it('joins multiple validation errors into one message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [
            {
              loc: ['body', 'durationScalePct'],
              msg: 'Input should be less than or equal to 125',
            },
            {
              loc: ['body', 'intensityScalePct'],
              msg: 'Input should be less than or equal to 120',
            },
          ],
        }),
      })),
    );

    await expect(apiFetch('/api/v1/example')).rejects.toThrow(
      'durationScalePct: Input should be less than or equal to 125; intensityScalePct: Input should be less than or equal to 120',
    );
  });
});
