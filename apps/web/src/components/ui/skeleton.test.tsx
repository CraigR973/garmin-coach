import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Skeleton } from './skeleton';

// Batch 137 — Skeleton uses the bespoke shimmer sweep (not a flat opacity pulse)
// and stays static under reduced motion.
describe('Skeleton', () => {
  it('uses the shimmer sweep and disables it under reduced motion', () => {
    render(<Skeleton className="h-4 w-24" />);
    const el = screen.getByRole('status');
    expect(el.className).toContain('animate-shimmer');
    expect(el.className).not.toContain('animate-pulse');
    expect(el.className).toContain('motion-reduce:animate-none');
  });
});
