import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PinInput } from './PinInput';
import { controlFieldClassName } from './ui/input';

// Batch 137 — the PIN cells sit on the shared control-field system (raised fill
// + control border + focus ring) instead of the pre-Batch-52 bg-surface look, so
// they match every other input.
describe('PinInput', () => {
  it('renders maxLength cells on the shared control-field fill', () => {
    render(<PinInput value="" onChange={() => {}} maxLength={4} />);
    const cells = screen.getAllByLabelText(/PIN digit/);
    expect(cells).toHaveLength(4);
    const first = cells[0];
    expect(first.className).toContain('bg-control');
    expect(first.className).toContain('border-control-border');
    expect(first.className).not.toContain('bg-surface');
    // w-12 overrides controlFieldClassName's w-full via tailwind-merge.
    expect(first.className).toContain('w-12');
    expect(first.className).not.toContain('w-full');
    // Focus-ring token from the shared base is present.
    expect(controlFieldClassName).toContain('focus-visible:shadow-glow');
  });
});
