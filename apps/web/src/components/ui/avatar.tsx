import { useState, useEffect, type HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  name: string;
  size?: 'sm' | 'md' | 'lg';
  /** Optional photo URL. Falls back to initials when null/undefined or on load error. */
  src?: string | null;
}

const SIZE: Record<NonNullable<AvatarProps['size']>, string> = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-14 w-14 text-lg',
};

/** Returns 1–2 initial letters from a display name. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Deterministic surface tint per name so avatars stay visually distinct.
 * Uses a small hash on the name to pick from a curated palette of muted
 * dark-mode-safe backgrounds.
 *
 * Tints are built with `color-mix` rather than Tailwind's `/opacity` modifier:
 * the brand colours are defined as raw `var(--x)` hex tokens, so `bg-silver/15`
 * et al. emit invalid CSS and fall back to transparent (the badge had no
 * background at all). `color-mix` works on the hex vars directly and stays
 * theme-aware; text uses `text-[var(--x)]` to avoid the `.text-steele` gradient
 * utility hijacking the background.
 */
const PALETTE = [
  'bg-[color-mix(in_srgb,var(--primary)_15%,transparent)] text-[var(--primary)]',
  'bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]',
  'bg-[color-mix(in_srgb,var(--steele-dark)_35%,transparent)] text-[var(--steele)]',
  'bg-[color-mix(in_srgb,var(--gold)_15%,transparent)] text-[var(--gold)]',
  'bg-[color-mix(in_srgb,var(--silver)_15%,transparent)] text-[var(--silver)]',
  'bg-[color-mix(in_srgb,var(--bronze)_15%,transparent)] text-[var(--bronze)]',
];

function tintFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length]!;
}

export function Avatar({ name, size = 'md', src, className, ...props }: AvatarProps) {
  const [imgError, setImgError] = useState(false);
  useEffect(() => { setImgError(false); }, [src]);
  const showPhoto = !!src && !imgError;

  return (
    <div
      className={cn(
        'inline-flex items-center justify-center rounded-full select-none overflow-hidden',
        SIZE[size],
        !showPhoto && cn('font-sans font-semibold', tintFor(name)),
        className,
      )}
      aria-hidden
      {...props}
    >
      {showPhoto ? (
        <img
          src={src}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        initials(name)
      )}
    </div>
  );
}
