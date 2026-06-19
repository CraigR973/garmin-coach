import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { CalcioLogo } from '@/components/CalcioLogo';

describe('CalcioLogo', () => {
  it('renders the mark variant as an inline themed SVG using currentColor', () => {
    const { container } = render(<CalcioLogo variant="mark" label="Calcio" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    // Ring + spokes follow the theme via currentColor rather than a fixed navy.
    expect(svg!.querySelector('[stroke="currentColor"]')).not.toBeNull();
    // currentColor is wired to the themed steele token so it flips light/dark.
    expect(svg!.getAttribute('class')).toContain('text-[var(--steele)]');
    expect(svg!.getAttribute('aria-label')).toBe('Calcio');
  });

  it('keeps the gold brand accent and hides decorative marks from a11y', () => {
    const { container } = render(<CalcioLogo variant="mark" decorative />);
    const svg = container.querySelector('svg');
    expect(svg!.querySelector('[fill="#D4A44B"]')).not.toBeNull();
    expect(svg!.getAttribute('aria-hidden')).toBe('true');
  });

  it('renders the filled-tile primary variant as an <img> for app icons', () => {
    const { container } = render(<CalcioLogo variant="primary" label="Calcio" />);
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img!.getAttribute('src')).toBe('/brand/calcio-icon-primary.svg');
  });
});
