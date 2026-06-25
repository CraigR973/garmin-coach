import { cn } from '@/lib/utils';
import { brand } from '@/theme/tokens';

interface BrandProps {
  variant?: 'splash' | 'compact' | 'mono';
  size?: number;
  label?: string;
  decorative?: boolean;
  className?: string;
}

/**
 * "CheckMark" wordmark.
 *
 * variants:
 *   splash  - vertical two-line wordmark (login / onboarding)
 *   compact - single-line header lockup
 *   mono    - short name in mono (misc)
 */
export function Brand({
  variant = 'splash',
  label = brand.full,
  decorative = false,
  className,
}: BrandProps) {
  if (variant === 'mono') {
    return (
      <span
        className={cn(
          'font-mono font-semibold tracking-[0.3em] text-wordmark text-sm uppercase',
          className,
        )}
        aria-hidden={decorative ? true : undefined}
        aria-label={decorative ? undefined : label}
      >
        {brand.short}
      </span>
    );
  }

  if (variant === 'compact') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-2 font-mono font-semibold uppercase tracking-[0.2em] text-[11px] leading-none text-wordmark-h whitespace-nowrap select-none',
          className,
        )}
        aria-hidden={decorative ? true : undefined}
        aria-label={decorative ? undefined : label}
      >
        <span>{brand.full}</span>
      </span>
    );
  }

  // splash — vertical two-line lockup
  return (
    <div
      className={cn('flex flex-col items-center text-center select-none gap-1', className)}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : label}
    >
      <p className="font-mono font-semibold uppercase tracking-[0.18em] text-3xl sm:text-4xl leading-none text-text-primary">
        {brand.wordmarkTop}
      </p>
      <p className="font-mono font-semibold uppercase tracking-[0.18em] text-3xl sm:text-4xl leading-none text-primary">
        {brand.wordmarkBottom}
      </p>
    </div>
  );
}
