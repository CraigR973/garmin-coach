import type { ReactNode } from 'react';
import { Thermometer, Wind } from 'lucide-react';
import { PageHeader } from '@/components/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { formatDateTime, friendlyDate } from '@/lib/dailyFlow';

export function BedroomPage() {
  const query = useDailyLoop();

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
