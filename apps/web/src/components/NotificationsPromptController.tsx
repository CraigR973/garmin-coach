import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { isTourSeen } from './IntroTour';
import {
  NotificationsPromptModal,
  isNotifPromptSeen,
} from './NotificationsPromptModal';

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    ('standalone' in navigator && (navigator as { standalone?: boolean }).standalone === true)
  );
}

/**
 * Shows the notifications opt-in modal once, after login, when:
 *   - Running as an installed PWA (standalone mode)
 *   - The player is authenticated
 *   - Push permission not yet granted or denied
 *   - The prompt hasn't been seen/dismissed before
 *
 * Delays 3 s after mount so it doesn't fire mid-navigation on first load.
 */
export function NotificationsPromptController() {
  const { player } = useAuth();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!player) return;
    // Wait until first-run (the launchpad) is done so this can't stack on top of it.
    if (!isTourSeen(player.id)) return;
    if (!isStandalone()) return;
    if (isNotifPromptSeen(player.id)) return;
    if (typeof Notification !== 'undefined' && Notification.permission !== 'default') return;

    const t = setTimeout(() => setShow(true), 3_000);
    return () => clearTimeout(t);
  }, [player?.id]);

  if (!show) return null;

  return <NotificationsPromptModal playerId={player?.id} onClose={() => setShow(false)} />;
}
