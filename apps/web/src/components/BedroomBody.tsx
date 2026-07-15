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
  fans: FanState[];
};

function autoTargetFan(thermal: ThermalState) {
  return thermal.fans.find((fan) => fan.autoTarget) ?? thermal.fans[0] ?? null;
}

/** The bedroom climate + fan read: room stats, live fan status, and (in the
 *  `full` variant) the Auto toggle and manual Off/Low/Med/High controls.
 *  `compact` (Home's evening "Bedroom" section) shows the read-only status line
 *  and a detail link into `/environment`; `full` (the Climate tab, Batch 101)
 *  carries the actual controls. Extracted from `DashboardPage` so every
 *  climate surface renders the same stats block. */
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
    mutationFn: ({ fanId, power, speed }: { fanId: string; power?: boolean; speed?: number; label: string }) =>
      apiFetch('/api/v1/fan/command', {
        method: 'POST',
        body: JSON.stringify({ fanId, power, speed }),
      }),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(variables.label);
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not reach the fan'),
  });

  const commandPending = commandMutation.isPending;
  const autoFan = autoTargetFan(thermal);

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
              <p className="text-sm text-text-secondary">
                {autoFan ? fanStatusText(autoFan) : 'No controllable fan found'}
              </p>
            </div>
            <Toggle
              checked={autoFan?.autoEnabled ?? false}
              onCheckedChange={(checked) => autoMutation.mutate(checked)}
              disabled={autoMutation.isPending || autoFan == null}
              label="Overnight fan autopilot"
            />
          </div>

          <div className="space-y-3">
            <p className="text-xs text-text-muted">Manual control</p>
            {thermal.fans.map((fan) => (
              <div key={fan.id} className="rounded-xl border border-border px-3 py-3">
                <div className="mb-3">
                  <p className="font-medium text-text-primary">{fan.label}</p>
                  <p className="text-sm text-text-secondary">{fanStatusText(fan)}</p>
                  <p className="text-xs text-text-muted">
                    {fan.presetMode ? `Mode ${fan.presetMode}` : 'Mode unknown'}
                    {' · '}
                    {fan.oscillating == null ? 'Oscillation unknown' : fan.oscillating ? 'Oscillating' : 'Fixed'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={commandPending}
                    onClick={() =>
                      commandMutation.mutate({ fanId: fan.id, power: false, label: `${fan.label} turned off` })
                    }
                  >
                    Turn off
                  </Button>
                  {MANUAL_SPEEDS.map(({ label, speed }) => (
                    <Button
                      key={`${fan.id}-${speed}`}
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={commandPending}
                      onClick={() =>
                        commandMutation.mutate({
                          fanId: fan.id,
                          power: true,
                          speed,
                          label: `${fan.label} set to ${label}`,
                        })
                      }
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </div>
            ))}
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
              <p className="font-medium text-text-primary">
                {thermal.fans.length > 1 ? `Fans (${thermal.fans.length})` : 'Bedroom fan'}
              </p>
              <p className="text-text-secondary">
                {autoFan ? fanStatusText(autoFan) : 'No controllable fan found'}
              </p>
            </div>
          </div>
          <DetailLinkCard
            to="/environment"
            title="Open Climate"
            description="See the full room detail, overnight chart, and fan controls."
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
