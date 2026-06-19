/**
 * Single source of truth for visual design tokens — "Calcio" identity.
 * CSS variables in `index.css` mirror these values, Tailwind utilities
 * resolve to `var(--*)` references, and JS consumers (sonner toasts,
 * framer-motion variants, inline gradients) import these constants directly.
 */

export const colors = {
  // Surface tiers (cool graphite, slightly warmer than pure navy)
  bg: '#0B0E13',
  surface: '#131720',
  surfaceElevated: '#1B2030',
  surfaceOverlay: '#242938',
  border: '#2A3142',
  borderStrong: '#3A4258',

  // Text
  textPrimary: '#F0F4FF',
  textSecondary: '#94A3B8',
  textMuted: '#7B859B',
  textInverse: '#0B0E13',

  // Brand — refined emerald "go", deeper brass accent, neutral silver Steele
  primary: '#10B981',
  primaryDark: '#059669',
  primaryGlow: 'rgba(16, 185, 129, 0.35)',

  accent: '#C8943C',
  accentDark: '#A77C2A',
  accentGlow: 'rgba(200, 148, 60, 0.35)',

  steele: '#E8EBF0',
  steeleMid: '#B0B8C4',
  steeleDark: '#7A828F',

  // Semantic
  success: '#10B981',
  warning: '#F59E0B',
  error: '#EF4444',
  live: '#EF4444',
  locked: '#7B859B',

  // Rank medals
  gold: '#E5C46B',
  silver: '#B8C0CC',
  bronze: '#C28B5C',
} as const;

export const gradients = {
  steele: 'linear-gradient(180deg, #E8EBF0 0%, #B0B8C4 60%, #7A828F 100%)',
  steeleHorizontal: 'linear-gradient(90deg, #E8EBF0 0%, #B0B8C4 100%)',
  surface: 'linear-gradient(180deg, #131720 0%, #0B0E13 100%)',
} as const;

export const radius = {
  xs: '6px',
  sm: '10px',
  md: '14px',
  lg: '18px',
  xl: '22px',
  '2xl': '28px',
  full: '9999px',
} as const;

export const shadow = {
  sm: '0 1px 2px 0 rgba(0, 0, 0, 0.4)',
  md: '0 4px 16px -2px rgba(0, 0, 0, 0.5)',
  lg: '0 12px 40px -8px rgba(0, 0, 0, 0.6)',
  sheet: '0 -8px 32px -4px rgba(0, 0, 0, 0.6)',
  glow: '0 0 0 3px rgba(20, 184, 166, 0.25)',
  glowAccent: '0 0 0 3px rgba(212, 162, 74, 0.25)',
} as const;

export const font = {
  display: '"Outfit", system-ui, sans-serif',
  sans: '"Outfit", system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',
} as const;

export const motion = {
  duration: {
    fast: 0.15,
    base: 0.22,
    page: 0.28,
    sheet: 0.32,
  },
  ease: {
    out: [0.2, 0, 0, 1] as [number, number, number, number],
    inOut: [0.42, 0, 0.58, 1] as [number, number, number, number],
  },
  spring: { type: 'spring', stiffness: 320, damping: 30 } as const,
} as const;

export const z = {
  base: 0,
  tabBar: 40,
  header: 50,
  banner: 55,
  sheet: 60,
  modal: 70,
  toast: 80,
} as const;

export const brand = {
  full: 'Calcio',
  short: 'Calcio',
  wordmarkTop: 'Calcio',
  wordmarkBottom: '',
  tagline: 'Predict once, compete everywhere.',
  taglineSub: 'Scotland qualify once every 28 years — best make it count.',
} as const;
