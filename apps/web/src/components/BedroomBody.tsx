import type { ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Fan, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Toggle } from '@/components/ui/toggle';
import { DetailLinkCard } from '@/components/DetailLinkCard';
import { apiFetch } from '@/lib/api';
import { fanStatusText, type FanState } from '@/lib/dailyFlow';

// Manual presets mirror the overnight speed ladder (services/fan_control.SPEED_LADDER).
const MANUAL_SPEEDS: Array<{ label: string; speed: number }> = [
  { label: 'Low', speed: 3 },
  { label: 'Medium', speed: 5 },
  { label: 'High', speed: 7 },
];

type ThermalState = {
  latestTemperatureC?: number | null;
  targetTemperatureC?: number | null;
  overnightLowC?: number | null;
  overnightWindMaxMph?: number | null;
  fan: FanState;
};

/** The bedroom climate + fan read: room stats, live fan status, and (in the
 *  `full` variant) the Auto toggle and manual Off/Low/Med/High controls.
 *  `compact` (Home's evening "Bedroom" section) shows the read-only status line
 *  and a detail link into `/sleep`; `full` (the `/sleep` hub's Tonight view,
 *  Batch 49) carries the actual controls, moved from the retired `/bedroom`
 *  page (Batch 27). Extracted from `DashboardPage` so both render the same
 *  stats block. */
export function BedroomBody({
  thermal,
  variant = 'compact',
}: {
  thermal: ThermalState;
  variant?: 'compact' | 'full';
}) {
  const queryClient = useQueryClient();

  const autoMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      apiFetch('/api/v1/fan/auto', { method: 'PUT', body: JSON.stringify({ enabled }) }),
    onSuccess: async (_data, enabled) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(enabled ? 'Overnight autopilot on' : 'Overnight autopilot off');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not update the fan setting'),
  });

  const commandMutation = useMutation({
    mutationFn: ({ power, speed }: { power?: boolean; speed?: number; label: string }) =>
      apiFetch('/api/v1/fan/command', {
        method: 'POST',
        body: JSON.stringify({ power, speed }),
      }),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(variables.label);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not reach the fan'),
  });

  const commandPending = commandMutation.isPending;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Stat
          label="Indoor now"
          value={thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'Not synced'}
        />
        <Stat
          label="Thermostat"
          value={thermal.targetTemperatureC != null ? `${thermal.targetTemperatureC.toFixed(1)}°C` : '—'}
        />
        <Stat
          label="Overnight low"
          value={thermal.overnightLowC != null ? `${thermal.overnightLowC.toFixed(1)}°C` : '—'}
        />
        <Stat
          label="Wind"
          value={thermal.overnightWindMaxMph != null ? `${thermal.overnightWindMaxMph.toFixed(0)} mph` : '—'}
          icon={<Wind className="h-3.5 w-3.5 text-text-muted" aria-hidden />}
        />
      </div>

      {variant === 'full' ? (
        <>
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-3">
            <div className="min-w-0">
              <p className="font-medium text-text-primary">Overnight autopilot</p>
              <p className="text-sm text-text-secondary">{fanStatusText(thermal.fan)}</p>
            </div>
            <Toggle
              checked={thermal.fan.autoEnabled}
              onCheckedChange={(checked) => autoMutation.mutate(checked)}
              disabled={autoMutation.isPending}
              label="Overnight fan autopilot"
            />
          </div>

          <div className="space-y-2">
            <p className="text-xs text-text-muted">Manual control</p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={commandPending}
                onClick={() => commandMutation.mutate({ power: false, label: 'Fan turned off' })}
              >
                Turn off
              </Button>
              {MANUAL_SPEEDS.map(({ label, speed }) => (
                <Button
                  key={speed}
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={commandPending}
                  onClick={() => commandMutation.mutate({ power: true, speed, label: `Fan set to ${label}` })}
                >
                  {label}
                </Button>
              ))}
            </div>
            <p className="text-[11px] text-text-muted">
              Using a manual control turns the overnight autopilot off.
            </p>
          </div>
        </>
      ) : (
        <>
          <div className="flex items-start gap-2 rounded-xl border border-border px-3 py-3 text-sm">
            <Fan className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <div className="min-w-0">
              <p className="font-medium text-text-primary">Bedroom fan</p>
              <p className="text-text-secondary">{fanStatusText(thermal.fan)}</p>
            </div>
          </div>
          <DetailLinkCard
            to="/sleep"
            title="Bedroom & weather detail"
            description="Open the full room and overnight weather read, and control the fan."
          />
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border px-3 py-3">
      <p className="flex items-center gap-1.5 text-xs text-text-muted">
        {icon}
        {label}
      </p>
      <p className="text-lg font-semibold text-text-primary">{value}</p>
      {hint && <p className="text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}
