/**
 * Tests for Avatar component (U23.3) — photo src + initials fallback.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Avatar, initials } from '@/components/ui/avatar';

// ── initials helper ────────────────────────────────────────────────────────────

describe('initials()', () => {
  it('returns "?" for empty string', () => {
    expect(initials('')).toBe('?');
  });

  it('returns first two chars for single word', () => {
    expect(initials('Alice')).toBe('AL');
  });

  it('returns first+last initials for two words', () => {
    expect(initials('Alice Smith')).toBe('AS');
  });

  it('uses first and last word for three-word names', () => {
    expect(initials('John Paul Jones')).toBe('JJ');
  });
});

// ── Avatar component ───────────────────────────────────────────────────────────

describe('Avatar', () => {
  it('renders initials when no src provided', () => {
    render(<Avatar name="Alice Smith" />);
    expect(screen.getByText('AS')).toBeInTheDocument();
  });

  it('renders initials when src is null', () => {
    render(<Avatar name="Bob" src={null} />);
    expect(screen.getByText('BO')).toBeInTheDocument();
  });

  it('renders an img when src is provided', () => {
    const { container } = render(<Avatar name="Carol" src="https://example.com/carol.jpg" />);
    const img = container.querySelector('img');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', 'https://example.com/carol.jpg');
  });

  it('falls back to initials when img fails to load', () => {
    const { container } = render(<Avatar name="Dave" src="https://example.com/bad.jpg" />);
    const img = container.querySelector('img')!;
    expect(img).toBeInTheDocument();
    // Simulate broken image
    fireEvent.error(img);
    expect(screen.getByText('DA')).toBeInTheDocument();
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });

  it('applies size classes', () => {
    const { container } = render(<Avatar name="Eve" size="lg" />);
    expect(container.firstChild).toHaveClass('h-14', 'w-14');
  });

  it('is aria-hidden', () => {
    const { container } = render(<Avatar name="Frank" />);
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true');
  });
});
