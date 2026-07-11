import { useEffect, useMemo, useState } from 'react';
import type { freeformBikeWorkoutInputSchema } from '@coach/shared';
import { Bike, ChevronDown, ChevronUp, MapPin, Plus, Trash2, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

type FreeformBikeWorkoutInput = typeof freeformBikeWorkoutInputSchema._type;
type Delivery = FreeformBikeWorkoutInput['delivery'];
type SegmentKind = 'ramp' | 'steady' | 'interval';

// Mirror the server floor/band (structured_workout_builder.py). The soft band only
// drives non-blocking warnings; the hard floor blocks submit because the API 422s it.
const SOFT_MIN_PCT = 45;
const SOFT_MAX_PCT = 150;
const ABS_MIN_PCT = 1;
const ABS_MAX_PCT = 300;
const MAX_TOTAL_MIN = 480;

// Editor state carries nullable numbers (a field can be mid-edit / cleared); the
// strict payload is assembled from a valid form on submit.
interface EditorSegment {
  kind: SegmentKind;
  durationMin: number | null;
  startFtpPct: number | null;
  endFtpPct: number | null;
  ftpPct: number | null;
  repeats: number | null;
  workMin: number | null;
  workFtpPct: number | null;
  recoverMin: number | null;
  recoverFtpPct: number | null;
}

function blankSegment(kind: SegmentKind): EditorSegment {
  const base: EditorSegment = {
    kind,
    durationMin: null,
    startFtpPct: null,
    endFtpPct: null,
    ftpPct: null,
    repeats: null,
    workMin: null,
    workFtpPct: null,
    recoverMin: null,
    recoverFtpPct: null,
  };
  if (kind === 'ramp') return { ...base, durationMin: 10, startFtpPct: 45, endFtpPct: 75 };
  if (kind === 'steady') return { ...base, durationMin: 20, ftpPct: 65 };
  return { ...base, repeats: 4, workMin: 4, workFtpPct: 110, recoverMin: 4, recoverFtpPct: 55 };
}

const DEFAULT_SEGMENTS: EditorSegment[] = [
  blankSegment('ramp'),
  blankSegment('steady'),
  { ...blankSegment('ramp'), durationMin: 5, startFtpPct: 75, endFtpPct: 45 },
];

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
  const initial = useMemo(
    () => stateFromStructuredWorkout(initialStructuredWorkout),
    [initialStructuredWorkout],
  );
  const [delivery, setDelivery] = useState<Delivery>(initial.delivery);
  const [segments, setSegments] = useState<EditorSegment[]>(initial.segments);

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

  const update = (index: number, patch: Partial<EditorSegment>) =>
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

interface PowerBar {
  durationMin: number;
  startPct: number;
  endPct: number;
}

function PowerProfilePreview({
  bars,
  totalMin,
  peakPct,
}: {
  bars: PowerBar[];
  totalMin: number;
  peakPct: number;
}) {
  if (bars.length === 0 || totalMin <= 0) {
    return (
      <div className="rounded-lg border border-border p-3 text-center text-xs text-text-secondary">
        Fill in the segments to preview the ride.
      </div>
    );
  }
  const height = 120;
  const yMax = Math.max(150, peakPct);
  const y = (pct: number) => height - (Math.max(0, pct) / yMax) * height;
  let cursor = 0;
  const shapes = bars.map((bar, index) => {
    const x = cursor;
    const width = bar.durationMin;
    cursor += width;
    const opacity = Math.min(0.95, Math.max(0.3, 0.3 + (Math.max(bar.startPct, bar.endPct) / 200) * 0.6));
    if (bar.startPct === bar.endPct) {
      return (
        <rect
          key={index}
          x={x}
          y={y(bar.startPct)}
          width={width}
          height={height - y(bar.startPct)}
          fill="currentColor"
          opacity={opacity}
        />
      );
    }
    const points = `${x},${height} ${x},${y(bar.startPct)} ${x + width},${y(bar.endPct)} ${x + width},${height}`;
    return <polygon key={index} points={points} fill="currentColor" opacity={opacity} />;
  });
  return (
    <div className="space-y-1">
      <div className="text-primary">
        <svg
          viewBox={`0 0 ${totalMin} ${height}`}
          preserveAspectRatio="none"
          className="h-24 w-full rounded-lg bg-surface-muted"
          role="img"
          aria-label="Power profile preview"
        >
          {shapes}
          <line
            x1={0}
            x2={totalMin}
            y1={y(100)}
            y2={y(100)}
            stroke="currentColor"
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.5}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div className="flex justify-between text-xs text-text-secondary">
        <span>Total {totalMin} min</span>
        <span>Peak {peakPct}% FTP · dashed = 100%</span>
      </div>
    </div>
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
  segment: EditorSegment;
  disabled: boolean;
  isFirst: boolean;
  isLast: boolean;
  onKind: (kind: SegmentKind) => void;
  onChange: (patch: Partial<EditorSegment>) => void;
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

function segmentPowers(segment: EditorSegment): number[] {
  if (segment.kind === 'ramp') return [segment.startFtpPct, segment.endFtpPct].filter(isNum);
  if (segment.kind === 'steady') return [segment.ftpPct].filter(isNum);
  return [segment.workFtpPct, segment.recoverFtpPct].filter(isNum);
}

function expand(segments: EditorSegment[]): PowerBar[] {
  const bars: PowerBar[] = [];
  for (const segment of segments) {
    if (segment.kind === 'ramp') {
      if (positive(segment.durationMin) && isNum(segment.startFtpPct) && isNum(segment.endFtpPct)) {
        bars.push({ durationMin: segment.durationMin, startPct: segment.startFtpPct, endPct: segment.endFtpPct });
      }
    } else if (segment.kind === 'steady') {
      if (positive(segment.durationMin) && isNum(segment.ftpPct)) {
        bars.push({ durationMin: segment.durationMin, startPct: segment.ftpPct, endPct: segment.ftpPct });
      }
    } else if (
      positive(segment.repeats) &&
      positive(segment.workMin) &&
      isNum(segment.workFtpPct) &&
      positive(segment.recoverMin) &&
      isNum(segment.recoverFtpPct)
    ) {
      for (let rep = 0; rep < segment.repeats; rep += 1) {
        bars.push({ durationMin: segment.workMin, startPct: segment.workFtpPct, endPct: segment.workFtpPct });
        bars.push({ durationMin: segment.recoverMin, startPct: segment.recoverFtpPct, endPct: segment.recoverFtpPct });
      }
    }
  }
  return bars;
}

function liveWarnings(segments: EditorSegment[]): string[] {
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

function isValidSegment(segment: EditorSegment): boolean {
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

function isValid(segments: EditorSegment[]): boolean {
  return segments.length > 0 && segments.every(isValidSegment);
}

function toPayload(delivery: Delivery, segments: EditorSegment[]): FreeformBikeWorkoutInput | null {
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

function stateFromStructuredWorkout(
  structuredWorkout: Record<string, unknown> | null | undefined,
): { delivery: Delivery; segments: EditorSegment[] } {
  if (!structuredWorkout) return { delivery: 'indoor', segments: DEFAULT_SEGMENTS.map((s) => ({ ...s })) };
  const delivery: Delivery = structuredWorkout.delivery === 'outdoor' ? 'outdoor' : 'indoor';
  const rawSteps = Array.isArray(structuredWorkout.steps) ? structuredWorkout.steps : [];
  const segments: EditorSegment[] = [];
  for (const rawStep of rawSteps) {
    const segment = segmentFromStep(rawStep);
    if (segment) segments.push(segment);
  }
  if (segments.length === 0) return { delivery, segments: DEFAULT_SEGMENTS.map((s) => ({ ...s })) };
  return { delivery, segments };
}

function segmentFromStep(rawStep: unknown): EditorSegment | null {
  if (typeof rawStep !== 'object' || rawStep === null) return null;
  const step = rawStep as Record<string, unknown>;
  const minutes = numberOrNull(step.minutes);
  const ramp = Array.isArray(step.ramp) ? step.ramp : null;
  const target = typeof step.target === 'string' ? step.target : '';
  const pattern = typeof step.pattern === 'string' ? step.pattern : '';

  if (ramp && ramp.length === 2 && minutes) {
    return {
      ...blankSegment('ramp'),
      durationMin: minutes,
      startFtpPct: Math.round(Number(ramp[0])),
      endFtpPct: Math.round(Number(ramp[1])),
    };
  }
  if (pattern) {
    const parsed = parsePattern(pattern, target);
    if (parsed) return parsed;
  }
  const pct = parsePower(target);
  if (minutes && pct !== null) {
    return { ...blankSegment('steady'), durationMin: minutes, ftpPct: pct };
  }
  return null;
}

function parsePattern(pattern: string, target: string): EditorSegment | null {
  const match = pattern.match(/(\d+)\s*x\s*(\d+)min\s*\/\s*(\d+)min\s*@(\d+)%/i);
  if (!match) return null;
  return {
    ...blankSegment('interval'),
    repeats: Number(match[1]),
    workMin: Number(match[2]),
    workFtpPct: parsePower(target) ?? 110,
    recoverMin: Number(match[3]),
    recoverFtpPct: Number(match[4]),
  };
}

function parsePower(value: string): number | null {
  const match = value.match(/(\d+(?:\.\d+)?)\s*%/);
  return match ? Math.round(Number(match[1])) : null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isNum(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function positive(value: number | null | undefined): value is number {
  return isNum(value) && value > 0;
}
