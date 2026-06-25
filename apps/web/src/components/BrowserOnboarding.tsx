import { Share, Plus } from 'lucide-react';
import { Brand } from '@/components/Brand';
import { Button } from '@/components/ui/button';
import { brand } from '@/theme/tokens';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';

/**
 * Full-page onboarding screen shown to mobile browser users who haven't
 * installed the app. Tells them to install first, then sign in.
 */
export function BrowserOnboarding() {
  const { isIos, isIosSafari, canInstall, prompt: triggerInstall } = useInstallPrompt();

  const isIosChrome = isIos && !isIosSafari;

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-6 pt-safe pb-safe">
      <div className="w-full max-w-sm space-y-8">

        {/* Brand */}
        <div className="text-center space-y-3">
          <Brand variant="splash" />
          <p className="text-text-primary font-sans text-lg italic mt-6">
            {brand.tagline}
          </p>
        </div>

        {/* About */}
        <div className="rounded-xl border border-border bg-surface px-5 py-5 space-y-3">
          <p className="text-base font-sans font-semibold text-text-primary">About</p>
          <p className="text-sm font-sans text-text-secondary leading-relaxed">
            CheckMark is your private AI fitness and sleep coach. It pulls data from your
            Garmin watch and delivers a daily morning brief with training guidance tailored to you.
          </p>
        </div>

        {/* Install steps */}
        <div className="space-y-4">
          <p className="text-xs font-mono uppercase tracking-widest text-text-muted">Get started</p>

          {canInstall && (
            <Button variant="accent" className="w-full gap-2" onClick={triggerInstall}>
              <Plus className="h-4 w-4" aria-hidden />
              Add to home screen
            </Button>
          )}

          {isIosSafari && (
            <div className="rounded-lg border border-border bg-surface/60 px-4 py-4 space-y-3">
              <p className="text-sm font-sans font-semibold text-text-primary">Install from Safari</p>
              <ol className="space-y-2">
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                  <span>Tap <strong className="text-text-primary">Share</strong>{' '}
                    <Share className="inline h-3.5 w-3.5 text-[#007AFF] align-text-bottom" aria-hidden />
                  </span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
                  <span>Tap <strong className="text-text-primary">Add to Home Screen</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
                  <span>Tap <strong className="text-text-primary">Add</strong></span>
                </li>
              </ol>
            </div>
          )}

          {isIosChrome && (
            <div className="rounded-lg border border-border bg-surface/60 px-4 py-4 space-y-3">
              <p className="text-sm font-sans font-semibold text-text-primary">Install from Chrome</p>
              <ol className="space-y-2">
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                  <span>Tap <strong className="text-text-primary">Share</strong>{' '}
                    <Share className="inline h-3.5 w-3.5 text-[#007AFF] align-text-bottom" aria-hidden />{' '}
                    in the address bar
                  </span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
                  <span>Tap <strong className="text-text-primary">Add to Home Screen</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
                  <span>Tap <strong className="text-text-primary">Add</strong></span>
                </li>
              </ol>
            </div>
          )}

          <ol className="space-y-3">
            {(canInstall || isIos) && (
              <li className="flex gap-3 text-sm font-sans text-text-secondary">
                <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                <span>Install using the steps above, then open from your home screen</span>
              </li>
            )}
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">{canInstall || isIos ? '2.' : '1.'}</span>
              <span>Sign in with your name and PIN</span>
            </li>
          </ol>
        </div>

      </div>
    </div>
  );
}
