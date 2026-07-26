import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearTokens,
  getAuthToken,
  getStoredPlayer,
  storeDeviceToken,
  type StoredPlayer,
} from './tokens';

const player: StoredPlayer = {
  id: 'profile-1',
  displayName: 'Mark',
  role: 'admin',
  timezone: 'Europe/London',
};

beforeEach(() => {
  localStorage.clear();
});

describe('device-token storage', () => {
  it('stores the device credential as the sole auth token and clears legacy JWT keys', () => {
    localStorage.setItem('coach_access', 'legacy-access');
    localStorage.setItem('coach_refresh', 'legacy-refresh');

    storeDeviceToken('opaque-device-token', player);

    expect(getAuthToken()).toBe('opaque-device-token');
    expect(getStoredPlayer()).toEqual(player);
    expect(localStorage.getItem('coach_access')).toBeNull();
    expect(localStorage.getItem('coach_refresh')).toBeNull();
  });

  it('clears device, profile, and residual legacy credentials', async () => {
    storeDeviceToken('opaque-device-token', player);
    localStorage.setItem('coach_access', 'legacy-access');
    localStorage.setItem('coach_refresh', 'legacy-refresh');

    await clearTokens();

    expect(getAuthToken()).toBeNull();
    expect(getStoredPlayer()).toBeNull();
    expect(localStorage.getItem('coach_access')).toBeNull();
    expect(localStorage.getItem('coach_refresh')).toBeNull();
  });
});
