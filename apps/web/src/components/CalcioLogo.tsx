import { cn } from '@/lib/utils';
import { brand } from '@/theme/tokens';

export type CalcioLogoVariant = 'primary' | 'gold' | 'mark' | 'mono';

// Only the filled-tile icons are raster SVGs loaded by <img> — they back the
// installed-app / PWA icons where a solid background is wanted.
const LOGO_SRC: Record<'primary' | 'gold', string> = {
  primary: '/brand/calcio-icon-primary.svg',
  gold: '/brand/calcio-icon-gold.svg',
};

interface CalcioLogoProps {
  variant?: CalcioLogoVariant;
  size?: number;
  label?: string;
  decorative?: boolean;
  className?: string;
}

/**
 * Calcio target-ball mark.
 *
 * `mark` / `mono` render an inline SVG whose ring + spokes use `currentColor`
 * (defaulting to the themed steele tone via `text-[var(--steele)]`), so the
 * emblem tracks light/dark mode instead of sitting in a fixed navy tile. This
 * is what the in-app chrome (header, splash, lockup) uses. `mono` also drops
 * the gold accent. `primary` / `gold` keep the filled-tile raster for icons.
 */
export function CalcioLogo({
  variant = 'primary',
  size = 32,
  label = brand.full,
  decorative = false,
  className,
}: CalcioLogoProps) {
  if (variant === 'primary' || variant === 'gold') {
    return (
      <img
        src={LOGO_SRC[variant]}
        alt={decorative ? '' : label}
        aria-hidden={decorative ? true : undefined}
        width={size}
        height={size}
        className={cn('inline-block shrink-0 select-none', className)}
        draggable={false}
      />
    );
  }

  const accent = variant === 'mono' ? 'currentColor' : '#D4A44B';
  return (
    <svg
      viewBox="0 0 512 512"
      width={size}
      height={size}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative ? true : undefined}
      className={cn('inline-block shrink-0 select-none text-[var(--steele)]', className)}
    >
      <path d="M378.6 153.2a160 160 0 0 1 0 205.6l-68.9-57.8a70 70 0 0 0 0-90Z" fill={accent} />
      <circle cx="256" cy="256" r="160" fill="none" stroke="currentColor" strokeWidth="30" />
      <circle cx="256" cy="256" r="98" fill="none" stroke="currentColor" strokeWidth="18" />
      <path
        d="M256 217a39 39 0 1 0 0 78a39 39 0 1 0 0-78ZM256 240a16 16 0 1 1 0 32a16 16 0 1 1 0-32Z"
        fill="currentColor"
        fillRule="evenodd"
      />
      <path
        d="M176 142l46 78M336 142l-46 78M118 276h92M394 276h-92M176 370l46-78M336 370l-46-78"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="18"
      />
    </svg>
  );
}
