import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  coachingStateEnvelopeSchema,
  coachingStateSchema,
  knowledgeBaseUpdateInputSchema,
  plannedWorkoutOverrideInputSchema,
} from '@coach/shared';
import { toast } from 'sonner';
import { CalendarRange, FileJson, History, Save } from 'lucide-react';
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

type EditorTab = 'knowledge' | 'plan';

const SECTION_ORDER = [
  'profile',
  'data_quality_rules',
  'age_adjustment',
  'sleep_protocol',
  'training_plan',
  'active_hypotheses',
] as const;

const TAB_ITEMS = [
  { value: 'knowledge', label: 'Knowledge Base' },
  { value: 'plan', label: 'Training Plan' },
] as const;

const textareaClassName =
  'min-h-[220px] w-full rounded-md border border-border bg-bg px-3 py-3 text-sm font-mono text-text-primary shadow-sm focus-visible:outline-none focus-visible:shadow-glow';

function sectionLabel(section: string): string {
  return section
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

async function fetchCoachingState() {
  const response = await apiFetch<unknown>('/api/v1/admin/coaching-state');
  return coachingStateEnvelopeSchema.parse(response);
}

export function CoachStatePage() {
  const { player } = useAuth();
  const queryClient = useQueryClient();
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

  const query = useQuery({
    queryKey: ['coaching-state'],
    queryFn: fetchCoachingState,
    enabled: player?.role === 'admin',
  });

  const activeSections = useMemo(() => {
    const sections = query.data?.data.knowledgeBaseSections ?? [];
    return SECTION_ORDER.map((section) => sections.find((entry) => entry.section === section && entry.isActive)).filter(
      Boolean,
    ) as KnowledgeBaseSection[];
  }, [query.data]);

  const activeWorkouts = useMemo(
    () =>
      (query.data?.data.plannedWorkouts ?? [])
        .filter((workout) => workout.isActive)
        .sort((a, b) => a.workoutDate.localeCompare(b.workoutDate)),
    [query.data],
  );

  const selectedWorkout = useMemo(
    () => activeWorkouts.find((workout) => workout.workoutDate === selectedDate) ?? null,
    [activeWorkouts, selectedDate],
  );

  const selectedWorkoutHistory = useMemo(
    () =>
      (query.data?.data.plannedWorkouts ?? [])
        .filter((workout) => workout.workoutDate === selectedDate)
        .sort((a, b) => b.version - a.version),
    [query.data, selectedDate],
  );

  useEffect(() => {
    if (!activeSections.length) return;
    const nextDrafts = Object.fromEntries(
      activeSections.map((section) => [section.section, JSON.stringify(section.content, null, 2)]),
    );
    setSectionDrafts(nextDrafts);
  }, [activeSections]);

  useEffect(() => {
    if (!selectedDate && activeWorkouts[0]) {
      setSelectedDate(activeWorkouts[0].workoutDate);
    }
  }, [activeWorkouts, selectedDate]);

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
      await queryClient.invalidateQueries({ queryKey: ['coaching-state'] });
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
      await queryClient.invalidateQueries({ queryKey: ['coaching-state'] });
      toast.success('Workout override saved');
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'Failed to save workout override');
    },
  });

  if (player?.role !== 'admin') {
    return (
      <div className="space-y-6 max-w-4xl">
        <PageHeader title="Coach State" />
        <Card>
          <CardHeader>
            <CardTitle>Admin access required</CardTitle>
            <CardDescription>
              This internal editor is only available to the seeded admin profile.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isLoading) {
    return (
      <div className="space-y-6 max-w-6xl">
        <PageHeader title="Coach State" />
        <Card>
          <CardHeader>
            <CardTitle>Loading coaching state…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-6 max-w-6xl">
        <PageHeader title="Coach State" />
        <Card>
          <CardHeader>
            <CardTitle>Coach state unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'The internal editor could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <PageHeader
        title="Coach State"
        eyebrow="Editable retained context for the morning and post-workout engine"
        wrapTitle
      />

      <Card className="bg-surface-elevated/60">
        <CardContent className="flex flex-wrap items-center gap-3 pt-5 text-sm text-text-secondary">
          <span>Generated {new Date(query.data.meta.generatedAtUtc).toLocaleString()}</span>
          <span className="rounded-full border border-border px-3 py-1 text-text-primary">
            {query.data.data.planBlocks.length} plan blocks
          </span>
          <span className="rounded-full border border-border px-3 py-1 text-text-primary">
            {activeWorkouts.length} active workouts
          </span>
          {query.data.meta.seeded ? (
            <span className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-primary">
              Seeded from current spec
            </span>
          ) : null}
        </CardContent>
      </Card>

      <Tabs
        items={TAB_ITEMS}
        value={tab}
        onChange={(value) => setTab(value)}
        variant="segmented"
      />

      {tab === 'knowledge' ? (
        <div className="grid gap-5 lg:grid-cols-2">
          {activeSections.map((section) => {
            const historyCount = query.data.data.knowledgeBaseSections.filter(
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
                      {activeWorkouts.map((workout) => (
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
                      {query.data.data.planBlocks.map((block) => (
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
                {query.data.data.planBlocks.map((block) => (
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
                      workout.isActive
                        ? 'border-primary/40 bg-primary/5'
                        : 'border-border bg-bg/60',
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
    </div>
  );
}
