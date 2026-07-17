import { useRef } from 'react';
import { cn } from '@/lib/utils';
import { controlFieldClassName } from '@/components/ui/input';

interface PinInputProps {
  value: string;
  onChange: (v: string) => void;
  maxLength?: number;
  autoComplete?: string;
  label?: string;
}

export function PinInput({ value, onChange, maxLength = 4, autoComplete = 'current-password', label = 'PIN' }: PinInputProps) {
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  // Tracks the latest committed value synchronously so rapid desktop keystrokes
  // don't read stale React state before the next render cycle.
  const latestValue = useRef(value);
  latestValue.current = value;

  function focusCell(i: number) {
    inputs.current[i]?.focus();
  }

  function getDigitFrom(v: string, i: number): string {
    return i < v.length ? v[i] : '';
  }

  function handleChange(i: number, raw: string) {
    // Autofill / paste into a single cell — distribute digits across all cells.
    if (raw.length > 1) {
      const digits = raw.replace(/\D/g, '').slice(0, maxLength);
      latestValue.current = digits;
      onChange(digits);
      if (digits.length > 0) focusCell(Math.min(digits.length, maxLength - 1));
      return;
    }
    const digit = raw.replace(/\D/g, '').slice(-1);
    // Read from the ref so rapid typing always sees the up-to-date value even
    // if React hasn't committed the previous state update yet.
    const current = latestValue.current;
    const arr = Array.from({ length: maxLength }, (_, j) => getDigitFrom(current, j));
    arr[i] = digit;
    const next = arr.join('').replace(/\s+$/, '').trimEnd();
    latestValue.current = next;
    onChange(next);
    if (digit && i < maxLength - 1) focusCell(i + 1);
  }

  function handleKeyDown(i: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace') {
      e.preventDefault();
      const current = latestValue.current;
      if (getDigitFrom(current, i)) {
        const arr = Array.from({ length: maxLength }, (_, j) => getDigitFrom(current, j));
        arr[i] = '';
        const next = arr.join('').trimEnd();
        latestValue.current = next;
        onChange(next);
      } else if (i > 0) {
        const arr = Array.from({ length: maxLength }, (_, j) => getDigitFrom(current, j));
        arr[i - 1] = '';
        const next = arr.join('').trimEnd();
        latestValue.current = next;
        onChange(next);
        focusCell(i - 1);
      }
    } else if (e.key === 'ArrowLeft' && i > 0) {
      focusCell(i - 1);
    } else if (e.key === 'ArrowRight' && i < maxLength - 1) {
      focusCell(i + 1);
    }
  }

  function handlePaste(e: React.ClipboardEvent) {
    e.preventDefault();
    const digits = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, maxLength);
    onChange(digits);
    if (digits.length > 0) focusCell(Math.min(digits.length, maxLength - 1));
  }

  return (
    <div className="flex gap-2" role="group" aria-label={label}>
      {Array.from({ length: maxLength }, (_, i) => (
        <input
          key={i}
          ref={(el) => { inputs.current[i] = el; }}
          type="password"
          inputMode="numeric"
          maxLength={1}
          value={getDigitFrom(value, i)}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          autoComplete={i === 0 ? autoComplete : 'off'}
          aria-label={`PIN digit ${i + 1}`}
          // Shares the control-field fill/border/focus-ring system (Batch 137);
          // w-12 overrides controlFieldClassName's w-full via tailwind-merge.
          className={cn(
            controlFieldClassName,
            'w-12 h-12 text-center text-lg font-mono tracking-widest caret-transparent',
          )}
        />
      ))}
    </div>
  );
}
