import { Toaster } from 'sonner';
import { useTheme } from '@/contexts/ThemeContext';

/**
 * App-wide toast host (Batch 137). Config lives here rather than inline in App
 * so it can follow the in-app theme toggle and the token palette:
 *
 *  - bottom-center, offset clear of the mobile tab bar (was bottom-right, which
 *    floated toasts into the thumb / tab-bar zone on phones);
 *  - `theme` tracks the resolved app theme, not the OS, so toasts match the
 *    class-based light/dark toggle;
 *  - colours come from the design tokens (surface-elevated fill, a left accent
 *    bar per type) instead of sonner's saturated `richColors` palette.
 */
export function AppToaster() {
  const { resolved } = useTheme();
  return (
    <Toaster
      theme={resolved}
      position="bottom-center"
      offset="calc(var(--tabbar-height) + var(--safe-bottom) + 12px)"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'rounded-lg border border-border bg-surface-elevated text-text-primary shadow-lg',
          title: 'text-text-primary font-sans',
          description: 'text-text-secondary',
          actionButton: 'bg-primary text-on-primary',
          cancelButton: 'bg-surface-overlay text-text-secondary',
          closeButton: 'bg-surface-elevated border-border text-text-secondary',
          success: 'border-l-4 border-l-success',
          error: 'border-l-4 border-l-error',
          warning: 'border-l-4 border-l-warning',
          info: 'border-l-4 border-l-primary',
        },
      }}
    />
  );
}
