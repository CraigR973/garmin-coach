import { render, screen } from '@testing-library/react';
import { Star } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { SaveButton } from './save-button';

const CHECK_PATH = 'M3 8.5 L6.5 12 L13 4.5';

// Batch 137 — the shared save affordance: leading icon in idle/saving, an
// animated check in saved, disabled while saving/saved.
describe('SaveButton', () => {
  it('shows the idle label and a leading icon at rest, enabled', () => {
    const { container } = render(
      <SaveButton state="idle" idleLabel="Save setting" icon={Star} />,
    );
    const button = screen.getByRole('button') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    // The leading icon renders; the saved check does not.
    expect(container.querySelector('svg')).not.toBeNull();
    expect(container.querySelector(`path[d="${CHECK_PATH}"]`)).toBeNull();
  });

  it('is disabled while saving and shows the saving label', () => {
    render(<SaveButton state="saving" idleLabel="Save setting" savingLabel="Saving…" />);
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText('Saving…').length).toBeGreaterThan(0);
  });

  it('draws the check and holds disabled in the saved state', () => {
    const { container } = render(
      <SaveButton state="saved" idleLabel="Save setting" savedLabel="Setting saved" icon={Star} />,
    );
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true);
    expect(container.querySelector(`path[d="${CHECK_PATH}"]`)).not.toBeNull();
  });
});
