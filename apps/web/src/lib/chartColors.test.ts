import { renderHook } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { chartColors, useChartColors } from './chartColors';

// Batch 137 — charts pass literal hex to recharts SVG props (CSS var() doesn't
// resolve there), so the palette must swap with the resolved theme rather than
// freeze to the dark values.

describe('chartColors', () => {
  afterEach(() => window.localStorage.clear());

  it('light and dark palettes are genuinely different for grid/axis/line', () => {
    expect(chartColors.light.border).not.toBe(chartColors.dark.border);
    expect(chartColors.light.textMuted).not.toBe(chartColors.dark.textMuted);
    expect(chartColors.light.primary).not.toBe(chartColors.dark.primary);
    expect(chartColors.light.accent).not.toBe(chartColors.dark.accent);
    // Every key is a concrete hex, not a CSS var reference.
    for (const value of Object.values(chartColors.dark)) {
      expect(value).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('useChartColors follows the resolved app theme', () => {
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(ThemeProvider, null, children);

    window.localStorage.setItem('sss_theme', 'dark');
    const dark = renderHook(() => useChartColors(), { wrapper });
    expect(dark.result.current).toEqual(chartColors.dark);

    window.localStorage.setItem('sss_theme', 'light');
    const light = renderHook(() => useChartColors(), { wrapper });
    expect(light.result.current).toEqual(chartColors.light);
  });
});
