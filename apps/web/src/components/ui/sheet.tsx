import { type ReactNode } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Bottom sheet built on Radix Dialog with CSS-driven slide animations.
 *
 * Why no framer-motion: two prior attempts with framer animation orchestration
 * still left the overlay/panel "stuck open" after item taps on iOS Safari.
 * Radix handles mount/unmount, focus trap, body scroll lock, ESC, and
 * overlay-click dismissal natively, and `data-[state=open|closed]` with
 * tailwindcss-animate utilities gives a clean slide-up/down without manual
 * AnimatePresence orchestration.
 *
 * Drag-to-dismiss is intentionally dropped — the X button + overlay tap +
 * route-change auto-close in TabBar all do the job reliably.
 */
export function Sheet({ open, onClose, title, children, className }: SheetProps) {
  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className={cn(
            'fixed inset-0 z-sheet bg-black/60 backdrop-blur-sm',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0',
            'duration-200',
          )}
        />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className={cn(
            'fixed bottom-0 left-0 right-0 z-sheet',
            'bg-surface-elevated border-t border-border rounded-t-2xl shadow-sheet',
            'pb-safe',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom',
            'duration-300',
            className,
          )}
        >
          {/* Static drag handle (decorative — Radix close paths handle dismissal) */}
          <div className="pt-3 pb-1" aria-hidden>
            <div className="mx-auto h-1 w-10 rounded-full bg-border-strong" />
          </div>
          {title && (
            <div className="flex items-center justify-between px-5 pb-2 pt-1">
              <DialogPrimitive.Title className="text-base font-semibold text-text-primary font-sans tracking-tight">
                {title}
              </DialogPrimitive.Title>
              <DialogPrimitive.Close asChild>
                <button
                  type="button"
                  className="tap-target inline-flex items-center justify-center rounded-sm text-text-muted hover:text-text-primary focus-visible:outline-none focus-visible:shadow-glow press-down"
                  aria-label="Close"
                >
                  <X className="h-5 w-5" />
                </button>
              </DialogPrimitive.Close>
            </div>
          )}
          <div className="px-5 pb-5 max-h-[80vh] overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
