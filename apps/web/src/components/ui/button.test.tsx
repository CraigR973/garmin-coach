import { describe, expect, it } from 'vitest';
import { buttonVariants } from './button';

describe('buttonVariants', () => {
  it('keeps small buttons at the 44px touch target floor', () => {
    const classes = buttonVariants({ size: 'sm' });
    expect(classes).toContain('min-h-11');
    expect(classes).not.toContain('h-9');
  });
});
