import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProvenancePanel } from './ProvenancePanel';

const hrvFloor = {
  figure: 'verdict.acutePhysiology.hrvAcuteFloorMs',
  label: 'acute personal HRV floor',
  value: 39.63,
  units: 'ms',
  rule: 'his own median minus 1.5 standard deviations',
  window: { kind: 'rolling_days', startUtc: '2026-06-30', endUtc: '2026-09-21', label: null },
  sources: { windowDays: 84, stddevsBelowMedian: 1.5, nightsUsed: 47, medianMs: 46 },
  threshold: { name: 'this morning', comparedAgainst: 36, units: 'ms', source: null },
};

describe('ProvenancePanel (Batch 273.2)', () => {
  it('is collapsed by default under one heading, with a row per figure on the screen', () => {
    render(<ProvenancePanel sources={[[hrvFloor], undefined]} timeZone="Europe/London" />);

    const panel = screen.getByTestId('provenance-panel');
    expect(panel.tagName).toBe('DETAILS');
    expect(panel.hasAttribute('open')).toBe(false);
    expect(within(panel).getByText('How these numbers were worked out')).toBeTruthy();
    expect(within(panel).getByText('Acute personal HRV floor — 39.6 ms')).toBeTruthy();
    expect(within(panel).getByText(/47 of your own overnight readings/)).toBeTruthy();
  });

  it('shows nothing on a screen whose packet carries no working', () => {
    const { container } = render(<ProvenancePanel sources={[undefined, [], [{ figure: 'broken' }]]} />);
    expect(container.innerHTML).toBe('');
  });
});
