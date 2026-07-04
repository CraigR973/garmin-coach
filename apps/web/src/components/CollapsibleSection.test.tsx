import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { CollapsibleSection } from './CollapsibleSection';

describe('CollapsibleSection', () => {
  it('defaults to the prominent variant — bold title, no receded card styling', () => {
    render(
      <CollapsibleSection title="Today" summary="Cycle day">
        <p>Body</p>
      </CollapsibleSection>,
    );
    const title = screen.getByText('Today');
    expect(title.className).toContain('font-semibold');
    expect(title.className).toContain('text-lg');
  });

  it('recedes under the secondary variant (Batch 54 "More detail" grouping)', () => {
    const { container } = render(
      <CollapsibleSection title="Bedroom" summary="Indoor 17.4°C" variant="secondary">
        <p>Body</p>
      </CollapsibleSection>,
    );
    const title = screen.getByText('Bedroom');
    expect(title.className).toContain('font-medium');
    expect(title.className).not.toContain('font-semibold');
    expect(container.firstElementChild?.className).toContain('border-transparent');
  });

  it('truncates a long collapsed summary on a word boundary, not mid-word', () => {
    render(
      <CollapsibleSection
        title="Tonight"
        summary="REM in your 65-90 minute range last night, and a warm room may make sleep more fragile"
      >
        <p>Body</p>
      </CollapsibleSection>,
    );
    // Cuts at the last whole word within 72 chars, not mid-word ("… may make…", not "… may mak…").
    expect(screen.getByText(/REM in your 65-90 minute range last night, and a warm room may make…/)).toBeTruthy();
  });

  it('only mounts the body once expanded, and hides the summary once open', async () => {
    const user = userEvent.setup();
    render(
      <CollapsibleSection title="Today" summary="Cycle day">
        <p>Body content</p>
      </CollapsibleSection>,
    );
    expect(screen.getByText('Cycle day')).toBeTruthy();
    expect(screen.queryByText('Body content')).toBeNull();

    await user.click(screen.getByRole('button', { name: /today/i }));

    expect(screen.getByText('Body content')).toBeTruthy();
    expect(screen.queryByText('Cycle day')).toBeNull();
  });

  it('shows the "needs a tap" dot only while collapsed with a warning tone', async () => {
    const user = userEvent.setup();
    render(
      <CollapsibleSection title="After your ride" tone="warning" summary="Tempo ride">
        <p>Body</p>
      </CollapsibleSection>,
    );
    expect(screen.getByLabelText('Needs attention')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /after your ride/i }));
    expect(screen.queryByLabelText('Needs attention')).toBeNull();
  });
});
