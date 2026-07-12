import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { isPushNavigationMessage, normalizePushNavigationUrl } from '../lib/pushNavigation';

export function PushNavigationController() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;

    const onMessage = (event: MessageEvent<unknown>) => {
      if (!isPushNavigationMessage(event.data)) return;
      navigate(normalizePushNavigationUrl(event.data.url, window.location.origin));
    };

    navigator.serviceWorker.addEventListener('message', onMessage as EventListener);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage as EventListener);
  }, [navigate]);

  return null;
}
