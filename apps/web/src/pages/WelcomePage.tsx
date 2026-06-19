import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Brand } from '@/components/Brand';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { brand } from '@/theme/tokens';

function useDetectedPlatform(): 'ios' | 'android' | 'desktop' {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua)) return 'ios';
  if (/Android/.test(ua)) return 'android';
  return 'desktop';
}

function IOSInstructions() {
  return (
    <ol className="space-y-3 text-sm font-sans text-text-secondary">
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">1</span>
        <span>Tap the <strong className="text-text-primary">Share</strong> button at the bottom of Safari (the box with an arrow pointing up).</span>
      </li>
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">2</span>
        <span>Scroll down and tap <strong className="text-text-primary">Add to Home Screen</strong>.</span>
      </li>
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">3</span>
        <span>Tap <strong className="text-text-primary">Add</strong> in the top-right corner.</span>
      </li>
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">4</span>
        <span>Open the app from your home screen and use your join code or link to join a league.</span>
      </li>
    </ol>
  );
}

function AndroidInstructions() {
  return (
    <ol className="space-y-3 text-sm font-sans text-text-secondary">
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">1</span>
        <span>Tap the <strong className="text-text-primary">menu (⋮)</strong> in Chrome's top-right corner.</span>
      </li>
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">2</span>
        <span>Tap <strong className="text-text-primary">Add to Home screen</strong> and confirm.</span>
      </li>
      <li className="flex gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">3</span>
        <span>Open the app from your home screen and use your join code or link to join a league.</span>
      </li>
    </ol>
  );
}

function DesktopInstructions() {
  return (
    <p className="text-sm font-sans text-text-secondary">
      Open this page on your phone to install the app. On desktop, you can use the app directly in your browser — just{' '}
      <Link to="/login" className="text-primary underline">sign in</Link> or{' '}
      <Link to="/signup" className="text-primary underline">create an account</Link>.
    </p>
  );
}

export function WelcomePage() {
  const platform = useDetectedPlatform();
  const [copied, setCopied] = useState(false);
  const appUrl = window.location.origin;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(appUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm space-y-6">
        <div className="mb-8 flex flex-col items-center text-center">
          <Brand variant="splash" />
          <p className="mt-6 font-sans text-lg font-semibold text-text-primary">{brand.tagline}</p>
          <p className="mt-1 font-sans text-sm italic text-text-secondary">{brand.taglineSub}</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {platform === 'ios' && 'Install on iPhone / iPad'}
              {platform === 'android' && 'Install on Android'}
              {platform === 'desktop' && 'Get the app'}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {platform === 'ios' && <IOSInstructions />}
            {platform === 'android' && <AndroidInstructions />}
            {platform === 'desktop' && <DesktopInstructions />}
          </CardContent>
        </Card>

        {platform !== 'desktop' && (
          <Card>
            <CardContent className="pt-4 space-y-3">
              <p className="text-sm font-sans text-text-secondary">
                Already have the app?{' '}
                <Link to="/login" className="text-primary underline">Sign in</Link>
                {' or '}
                <Link to="/signup" className="text-primary underline">create an account</Link>.
              </p>
            </CardContent>
          </Card>
        )}

        <div className="text-center">
          <p className="text-xs text-text-muted font-sans mb-2">Share this page with friends</p>
          <Button variant="outline" size="sm" onClick={copyLink}>
            {copied ? 'Copied!' : 'Copy link'}
          </Button>
        </div>
      </div>
    </div>
  );
}
