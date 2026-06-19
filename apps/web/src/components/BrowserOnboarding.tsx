import { Share, Plus } from 'lucide-react';
import { Brand } from '@/components/Brand';
import { Button } from '@/components/ui/button';
import { brand } from '@/theme/tokens';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';

/**
 * Full-page onboarding screen shown to mobile browser users who haven't
 * installed the app. Used by both InstallPromptController (all routes) and
 * JoinPage (/join/:token). No joining happens here — everything is in the app.
 */
export function BrowserOnboarding() {
  const { isIos, isIosSafari, canInstall, prompt: triggerInstall } = useInstallPrompt();

  const isIosChrome = isIos && !isIosSafari;

  const hasInstallStep = canInstall || isIos;

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
          <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5">
            <p className="text-sm font-sans font-semibold text-text-primary leading-snug">
              Predict once — compete in as many leagues as you like
            </p>
            <p className="text-xs font-sans text-text-secondary leading-relaxed mt-1">
              Like fantasy football, one set of picks counts across every league you join simultaneously.
            </p>
          </div>
          <p className="text-sm font-sans text-text-secondary leading-relaxed">
            Calcio is a multi-league World Cup 2026 prediction app.
            Pick scores match by match as the tournament unfolds — no bracket to fill in
            upfront, just predict each game before kick-off.
          </p>
          <p className="text-sm font-sans text-text-secondary leading-relaxed">
            Built for the World Cup from the ground up, Calcio keeps league play,
            match picks, and standings in one place.
          </p>
        </div>

        {/* New to the app */}
        <div className="space-y-4">
          <p className="text-xs font-mono uppercase tracking-widest text-text-muted">New to the app?</p>

          {/* Android — native install prompt */}
          {canInstall && (
            <Button variant="accent" className="w-full gap-2" onClick={triggerInstall}>
              <Plus className="h-4 w-4" aria-hidden />
              Add to home screen
            </Button>
          )}

          {/* Safari on iOS — exact steps */}
          {isIosSafari && (
            <div className="rounded-lg border border-border bg-surface/60 px-4 py-4 space-y-3">
              <p className="text-sm font-sans font-semibold text-text-primary">
                Install from Safari
              </p>
              <ol className="space-y-2">
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                  <span>Tap <strong className="text-text-primary">•••</strong> in the bottom toolbar</span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
                  <span>Tap <strong className="text-text-primary">Share</strong>{' '}
                    <Share className="inline h-3.5 w-3.5 text-[#007AFF] align-text-bottom" aria-hidden />
                  </span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
                  <span>Tap <strong className="text-text-primary">View More</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">4.</span>
                  <span>Tap <strong className="text-text-primary">Add to Home Screen</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">5.</span>
                  <span>Tap <strong className="text-text-primary">Add</strong> in the top-right corner</span>
                </li>
              </ol>
            </div>
          )}

          {/* Chrome on iOS — exact steps */}
          {isIosChrome && (
            <div className="rounded-lg border border-border bg-surface/60 px-4 py-4 space-y-3">
              <p className="text-sm font-sans font-semibold text-text-primary">
                Install from Chrome
              </p>
              <ol className="space-y-2">
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                  <span>Tap the <strong className="text-text-primary">Share</strong> button{' '}
                    <Share className="inline h-3.5 w-3.5 text-[#007AFF] align-text-bottom" aria-hidden />{' '}
                    in the address bar at the top
                  </span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
                  <span>Tap <strong className="text-text-primary">View More</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
                  <span>Tap <strong className="text-text-primary">Add to Home Screen</strong></span>
                </li>
                <li className="flex gap-2.5 text-sm font-sans text-text-secondary">
                  <span className="shrink-0 font-mono text-primary font-semibold">4.</span>
                  <span>Tap <strong className="text-text-primary">Add</strong> in the top-right corner</span>
                </li>
              </ol>
            </div>
          )}

          {/* Join steps — follow on from install */}
          <ol className="space-y-3">
            {hasInstallStep && (
              <li className="flex gap-3 text-sm font-sans text-text-secondary">
                <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                <span>
                  {canInstall ? 'Tap the button above to install, then open the app from your home screen' : 'Follow the install steps above, then open the app from your home screen'}
                </span>
              </li>
            )}
            {!hasInstallStep && (
              <li className="flex gap-3 text-sm font-sans text-text-secondary">
                <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
                <span>Open the app from your home screen</span>
              </li>
            )}
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
              <span>
                If you are new, tap <strong className="text-text-primary">Create account</strong>
                and finish signup
              </span>
            </li>
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
              <span>
                Tap <strong className="text-text-primary">Leagues → Join by code</strong> and
                enter the join code you were sent
              </span>
            </li>
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">4.</span>
              <span>
                Before the tournament starts, go to{' '}
                <strong className="text-text-primary">Predict → Specials</strong> to lock in
                your tournament award picks
              </span>
            </li>
          </ol>
        </div>

        {/* Already have the app */}
        <div className="space-y-4">
          <p className="text-xs font-mono uppercase tracking-widest text-text-muted">Already have the app?</p>
          <ol className="space-y-3">
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">1.</span>
              <span>Open it from your home screen</span>
            </li>
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">2.</span>
              <span>If you are new, tap <strong className="text-text-primary">Create account</strong></span>
            </li>
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">3.</span>
              <span>Tap <strong className="text-text-primary">Leagues → Join by code</strong></span>
            </li>
            <li className="flex gap-3 text-sm font-sans text-text-secondary">
              <span className="shrink-0 font-mono text-primary font-semibold">4.</span>
              <span>Enter the join code you were sent</span>
            </li>
          </ol>
        </div>

      </div>
    </div>
  );
}
