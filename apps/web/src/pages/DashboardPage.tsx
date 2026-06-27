import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  BedDouble,
  Bike,
  ChevronRight,
  ClipboardCheck,
  Dumbbell,
  MoonStar,
  Thermometer,
  Wind,
  type LucideIcon,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { VerdictHero } from '@/components/VerdictHero';
import { useAuth } from '@/contexts/AuthContext';
import { isBikeWorkout, useDailyPhase } from '@/hooks/useDailyPhase';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { formatDateTime, friendlyDate, hm, remContext } from '@/lib/dailyFlow';
import { greetingForNow, verdictLabel } from '@/lib/copy';

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

export function DashboardPage() {
  const { player } = useAuth();
  const isOnline = useOnlineStatus();
  const query = useDailyLoop();
  const greeting = `${greetingForNow()}${player ? `, ${player.displayName}` : ''}`;
  const data = query.data?.data;
  const phase = useDailyPhase(data);

  if (query.isLoading) {
    return (
      <div className="space-y-5">
        <PageHeader title={greeting} />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-40 w-full rounded-2xl" />
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

  const daily = data!;
  const analysis = daily.morningAnalysis;
  const sleep = daily.sleep;
  const thermal = daily.thermalState;
  const postWorkouts = daily.postWorkoutAnalyses ?? [];
  const todaysWorkouts = daily.plannedWorkouts;
  const bikeWorkouts = todaysWorkouts.filter((workout) => isBikeWorkout(workout.workoutType));
  const strengthWorkouts = todaysWorkouts.filter((workout) => !isBikeWorkout(workout.workoutType));

  return (
    <div className="space-y-5">
      {!isOnline && (
        <div
          role="status"
          className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
        >
          You&apos;re offline — showing your last saved brief for {friendlyDate(daily.subjectDate)}.
        </div>
      )}

      <PageHeader title={greeting} />

      <VerdictHero verdict={analysis?.verdict} dateLabel={friendlyDate(daily.subjectDate)} />

      {phase === 'pre_ride' && (
        <>
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link to="/check-in">
                <ClipboardCheck className="mr-2 h-4 w-4" aria-hidden />
                {daily.manualEntry ? 'Update check-in' : 'Check in'}
              </Link>
            </Button>
          </div>

          <SleepSnapshotCard
            sleep={sleep}
            analysisGeneratedAtUtc={analysis?.generatedAtUtc}
            morningBriefLink="/brief"
            baselinesLink="/baselines"
          />

          <WorkoutCard
            title="Today&apos;s ride"
            description="The one thing to focus on now."
            verdict={analysis?.verdict}
            workouts={bikeWorkouts}
            adjustments={analysis?.planAdjustments ?? []}
            emptyTitle="Nothing to ride today"
            emptyCopy={
              strengthWorkouts.length > 0
                ? 'Today is a strength or non-bike day, so there is nothing to send to Zwift.'
                : 'Today is a rest day.'
            }
          />

          {strengthWorkouts.length > 0 && (
            <WorkoutListCard
              title="Also on today"
              description="The non-bike work still on your slate."
              workouts={strengthWorkouts}
            />
          )}
        </>
      )}

      {phase === 'post_ride' && (
        <>
          <PostRideCard items={postWorkouts} />

          <TomorrowCard
            tomorrowImpact={postWorkouts[0]?.tomorrowImpact}
            fallback={
              analysis?.verdict
                ? `${verdictLabel(analysis.verdict)} tomorrow starts from today&apos;s recovery picture.`
                : 'Tomorrow&apos;s cue will show up here after the coach read.'
            }
          />

          <SleepPrepCard />

          <BedroomSummaryCard thermal={thermal} />
        </>
      )}

      {phase === 'rest_day' && (
        <>
          <SleepSnapshotCard
            sleep={sleep}
            analysisGeneratedAtUtc={analysis?.generatedAtUtc}
            morningBriefLink="/brief"
            baselinesLink="/baselines"
          />

          <WorkoutCard
            title="Today"
            description="A calm read of the day ahead."
            verdict={analysis?.verdict}
            workouts={bikeWorkouts}
            adjustments={analysis?.planAdjustments ?? []}
            emptyTitle="Nothing to ride today"
            emptyCopy="No bike session is scheduled today."
          />

          {strengthWorkouts.length > 0 && (
            <WorkoutListCard
              title="Also on today"
              description="The non-bike work still on your slate."
              workouts={strengthWorkouts}
            />
          )}

          <BedroomSummaryCard thermal={thermal} />
        </>
      )}
    </div>
  );
}

function SleepSnapshotCard({
  sleep,
  analysisGeneratedAtUtc,
  morningBriefLink,
  baselinesLink,
}: {
  sleep: {
    qualifier?: string | null;
    durationSec?: number | null;
    remSleepSec?: number | null;
    ageAdjustedScore?: number | null;
    score?: number | null;
    deepSleepSec?: number | null;
    averageSpo2Pct?: number | null;
    restingHeartRateBpm?: number | null;
  } | null;
  analysisGeneratedAtUtc?: string | null;
  morningBriefLink: string;
  baselinesLink: string;
}) {
  return (
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
      {sleep ? (
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Stat
              label="Score"
              value={sleep.ageAdjustedScore ?? sleep.score ?? '—'}
              hint={sleep.ageAdjustedScore ? 'age-adjusted' : undefined}
            />
            <Stat label="REM" value={hm(sleep.remSleepSec)} />
            <Stat label="Deep" value={hm(sleep.deepSleepSec)} />
            <Stat
              label="SpO2"
              value={
                sleep.averageSpo2Pct !== null && sleep.averageSpo2Pct !== undefined
                  ? `${sleep.averageSpo2Pct.toFixed(0)}%`
                  : '—'
              }
            />
            <Stat label="Resting HR" value={sleep.restingHeartRateBpm ?? '—'} />
            <Stat label="Coach read" value={analysisGeneratedAtUtc ? formatDateTime(analysisGeneratedAtUtc) : 'Pending'} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <DetailLinkCard
              to={morningBriefLink}
              title="Full morning brief"
              description="Open the complete coach read and verdict notes."
            />
            <DetailLinkCard
              to={baselinesLink}
              title="Baselines"
              description="See the full metrics-vs-baselines table."
            />
          </div>
        </CardContent>
      ) : null}
    </Card>
  );
}

function WorkoutCard({
  title,
  description,
  verdict,
  workouts,
  adjustments,
  emptyTitle,
  emptyCopy,
}: {
  title: string;
  description: string;
  verdict: string | null | undefined;
  workouts: Array<{
    id: string;
    title: string;
    workoutType: string;
    plannedDurationMin?: number | null;
    intensityTarget?: string | null;
    adherence?: { adherenceStatus?: string | null } | null;
  }>;
  adjustments: string[];
  emptyTitle: string;
  emptyCopy: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>{title}</span>
          <Badge variant={verdictBadgeVariant(verdict)}>{verdictLabel(verdict)}</Badge>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {workouts.length > 0 ? (
          workouts.map((workout) => {
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
          })
        ) : (
          <div className="rounded-xl border border-dashed border-border px-4 py-4">
            <p className="font-medium text-text-primary">{emptyTitle}</p>
            <p className="mt-1 text-sm text-text-secondary">{emptyCopy}</p>
          </div>
        )}

        {adjustments.length > 0 && (
          <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-3 text-sm">
            <p className="mb-1 font-medium text-warning">Today&apos;s adjustments</p>
            <ul className="ml-4 list-disc space-y-1 text-text-primary marker:text-warning">
              {adjustments.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function WorkoutListCard({
  title,
  description,
  workouts,
}: {
  title: string;
  description: string;
  workouts: Array<{
    id: string;
    title: string;
    workoutType: string;
    plannedDurationMin?: number | null;
  }>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {workouts.map((workout) => {
          const Icon = workoutIcon(workout.workoutType);
          return (
            <div key={workout.id} className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-3">
              <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-text-primary">{workout.title}</p>
                <p className="text-sm text-text-secondary">
                  {prettyType(workout.workoutType)}
                  {workout.plannedDurationMin ? ` · ${workout.plannedDurationMin} min` : ''}
                </p>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function PostRideCard({
  items,
}: {
  items: Array<{
    id: string;
    activityName?: string | null;
    generatedAtUtc: string;
    outputMarkdown: string;
    recoveryDecision?: { excluded?: boolean } | null;
  }>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bike className="h-4 w-4 text-primary" aria-hidden />
          After your ride
        </CardTitle>
        <CardDescription>Your latest ride, recovery, and what it means for tomorrow.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((item) => (
          <div key={item.id} className="rounded-2xl border border-border bg-bg px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-semibold text-text-primary">{item.activityName ?? 'Your ride'}</p>
                <p className="text-sm text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
              </div>
              {item.recoveryDecision?.excluded ? <Badge variant="warning">Not counted for recovery</Badge> : null}
            </div>
            <div className="mt-3">
              <Markdown>{item.outputMarkdown}</Markdown>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function TomorrowCard({ tomorrowImpact, fallback }: { tomorrowImpact: string | null | undefined; fallback: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tomorrow</CardTitle>
        <CardDescription>The next cue to keep in mind.</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-text-primary">{tomorrowImpact ?? fallback}</p>
      </CardContent>
    </Card>
  );
}

function SleepPrepCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MoonStar className="h-4 w-4 text-primary" aria-hidden />
          Tonight
        </CardTitle>
        <CardDescription>Keep the bedroom and bedtime routine working for you.</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-text-primary">
          Aim for the usual sleep setup: pre-cool the room, keep the evening calm, and stay on the bedtime routine.
        </p>
      </CardContent>
    </Card>
  );
}

function BedroomSummaryCard({
  thermal,
}: {
  thermal: {
    latestTemperatureC?: number | null;
    targetTemperatureC?: number | null;
    overnightLowC?: number | null;
    overnightWindMaxMph?: number | null;
  };
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Thermometer className="h-4 w-4 text-primary" aria-hidden />
          Bedroom
        </CardTitle>
        <CardDescription>One tap away from the full climate detail.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
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
        <DetailLinkCard
          to="/bedroom"
          title="Bedroom & weather detail"
          description="Open the full room and overnight weather read."
        />
      </CardContent>
    </Card>
  );
}

function DetailLinkCard({
  to,
  title,
  description,
}: {
  to: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-xl border border-border bg-bg px-4 py-4 transition hover:border-accent/40 hover:bg-panel"
    >
      <div>
        <p className="font-medium text-text-primary">{title}</p>
        <p className="mt-1 text-sm text-text-secondary">{description}</p>
      </div>
      <ChevronRight className="h-4 w-4 text-text-muted" aria-hidden />
    </Link>
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
