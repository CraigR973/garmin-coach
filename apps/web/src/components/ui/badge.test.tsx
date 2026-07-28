import { describe, expect, it } from 'vitest';
import { badgeVariants } from './badge';

describe('badgeVariants', () => {
  it('uses AA semantic text tokens instead of decorative fill tokens', () => {
    expect(badgeVariants({ variant: 'default' })).toContain('text-primary-text');
    expect(badgeVariants({ variant: 'success' })).toContain('text-success-text');
    expect(badgeVariants({ variant: 'warning' })).toContain('text-warning-text');
    expect(badgeVariants({ variant: 'error' })).toContain('text-error-text');
    expect(badgeVariants({ variant: 'live' })).toContain('text-live-text');
  });
});
