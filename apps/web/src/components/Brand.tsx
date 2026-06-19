import { cn } from '@/lib/utils';
import { brand } from '@/theme/tokens';
import { CalcioLogo, type CalcioLogoVariant } from '@/components/CalcioLogo';

interface BrandProps {
  variant?: 'splash' | 'compact' | 'mono' | 'lockup' | 'mark' | CalcioLogoVariant;
  size?: number;
  label?: string;
  decorative?: boolean;
  className?: string;
}

/**
 * "Calcio" wordmark.
 *
 * variants:
 *   splash  - vertical primary icon + wordmark
 *   lockup  - primary icon left + wordmark right
 *   compact - small header lockup
 *   mono    — short name in mono (misc)
 *   mark    - transparent target-ball mark
 *   primary/gold - icon-only brand variants
 */
export function Brand({
  variant = 'splash',
  size,
  label = brand.full,
  decorative = false,
  className,
}: BrandProps) {
  const logoSize = size ?? 32;

  if (variant === 'primary' || variant === 'gold') {
    return (
      <CalcioLogo
        variant={variant}
        size={logoSize}
        label={label}
        decorative={decorative}
        className={className}
      />
    );
  }

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
        <CalcioLogo variant="mark" size={size ?? 24} decorative />
        <span>CALCIO</span>
      </span>
    );
  }

  if (variant === 'mark') {
    return <CalcioLogo variant="mark" size={logoSize} label={label} decorative={decorative} className={className} />;
  }

  if (variant === 'lockup') {
    return (
      <div
        className={cn('flex items-center gap-4 select-none', className)}
        aria-hidden={decorative ? true : undefined}
        aria-label={decorative ? undefined : label}
      >
        <CalcioLogo variant="mark" size={64} decorative />
        <p className="font-mono font-semibold uppercase tracking-[0.18em] text-2xl sm:text-3xl leading-none text-wordmark">
          CALCIO
        </p>
      </div>
    );
  }

  // splash — vertical lockup: mark above the wordmark (login / signup / welcome)
  return (
    <div
      className={cn('flex flex-col items-center text-center select-none gap-4', className)}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : label}
    >
      <CalcioLogo variant="mark" size={72} decorative />
      <p className="font-mono font-semibold uppercase tracking-[0.18em] text-3xl sm:text-4xl leading-none text-wordmark">
        CALCIO
      </p>
    </div>
  );
}
