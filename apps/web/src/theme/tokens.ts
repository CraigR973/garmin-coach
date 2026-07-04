/**
 * Single source of truth for visual design tokens — CheckMark identity.
 * CSS variables in `index.css` mirror these values, Tailwind utilities
 * resolve to `var(--*)` references, and JS consumers (sonner toasts,
 * framer-motion variants, inline gradients) import these constants directly.
 */

export const colors = {
  // Surface tiers (deep teal-graphite — harmonizes with the CheckMark icon tile).
  // Re-spaced in Batch 52 into a clear value ramp so cards separate; mirrors the
  // dark palette in index.css (`:root, html.dark`).
  bg: '#0A1314',
  surface: '#152628',
  surfaceElevated: '#1F383A',
  surfaceOverlay: '#294648',
  border: '#2E4C4E',
  borderStrong: '#3D5F61',

  // Control fill — raised well for inputs/selects/textareas (Batch 52).
  control: '#223C3E',
  controlBorder: '#436769',

  // Text (secondary/muted lifted for WCAG AA on the re-spaced surfaces)
  textPrimary: '#F0F4FF',
  textSecondary: '#A6B4C4',
  textMuted: '#98A2B4',
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
  surface: 'linear-gradient(180deg, #152628 0%, #0A1314 100%)',
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

// Mirrors the dark `--shadow-*` set in index.css (Batch 52: softer elevation,
// stronger focus ring). `glow`/`glowAccent` now match the emerald/brass CSS vars
// (they previously drifted to a stale teal/gold that no JS consumer wanted).
export const shadow = {
  sm: '0 1px 2px 0 rgba(0, 0, 0, 0.30)',
  md: '0 4px 16px -4px rgba(0, 0, 0, 0.44)',
  lg: '0 16px 48px -12px rgba(0, 0, 0, 0.55)',
  sheet: '0 -8px 32px -6px rgba(0, 0, 0, 0.55)',
  glow: '0 0 0 3px rgba(16, 185, 129, 0.35)',
  glowAccent: '0 0 0 3px rgba(200, 148, 60, 0.30)',
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
  full: 'CheckMark',
  short: 'CheckMark',
  wordmarkTop: 'Check',
  wordmarkBottom: 'Mark',
  tagline: 'Your daily coaching brief.',
  taglineSub: 'Powered by your Garmin data.',
} as const;
