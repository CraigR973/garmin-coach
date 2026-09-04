import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

/**
 * Batch 254 (UX241-12/13). The app is read every morning by a 61-year-old, and it
 * held **26** hard-coded `text-[10px]` / `text-[11px]` utilities — literal pixel
 * values that ignore the reader's text-size setting entirely. Body text is
 * `text-sm` and rem-based, so raising the phone's text size grew the body and left
 * these behind: the gap widened rather than closed. One of them was the date
 * eyebrow on every page, and another was every tab label in the app.
 *
 * A source guard rather than a render assertion, because the property is "no
 * component reintroduces one", which no single rendered tree can show.
 */
const SRC = dirname(dirname(fileURLToPath(import.meta.url)));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : [];
  });
}

describe('type scale', () => {
  const files = sourceFiles(SRC);

  it('finds the components it is guarding', () => {
    expect(files.length).toBeGreaterThan(50);
  });

  it('has no hard-coded font size below the rem scale', () => {
    const offenders = files
      .map((file) => [file, readFileSync(file, 'utf8')] as const)
      .filter(([, source]) => /text-\[\d+px\]/.test(source))
      .map(([file]) => file.replace(`${SRC}/`, ''));

    expect(offenders).toEqual([]);
  });

  it('keeps the correction affordance above the 44 px floor', () => {
    // The "Change" link in the verdict hero measured 49 x 20 px — the last
    // control under the app's own floor, inside its highest-traffic card, and it
    // is reached precisely when he has mis-tapped something already.
    const hero = readFileSync(join(SRC, 'components/VerdictHero.tsx'), 'utf8');
    const link = hero.slice(hero.indexOf('recap.ctaLabel && recap.ctaTo'));
    expect(link).toContain('tap-target');
  });
});
