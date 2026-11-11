import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Markdown } from './Markdown';

describe('Markdown', () => {
  it('renders bold headlines as <strong>, not literal asterisks', () => {
    const { container } = render(<Markdown>{'**REM 1h 3m** — at the floor of your band.'}</Markdown>);
    const strong = container.querySelector('strong');
    expect(strong?.textContent).toBe('REM 1h 3m');
    // The literal asterisks must not survive into the rendered text.
    expect(container.textContent).not.toContain('**');
  });

  it('renders GFM tables', () => {
    const md = ['| Metric | Last night |', '| --- | --- |', '| HRV | 51 |'].join('\n');
    const { container } = render(<Markdown>{md}</Markdown>);
    expect(container.querySelector('table')).toBeTruthy();
    expect(screen.getByText('HRV')).toBeTruthy();
    expect(screen.getByText('51')).toBeTruthy();
  });

  it('shows a read stored inside one code block as the markdown it is (Decision #501)', () => {
    const md = '```markdown\n# Post-ride read\n\n**Steady.** Your heart rate drifted 3.1%.\n```';
    const { container } = render(<Markdown>{md}</Markdown>);
    expect(container.querySelector('h1')?.textContent).toBe('Post-ride read');
    expect(container.querySelector('strong')?.textContent).toBe('Steady.');
    expect(container.querySelector('pre')).toBeNull();
    expect(container.textContent).not.toContain('```');
  });

  it('still shows a code block inside a read as code', () => {
    const { container } = render(<Markdown>{'Before it.\n\n```\nnot a wrapper\n```'}</Markdown>);
    expect(container.querySelector('pre')?.textContent).toBe('not a wrapper\n');
  });

  it('makes overflowing markdown tables keyboard focusable', () => {
    const md = ['| Metric | Last night |', '| --- | --- |', '| HRV | 51 |'].join('\n');
    render(<Markdown>{md}</Markdown>);

    const region = screen.getByRole('region', { name: 'Scrollable markdown table' });
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.className).toContain('focus-visible:shadow-glow');
  });
});
