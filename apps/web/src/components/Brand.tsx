import { cn } from '@/lib/utils';
import { brand } from '@/theme/tokens';

interface BrandProps {
  variant?: 'splash' | 'compact' | 'mono';
  size?: number;
  label?: string;
  decorative?: boolean;
  showMark?: boolean;
  className?: string;
}

interface LogomarkProps {
  size?: number;
  label?: string;
  decorative?: boolean;
  className?: string;
}

export function Logomark({
  size = 40,
  label = `${brand.full} logomark`,
  decorative = false,
  className,
}: LogomarkProps) {
  return (
    <img
      src="/brand/checkmark-icon-primary.svg"
      alt={decorative ? '' : label}
      aria-hidden={decorative ? true : undefined}
      data-testid="logomark"
      className={cn('inline-block shrink-0 rounded-[22%] shadow-sm', className)}
      style={{ width: size, height: size }}
    />
  );
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
  size,
  label = brand.full,
  decorative = false,
  showMark = variant !== 'mono',
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
          'inline-flex items-center gap-2 font-mono font-semibold uppercase tracking-[0.18em] text-[11px] leading-none text-wordmark-h whitespace-nowrap select-none',
          className,
        )}
        aria-hidden={decorative ? true : undefined}
        aria-label={decorative ? undefined : label}
      >
        {showMark && <Logomark size={size ?? 28} decorative />}
        <span>{brand.full}</span>
      </span>
    );
  }

  // splash — vertical two-line lockup
  return (
    <div
      className={cn('flex flex-col items-center text-center select-none gap-3', className)}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : label}
    >
      {showMark && <Logomark size={size ?? 88} decorative />}
      <div className="space-y-1">
        <p className="font-mono font-semibold uppercase tracking-[0.18em] text-3xl sm:text-4xl leading-none text-wordmark">
          {brand.wordmarkTop}
        </p>
        <p className="font-mono font-semibold uppercase tracking-[0.18em] text-3xl sm:text-4xl leading-none text-wordmark">
          {brand.wordmarkBottom}
        </p>
      </div>
    </div>
  );
}
