import type { FanState } from '@/lib/dailyFlow';

type ThermalSnapshot = {
  latestTemperatureC?: number | null;
  fans: FanState[];
};

export function bedroomLiveSummary(thermal: ThermalSnapshot): string {
  const temp =
    thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'not synced';
  const autoFan = thermal.fans.find((fan) => fan.autoTarget) ?? thermal.fans[0] ?? null;
  const fan = autoFan == null ? 'fan unavailable' : autoFan.autoEnabled ? 'fan on auto' : 'fan on manual';
  return `Indoor ${temp} · ${fan}`;
}
