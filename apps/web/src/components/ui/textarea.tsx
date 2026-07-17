import * as React from 'react';
import { cn } from '@/lib/utils';
import { controlFieldClassName } from './input';

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Multi-line control field (Batch 52). Shares `controlFieldClassName` with Input
 * so textareas sit on the same raised `--control` fill with the same border and
 * focus ring — replacing the two ad-hoc `textareaClassName` copies that used the
 * dark-on-dark page background. Pass `className` for per-use sizing (min-height).
 */
const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      // text-base on mobile (16px) prevents iOS Safari's zoom-on-focus; falls
      // back to text-sm at sm+ — mirrors the Input primitive (Batch 137).
      className={cn(controlFieldClassName, 'min-h-[88px] px-3 py-3 text-base sm:text-sm', className)}
      ref={ref}
      {...props}
    />
  ),
);
Textarea.displayName = 'Textarea';

export { Textarea };
