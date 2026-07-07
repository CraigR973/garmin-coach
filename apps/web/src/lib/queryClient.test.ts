import { QueryClient, type Query } from '@tanstack/react-query';
import { afterEach, describe, expect, it } from 'vitest';
import {
  PERSIST_KEY,
  clearPersistedCache,
  persistOptions,
  shouldPersistQuery,
} from './queryClient';

function fakeQuery(key: unknown[], status: 'success' | 'pending' | 'error'): Query {
  return { queryKey: key, state: { status } } as unknown as Query;
}

afterEach(() => {
  window.localStorage.clear();
});

describe('shouldPersistQuery', () => {
  it('persists only a successful daily-loop query', () => {
    expect(shouldPersistQuery(fakeQuery(['daily-loop'], 'success'))).toBe(true);
  });

  it('does not persist a daily-loop query that has not resolved', () => {
    expect(shouldPersistQuery(fakeQuery(['daily-loop'], 'pending'))).toBe(false);
    expect(shouldPersistQuery(fakeQuery(['daily-loop'], 'error'))).toBe(false);
  });

  it('does not persist other query keys (health data stays bounded)', () => {
    expect(shouldPersistQuery(fakeQuery(['week-ahead'], 'success'))).toBe(false);
    expect(shouldPersistQuery(fakeQuery(['reviews'], 'success'))).toBe(false);
  });

  it('is the dehydrate gate used by persistOptions', () => {
    expect(persistOptions.dehydrateOptions?.shouldDehydrateQuery).toBe(shouldPersistQuery);
  });
});

describe('persistOptions', () => {
  it('caps the persisted cache at 24h and carries a build buster', () => {
    expect(persistOptions.maxAge).toBe(24 * 60 * 60 * 1000);
    expect(typeof persistOptions.buster).toBe('string');
    expect(persistOptions.buster).not.toBe('');
  });
});

describe('clearPersistedCache', () => {
  it('removes the persisted cache key on logout/login', () => {
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify({ clientState: {} }));
    expect(window.localStorage.getItem(PERSIST_KEY)).not.toBeNull();
    clearPersistedCache();
    expect(window.localStorage.getItem(PERSIST_KEY)).toBeNull();
  });

  it('is a no-op when nothing is persisted', () => {
    expect(() => clearPersistedCache()).not.toThrow();
    // A real QueryClient still constructs fine alongside the cleared storage.
    expect(new QueryClient()).toBeInstanceOf(QueryClient);
  });
});
