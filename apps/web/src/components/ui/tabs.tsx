import { type ReactNode, useId } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

export interface TabItem<T extends string = string> {
  value: T;
  label: ReactNode;
}

interface TabsProps<T extends string> {
  items: ReadonlyArray<TabItem<T>>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
  /** Segmented = pill-style on a surface (settings, filters). Default is underlined bottom-border style. */
  variant?: 'default' | 'segmented';
}

/**
 * Lightweight roving-tab control. The active indicator uses a shared
 * framer-motion layoutId so it slides between tabs instead of cutting.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
  variant = 'default',
}: TabsProps<T>) {
  const layoutId = useId();
  const isSegmented = variant === 'segmented';

  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex items-center font-sans',
        isSegmented
          ? 'rounded-md bg-surface p-1 gap-1 border border-border'
          : 'gap-1 border-b border-border',
        className,
      )}
    >
      {items.map((item) => {
        const isActive = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(item.value)}
            className={cn(
              'relative px-4 py-2 text-sm font-medium tracking-tight transition-colors focus-visible:outline-none focus-visible:shadow-glow press-down',
              isSegmented ? 'rounded-sm tap-target' : 'tap-target',
              isActive
                ? 'text-text-primary'
                : 'text-text-secondary hover:text-text-primary',
            )}
          >
            <span className="relative z-10">{item.label}</span>
            {isActive && (
              <motion.span
                layoutId={layoutId}
                className={cn(
                  'absolute inset-x-0',
                  isSegmented
                    ? 'inset-0 rounded-sm bg-surface-elevated -z-0'
                    : 'bottom-0 h-0.5 bg-primary',
                )}
                transition={{ type: 'spring', stiffness: 360, damping: 32 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
