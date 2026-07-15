import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  coachingStateEnvelopeSchema,
  coachingStateSchema,
  knowledgeBaseUpdateInputSchema,
  plannedWorkoutOverrideInputSchema,
} from '@coach/shared';
import { toast } from 'sonner';
import { CalendarRange, ChevronDown, ChevronUp, ClipboardList, FileJson, History, Save } from 'lucide-react';
import { PageHeader } from '@/components/PageHeader';
import { Tabs } from '@/components/ui/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/contexts/AuthContext';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';

type CoachingState = typeof coachingStateSchema._type;
type KnowledgeBaseSection = CoachingState['knowledgeBaseSections'][number];
type SectionContent = Record<string, unknown>;
type EditorTab = 'knowledge' | 'plan';

const READ_QUERY_KEY = ['coach-memory'];
const ADMIN_QUERY_KEY = ['coach-memory-admin'];

const SECTION_ORDER = [
  'profile',
  'data_quality_rules',
  'age_adjustment',
  'sleep_protocol',
  'training_plan',
  'training_schedule',
  'active_hypotheses',
  'coaching_protocol',
] as const;

const TAB_ITEMS = [
  { value: 'knowledge', label: 'Knowledge base' },
  { value: 'plan', label: 'Training plan' },
] as const;

const textareaClassName =
  'min-h-[220px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm font-mono text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

function sectionLabel(section: string): string {
  return section
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function asRecord(value: unknown): SectionContent {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as SectionContent) : {};
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function valueText(value: unknown): string | null {
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return null;
}

function formatRange(low: unknown, high: unknown, suffix = ''): string | null {
  const lowText = valueText(low);
  const highText = valueText(high);
  if (lowText && highText) return `${lowText}-${highText}${suffix}`;
  return null;
}

async function fetchCoachMemory() {
  const response = await apiFetch<unknown>('/api/v1/coach-memory');
  return coachingStateEnvelopeSchema.parse(response);
}

async function fetchAdminCoachingState() {
  const response = await apiFetch<unknown>('/api/v1/admin/coaching-state');
  return coachingStateEnvelopeSchema.parse(response);
}

export function CoachStatePage() {
  const { player } = useAuth();
  const queryClient = useQueryClient();
  const [showAdminTools, setShowAdminTools] = useState(false);
  const [tab, setTab] = useState<EditorTab>('knowledge');
  const [sectionDrafts, setSectionDrafts] = useState<Record<string, string>>({});
  const [selectedDate, setSelectedDate] = useState('');
  const [workoutForm, setWorkoutForm] = useState({
    planBlockId: '',
    title: '',
    workoutType: '',
    status: 'planned',
    plannedDurationMin: '',
    intensityTarget: '',
    source: 'manual_override',
    structuredWorkout: '{\n  "format": "bike",\n  "steps": []\n}',
  });

  const readQuery = useQuery({
    queryKey: READ_QUERY_KEY,
    queryFn: fetchCoachMemory,
  });

  const adminQuery = useQuery({
    queryKey: ADMIN_QUERY_KEY,
    queryFn: fetchAdminCoachingState,
    enabled: player?.role === 'admin' && showAdminTools,
  });

  const readActiveSections = useMemo(() => {
    const sections = readQuery.data?.data.knowledgeBaseSections ?? [];
    return SECTION_ORDER.map((section) => sections.find((entry) => entry.section === section && entry.isActive)).filter(
      Boolean,
    ) as KnowledgeBaseSection[];
  }, [readQuery.data]);

  const readSectionsByName = useMemo(
    () => Object.fromEntries(readActiveSections.map((section) => [section.section, section.content])),
    [readActiveSections],
  );

  const profile = asRecord(readSectionsByName.profile);
  const dataQualityRules = asRecord(readSectionsByName.data_quality_rules);
  const sleepProtocol = asRecord(readSectionsByName.sleep_protocol);
  const trainingPlan = asRecord(readSectionsByName.training_plan);
  const trainingSchedule = asRecord(readSectionsByName.training_schedule);
  const activeHypotheses = asRecord(readSectionsByName.active_hypotheses);
  const coachingProtocol = asRecord(readSectionsByName.coaching_protocol);

  const activeWorkouts = useMemo(
    () =>
      (readQuery.data?.data.plannedWorkouts ?? [])
        .filter((workout) => workout.isActive)
        .sort((a, b) => a.workoutDate.localeCompare(b.workoutDate)),
    [readQuery.data],
  );

  const adminActiveSections = useMemo(() => {
    const sections = adminQuery.data?.data.knowledgeBaseSections ?? [];
    return SECTION_ORDER.map((section) => sections.find((entry) => entry.section === section && entry.isActive)).filter(
      Boolean,
    ) as KnowledgeBaseSection[];
  }, [adminQuery.data]);

  const adminActiveWorkouts = useMemo(
    () =>
      (adminQuery.data?.data.plannedWorkouts ?? [])
        .filter((workout) => workout.isActive)
        .sort((a, b) => a.workoutDate.localeCompare(b.workoutDate)),
    [adminQuery.data],
  );

  const selectedWorkout = useMemo(
    () => adminActiveWorkouts.find((workout) => workout.workoutDate === selectedDate) ?? null,
    [adminActiveWorkouts, selectedDate],
  );

  const selectedWorkoutHistory = useMemo(
    () =>
      (adminQuery.data?.data.plannedWorkouts ?? [])
        .filter((workout) => workout.workoutDate === selectedDate)
        .sort((a, b) => b.version - a.version),
    [adminQuery.data, selectedDate],
  );

  useEffect(() => {
    if (!adminActiveSections.length) return;
    const nextDrafts = Object.fromEntries(
      adminActiveSections.map((section) => [section.section, JSON.stringify(section.content, null, 2)]),
    );
    setSectionDrafts(nextDrafts);
  }, [adminActiveSections]);

  useEffect(() => {
    if (!selectedDate && adminActiveWorkouts[0]) {
      setSelectedDate(adminActiveWorkouts[0].workoutDate);
    }
  }, [adminActiveWorkouts, selectedDate]);

  useEffect(() => {
    if (!selectedWorkout) return;
    setWorkoutForm({
      planBlockId: selectedWorkout.planBlockId ?? '',
      title: selectedWorkout.title,
      workoutType: selectedWorkout.workoutType,
      status: selectedWorkout.status,
      plannedDurationMin:
        selectedWorkout.plannedDurationMin === null || selectedWorkout.plannedDurationMin === undefined
          ? ''
          : String(selectedWorkout.plannedDurationMin),
      intensityTarget: selectedWorkout.intensityTarget ?? '',
      source: selectedWorkout.source ?? 'manual_override',
      structuredWorkout: JSON.stringify(selectedWorkout.structuredWorkout, null, 2),
    });
  }, [selectedWorkout]);

  const saveSectionMutation = useMutation({
    mutationFn: async (section: string) => {
      const parsed = knowledgeBaseUpdateInputSchema.parse({
        source: 'manual_edit',
        content: JSON.parse(sectionDrafts[section] ?? '{}'),
      });
      return apiFetch<unknown>(`/api/v1/admin/coaching-state/knowledge-base/${section}`, {
        method: 'PUT',
        body: JSON.stringify(parsed),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: READ_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: ADMIN_QUERY_KEY }),
      ]);
      toast.success('Knowledge base saved');
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Failed to save knowledge base section');
    },
  });

  const saveWorkoutMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDate) {
        throw new Error('Choose a workout date before saving an override');
      }
      const parsed = plannedWorkoutOverrideInputSchema.parse({
        planBlockId: workoutForm.planBlockId || null,
        title: workoutForm.title,
        workoutType: workoutForm.workoutType,
        status: workoutForm.status,
        plannedDurationMin: workoutForm.plannedDurationMin ? Number(workoutForm.plannedDurationMin) : null,
        intensityTarget: workoutForm.intensityTarget || null,
        structuredWorkout: JSON.parse(workoutForm.structuredWorkout),
        source: workoutForm.source || 'manual_override',
      });
      return apiFetch<unknown>(`/api/v1/admin/coaching-state/planned-workouts/${selectedDate}`, {
        method: 'PUT',
        body: JSON.stringify(parsed),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: READ_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: ADMIN_QUERY_KEY }),
      ]);
      toast.success('Workout override saved');
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Failed to save workout override');
    },
  });

  const profileFacts = [
    profile.athleteName ? `Name: ${profile.athleteName}` : null,
    profile.age ? `Age: ${profile.age}` : null,
    profile.ftpWatts ? `FTP: ${profile.ftpWatts} W` : null,
    profile.vo2max ? `VO2max: ${profile.vo2max}` : null,
    formatRange(asRecord(profile.hrvBandMs).low, asRecord(profile.hrvBandMs).high, ' ms')
      ? `Typical HRV band: ${formatRange(asRecord(profile.hrvBandMs).low, asRecord(profile.hrvBandMs).high, ' ms')}`
      : null,
    profile.restingHeartRateBpm ? `Resting heart rate: ${profile.restingHeartRateBpm} bpm` : null,
    formatRange(asRecord(profile.bloodPressure).systolic, asRecord(profile.bloodPressure).diastolic)
      ? `Usual blood pressure: ${formatRange(
          asRecord(profile.bloodPressure).systolic,
          asRecord(profile.bloodPressure).diastolic,
        )}`
      : null,
    profile.fitnessAge ? `Fitness age: ${profile.fitnessAge}` : null,
  ].filter((item): item is string => Boolean(item));

  const protocolItems = [
    sleepProtocol.preCoolTemperatureC ? `Pre-cool the room to ${sleepProtocol.preCoolTemperatureC}°C.` : null,
    sleepProtocol.sealTargetTime ? `Seal the room by ${sleepProtocol.sealTargetTime}.` : null,
    formatRange(
      asRecord(sleepProtocol.thermalDisruptionThresholdC).low,
      asRecord(sleepProtocol.thermalDisruptionThresholdC).high,
      '°C',
    )
      ? `Treat ${formatRange(
          asRecord(sleepProtocol.thermalDisruptionThresholdC).low,
          asRecord(sleepProtocol.thermalDisruptionThresholdC).high,
          '°C',
        )} as the thermal disruption band.`
      : null,
    sleepProtocol.coherenceBreathingTime
      ? `Do coherence breathing at ${sleepProtocol.coherenceBreathingTime}.`
      : null,
    sleepProtocol.bedtime ? `Aim to be in bed by ${sleepProtocol.bedtime}.` : null,
    sleepProtocol.latestSnackTime ? `Finish any snack by ${sleepProtocol.latestSnackTime}.` : null,
  ].filter((item): item is string => Boolean(item));

  const rhythmItems = [
    ...asStringArray(trainingPlan.weeklyRhythm),
    ...Object.entries(asRecord(trainingSchedule.regularTrainingDays)).map(
      ([day, focus]) => `${day}: ${valueText(focus) ?? ''}`,
    ),
  ].filter((item) => item.trim().length > 0);

  const restDays = asStringArray(trainingSchedule.restDays);
  const hypotheses = Array.isArray(activeHypotheses.hypotheses)
    ? activeHypotheses.hypotheses
        .map((item) => asRecord(item))
        .filter((item) => valueText(item.title))
    : [];
  const dataRules = Array.isArray(dataQualityRules.rules)
    ? dataQualityRules.rules
        .map((item) => asRecord(item))
        .filter((item) => valueText(item.summary))
    : [];
  const cycleStructure = asStringArray(trainingPlan.cycleStructure);
  const trainingConstraints = asStringArray(trainingPlan.constraints);
  const swapFirstRule = valueText(asRecord(coachingProtocol.lowReadinessResponse).rule);

  if (readQuery.isLoading) {
    return (
      <div className="space-y-6 max-w-6xl">
        <PageHeader title="Coach memory" eyebrow="What your coach knows about you" />
        <Card>
          <CardHeader>
            <CardTitle>Loading coach memory…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (readQuery.isError || !readQuery.data) {
    return (
      <div className="space-y-6 max-w-6xl">
        <PageHeader title="Coach memory" eyebrow="What your coach knows about you" />
        <Card>
          <CardHeader>
            <CardTitle>Coach memory unavailable</CardTitle>
            <CardDescription>
              {readQuery.error instanceof Error ? readQuery.error.message : 'The saved context could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <PageHeader
        title="Coach memory"
        eyebrow="What your coach knows about you"
        wrapTitle
        action={
          player?.role === 'admin' ? (
            <Button type="button" variant="outline" onClick={() => setShowAdminTools((value) => !value)}>
              {showAdminTools ? <ChevronUp className="h-4 w-4" aria-hidden /> : <ChevronDown className="h-4 w-4" aria-hidden />}
              {showAdminTools ? 'Hide editor' : 'Open editor'}
            </Button>
          ) : null
        }
      />

      <Card className="bg-surface-elevated/60">
        <CardContent className="space-y-3 pt-5">
          <p className="text-sm text-text-primary">
            This is the retained context your coach uses to interpret your sleep, your training, and the rules it
            should follow when it talks to you.
          </p>
          <div className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
            <span>Generated {new Date(readQuery.data.meta.generatedAtUtc).toLocaleString()}</span>
            <span className="rounded-full border border-border px-3 py-1 text-text-primary">
              {readActiveSections.length} active memory sections
            </span>
            <span className="rounded-full border border-border px-3 py-1 text-text-primary">
              {activeWorkouts.length} active planned workouts
            </span>
            {readQuery.data.meta.seeded ? (
              <span className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-primary">
                Seeded from current spec
              </span>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Profile facts</CardTitle>
            <CardDescription>The fixed background your coach keeps in mind every day.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-text-primary">
            {profileFacts.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sleep protocol</CardTitle>
            <CardDescription>The routine and room targets the coach treats as your default.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-text-primary">
            {protocolItems.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Data-quality rules</CardTitle>
            <CardDescription>What the coach should ignore or down-weight before drawing conclusions.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {dataRules.map((rule) => {
              const summary = valueText(rule.summary);
              if (!summary) return null;
              return (
                <div key={summary} className="rounded-lg border border-border bg-bg/60 p-4">
                  <p className="text-sm font-semibold text-text-primary">{summary}</p>
                  {valueText(rule.reason) ? (
                    <p className="mt-1 text-sm text-text-secondary">{valueText(rule.reason)}</p>
                  ) : null}
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Plan rhythm</CardTitle>
            <CardDescription>The weekly shape and plan rules your coach assumes before it suggests changes.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-text-primary">
            {restDays.length ? <p>Normal recovery days: {restDays.join(' and ')}.</p> : null}
            {rhythmItems.length ? (
              <div className="space-y-2">
                {rhythmItems.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
            {swapFirstRule ? (
              <div className="rounded-lg border border-border bg-bg/60 p-4">
                <p className="font-semibold text-text-primary">Low-readiness rule</p>
                <p className="mt-1 text-text-secondary">{swapFirstRule}</p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Active hypotheses</CardTitle>
            <CardDescription>Open things the coach is explicitly tracking rather than assuming away.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {hypotheses.map((hypothesis) => {
              const title = valueText(hypothesis.title);
              if (!title) return null;
              return (
                <div key={title} className="rounded-lg border border-border bg-bg/60 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-text-primary">{title}</p>
                    {valueText(hypothesis.status) ? (
                      <span className="text-xs uppercase tracking-wide text-text-secondary">
                        {valueText(hypothesis.status)}
                      </span>
                    ) : null}
                  </div>
                  {valueText(hypothesis.rule) ? (
                    <p className="mt-1 text-sm text-text-secondary">{valueText(hypothesis.rule)}</p>
                  ) : null}
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>13-week framework</CardTitle>
            <CardDescription>The larger plan structure this memory is grounded in.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-text-primary">
            {valueText(trainingPlan.framework) ? <p>{valueText(trainingPlan.framework)}</p> : null}
            {cycleStructure.length ? (
              <div className="space-y-2">
                {cycleStructure.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
            {trainingConstraints.length ? (
              <div className="space-y-2 text-text-secondary">
                {trainingConstraints.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {player?.role === 'admin' && showAdminTools ? (
        <section className="space-y-6" aria-label="Coach memory editor">
          <Card className="bg-surface-elevated/60">
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle>Admin editor</CardTitle>
                  <CardDescription>
                    Raw JSON and plan overrides remain admin-only. Mark-facing memory above stays plain English.
                  </CardDescription>
                </div>
                <ClipboardList className="h-5 w-5 text-text-secondary" aria-hidden />
              </div>
            </CardHeader>
          </Card>

          {adminQuery.isLoading ? (
            <Card>
              <CardHeader>
                <CardTitle>Loading editor…</CardTitle>
              </CardHeader>
            </Card>
          ) : adminQuery.isError || !adminQuery.data ? (
            <Card>
              <CardHeader>
                <CardTitle>Editor unavailable</CardTitle>
                <CardDescription>
                  {adminQuery.error instanceof Error ? adminQuery.error.message : 'The internal editor could not load.'}
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <>
              <Tabs items={TAB_ITEMS} value={tab} onChange={(value) => setTab(value)} variant="segmented" />

              {tab === 'knowledge' ? (
                <div className="grid gap-5 lg:grid-cols-2">
                  {adminActiveSections.map((section) => {
                    const historyCount = adminQuery.data.data.knowledgeBaseSections.filter(
                      (entry) => entry.section === section.section,
                    ).length;
                    return (
                      <Card key={section.id} className="h-full">
                        <CardHeader>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <CardTitle>{sectionLabel(section.section)}</CardTitle>
                              <CardDescription>
                                Version {section.version}
                                {historyCount > 1 ? ` · ${historyCount} retained versions` : ''}
                              </CardDescription>
                            </div>
                            <FileJson className="h-5 w-5 text-text-secondary" aria-hidden />
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          <textarea
                            value={sectionDrafts[section.section] ?? ''}
                            onChange={(event) =>
                              setSectionDrafts((current) => ({ ...current, [section.section]: event.target.value }))
                            }
                            className={textareaClassName}
                            spellCheck={false}
                            aria-label={`${sectionLabel(section.section)} JSON editor`}
                          />
                          <div className="flex items-center justify-between gap-3 text-xs text-text-secondary">
                            <span>{section.source ?? 'manual_edit'}</span>
                            <Button
                              onClick={() => saveSectionMutation.mutate(section.section)}
                              disabled={saveSectionMutation.isPending}
                            >
                              <Save className="h-4 w-4" aria-hidden />
                              Save section
                            </Button>
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              ) : (
                <div className="grid gap-5 xl:grid-cols-[1.25fr,0.75fr]">
                  <div className="space-y-5">
                    <Card>
                      <CardHeader>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <CardTitle>Per-day workout override</CardTitle>
                            <CardDescription>
                              Editing a workout creates a new version and keeps the prior plan in history.
                            </CardDescription>
                          </div>
                          <CalendarRange className="h-5 w-5 text-text-secondary" aria-hidden />
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor="workout-date">Workout date</Label>
                            <select
                              id="workout-date"
                              value={selectedDate}
                              onChange={(event) => setSelectedDate(event.target.value)}
                              className="h-11 w-full rounded-md border border-border bg-bg px-3 text-sm text-text-primary focus-visible:outline-none focus-visible:shadow-glow"
                            >
                              {adminActiveWorkouts.map((workout) => (
                                <option key={workout.id} value={workout.workoutDate}>
                                  {workout.workoutDate} · {workout.title}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="plan-block">Plan block</Label>
                            <select
                              id="plan-block"
                              value={workoutForm.planBlockId}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, planBlockId: event.target.value }))
                              }
                              className="h-11 w-full rounded-md border border-border bg-bg px-3 text-sm text-text-primary focus-visible:outline-none focus-visible:shadow-glow"
                            >
                              <option value="">Unassigned</option>
                              {adminQuery.data.data.planBlocks.map((block) => (
                                <option key={block.id} value={block.id}>
                                  {block.name} · {block.startDate}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor="workout-title">Title</Label>
                            <Input
                              id="workout-title"
                              value={workoutForm.title}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, title: event.target.value }))
                              }
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="workout-type">Workout type</Label>
                            <Input
                              id="workout-type"
                              value={workoutForm.workoutType}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, workoutType: event.target.value }))
                              }
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="workout-status">Status</Label>
                            <Input
                              id="workout-status"
                              value={workoutForm.status}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, status: event.target.value }))
                              }
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="workout-duration">Planned duration (min)</Label>
                            <Input
                              id="workout-duration"
                              type="number"
                              min="1"
                              value={workoutForm.plannedDurationMin}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, plannedDurationMin: event.target.value }))
                              }
                            />
                          </div>
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor="intensity-target">Intensity target</Label>
                            <Input
                              id="intensity-target"
                              value={workoutForm.intensityTarget}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, intensityTarget: event.target.value }))
                              }
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="workout-source">Source</Label>
                            <Input
                              id="workout-source"
                              value={workoutForm.source}
                              onChange={(event) =>
                                setWorkoutForm((current) => ({ ...current, source: event.target.value }))
                              }
                            />
                          </div>
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="structured-workout">Structured workout JSON</Label>
                          <textarea
                            id="structured-workout"
                            value={workoutForm.structuredWorkout}
                            onChange={(event) =>
                              setWorkoutForm((current) => ({ ...current, structuredWorkout: event.target.value }))
                            }
                            className={cn(textareaClassName, 'min-h-[260px]')}
                            spellCheck={false}
                          />
                        </div>

                        <Button onClick={() => saveWorkoutMutation.mutate()} disabled={saveWorkoutMutation.isPending}>
                          <Save className="h-4 w-4" aria-hidden />
                          Save workout override
                        </Button>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader>
                        <CardTitle>13-week block map</CardTitle>
                        <CardDescription>Seeded structure for the retained plan context.</CardDescription>
                      </CardHeader>
                      <CardContent className="grid gap-3 md:grid-cols-2">
                        {adminQuery.data.data.planBlocks.map((block) => (
                          <div key={block.id} className="rounded-lg border border-border bg-bg/60 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-semibold text-text-primary">{block.name}</p>
                              <span className="text-xs uppercase tracking-wide text-text-secondary">
                                {block.blockType}
                              </span>
                            </div>
                            <p className="mt-2 text-xs text-text-secondary">
                              {block.startDate} to {block.endDate}
                            </p>
                            <p className="mt-2 text-sm text-text-primary">
                              {(block.goalsJson.focus as string) ?? 'No focus set'}
                            </p>
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  </div>

                  <Card className="h-fit">
                    <CardHeader>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <CardTitle>Version history</CardTitle>
                          <CardDescription>
                            {selectedDate ? `All saved versions for ${selectedDate}` : 'Choose a date to inspect history.'}
                          </CardDescription>
                        </div>
                        <History className="h-5 w-5 text-text-secondary" aria-hidden />
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {selectedWorkoutHistory.length ? (
                        selectedWorkoutHistory.map((workout) => (
                          <div
                            key={workout.id}
                            className={cn(
                              'rounded-lg border p-4',
                              workout.isActive ? 'border-primary/40 bg-primary/5' : 'border-border bg-bg/60',
                            )}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-semibold text-text-primary">
                                v{workout.version} · {workout.title}
                              </p>
                              <span className="text-xs text-text-secondary">
                                {workout.isActive ? 'Active' : 'Retained'}
                              </span>
                            </div>
                            <p className="mt-2 text-sm text-text-secondary">
                              {workout.workoutType} · {workout.status}
                            </p>
                            <p className="mt-2 text-xs text-text-secondary">
                              {workout.intensityTarget ?? 'No intensity target'}
                            </p>
                          </div>
                        ))
                      ) : (
                        <p className="text-sm text-text-secondary">No versions saved for this date yet.</p>
                      )}
                    </CardContent>
                  </Card>
                </div>
              )}
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
