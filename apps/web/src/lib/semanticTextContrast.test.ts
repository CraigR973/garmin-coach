import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(resolve(here, '../index.css'), 'utf8');

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '');
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ];
}

function channel(value: number): number {
  const normal = value / 255;
  return normal <= 0.03928 ? normal / 12.92 : ((normal + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(foreground: string, background: string): number {
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

function token(scope: 'dark' | 'light', name: string): string {
  const pattern =
    scope === 'dark'
      ? /:root,\s*html\.dark\s*\{(?<body>[\s\S]*?)\n\s*\}/
      : /html\.light\s*\{(?<body>[\s\S]*?)\n\s*\}/;
  const body = css.match(pattern)?.groups?.body;
  if (!body) throw new Error(`Missing ${scope} token scope`);
  const value = body.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`))?.[1];
  if (!value) throw new Error(`Missing token ${name}`);
  return value;
}

describe('semantic text tokens', () => {
  it('keeps foreground semantic tokens AA-readable on surface in both themes', () => {
    const names = [
      'primary-text',
      'accent-text',
      'success-text',
      'warning-text',
      'error-text',
      'live-text',
      'gold-text',
      'silver-text',
      'bronze-text',
    ];

    for (const scope of ['dark', 'light'] as const) {
      const surface = token(scope, 'surface');
      for (const name of names) {
        expect(contrast(token(scope, name), surface), `${scope} ${name}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
