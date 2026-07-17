import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { Input, controlFieldClassName } from './input';
import { Textarea } from './textarea';
import { Label } from './label';

// Batch 52 — the control tier: inputs/textareas render on the raised `--control`
// fill (not the dark-on-dark page bg), and form labels are sentence-case, not
// mono-uppercase. These lock the P0-2 legibility fix and the P1-6 label pullback.

describe('control-field primitives (Batch 52)', () => {
  it('Input renders on the control fill with a stronger border and focus ring', () => {
    render(<Input aria-label="field" placeholder="type here" />);
    const input = screen.getByLabelText('field');
    // Elevated control fill — never the page background (bg-bg / bg-surface).
    expect(input.className).toContain('bg-control');
    expect(input.className).toContain('border-control-border');
    expect(input.className).toContain('focus-visible:shadow-glow');
    expect(input.className).not.toContain('bg-bg');
  });

  it('Textarea shares the control-field base so it matches Input', () => {
    render(<Textarea aria-label="notes" />);
    const area = screen.getByLabelText('notes');
    expect(area.tagName).toBe('TEXTAREA');
    for (const cls of controlFieldClassName.split(' ')) {
      expect(area.className).toContain(cls);
    }
  });

  it('Textarea is 16px on mobile so iOS Safari does not zoom on focus (Batch 137)', () => {
    render(<Textarea aria-label="notes" />);
    const area = screen.getByLabelText('notes');
    expect(area.className).toContain('text-base');
    expect(area.className).toContain('sm:text-sm');
  });

  it('Textarea forwards value/onChange and merges a custom min-height', async () => {
    const onChange = vi.fn();
    render(<Textarea aria-label="notes" value="" onChange={onChange} className="min-h-[100px]" />);
    const area = screen.getByLabelText('notes');
    // twMerge keeps the override and drops the default min-h-[88px].
    expect(area.className).toContain('min-h-[100px]');
    expect(area.className).not.toContain('min-h-[88px]');
    await userEvent.type(area, 'x');
    expect(onChange).toHaveBeenCalled();
  });

  it('Label is sentence-case (no mono-uppercase treatment)', () => {
    render(<Label>Overall (0–10)</Label>);
    const label = screen.getByText('Overall (0–10)');
    expect(label.className).not.toContain('uppercase');
    expect(label.className).not.toContain('tracking-wider');
    expect(label.className).not.toContain('font-mono');
  });
});
