import { useState } from 'react';
import { Lock, Trophy, RefreshCw, BarChart2, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const STORAGE_KEY = 'sss_tour_seen';

export function markTourSeen(playerId?: string): void {
  const key = playerId ? `${STORAGE_KEY}_${playerId}` : STORAGE_KEY;
  try { localStorage.setItem(key, '1'); } catch { /* ignore */ }
}

export function isTourSeen(playerId?: string): boolean {
  try {
    // Check per-user key first; fall back to global key for backward compat
    if (playerId && localStorage.getItem(`${STORAGE_KEY}_${playerId}`) === '1') return true;
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch { return false; }
}

interface Slide {
  icon: React.ElementType;
  label: string;
  title: string;
  body: React.ReactNode;
}

const SLIDES: Slide[] = [
  {
    icon: Trophy,
    label: 'Scoring',
    title: 'How scoring stacks',
    body: (
      <>
        Correct result earns <strong className="text-text-primary">3 pts</strong>, correct goals
        total adds <strong className="text-text-primary">2 pts</strong>, and the exact score is worth{' '}
        <strong className="text-text-primary">5 pts</strong> — up to{' '}
        <strong className="text-text-primary">10 per match</strong>. Predict 2–1 but it ends 1–2?
        {' '}You still bank <strong className="text-text-primary">2 pts</strong> for the right total
        goals — result + exact stack on top. Full worked examples live on{' '}
        <strong className="text-text-primary">/about</strong>.
      </>
    ),
  },
  {
    icon: Lock,
    label: 'Deadlines',
    title: 'Predict before kickoff',
    body: (
      <>
        Predictions <strong className="text-text-primary">lock at each match's kickoff</strong>{' '}
        — there's no single tournament deadline. Miss the whistle and you score zero. A banner
        countdown warns you when time is running short.
      </>
    ),
  },
  {
    icon: RefreshCw,
    label: 'Knockout',
    title: 'Knockout opens round-by-round',
    body: (
      <>
        You don't fill in a full bracket upfront. Knockout winner picks{' '}
        <strong className="text-text-primary">unlock each round</strong> once the qualifying teams are
        confirmed — so you always predict with real information.
      </>
    ),
  },
  {
    icon: BarChart2,
    label: 'Leagues',
    title: 'Leaderboard & leagues',
    body: (
      <>
        Your main league table is under <strong className="text-text-primary">Leagues</strong> in the
        bottom nav. You can join multiple leagues and check head-to-head comparisons, round-by-round
        history, and how each match affected the standings.
      </>
    ),
  },
];

interface Props {
  onClose: () => void;
}

export function IntroTour({ onClose }: Props) {
  const [slide, setSlide] = useState(0);
  const isLast = slide === SLIDES.length - 1;

  function handleNext() {
    if (isLast) {
      markTourSeen();
      onClose();
    } else {
      setSlide((s) => s + 1);
    }
  }

  function handleSkip() {
    markTourSeen();
    onClose();
  }

  function handleBack() {
    setSlide((s) => Math.max(0, s - 1));
  }

  const { icon: Icon, title, body, label } = SLIDES[slide];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Quick intro tour"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-4"
    >
      <div className="w-full max-w-sm rounded-2xl bg-surface border border-border shadow-2xl overflow-hidden animate-in slide-in-from-bottom-4 sm:slide-in-from-bottom-0 sm:zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <p className="font-mono text-[10px] tracking-[0.25em] uppercase text-primary">
            {label}
          </p>
          <button
            onClick={handleSkip}
            aria-label="Skip tour"
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors focus-visible:outline-none focus-visible:shadow-glow"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>

        {/* Content */}
        <div className="px-5 pb-2 min-h-[180px]">
          <div className="flex items-start gap-3 mb-3">
            <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
              <Icon className="h-5 w-5 text-primary" aria-hidden />
            </div>
            <h2 className="text-base font-semibold text-text-primary font-sans pt-2">{title}</h2>
          </div>
          <p className="text-sm font-sans text-text-secondary leading-relaxed">{body}</p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 flex items-center justify-between gap-4">
          {/* Dot indicators */}
          <div className="flex gap-1.5" aria-label={`Slide ${slide + 1} of ${SLIDES.length}`}>
            {SLIDES.map((_, i) => (
              <span
                key={i}
                className={cn(
                  'h-1.5 rounded-full transition-all duration-200',
                  i === slide ? 'w-4 bg-primary' : 'w-1.5 bg-border',
                )}
              />
            ))}
          </div>

          <div className="flex items-center gap-3">
            {slide > 0 && (
              <Button size="sm" variant="ghost" onClick={handleBack} className="gap-1.5">
                <ChevronLeft className="h-4 w-4" aria-hidden />
                Back
              </Button>
            )}
            {!isLast && (
              <button
                onClick={handleSkip}
                className="text-sm font-sans text-text-muted hover:text-text-primary transition-colors"
              >
                Skip
              </button>
            )}
            <Button size="sm" onClick={handleNext} className="gap-1.5">
              {isLast ? 'Get started' : (
                <>Next <ChevronRight className="h-4 w-4" aria-hidden /></>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
