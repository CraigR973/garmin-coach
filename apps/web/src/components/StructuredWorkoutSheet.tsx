import { useEffect, useMemo, useState } from 'react';
import type { customBikeWorkoutInputSchema } from '@coach/shared';
import { Bike, MapPin, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

type CustomBikeWorkoutInput = typeof customBikeWorkoutInputSchema._type;

const DEFAULT_WORKOUT: CustomBikeWorkoutInput = {
  delivery: 'indoor',
  warmupEnabled: true,
  warmupDurationMin: 10,
  z2LeadInEnabled: false,
  z2LeadInDurationMin: 10,
  intervalsEnabled: false,
  interval1DurationMin: 2,
  interval1FtpPct: 110,
  interval2DurationMin: 2,
  interval2FtpPct: 55,
  repeats: 5,
  blockDurationMin: 30,
  blockFtpPct: 65,
  cooldownEnabled: true,
  cooldownDurationMin: 5,
};

interface StructuredWorkoutSheetProps {
  open: boolean;
  mode: 'add' | 'edit';
  workoutTitle?: string;
  initialStructuredWorkout?: Record<string, unknown> | null;
  busy: boolean;
  onClose: () => void;
  onConfirm: (payload: CustomBikeWorkoutInput) => void;
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
  const initialValue = useMemo(
    () => inputFromStructuredWorkout(initialStructuredWorkout),
    [initialStructuredWorkout],
  );
  const [form, setForm] = useState<CustomBikeWorkoutInput>(initialValue);

  useEffect(() => {
    if (open) setForm(initialValue);
  }, [initialValue, open]);

  const canSubmit = isValid(form);
  const title = mode === 'edit' ? `Edit ${workoutTitle ?? 'workout'}` : 'Build a ride';

  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-2">
          <OptionButton
            active={form.delivery === 'indoor'}
            disabled={busy}
            icon={Bike}
            label="Indoor"
            onClick={() => setForm((current) => ({ ...current, delivery: 'indoor' }))}
          />
          <OptionButton
            active={form.delivery === 'outdoor'}
            disabled={busy}
            icon={MapPin}
            label="Outdoor"
            onClick={() => setForm((current) => ({ ...current, delivery: 'outdoor' }))}
          />
        </div>

        <EnabledNumber
          label="Warm-up ramp"
          enabled={form.warmupEnabled}
          value={form.warmupDurationMin}
          suffix="45-75% FTP"
          disabled={busy}
          onToggle={(enabled) => setForm((current) => ({ ...current, warmupEnabled: enabled }))}
          onChange={(value) => setForm((current) => ({ ...current, warmupDurationMin: value }))}
        />

        <EnabledNumber
          label="Z2 lead-in"
          enabled={form.z2LeadInEnabled}
          value={form.z2LeadInDurationMin}
          suffix="55% FTP"
          disabled={busy}
          onToggle={(enabled) => setForm((current) => ({ ...current, z2LeadInEnabled: enabled }))}
          onChange={(value) => setForm((current) => ({ ...current, z2LeadInDurationMin: value }))}
        />

        <div className="space-y-3 rounded-lg border border-border p-3">
          <div className="grid grid-cols-2 gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              className={cn(!form.intervalsEnabled && 'border-primary/60 bg-primary/10')}
              onClick={() => setForm((current) => ({ ...current, intervalsEnabled: false }))}
            >
              Single block
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              className={cn(form.intervalsEnabled && 'border-primary/60 bg-primary/10')}
              onClick={() => setForm((current) => ({ ...current, intervalsEnabled: true }))}
            >
              Intervals
            </Button>
          </div>

          {form.intervalsEnabled ? (
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label="Int 1 minutes"
                value={form.interval1DurationMin}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, interval1DurationMin: value }))}
              />
              <NumberField
                label="Int 1 %FTP"
                value={form.interval1FtpPct}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, interval1FtpPct: value }))}
              />
              <NumberField
                label="Int 2 minutes"
                value={form.interval2DurationMin}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, interval2DurationMin: value }))}
              />
              <NumberField
                label="Int 2 %FTP"
                value={form.interval2FtpPct}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, interval2FtpPct: value }))}
              />
              <NumberField
                label="Repeats"
                value={form.repeats}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, repeats: value }))}
              />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                label="Block minutes"
                value={form.blockDurationMin}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, blockDurationMin: value }))}
              />
              <NumberField
                label="Block %FTP"
                value={form.blockFtpPct}
                disabled={busy}
                onChange={(value) => setForm((current) => ({ ...current, blockFtpPct: value }))}
              />
            </div>
          )}
        </div>

        <EnabledNumber
          label="Cool-down ramp"
          enabled={form.cooldownEnabled}
          value={form.cooldownDurationMin}
          suffix="75-45% FTP"
          disabled={busy}
          onToggle={(enabled) => setForm((current) => ({ ...current, cooldownEnabled: enabled }))}
          onChange={(value) => setForm((current) => ({ ...current, cooldownDurationMin: value }))}
        />

        <Button
          type="button"
          className="w-full"
          disabled={busy || !canSubmit}
          onClick={() => onConfirm(form)}
        >
          {mode === 'edit' ? 'Save structure' : 'Add workout'}
        </Button>
      </div>
    </Sheet>
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

function EnabledNumber({
  label,
  enabled,
  value,
  suffix,
  disabled,
  onToggle,
  onChange,
}: {
  label: string;
  enabled: boolean;
  value: number | null | undefined;
  suffix: string;
  disabled: boolean;
  onToggle: (enabled: boolean) => void;
  onChange: (value: number | null) => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-text-primary">{label}</p>
          <p className="text-xs text-text-secondary">{suffix}</p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onToggle(!enabled)}
        >
          {enabled ? 'On' : 'Off'}
        </Button>
      </div>
      {enabled ? (
        <NumberField label="Minutes" value={value} disabled={disabled} onChange={onChange} />
      ) : null}
    </div>
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

function isValid(form: CustomBikeWorkoutInput): boolean {
  if (form.warmupEnabled && !positive(form.warmupDurationMin)) return false;
  if (form.z2LeadInEnabled && !positive(form.z2LeadInDurationMin)) return false;
  if (form.cooldownEnabled && !positive(form.cooldownDurationMin)) return false;
  if (form.intervalsEnabled) {
    return (
      positive(form.interval1DurationMin) &&
      validPower(form.interval1FtpPct) &&
      positive(form.interval2DurationMin) &&
      validPower(form.interval2FtpPct) &&
      positive(form.repeats)
    );
  }
  return positive(form.blockDurationMin) && validPower(form.blockFtpPct);
}

function positive(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function validPower(value: number | null | undefined): value is number {
  return positive(value) && value >= 45 && value <= 150;
}

function inputFromStructuredWorkout(
  structuredWorkout: Record<string, unknown> | null | undefined,
): CustomBikeWorkoutInput {
  const next = { ...DEFAULT_WORKOUT };
  if (!structuredWorkout) return next;
  next.delivery = structuredWorkout.delivery === 'outdoor' ? 'outdoor' : 'indoor';
  const rawSteps = Array.isArray(structuredWorkout.steps) ? structuredWorkout.steps : [];
  for (const rawStep of rawSteps) {
    if (!isStep(rawStep)) continue;
    const label = String(rawStep.label ?? '').toLowerCase();
    const target = String(rawStep.target ?? '');
    const minutes = numberOrNull(rawStep.minutes);
    const ramp = Array.isArray(rawStep.ramp) ? rawStep.ramp : null;
    if (label.includes('warm') && ramp && minutes) {
      next.warmupEnabled = true;
      next.warmupDurationMin = minutes;
      continue;
    }
    if (label.includes('cool') && ramp && minutes) {
      next.cooldownEnabled = true;
      next.cooldownDurationMin = minutes;
      continue;
    }
    if ((label.includes('z2') || target === '55%') && minutes) {
      next.z2LeadInEnabled = true;
      next.z2LeadInDurationMin = minutes;
      continue;
    }
    if (typeof rawStep.pattern === 'string') {
      const parsed = parsePattern(rawStep.pattern, target);
      if (parsed) {
        next.intervalsEnabled = true;
        Object.assign(next, parsed);
      }
      continue;
    }
    const pct = parsePower(target);
    if (minutes && pct) {
      next.intervalsEnabled = false;
      next.blockDurationMin = minutes;
      next.blockFtpPct = pct;
    }
  }
  return next;
}

function isStep(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function parsePower(value: string): number | null {
  const match = value.match(/(\d+(?:\.\d+)?)\s*%/);
  return match ? Math.round(Number(match[1])) : null;
}

function parsePattern(pattern: string, target: string): Partial<CustomBikeWorkoutInput> | null {
  const match = pattern.match(/(\d+)\s*x\s*(\d+)min\s*\/\s*(\d+)min\s*@(\d+)%/i);
  if (!match) return null;
  return {
    repeats: Number(match[1]),
    interval1DurationMin: Number(match[2]),
    interval1FtpPct: parsePower(target) ?? DEFAULT_WORKOUT.interval1FtpPct,
    interval2DurationMin: Number(match[3]),
    interval2FtpPct: Number(match[4]),
  };
}
