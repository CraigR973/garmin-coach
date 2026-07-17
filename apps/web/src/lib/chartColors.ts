import { useTheme } from '@/contexts/ThemeContext';
import { colors } from '@/theme/tokens';

/**
 * Literal-hex chart colours for recharts SVG props (Batch 137).
 *
 * CSS `var(--x)` does NOT resolve inside SVG stroke/fill *attributes*, so charts
 * can't lean on the token CSS vars the way the rest of the UI does — they need
 * concrete hex. The static `theme/tokens.ts` `colors` object mirrors only the
 * dark palette, which froze `<CartesianGrid>` / axes / lines to dark styling in
 * light mode (dark-teal grid on white). These two sets mirror the `:root`/dark
 * and `html.light` blocks in `index.css` so charts follow the active theme.
 */
export interface ChartColors {
  border: string;
  textMuted: string;
  primary: string;
  primaryDark: string;
  accent: string;
  steeleDark: string;
  warning: string;
  error: string;
  locked: string;
}

// Mirrors `:root, html.dark` in index.css (identical to the dark `colors` object).
const DARK: ChartColors = {
  border: colors.border,
  textMuted: colors.textMuted,
  primary: colors.primary,
  primaryDark: colors.primaryDark,
  accent: colors.accent,
  steeleDark: colors.steeleDark,
  warning: colors.warning,
  error: colors.error,
  locked: colors.locked,
};

// Mirrors `html.light` in index.css.
const LIGHT: ChartColors = {
  border: '#E5E8EB',
  textMuted: '#6B7280',
  primary: '#059669',
  primaryDark: '#047857',
  accent: '#A77C2A',
  steeleDark: '#9CA3AF',
  warning: '#D97706',
  error: '#DC2626',
  locked: '#9CA3AF',
};

export const chartColors: Record<'light' | 'dark', ChartColors> = { light: LIGHT, dark: DARK };

/** Chart colours for the resolved app theme (class-based, not OS). */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return chartColors[resolved];
}
