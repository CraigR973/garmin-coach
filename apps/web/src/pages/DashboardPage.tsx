import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { dailyLoopEnvelopeSchema } from '@coach/shared';
import {
  Activity,
  Bike,
  Dumbbell,
  BedDouble,
  ClipboardCheck,
  Thermometer,
  Wind,
  type LucideIcon,
} from 'lucide-react';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Markdown } from '@/components/Markdown';
import { MetricsBaselineTable, type MetricBaselineRow } from '@/components/MetricsBaselineTable';
import { VerdictHero } from '@/components/VerdictHero';
import { greetingForNow, verdictLabel } from '@/lib/copy';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';

type DailyLoopEnvelope = typeof dailyLoopEnvelopeSchema._type;
type DailyLoopData = DailyLoopEnvelope['data'];

// ── Formatting helpers ──────────────────────────────────────────────────────

function hm(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  const mins = Math.round(seconds / 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

function friendlyDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Not synced';
  const d = new Date(value);
  if (d.getTime() > Date.now() + 24 * 60 * 60 * 1000) return 'Sync error';
  return d.toLocaleString();
}

function verdictBadgeVariant(verdict: string | null | undefined): 'success' | 'warning' | 'error' | 'muted' {
  if (verdict === 'green') return 'success';
  if (verdict === 'amber') return 'warning';
  if (verdict === 'red') return 'error';
  return 'muted';
}

function workoutIcon(type: string): LucideIcon {
  const t = type.toLowerCase();
  if (/dumbbell|bodyweight|strength|resist/.test(t)) return Dumbbell;
  if (/bike|cycl|ride|vo2|z2|sweet|endurance|tempo|threshold/.test(t)) return Bike;
  return Activity;
}

function prettyType(type: string): string {
  const cleaned = type.replace(/[_-]+/g, ' ').trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

// REM is Mark's most sensitive metric; his age-appropriate band is 65–90 min.
function remContext(remSeconds: number | null | undefined): string | null {
  if (remSeconds === null || remSeconds === undefined) return null;
  const mins = Math.round(remSeconds / 60);
  if (mins < 65) return 'below your 65–90 min range';
  if (mins > 90) return 'above your 65–90 min range';
  return 'in your 65–90 min range';
}

async function fetchDailyLoop() {
  const response = await apiFetch<unknown>('/api/v1/daily-loop');
  return dailyLoopEnvelopeSchema.parse(response);
}

// ── Page ────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { player } = useAuth();
  const isOnline = useOnlineStatus();

  const query = useQuery({ queryKey: ['daily-loop'], queryFn: fetchDailyLoop });
  const greeting = `${greetingForNow()}${player ? `, ${player.displayName}` : ''}`;

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title={greeting} />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-5">
        <PageHeader title={greeting} />
        <Card>
          <CardHeader>
            <CardTitle>Today&apos;s brief couldn&apos;t load</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Please try again in a moment.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const data: DailyLoopData = query.data.data;
  const analysis = data.morningAnalysis;
  const sleep = data.sleep;
  const thermal = data.thermalState;
  const postWorkouts = data.postWorkoutAnalyses ?? [];
  const baselines = (analysis?.metricsVsBaselines ?? []) as MetricBaselineRow[];
  const checkInDone = Boolean(data.manualEntry);

  return (
    <div className="space-y-5">
      {!isOnline && (
        <div
          role="status"
          className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
        >
          You&apos;re offline — showing your last saved brief for {friendlyDate(data.subjectDate)}.
        </div>
      )}

      <PageHeader title={greeting} />

      <VerdictHero verdict={analysis?.verdict} dateLabel={friendlyDate(data.subjectDate)} />

      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link to="/check-in">
            <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
            {checkInDone ? 'Update check-in' : 'Check in'}
          </Link>
        </Button>
      </div>

      {/* Last night's sleep */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BedDouble className="h-4 w-4 text-primary" aria-hidden />
            Last night&apos;s sleep
          </CardTitle>
          {sleep ? (
            <CardDescription>
              {hm(sleep.durationSec)} asleep
              {sleep.qualifier ? ` · ${sleep.qualifier}` : ''}
              {remContext(sleep.remSleepSec) ? ` · REM ${remContext(sleep.remSleepSec)}` : ''}
            </CardDescription>
          ) : (
            <CardDescription>No sleep data has synced for last night yet.</CardDescription>
          )}
        </CardHeader>
        {sleep && (
          <CardContent>
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <Stat label="Score" value={sleep.ageAdjustedScore ?? sleep.score ?? '—'} hint={sleep.ageAdjustedScore ? 'age-adjusted' : undefined} />
              <Stat label="REM" value={hm(sleep.remSleepSec)} />
              <Stat label="Deep" value={hm(sleep.deepSleepSec)} />
              <Stat
                label="SpO₂"
                value={
                  sleep.averageSpo2Pct !== null && sleep.averageSpo2Pct !== undefined
                    ? `${sleep.averageSpo2Pct.toFixed(0)}%`
                    : '—'
                }
              />
              <Stat label="Resting HR" value={sleep.restingHeartRateBpm ?? '—'} />
              <Stat label="Restless" value={sleep.restlessMomentsCount ?? '—'} />
            </div>
          </CardContent>
        )}
      </Card>

      {/* Metrics vs baselines — the table Mark asked for */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" aria-hidden />
            Metrics vs your baselines
          </CardTitle>
          <CardDescription>How last night compares with your own normal range.</CardDescription>
        </CardHeader>
        <CardContent>
          <MetricsBaselineTable rows={baselines} />
        </CardContent>
      </Card>

      {/* Today's training */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2">
            <span>Today&apos;s training</span>
            <Badge variant={verdictBadgeVariant(analysis?.verdict)}>{verdictLabel(analysis?.verdict)}</Badge>
          </CardTitle>
          <CardDescription>
            {data.plannedWorkouts.length
              ? 'Your sessions for today, judged against how you slept and recovered.'
              : `No sessions are scheduled for ${friendlyDate(data.subjectDate)}.`}
          </CardDescription>
        </CardHeader>
        {(data.plannedWorkouts.length > 0 || (analysis?.planAdjustments.length ?? 0) > 0) && (
          <CardContent className="space-y-3">
            {data.plannedWorkouts.map((workout) => {
              const Icon = workoutIcon(workout.workoutType);
              return (
                <div
                  key={workout.id}
                  className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-3"
                >
                  <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-text-primary">{workout.title}</p>
                    <p className="text-sm text-text-secondary">
                      {prettyType(workout.workoutType)}
                      {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                      {workout.intensityTarget ? ` · ${workout.intensityTarget}` : ''}
                    </p>
                  </div>
                  {workout.adherence?.adherenceStatus ? (
                    <Badge variant="muted" className="shrink-0 capitalize">
                      {workout.adherence.adherenceStatus}
                    </Badge>
                  ) : null}
                </div>
              );
            })}

            {analysis && analysis.planAdjustments.length > 0 && (
              <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-3 text-sm">
                <p className="mb-1 font-medium text-warning">Today&apos;s adjustments</p>
                <ul className="ml-4 list-disc space-y-1 text-text-primary marker:text-warning">
                  {analysis.planAdjustments.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* The coach's full read */}
      {analysis ? (
        <Card>
          <CardHeader>
            <CardTitle>The full picture</CardTitle>
            <CardDescription>Generated {formatDateTime(analysis.generatedAtUtc)}</CardDescription>
          </CardHeader>
          <CardContent>
            <Markdown>{analysis.outputMarkdown}</Markdown>
          </CardContent>
        </Card>
      ) : null}

      {/* Post-workout analysis */}
      {postWorkouts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bike className="h-4 w-4 text-primary" aria-hidden />
              After your workout
            </CardTitle>
            <CardDescription>
              {postWorkouts.length === 1
                ? 'Your latest ride, recovery, and what it means for tomorrow.'
                : `${postWorkouts.length} ride analyses for today.`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {postWorkouts.map((item) => (
              <div key={item.id} className="rounded-2xl border border-border bg-bg px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-text-primary">{item.activityName ?? 'Your ride'}</p>
                    <p className="text-sm text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
                  </div>
                  {item.recoveryDecision?.excluded ? (
                    <Badge variant="warning">Not counted for recovery</Badge>
                  ) : null}
                </div>
                <div className="mt-3">
                  <Markdown>{item.outputMarkdown}</Markdown>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Bedroom & weather (secondary) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Thermometer className="h-4 w-4 text-primary" aria-hidden />
            Bedroom &amp; weather
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat
            label="Indoor now"
            value={
              thermal.latestTemperatureC != null ? `${thermal.latestTemperatureC.toFixed(1)}°C` : 'Not synced'
            }
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
            label="Overnight wind"
            value={thermal.overnightWindMaxMph != null ? `${thermal.overnightWindMaxMph.toFixed(0)} mph` : '—'}
            icon={<Wind className="h-3.5 w-3.5 text-text-muted" aria-hidden />}
          />
        </CardContent>
      </Card>
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
  icon?: React.ReactNode;
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
