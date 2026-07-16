import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BedroomBody } from './BedroomBody';
import type { FanState } from '@/lib/dailyFlow';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function baseFan(overrides: Partial<FanState> = {}): FanState {
  return {
    id: 'fan-bedroom',
    label: 'Bedroom fan',
    autoEnabled: true,
    autoTarget: true,
    mode: 'control',
    isOn: true,
    speed: 4,
    respondingToC: 20.8,
    oscillating: null,
    presetMode: null,
    ...overrides,
  };
}

function renderBedroom(fan: FanState) {
  const thermal = {
    latestTemperatureC: 18.9,
    targetTemperatureC: 17,
    overnightLowC: 12.4,
    overnightWindMaxMph: 11,
    fans: [fan],
  };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <BedroomBody thermal={thermal} variant="full" />
    </QueryClientProvider>,
  );
}

describe('BedroomBody (Batch 129)', () => {
  it('does not print the same live fan status twice for a single fan', () => {
    renderBedroom(baseFan());
    // The live "Auto · on at speed 4, responding to 20.8°C" line belongs to the fan
    // card only; the autopilot row now describes what the toggle does.
    expect(screen.getAllByText(/Auto · on at speed 4, responding to 20\.8°C/)).toHaveLength(1);
    expect(screen.getByText(/Following the room overnight/)).toBeTruthy();
  });

  it('describes the autopilot as off when auto is disabled', () => {
    renderBedroom(baseFan({ autoEnabled: false, isOn: false }));
    expect(screen.getByText(/holds your manual setting/)).toBeTruthy();
  });

  it('hides the mode/oscillation line entirely when neither is reported', () => {
    renderBedroom(baseFan({ presetMode: null, oscillating: null }));
    expect(screen.queryByText(/unknown/i)).toBeNull();
  });

  it('shows mode/oscillation only for the fields that are reported', () => {
    renderBedroom(baseFan({ presetMode: 'auto', oscillating: true }));
    expect(screen.getByText('Mode auto · Oscillating')).toBeTruthy();
    expect(screen.queryByText(/unknown/i)).toBeNull();
  });
});
