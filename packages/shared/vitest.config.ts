import { configDefaults, defineConfig } from 'vitest/config';

// Batch 341: Vitest 3 dropped `dist` from its default excludes, so a stale compiled
// copy of the tests (dist/schemas.test.js, build output git ignores) ran beside the
// sources. Keep testing the sources only, as Vitest 2 did.
export default defineConfig({
  test: {
    exclude: [...configDefaults.exclude, '**/dist/**'],
  },
});
