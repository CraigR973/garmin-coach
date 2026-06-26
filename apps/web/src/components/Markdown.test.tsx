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
});
