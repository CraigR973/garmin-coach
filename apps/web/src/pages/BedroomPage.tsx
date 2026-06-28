import type { ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Fan, Thermometer, Wind } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { Toggle } from '@/components/ui/toggle';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { apiFetch } from '@/lib/api';
import { fanStatusText, formatDateTime, friendlyDate } from '@/lib/dailyFlow';

// Manual presets mirror the overnight speed ladder (services/fan_control.SPEED_LADDER).
const MANUAL_SPEEDS: Array<{ label: string; speed: number }> = [
  { label: 'Low', speed: 3 },
  { label: 'Medium', speed: 5 },
  { label: 'High', speed: 7 },
];

export function BedroomPage() {
  const query = useDailyLoop();
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

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title="Bedroom & weather" back={{ to: '/', label: 'Home' }} />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Bedroom & weather" back={{ to: '/', label: 'Home' }} />
        <Card>
          <CardHeader>
            <CardTitle>Bedroom data couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const data = query.data.data;
  const thermal = data.thermalState;
  const fan = thermal.fan;
  const commandPending = commandMutation.isPending;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Bedroom & weather"
        eyebrow={friendlyDate(data.subjectDate)}
        back={{ to: '/', label: 'Home' }}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-primary" aria-hidden />
            Bedroom climate
          </CardTitle>
          <CardDescription>Latest room and overnight conditions for sleep.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <BedroomStat
            label="Indoor now"
            value={thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'Not synced'}
            hint={formatDateTime(thermal.capturedAtUtc)}
          />
          <BedroomStat
            label="Thermostat"
            value={thermal.targetTemperatureC != null ? `${thermal.targetTemperatureC.toFixed(1)}°C` : '—'}
          />
          <BedroomStat
            label="Overnight low"
            value={thermal.overnightLowC != null ? `${thermal.overnightLowC.toFixed(1)}°C` : '—'}
          />
          <BedroomStat
            label="Overnight wind"
            value={thermal.overnightWindMaxMph != null ? `${thermal.overnightWindMaxMph.toFixed(0)} mph` : '—'}
            icon={<Wind className="h-3.5 w-3.5 text-text-muted" aria-hidden />}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Fan className="h-4 w-4 text-primary" aria-hidden />
            Bedroom fan
          </CardTitle>
          <CardDescription>
            When the autopilot is on, the fan runs itself overnight from the room temperature.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-3">
            <div className="min-w-0">
              <p className="font-medium text-text-primary">Overnight autopilot</p>
              <p className="text-sm text-text-secondary">{fanStatusText(fan)}</p>
            </div>
            <Toggle
              checked={fan.autoEnabled}
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
        </CardContent>
      </Card>
    </div>
  );
}

function BedroomStat({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
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
      {hint ? <p className="text-[11px] text-text-muted">{hint}</p> : null}
    </div>
  );
}
