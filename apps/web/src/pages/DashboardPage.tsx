import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  BedDouble,
  Bike,
  ChevronRight,
  ClipboardCheck,
  Dumbbell,
  Fan,
  MoonStar,
  Send,
  SlidersHorizontal,
  Thermometer,
  Wind,
  type LucideIcon,
} from 'lucide-react';
import { postRideCheckInInputSchema } from '@coach/shared';
import { toast } from 'sonner';
import { AgeComparisonCard, type AgeComparison } from '@/components/AgeComparisonCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import { VerdictHero } from '@/components/VerdictHero';
import { useAuth } from '@/contexts/AuthContext';
import { isBikeWorkout, useDailyPhase } from '@/hooks/useDailyPhase';
import { useDailyLoop } from '@/hooks/useDailyLoop';
import { useOnlineStatus } from '@/hooks/useOnlineStatus';
import { apiFetch } from '@/lib/api';
import { fanStatusText, formatDateTime, friendlyDate, hm, remContext, type FanState } from '@/lib/dailyFlow';
import { greetingForNow, verdictLabel } from '@/lib/copy';

const textareaClassName =
  'min-h-[88px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

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
  const queryClient = useQueryClient();
  const isOnline = useOnlineStatus();
  const query = useDailyLoop();
  const greeting = `${greetingForNow()}${player ? `, ${player.displayName}` : ''}`;
  const data = query.data?.data;
  const phase = useDailyPhase(data);
  const sameDayMutation = useMutation({
    mutationFn: ({
      workoutId,
      durationScalePct,
      intensityScalePct,
    }: {
      workoutId: string;
      durationScalePct?: number;
      intensityScalePct?: number;
    }) =>
      apiFetch(`/api/v1/workout-delivery/planned-workouts/${workoutId}/send-today`, {
        method: 'POST',
        body: JSON.stringify({ durationScalePct, intensityScalePct }),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
      ]);
      toast.success('Sent to Zwift');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not send to Zwift'),
  });
  const postRideCheckInMutation = useMutation({
    mutationFn: ({
      activityId,
      subjectiveScore,
      rpe,
      feel,
      notes,
    }: {
      activityId: string;
      subjectiveScore: number | null;
      rpe: number | null;
      feel: string | null;
      notes: string | null;
    }) => {
      if (!data) throw new Error('Daily loop not loaded');
      const payload = postRideCheckInInputSchema.parse({
        subjectiveScore,
        rpe,
        feel,
        notes,
      });
      return apiFetch(`/api/v1/daily-loop/${data.subjectDate}/activities/${activityId}/post-ride-check-in`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success('Ride check-in saved');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not save ride check-in'),
  });

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
  const ageComparison = (analysis?.ageComparison ?? null) as AgeComparison | null;
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

          {ageComparison && <AgeComparisonCard comparison={ageComparison} />}

          <WorkoutCard
            title="Today&apos;s ride"
            description="The one thing to focus on now."
            verdict={analysis?.verdict}
            workouts={bikeWorkouts}
            adjustments={analysis?.planAdjustments ?? []}
            onSend={(payload) => sameDayMutation.mutate(payload)}
            sendingWorkoutId={sameDayMutation.variables?.workoutId ?? null}
            isSending={sameDayMutation.isPending}
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
          <PostRideCard
            items={postWorkouts}
            onSaveCheckIn={(payload) => postRideCheckInMutation.mutate(payload)}
            savingActivityId={postRideCheckInMutation.variables?.activityId ?? null}
            isSaving={postRideCheckInMutation.isPending}
          />

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

          {ageComparison && <AgeComparisonCard comparison={ageComparison} />}

          <WorkoutCard
            title="Today"
            description="A calm read of the day ahead."
            verdict={analysis?.verdict}
            workouts={bikeWorkouts}
            adjustments={analysis?.planAdjustments ?? []}
            onSend={(payload) => sameDayMutation.mutate(payload)}
            sendingWorkoutId={sameDayMutation.variables?.workoutId ?? null}
            isSending={sameDayMutation.isPending}
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
  onSend,
  sendingWorkoutId,
  isSending,
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
  onSend: (payload: {
    workoutId: string;
    durationScalePct?: number;
    intensityScalePct?: number;
  }) => void;
  sendingWorkoutId: string | null;
  isSending: boolean;
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
                className="rounded-xl border border-border bg-bg px-3 py-3"
              >
                <div className="flex items-center gap-3">
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
                <WorkoutDeliveryActions
                  workoutId={workout.id}
                  onSend={onSend}
                  isSending={isSending && sendingWorkoutId === workout.id}
                />
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

function WorkoutDeliveryActions({
  workoutId,
  onSend,
  isSending,
}: {
  workoutId: string;
  onSend: (payload: {
    workoutId: string;
    durationScalePct?: number;
    intensityScalePct?: number;
  }) => void;
  isSending: boolean;
}) {
  const [showOverride, setShowOverride] = useState(false);
  const [durationScalePct, setDurationScalePct] = useState('100');
  const [intensityScalePct, setIntensityScalePct] = useState('100');

  function sendOverride() {
    onSend({
      workoutId,
      durationScalePct: Number(durationScalePct),
      intensityScalePct: Number(intensityScalePct),
    });
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => onSend({ workoutId })} disabled={isSending}>
          <Send className="h-4 w-4" aria-hidden />
          {isSending ? 'Sending...' : 'Send to Zwift'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setShowOverride((value) => !value)}
          aria-expanded={showOverride}
        >
          <SlidersHorizontal className="h-4 w-4" aria-hidden />
          Override
        </Button>
      </div>
      {showOverride ? (
        <div className="grid gap-3 rounded-lg border border-border bg-surface-elevated/60 px-3 py-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <div className="space-y-1.5">
            <Label htmlFor={`duration-${workoutId}`}>Duration</Label>
            <Input
              id={`duration-${workoutId}`}
              type="number"
              min={50}
              max={125}
              step={5}
              value={durationScalePct}
              onChange={(event) => setDurationScalePct(event.target.value)}
              aria-label="Duration percentage"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`intensity-${workoutId}`}>Intensity</Label>
            <Input
              id={`intensity-${workoutId}`}
              type="number"
              min={50}
              max={120}
              step={5}
              value={intensityScalePct}
              onChange={(event) => setIntensityScalePct(event.target.value)}
              aria-label="Intensity percentage"
            />
          </div>
          <Button type="button" size="sm" onClick={sendOverride} disabled={isSending}>
            {isSending ? 'Sending...' : 'Send override'}
          </Button>
        </div>
      ) : null}
    </div>
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
  onSaveCheckIn,
  savingActivityId,
  isSaving,
}: {
  items: Array<{
    id: string;
    activityId?: string | null;
    activityName?: string | null;
    generatedAtUtc: string;
    outputMarkdown: string;
    recoveryDecision?: { excluded?: boolean } | null;
    postRideCheckIn?: {
      subjectiveScore?: number | null;
      rpe?: number | null;
      feel?: string | null;
      notes?: string | null;
    } | null;
  }>;
  onSaveCheckIn: (payload: {
    activityId: string;
    subjectiveScore: number | null;
    rpe: number | null;
    feel: string | null;
    notes: string | null;
  }) => void;
  savingActivityId: string | null;
  isSaving: boolean;
}) {
  const [drafts, setDrafts] = useState<
    Record<string, { subjectiveScore: string; rpe: string; feel: string; notes: string }>
  >({});

  function formFor(item: {
    activityId?: string | null;
    postRideCheckIn?: {
      subjectiveScore?: number | null;
      rpe?: number | null;
      feel?: string | null;
      notes?: string | null;
    } | null;
  }) {
    const key = item.activityId ?? '';
    if (drafts[key]) return drafts[key];
    return {
      subjectiveScore:
        item.postRideCheckIn?.subjectiveScore != null ? String(item.postRideCheckIn.subjectiveScore) : '',
      rpe: item.postRideCheckIn?.rpe != null ? String(item.postRideCheckIn.rpe) : '',
      feel: item.postRideCheckIn?.feel ?? '',
      notes: item.postRideCheckIn?.notes ?? '',
    };
  }

  function patchDraft(
    activityId: string,
    patch: Partial<{ subjectiveScore: string; rpe: string; feel: string; notes: string }>,
    item: { postRideCheckIn?: { subjectiveScore?: number | null; rpe?: number | null; feel?: string | null; notes?: string | null } | null },
  ) {
    setDrafts((current) => ({
      ...current,
      [activityId]: { ...formFor({ activityId, postRideCheckIn: item.postRideCheckIn }), ...patch },
    }));
  }

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
          <div key={item.id} className="space-y-4 rounded-2xl border border-border bg-bg px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-semibold text-text-primary">{item.activityName ?? 'Your ride'}</p>
                <p className="text-sm text-text-secondary">Generated {formatDateTime(item.generatedAtUtc)}</p>
              </div>
              {item.recoveryDecision?.excluded ? <Badge variant="warning">Not counted for recovery</Badge> : null}
            </div>
            {item.activityId ? (
              <PostRideCheckInForm
                activityId={item.activityId}
                value={formFor(item)}
                logged={Boolean(item.postRideCheckIn)}
                onChange={(patch) => patchDraft(item.activityId!, patch, item)}
                onSave={(value) =>
                  onSaveCheckIn({
                    activityId: item.activityId!,
                    subjectiveScore: value.subjectiveScore ? Number(value.subjectiveScore) : null,
                    rpe: value.rpe ? Number(value.rpe) : null,
                    feel: value.feel || null,
                    notes: value.notes || null,
                  })
                }
                isSaving={isSaving && savingActivityId === item.activityId}
              />
            ) : null}
            <div>
              <Markdown>{item.outputMarkdown}</Markdown>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function PostRideCheckInForm({
  activityId,
  value,
  logged,
  onChange,
  onSave,
  isSaving,
}: {
  activityId: string;
  value: { subjectiveScore: string; rpe: string; feel: string; notes: string };
  logged: boolean;
  onChange: (patch: Partial<{ subjectiveScore: string; rpe: string; feel: string; notes: string }>) => void;
  onSave: (value: { subjectiveScore: string; rpe: string; feel: string; notes: string }) => void;
  isSaving: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated/60 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-text-primary">How did it feel?</p>
        {logged ? <Badge variant="muted">Logged</Badge> : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`post-ride-rpe-${activityId}`}>RPE</Label>
          <Input
            id={`post-ride-rpe-${activityId}`}
            inputMode="decimal"
            value={value.rpe}
            onChange={(event) => onChange({ rpe: event.target.value })}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`post-ride-legs-${activityId}`}>Legs</Label>
          <Input
            id={`post-ride-legs-${activityId}`}
            inputMode="numeric"
            placeholder="1-10"
            value={value.subjectiveScore}
            onChange={(event) => onChange({ subjectiveScore: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-feel-${activityId}`}>Feel</Label>
          <Input
            id={`post-ride-feel-${activityId}`}
            value={value.feel}
            onChange={(event) => onChange({ feel: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`post-ride-notes-${activityId}`}>Niggles or notes</Label>
          <textarea
            id={`post-ride-notes-${activityId}`}
            className={textareaClassName}
            value={value.notes}
            onChange={(event) => onChange({ notes: event.target.value })}
          />
        </div>
      </div>
      <div className="mt-3 flex justify-end">
        <Button type="button" variant="outline" onClick={() => onSave(value)} disabled={isSaving}>
          {isSaving ? 'Saving...' : 'Save ride check-in'}
        </Button>
      </div>
    </div>
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
    fan: FanState;
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
        <div className="flex items-start gap-2 rounded-xl border border-border px-3 py-3 text-sm">
          <Fan className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium text-text-primary">Bedroom fan</p>
            <p className="text-text-secondary">{fanStatusText(thermal.fan)}</p>
          </div>
        </div>
        <DetailLinkCard
          to="/bedroom"
          title="Bedroom & weather detail"
          description="Open the full room and overnight weather read, and control the fan."
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
