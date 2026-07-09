import { useEffect, useState } from 'react';
import type { quickAddOptionSchema } from '@coach/shared';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

type QuickAddOption = typeof quickAddOptionSchema._type;

const CATEGORY_TITLE: Record<string, string> = {
  cycle: 'Add a ride',
  weights: 'Add a strength session',
  flexibility: 'Add flexibility',
};

interface QuickAddSheetProps {
  open: boolean;
  category: string | null;
  options: QuickAddOption[];
  loading: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: (subtype: string, durationMin: number) => void;
}

export function QuickAddSheet({
  open,
  category,
  options,
  loading,
  busy,
  onClose,
  onConfirm,
}: QuickAddSheetProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [duration, setDuration] = useState<number | null>(null);

  useEffect(() => {
    if (!open) {
      setSelected(null);
      setDuration(null);
      return;
    }
    const first = options[0];
    if (first && selected === null) {
      setSelected(first.subtype);
      setDuration(first.defaultDurationMin);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, options]);

  const active = options.find((option) => option.subtype === selected) ?? null;

  const selectOption = (option: QuickAddOption) => {
    setSelected(option.subtype);
    setDuration(option.defaultDurationMin);
  };

  const durationValid =
    active !== null &&
    duration !== null &&
    duration >= active.minDurationMin &&
    duration <= active.maxDurationMin;

  return (
    <Sheet open={open} onClose={onClose} title={category ? CATEGORY_TITLE[category] : 'Add a session'}>
      <div className="space-y-4">
        {loading ? (
          <p className="text-sm text-text-secondary">Loading options…</p>
        ) : (
          <>
            <div className="space-y-2">
              {options.map((option) => (
                <Button
                  key={option.subtype}
                  type="button"
                  variant="outline"
                  disabled={busy}
                  className={cn(
                    'h-auto w-full justify-start rounded-xl px-4 py-3 text-left',
                    option.subtype === selected && 'border-primary/60 bg-primary/10',
                  )}
                  onClick={() => selectOption(option)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="text-sm font-medium text-text-primary">{option.label}</span>
                    <span className="mt-1 block text-xs text-text-secondary">
                      Default {option.defaultDurationMin} min
                    </span>
                  </span>
                </Button>
              ))}
            </div>

            {active && (
              <label className="block space-y-1">
                <span className="text-sm font-medium text-text-primary">Duration (minutes)</span>
                <Input
                  type="number"
                  min={active.minDurationMin}
                  max={active.maxDurationMin}
                  value={duration ?? ''}
                  onChange={(event) => setDuration(Number(event.target.value))}
                />
                <span className="block text-xs text-text-secondary">
                  {active.minDurationMin}–{active.maxDurationMin} min
                </span>
              </label>
            )}

            <Button
              type="button"
              className="w-full"
              disabled={busy || !active || !durationValid}
              onClick={() => active && duration !== null && onConfirm(active.subtype, duration)}
            >
              Add
            </Button>
          </>
        )}
      </div>
    </Sheet>
  );
}
