import { type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';
import { cn } from '@/lib/utils';

interface PageHeaderProps {
  title: ReactNode;
  /** Optional kicker / pre-title (e.g. "Round of 16"). */
  eyebrow?: ReactNode;
  /** When true, shows a back chevron (inline, left of title) that calls navigate(-1). */
  showBack?: boolean;
  /**
   * When set, renders a top-left back chip above the eyebrow row.
   * `to` navigates to a fixed path; omit to call navigate(-1).
   */
  back?: { to?: string; label?: string };
  /** Optional right-aligned action slot (forward actions only). */
  action?: ReactNode;
  className?: string;
  /** When true, the title may wrap to multiple lines instead of truncating. */
  wrapTitle?: boolean;
}

const backChipClass =
  'inline-flex items-center gap-1 mb-3 text-xs font-mono uppercase tracking-[0.2em] text-text-muted hover:text-text-primary press-down rounded-md focus-visible:outline-none focus-visible:shadow-glow';

export function PageHeader({ title, eyebrow, showBack, back, action, className, wrapTitle }: PageHeaderProps) {
  const navigate = useNavigate();

  return (
    <div className={cn('mb-5', className)}>
      {back && (
        back.to ? (
          <Link to={back.to} className={backChipClass}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
            {back.label ?? 'Back'}
          </Link>
        ) : (
          <button type="button" onClick={() => navigate(-1)} aria-label="Back" className={backChipClass}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
            {back.label ?? 'Back'}
          </button>
        )
      )}
      <div className="flex items-start gap-3">
        {showBack && (
          <button
            type="button"
            onClick={() => navigate(-1)}
            aria-label="Back"
            className="tap-target -ml-2 inline-flex items-center justify-center rounded-md text-text-secondary hover:text-text-primary press-down focus-visible:outline-none focus-visible:shadow-glow"
          >
            <ChevronLeft className="h-6 w-6" aria-hidden />
          </button>
        )}
        <div className="flex-1 min-w-0">
          {eyebrow && (
            <>
              <p className="font-mono text-[10px] tracking-[0.3em] uppercase text-text-muted mb-1.5">
                {eyebrow}
              </p>
              <div className="border-t border-accent/30 mb-2" aria-hidden />
            </>
          )}
          <h1
            className={cn(
              'text-2xl sm:text-3xl font-semibold text-text-primary tracking-tight font-sans leading-tight',
              wrapTitle ? 'break-words' : 'truncate',
            )}
          >
            {title}
          </h1>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  );
}
