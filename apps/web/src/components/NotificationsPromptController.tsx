import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';

const SEEN_KEY = 'coach_notif_prompt_seen';

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    ('standalone' in navigator && (navigator as { standalone?: boolean }).standalone === true)
  );
}

function isPromptSeen(playerId: string): boolean {
  return localStorage.getItem(`${SEEN_KEY}_${playerId}`) === '1';
}

function markPromptSeen(playerId: string): void {
  localStorage.setItem(`${SEEN_KEY}_${playerId}`, '1');
}

/**
 * Requests browser notification permission once, after login, when:
 *   - Running as an installed PWA (standalone mode)
 *   - The player is authenticated
 *   - Push permission not yet granted or denied
 *   - The prompt hasn't been seen/dismissed before
 *
 * Phase 0: no modal — just triggers the browser's native permission dialog.
 * Phase 1: replace with a styled pre-permission modal.
 */
export function NotificationsPromptController() {
  const { player } = useAuth();
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    if (!player || asked) return;
    if (!isStandalone()) return;
    if (isPromptSeen(player.id)) return;
    if (typeof Notification === 'undefined' || Notification.permission !== 'default') return;

    const t = setTimeout(async () => {
      setAsked(true);
      markPromptSeen(player.id);
      await Notification.requestPermission();
    }, 3_000);

    return () => clearTimeout(t);
  }, [player?.id, asked]);

  return null;
}
