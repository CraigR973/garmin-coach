import { BookOpen, Sparkles, Target, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { markFirstRunLaunchpadSeen } from '@/lib/firstRunLaunchpad';

interface Props {
  onClose: () => void;
}

const ACTIONS = [
  {
    title: 'Join or create a league',
    description: 'Enter the code a mate sent you, or start your own league.',
    to: '/leagues',
    icon: Users,
  },
  {
    title: 'Read the full rules',
    description: 'See the worked examples, deadlines, and late-join details in full on /about.',
    to: '/about',
    icon: BookOpen,
  },
  {
    title: 'Set your Specials',
    description: 'Set and update your six tournament picks any time until the opening match kicks off.',
    to: '/predictions/specials',
    icon: Sparkles,
  },
  {
    title: 'Make your first pick',
    description: 'Your first match prediction can also be made any time before the opening kickoff.',
    to: '/predictions',
    icon: Target,
  },
] as const;

export function FirstRunLaunchpad({ onClose }: Props) {
  const navigate = useNavigate();

  function handleExit() {
    markFirstRunLaunchpadSeen();
    onClose();
  }

  function handleNavigate(to: string) {
    markFirstRunLaunchpadSeen();
    onClose();
    navigate(to);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="First-run checklist launchpad"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center"
    >
      <div className="w-full max-w-md space-y-5 overflow-hidden rounded-2xl border border-border bg-surface p-6 shadow-2xl animate-in slide-in-from-bottom-4 duration-200 sm:slide-in-from-bottom-0 sm:zoom-in-95">
        <div className="space-y-2 text-center">
          <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-primary">
            Get started
          </p>
          <h2 className="text-lg font-semibold text-text-primary font-sans">
            Welcome to Calcio
          </h2>
          <p className="text-sm font-sans leading-relaxed text-text-secondary">
            A World Cup 2026 prediction game — you make one set of picks and they count across every
            league you join. Start by getting into a league below.
          </p>
        </div>

        <div className="space-y-3">
          {ACTIONS.map(({ title, description, to, icon: Icon }) => (
            <button
              key={to}
              type="button"
              onClick={() => handleNavigate(to)}
              className="flex w-full items-start gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 text-left transition-colors hover:bg-surface-overlay focus-visible:outline-none focus-visible:shadow-glow"
            >
              <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10">
                <Icon className="h-5 w-5 text-primary" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold font-sans text-text-primary">{title}</span>
                <span className="mt-1 block text-sm font-sans leading-relaxed text-text-secondary">
                  {description}
                </span>
              </span>
            </button>
          ))}
        </div>

        <div className="flex justify-end">
          <Button variant="ghost" onClick={handleExit}>
            Skip for now / Go to app
          </Button>
        </div>
      </div>
    </div>
  );
}
