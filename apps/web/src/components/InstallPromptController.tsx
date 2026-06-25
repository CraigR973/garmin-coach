import { Home } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';
import { BrowserOnboarding } from './BrowserOnboarding';
import { Brand } from './Brand';

// Routes that manage their own onboarding experience.
const SELF_MANAGED: string[] = [];

/**
 * Shown on Android immediately after install while the user is still in the
 * browser tab. Replaces the BrowserOnboarding gate and tells them to open from
 * the home screen icon.
 */
function PostInstallScreen() {
  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-6 pt-safe pb-safe">
      <div className="w-full max-w-sm space-y-8 text-center">
        <Brand variant="splash" />
        <div className="rounded-xl border border-border bg-surface px-6 py-6 space-y-4">
          <div className="h-14 w-14 rounded-full bg-success/10 flex items-center justify-center mx-auto">
            <Home className="h-7 w-7 text-success" aria-hidden />
          </div>
          <h2 className="text-lg font-semibold text-text-primary font-sans">
            CheckMark is installed!
          </h2>
          <p className="text-sm font-sans text-text-secondary leading-relaxed">
            Tap the <strong className="text-text-primary">CheckMark icon</strong> on your home
            screen to open the app and get started.
          </p>
          <p className="text-xs font-sans text-text-muted leading-relaxed">
            You can close this browser tab.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Global mobile browser gate. For any uninstalled mobile visitor on a route
 * that doesn't manage its own onboarding, renders BrowserOnboarding as a
 * full-screen overlay — covering the underlying route and replacing the old
 * "Install required" blocker with the full app description + install steps.
 *
 * Already installed (standalone) → null
 * Desktop → null
 * Self-managed route → null (the route handles it)
 * justInstalled (Android, still in browser) → PostInstallScreen
 * Everything else on mobile browser → BrowserOnboarding
 */
export function InstallPromptController() {
  const { pathname } = useLocation();
  const { isInstalled, justInstalled, isMobile } = useInstallPrompt();

  if (!isMobile) return null;
  if (SELF_MANAGED.some((prefix) => pathname.startsWith(prefix))) return null;

  // Android: install just completed but user is still in the browser tab
  if (justInstalled) {
    return (
      <div className="fixed inset-0 z-[70] overflow-y-auto bg-bg">
        <PostInstallScreen />
      </div>
    );
  }

  if (isInstalled) return null;

  return (
    <div className="fixed inset-0 z-[70] overflow-y-auto bg-bg">
      <BrowserOnboarding />
    </div>
  );
}
