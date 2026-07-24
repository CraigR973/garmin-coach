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

  it('falls back to a clean "API error {status}" for a non-JSON error body', async () => {
    // Batch 143: a day-time Anthropic outage reached the client as a bare 500
    // with a plain-text "Internal Server Error" body. Parsing it threw a
    // SyntaxError we used to re-throw verbatim ("Unexpected token 'I'…").
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 500,
        json: async () => {
          throw new SyntaxError('Unexpected token \'I\', "Internal S"... is not valid JSON');
        },
      })),
    );

    await expect(apiFetch('/api/v1/example')).rejects.toThrow('API error 500');
    await expect(apiFetch('/api/v1/example')).rejects.not.toThrow('Unexpected token');
  });
});
