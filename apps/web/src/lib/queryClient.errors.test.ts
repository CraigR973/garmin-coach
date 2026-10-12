import { beforeEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { reportClientError } from './queryClient';

const captureException = vi.hoisted(() => vi.fn());
vi.mock('@/sentry', () => ({ Sentry: { captureException } }));

describe('client error reporting', () => {
  beforeEach(() => captureException.mockReset());

  it('sends schema paths to Sentry without response values', () => {
    const result = z.object({ sleep: z.number() }).safeParse({ sleep: 'private health value' });
    if (result.success) throw new Error('Fixture must fail');
    reportClientError(result.error);

    expect(captureException).toHaveBeenCalledOnce();
    const [error, context] = captureException.mock.calls[0];
    expect(error.message).toBe('Client response schema mismatch');
    expect(context.extra.issues).toEqual([{ code: 'invalid_type', path: ['sleep'] }]);
    expect(JSON.stringify(context)).not.toContain('private health value');
  });
});
