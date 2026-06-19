import { useCallback, useEffect, useState } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export interface InstallPromptState {
  /** Running in standalone PWA mode — gate should not show. */
  isInstalled: boolean;
  /**
   * True immediately after the user accepts the Android install prompt —
   * the app is installed but they are still in the browser tab. Use this to
   * show a "now open from your home screen" message instead of revealing the
   * full app in the browser.
   */
  justInstalled: boolean;
  /** iOS device (any browser). */
  isIos: boolean;
  /** iOS Safari specifically — the only iOS browser that can install PWAs natively. */
  isIosSafari: boolean;
  /** Android device. */
  isAndroid: boolean;
  /** Mobile platform we want to gate (iOS or Android). */
  isMobile: boolean;
  /** A deferred native install prompt is ready (Android/Chrome/Edge/Samsung). */
  canInstall: boolean;
  /** Trigger the native Android install prompt. Must be called from a user gesture. */
  prompt: () => Promise<void>;
}

export function detectStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    ('standalone' in navigator && (navigator as { standalone?: boolean }).standalone === true)
  );
}

export function useInstallPrompt(): InstallPromptState {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [isInstalled, setIsInstalled] = useState(detectStandalone);
  const [justInstalled, setJustInstalled] = useState(false);

  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
  const isIos = /iphone|ipad|ipod/i.test(ua);
  const isIosSafari = isIos && /safari/i.test(ua) && !/criOS|fxiOS/i.test(ua);
  const isAndroid = /android/i.test(ua);
  const isMobile = isIos || isAndroid;

  useEffect(() => {
    const handleBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };
    const handleAppInstalled = () => {
      setIsInstalled(true);
      setJustInstalled(true);
      setDeferredPrompt(null);
    };
    window.addEventListener('beforeinstallprompt', handleBeforeInstall);
    window.addEventListener('appinstalled', handleAppInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  const prompt = useCallback(async () => {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    setDeferredPrompt(null);
    if (outcome === 'accepted') {
      setIsInstalled(true);
      setJustInstalled(true);
    }
  }, [deferredPrompt]);

  return {
    isInstalled,
    justInstalled,
    isIos,
    isIosSafari,
    isAndroid,
    isMobile,
    canInstall: !isInstalled && deferredPrompt !== null,
    prompt,
  };
}
