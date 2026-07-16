import { useEffect, useMemo, useState } from 'react';
import type { freeformBikeWorkoutInputSchema } from '@coach/shared';
import { Bike, ChevronDown, ChevronUp, MapPin, Plus, Trash2, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet } from '@/components/ui/sheet';
import { PowerProfilePreview } from '@/components/PowerProfilePreview';
import { cn } from '@/lib/utils';
import {
  DEFAULT_SEGMENTS,
  blankSegment,
  expand,
  isNum,
  parseStructuredWorkout,
  positive,
  type Delivery,
  type SegmentKind,
  type WorkoutSegment,
} from '@/lib/structuredWorkout';

type FreeformBikeWorkoutInput = typeof freeformBikeWorkoutInputSchema._type;

// Mirror the server floor/band (structured_workout_builder.py). The soft band only
// drives non-blocking warnings; the hard floor blocks submit because the API 422s it.
const SOFT_MIN_PCT = 45;
const SOFT_MAX_PCT = 150;
const ABS_MIN_PCT = 1;
const ABS_MAX_PCT = 300;
const MAX_TOTAL_MIN = 480;

interface StructuredWorkoutSheetProps {
  open: boolean;
  mode: 'add' | 'edit';
  workoutTitle?: string;
  initialStructuredWorkout?: Record<string, unknown> | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: (payload: FreeformBikeWorkoutInput) => void;
}

export function StructuredWorkoutSheet({
  open,
  mode,
  workoutTitle,
  initialStructuredWorkout,
  busy,
  onClose,
  onConfirm,
}: StructuredWorkoutSheetProps) {
  const initial = useMemo(() => {
    // Faithful parse, then fall back to the editor's starting template when the
    // workout has no structure yet (add flow, or a non-structured session).
    const parsed = parseStructuredWorkout(initialStructuredWorkout);
    return parsed.segments.length > 0
      ? parsed
      : { delivery: parsed.delivery, segments: DEFAULT_SEGMENTS.map((s) => ({ ...s })) };
  }, [initialStructuredWorkout]);
  const [delivery, setDelivery] = useState<Delivery>(initial.delivery);
  const [segments, setSegments] = useState<WorkoutSegment[]>(initial.segments);

  useEffect(() => {
    if (open) {
      setDelivery(initial.delivery);
      setSegments(initial.segments);
    }
  }, [initial, open]);

  const bars = useMemo(() => expand(segments), [segments]);
  const totalMin = useMemo(() => bars.reduce((sum, bar) => sum + bar.durationMin, 0), [bars]);
  const peakPct = bars.reduce((max, bar) => Math.max(max, bar.startPct, bar.endPct), 0);
  const warnings = useMemo(() => liveWarnings(segments), [segments]);
  const canSubmit = isValid(segments) && totalMin <= MAX_TOTAL_MIN;
  const title = mode === 'edit' ? `Edit ${workoutTitle ?? 'workout'}` : 'Build a ride';

  const update = (index: number, patch: Partial<WorkoutSegment>) =>
    setSegments((current) =>
      current.map((segment, idx) => (idx === index ? { ...segment, ...patch } : segment)),
    );
  const changeKind = (index: number, kind: SegmentKind) =>
    setSegments((current) =>
      current.map((segment, idx) => (idx === index ? blankSegment(kind) : segment)),
    );
  const remove = (index: number) =>
    setSegments((current) => current.filter((_, idx) => idx !== index));
  const move = (index: number, delta: number) =>
    setSegments((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const add = (kind: SegmentKind) => setSegments((current) => [...current, blankSegment(kind)]);

  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-2">
          <OptionButton
            active={delivery === 'indoor'}
            disabled={busy}
            icon={Bike}
            label="Indoor"
            onClick={() => setDelivery('indoor')}
          />
          <OptionButton
            active={delivery === 'outdoor'}
            disabled={busy}
            icon={MapPin}
            label="Outdoor"
            onClick={() => setDelivery('outdoor')}
          />
        </div>

        <PowerProfilePreview bars={bars} totalMin={totalMin} peakPct={peakPct} />

        <div className="space-y-3">
          {segments.map((segment, index) => (
            <SegmentRow
              key={index}
              segment={segment}
              disabled={busy}
              isFirst={index === 0}
              isLast={index === segments.length - 1}
              onKind={(kind) => changeKind(index, kind)}
              onChange={(patch) => update(index, patch)}
              onRemove={() => remove(index)}
              onMove={(delta) => move(index, delta)}
            />
          ))}
          {segments.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border p-3 text-sm text-text-secondary">
              Add a segment to start building your ride.
            </p>
          ) : null}
        </div>

        <div className="grid grid-cols-3 gap-2">
          <AddButton label="Ramp" disabled={busy} onClick={() => add('ramp')} />
          <AddButton label="Steady" disabled={busy} onClick={() => add('steady')} />
          <AddButton label="Intervals" disabled={busy} onClick={() => add('interval')} />
        </div>

        {warnings.length > 0 ? (
          <div className="space-y-1 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
            {warnings.map((warning) => (
              <p key={warning} className="text-xs text-amber-600 dark:text-amber-400">
                Heads-up: {warning} You can still deliver it.
              </p>
            ))}
          </div>
        ) : null}

        <Button
          type="button"
          className="w-full"
          disabled={busy || !canSubmit}
          onClick={() => {
            const payload = toPayload(delivery, segments);
            if (payload) onConfirm(payload);
          }}
        >
          {mode === 'edit' ? 'Save structure' : 'Add workout'}
        </Button>
      </div>
    </Sheet>
  );
}

function SegmentRow({
  segment,
  disabled,
  isFirst,
  isLast,
  onKind,
  onChange,
  onRemove,
  onMove,
}: {
  segment: WorkoutSegment;
  disabled: boolean;
  isFirst: boolean;
  isLast: boolean;
  onKind: (kind: SegmentKind) => void;
  onChange: (patch: Partial<WorkoutSegment>) => void;
  onRemove: () => void;
  onMove: (delta: number) => void;
}) {
  const rampRole = segment.kind === 'ramp' ? (isFirst ? ' (warm-up)' : isLast ? ' (cool-down)' : '') : '';
  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="grid grid-cols-3 gap-1">
          {(['ramp', 'steady', 'interval'] as const).map((kind) => (
            <Button
              key={kind}
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              className={cn('capitalize', segment.kind === kind && 'border-primary/60 bg-primary/10')}
              onClick={() => onKind(kind)}
            >
              {kind}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <IconButton disabled={disabled || isFirst} label="Move up" onClick={() => onMove(-1)}>
            <ChevronUp className="h-4 w-4" aria-hidden />
          </IconButton>
          <IconButton disabled={disabled || isLast} label="Move down" onClick={() => onMove(1)}>
            <ChevronDown className="h-4 w-4" aria-hidden />
          </IconButton>
          <IconButton disabled={disabled} label="Remove segment" onClick={onRemove}>
            <Trash2 className="h-4 w-4" aria-hidden />
          </IconButton>
        </div>
      </div>

      {segment.kind === 'ramp' ? (
        <>
          <p className="text-xs font-medium text-text-secondary">Ramp{rampRole}</p>
          <div className="grid grid-cols-3 gap-3">
            <NumberField label="Minutes" value={segment.durationMin} disabled={disabled} onChange={(v) => onChange({ durationMin: v })} />
            <NumberField label="Start %FTP" value={segment.startFtpPct} disabled={disabled} onChange={(v) => onChange({ startFtpPct: v })} />
            <NumberField label="End %FTP" value={segment.endFtpPct} disabled={disabled} onChange={(v) => onChange({ endFtpPct: v })} />
          </div>
        </>
      ) : null}

      {segment.kind === 'steady' ? (
        <div className="grid grid-cols-2 gap-3">
          <NumberField label="Minutes" value={segment.durationMin} disabled={disabled} onChange={(v) => onChange({ durationMin: v })} />
          <NumberField label="%FTP" value={segment.ftpPct} disabled={disabled} onChange={(v) => onChange({ ftpPct: v })} />
        </div>
      ) : null}

      {segment.kind === 'interval' ? (
        <div className="grid grid-cols-2 gap-3">
          <NumberField label="Repeats" value={segment.repeats} disabled={disabled} onChange={(v) => onChange({ repeats: v })} />
          <div />
          <NumberField label="Work min" value={segment.workMin} disabled={disabled} onChange={(v) => onChange({ workMin: v })} />
          <NumberField label="Work %FTP" value={segment.workFtpPct} disabled={disabled} onChange={(v) => onChange({ workFtpPct: v })} />
          <NumberField label="Recovery min" value={segment.recoverMin} disabled={disabled} onChange={(v) => onChange({ recoverMin: v })} />
          <NumberField label="Recovery %FTP" value={segment.recoverFtpPct} disabled={disabled} onChange={(v) => onChange({ recoverFtpPct: v })} />
        </div>
      ) : null}
    </div>
  );
}

function OptionButton({
  active,
  disabled,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  disabled: boolean;
  icon: LucideIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      disabled={disabled}
      className={cn('justify-start', active && 'border-primary/60 bg-primary/10')}
      onClick={onClick}
    >
      <Icon className="h-4 w-4" aria-hidden />
      {label}
    </Button>
  );
}

function AddButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={onClick}>
      <Plus className="h-4 w-4" aria-hidden />
      {label}
    </Button>
  );
}

function IconButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: React.ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button type="button" size="icon" variant="outline" disabled={disabled} aria-label={label} onClick={onClick}>
      {children}
    </Button>
  );
}

function NumberField({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number | null | undefined;
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-text-primary">{label}</span>
      <Input
        type="number"
        min={1}
        value={value ?? ''}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === '' ? null : Number(next));
        }}
      />
    </label>
  );
}

function segmentPowers(segment: WorkoutSegment): number[] {
  if (segment.kind === 'ramp') return [segment.startFtpPct, segment.endFtpPct].filter(isNum);
  if (segment.kind === 'steady') return [segment.ftpPct].filter(isNum);
  return [segment.workFtpPct, segment.recoverFtpPct].filter(isNum);
}

function liveWarnings(segments: WorkoutSegment[]): string[] {
  const warnings: string[] = [];
  const powers = segments.flatMap(segmentPowers);
  const outOfBand = [...new Set(powers.filter((p) => p < SOFT_MIN_PCT || p > SOFT_MAX_PCT))].sort(
    (a, b) => a - b,
  );
  if (outOfBand.length > 0) {
    const joined = outOfBand.map((p) => `${p}%`).join(', ');
    warnings.push(
      `power ${joined} FTP is outside the usual ${SOFT_MIN_PCT}–${SOFT_MAX_PCT}% band.`,
    );
  }
  if (segments.length > 0) {
    const opensRamp = segments[0].kind === 'ramp';
    const closesRamp = segments[segments.length - 1].kind === 'ramp';
    if (!opensRamp && !closesRamp) warnings.push('no warm-up or cool-down ramp.');
    else if (!opensRamp) warnings.push('no warm-up ramp.');
    else if (!closesRamp) warnings.push('no cool-down ramp.');
  }
  return warnings;
}

function validPower(value: number | null | undefined): value is number {
  return isNum(value) && value >= ABS_MIN_PCT && value <= ABS_MAX_PCT;
}

function isValidSegment(segment: WorkoutSegment): boolean {
  if (segment.kind === 'ramp') {
    return positive(segment.durationMin) && validPower(segment.startFtpPct) && validPower(segment.endFtpPct);
  }
  if (segment.kind === 'steady') {
    return positive(segment.durationMin) && validPower(segment.ftpPct);
  }
  return (
    positive(segment.repeats) &&
    positive(segment.workMin) &&
    validPower(segment.workFtpPct) &&
    positive(segment.recoverMin) &&
    validPower(segment.recoverFtpPct)
  );
}

function isValid(segments: WorkoutSegment[]): boolean {
  return segments.length > 0 && segments.every(isValidSegment);
}

function toPayload(delivery: Delivery, segments: WorkoutSegment[]): FreeformBikeWorkoutInput | null {
  if (!isValid(segments)) return null;
  const built = segments.map((segment) => {
    if (segment.kind === 'ramp') {
      return {
        kind: 'ramp' as const,
        durationMin: segment.durationMin as number,
        startFtpPct: segment.startFtpPct as number,
        endFtpPct: segment.endFtpPct as number,
      };
    }
    if (segment.kind === 'steady') {
      return {
        kind: 'steady' as const,
        durationMin: segment.durationMin as number,
        ftpPct: segment.ftpPct as number,
      };
    }
    return {
      kind: 'interval' as const,
      repeats: segment.repeats as number,
      workMin: segment.workMin as number,
      workFtpPct: segment.workFtpPct as number,
      recoverMin: segment.recoverMin as number,
      recoverFtpPct: segment.recoverFtpPct as number,
    };
  });
  return { delivery, segments: built };
}
