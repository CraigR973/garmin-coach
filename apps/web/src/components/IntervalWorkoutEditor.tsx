import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  intervalEditApproveInputSchema,
  intervalEditorEnvelopeSchema,
  type IntervalEditorEnvelope,
  type IntervalWorkoutBlock,
} from '@coach/shared';
import { Check, LockKeyhole } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';

type PresetKey = keyof IntervalEditorEnvelope['data']['presets'];

const PRESET_LABELS: Record<PresetKey, string> = {
  keep: 'Keep current',
  scale: 'Scale down',
  sweetSpot: 'Sweet Spot',
  zoneTwo: 'Z2',
};

function cloneBlock(block: IntervalWorkoutBlock): IntervalWorkoutBlock {
  return {
    repeat: block.repeat,
    work: { ...block.work },
    rest: { ...block.rest },
  };
}

function formatDuration(durationSec: number): string {
  const minutes = Math.floor(durationSec / 60);
  const seconds = durationSec % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function fetchEditor(workoutId: string) {
  return apiFetch<unknown>(
    `/api/v1/workout-delivery/planned-workouts/${workoutId}/interval-editor`,
  ).then((response) => intervalEditorEnvelopeSchema.parse(response));
}

export function IntervalWorkoutEditor({
  workoutId,
  onApproved,
}: {
  workoutId: string;
  onApproved: () => void;
}) {
  const query = useQuery({
    queryKey: ['interval-editor', workoutId],
    queryFn: () => fetchEditor(workoutId),
  });

  if (query.isPending) {
    return (
      <div className="space-y-3 rounded-lg border border-border bg-surface-elevated/60 px-3 py-3">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-3 text-sm text-text-primary">
        <p>This workout’s intervals could not be loaded.</p>
        <Button type="button" size="sm" variant="outline" className="mt-3" onClick={() => query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  return (
    <IntervalWorkoutEditorForm
      key={workoutId}
      workoutId={workoutId}
      editor={query.data.data}
      onApproved={onApproved}
    />
  );
}

function IntervalWorkoutEditorForm({
  workoutId,
  editor,
  onApproved,
}: {
  workoutId: string;
  editor: IntervalEditorEnvelope['data'];
  onApproved: () => void;
}) {
  const queryClient = useQueryClient();
  const [selectedPreset, setSelectedPreset] = useState<PresetKey | null>('scale');
  const [changeTo, setChangeTo] = useState<IntervalWorkoutBlock>(() =>
    cloneBlock(editor.changeTo),
  );

  const mutation = useMutation({
    mutationFn: (block: IntervalWorkoutBlock) => {
      const body = intervalEditApproveInputSchema.parse({ block });
      return apiFetch(
        `/api/v1/workout-delivery/planned-workouts/${workoutId}/interval-editor/approve`,
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['daily-loop'] }),
        queryClient.invalidateQueries({ queryKey: ['week-ahead'] }),
      ]);
      toast.success('Interval change approved and uploaded to Zwift');
      onApproved();
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not upload the interval change'),
  });

  const applyPreset = (preset: PresetKey) => {
    setSelectedPreset(preset);
    setChangeTo(cloneBlock(editor.presets[preset]));
  };
  const updateLeg = (
    leg: 'work' | 'rest',
    field: 'powerPct' | 'cadenceRpm',
    value: number | null,
  ) => {
    setSelectedPreset(null);
    setChangeTo((current) => ({
      ...current,
      [leg]: { ...current[leg], [field]: value },
    }));
  };
  const updateDuration = (leg: 'work' | 'rest', durationSec: number) => {
    setSelectedPreset(null);
    setChangeTo((current) => ({
      ...current,
      [leg]: { ...current[leg], durationSec },
    }));
  };

  return (
    <section
      aria-label="Per-interval workout editor"
      className="space-y-4 rounded-lg border border-border bg-surface-elevated/60 px-3 py-3"
    >
      <div>
        <p className="font-medium text-text-primary">Change the interval set</p>
        <p className="mt-1 text-xs text-text-secondary">
          Warm-up, cool-down and primer steps stay fixed. Choose a suggestion, then fine-tune it.
        </p>
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Workout type suggestions">
        {(Object.keys(PRESET_LABELS) as PresetKey[]).map((preset) => (
          <Button
            key={preset}
            type="button"
            size="sm"
            variant={selectedPreset === preset ? 'default' : 'outline'}
            aria-pressed={selectedPreset === preset}
            onClick={() => applyPreset(preset)}
          >
            {selectedPreset === preset ? <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden /> : null}
            {PRESET_LABELS[preset]}
          </Button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] border-separate border-spacing-y-1 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-text-secondary">
              <th className="px-2 py-1 font-medium">Setting</th>
              <th className="px-2 py-1 font-medium">Current</th>
              <th className="px-2 py-1 font-medium">Change to</th>
            </tr>
          </thead>
          <tbody>
            <EditorRow label="No. of intervals" current={String(editor.current.repeat)}>
              <BoundedNumberInput
                ariaLabel="Change to number of intervals"
                value={changeTo.repeat}
                min={1}
                max={20}
                onChange={(repeat) => {
                  setSelectedPreset(null);
                  setChangeTo((current) => ({ ...current, repeat }));
                }}
              />
            </EditorRow>
            <EditorRow label="Work time" current={formatDuration(editor.current.work.durationSec)}>
              <DurationInput
                label="Change to work time"
                value={changeTo.work.durationSec}
                maxMinutes={120}
                onChange={(durationSec) => updateDuration('work', durationSec)}
              />
            </EditorRow>
            <EditorRow label="Work %FTP" current={`${editor.current.work.powerPct}%`}>
              <BoundedNumberInput
                ariaLabel="Change to work percent FTP"
                value={changeTo.work.powerPct}
                min={40}
                max={150}
                suffix="%"
                onChange={(value) => updateLeg('work', 'powerPct', value)}
              />
            </EditorRow>
            <EditorRow
              label="Work cadence"
              current={editor.current.work.cadenceRpm ? `${editor.current.work.cadenceRpm} rpm` : 'Open'}
            >
              <NullableCadenceInput
                label="Change to work cadence"
                value={changeTo.work.cadenceRpm ?? null}
                onChange={(value) => updateLeg('work', 'cadenceRpm', value)}
              />
            </EditorRow>
            <EditorRow label="Rest time" current={formatDuration(editor.current.rest.durationSec)}>
              <DurationInput
                label="Change to rest time"
                value={changeTo.rest.durationSec}
                maxMinutes={60}
                onChange={(durationSec) => updateDuration('rest', durationSec)}
              />
            </EditorRow>
            <EditorRow label="Rest %FTP" current={`${editor.current.rest.powerPct}%`}>
              <BoundedNumberInput
                ariaLabel="Change to rest percent FTP"
                value={changeTo.rest.powerPct}
                min={40}
                max={150}
                suffix="%"
                onChange={(value) => updateLeg('rest', 'powerPct', value)}
              />
            </EditorRow>
            <EditorRow
              label="Rest cadence"
              current={editor.current.rest.cadenceRpm ? `${editor.current.rest.cadenceRpm} rpm` : 'Open'}
            >
              <NullableCadenceInput
                label="Change to rest cadence"
                value={changeTo.rest.cadenceRpm ?? null}
                onChange={(value) => updateLeg('rest', 'cadenceRpm', value)}
              />
            </EditorRow>
          </tbody>
        </table>
      </div>

      {editor.fixedSteps.length > 0 ? (
        <div className="rounded-md border border-border/70 bg-bg/50 px-3 py-2">
          <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-text-secondary">
            <LockKeyhole className="h-3.5 w-3.5" aria-hidden />
            Held constant
          </p>
          <ul className="mt-2 space-y-1 text-sm text-text-primary">
            {editor.fixedSteps.map((step) => (
              <li key={`${step.index}-${step.label}`} className="flex justify-between gap-3">
                <span>{step.label}</span>
                <span className="shrink-0 text-xs capitalize text-text-secondary">{step.role}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Button
        type="button"
        className="w-full sm:w-auto"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate(changeTo)}
      >
        {mutation.isPending ? 'Uploading…' : 'Approve & upload to Zwift'}
      </Button>
    </section>
  );
}

function EditorRow({
  label,
  current,
  children,
}: {
  label: string;
  current: string;
  children: ReactNode;
}) {
  return (
    <tr>
      <th scope="row" className="rounded-l-md bg-bg/70 px-2 py-2 text-left font-medium text-text-primary">
        {label}
      </th>
      <td className="bg-bg/70 px-2 py-2 tabular-nums text-text-secondary">{current}</td>
      <td className="rounded-r-md bg-bg/70 px-2 py-2">{children}</td>
    </tr>
  );
}

function DurationInput({
  label,
  value,
  maxMinutes,
  onChange,
}: {
  label: string;
  value: number;
  maxMinutes: number;
  onChange: (durationSec: number) => void;
}) {
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  return (
    <div className="flex items-center gap-1.5">
      <BoundedNumberInput
        ariaLabel={`${label} minutes`}
        value={minutes}
        min={0}
        max={maxMinutes}
        onChange={(nextMinutes) => onChange(nextMinutes * 60 + seconds)}
      />
      <span className="text-text-secondary">:</span>
      <BoundedNumberInput
        ariaLabel={`${label} seconds`}
        value={seconds}
        min={0}
        max={59}
        onChange={(nextSeconds) => onChange(minutes * 60 + nextSeconds)}
        pad
      />
    </div>
  );
}

function NullableCadenceInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  const [draft, setDraft] = useState(value == null ? '' : String(value));
  useEffect(() => {
    setDraft(value == null ? '' : String(value));
  }, [value]);
  return (
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        inputMode="numeric"
        aria-label={label}
        min={40}
        max={130}
        value={draft}
        placeholder="Open"
        className="h-9 w-24 tabular-nums"
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          if (next === '') onChange(null);
          else if (Number.isFinite(Number(next))) onChange(Number(next));
        }}
        onBlur={() => {
          if (draft === '') return;
          const bounded = Math.min(130, Math.max(40, Number(draft)));
          setDraft(String(bounded));
          onChange(bounded);
        }}
      />
      <span className="text-xs text-text-secondary">rpm</span>
    </div>
  );
}

function BoundedNumberInput({
  ariaLabel,
  value,
  min,
  max,
  suffix,
  pad = false,
  onChange,
}: {
  ariaLabel: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  pad?: boolean;
  onChange: (value: number) => void;
}) {
  const displayed = pad ? String(value).padStart(2, '0') : String(value);
  const [draft, setDraft] = useState(displayed);
  useEffect(() => {
    setDraft(displayed);
  }, [displayed]);
  return (
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        inputMode="numeric"
        aria-label={ariaLabel}
        min={min}
        max={max}
        value={draft}
        className={cn('h-9 tabular-nums', suffix ? 'w-20' : 'w-24')}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          if (next === '') return;
          const parsed = Number(next);
          if (Number.isFinite(parsed)) onChange(parsed);
        }}
        onBlur={() => {
          const parsed = Number(draft);
          const bounded = Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : min;
          setDraft(pad ? String(bounded).padStart(2, '0') : String(bounded));
          onChange(bounded);
        }}
      />
      {suffix ? <span className="text-xs text-text-secondary">{suffix}</span> : null}
    </div>
  );
}
