import type { ReactNode } from 'react';

/**
 * A read-only label/value row inside a `<dl>`, shared (Batch 136) by the
 * workout and activity detail sheets so both render metadata identically.
 */
export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-sm text-text-secondary">{label}</dt>
      <dd className="text-right text-sm font-medium text-text-primary">{children}</dd>
    </div>
  );
}
