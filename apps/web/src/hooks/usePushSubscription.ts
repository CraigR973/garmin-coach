import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

export type PushPermission = 'default' | 'granted' | 'denied';

interface PushSubscriptionState {
  permission: PushPermission;
  isSubscribed: boolean;
  isLoading: boolean;
  subscribe: () => Promise<void>;
  unsubscribe: () => Promise<void>;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  return new Uint8Array([...rawData].map((c) => c.charCodeAt(0))) as Uint8Array<ArrayBuffer>;
}

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined;

export function usePushSubscription(): PushSubscriptionState {
  const [permission, setPermission] = useState<PushPermission>(
    () => (typeof Notification !== 'undefined' ? Notification.permission : 'default') as PushPermission,
  );
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Check existing subscription on mount
  useEffect(() => {
    let cancelled = false;
    function check() {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        setIsLoading(false);
        return;
      }
      navigator.serviceWorker.ready
        .then((reg) => reg.pushManager.getSubscription())
        .then((sub) => {
          if (!cancelled) setIsSubscribed(sub !== null);
        })
        .catch(() => void 0)
        .finally(() => {
          if (!cancelled) setIsLoading(false);
        });
    }
    check();
    // Keep every hook instance (checklist, settings, prompt) in sync whenever the
    // subscription changes on any surface.
    window.addEventListener('push-sub-changed', check);
    return () => {
      cancelled = true;
      window.removeEventListener('push-sub-changed', check);
    };
  }, []);

  const subscribe = useCallback(async () => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    if (!VAPID_PUBLIC_KEY) {
      console.warn('VITE_VAPID_PUBLIC_KEY not set — push subscription skipped');
      return;
    }

    setIsLoading(true);
    try {
      const perm = await Notification.requestPermission();
      setPermission(perm as PushPermission);
      if (perm !== 'granted') return;

      const reg = await navigator.serviceWorker.ready;
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
      });

      const sub = subscription.toJSON();
      await apiFetch('/api/v1/push/subscribe', {
        method: 'POST',
        body: JSON.stringify({
          endpoint: sub.endpoint,
          keys: sub.keys,
          device_hint: navigator.userAgent.slice(0, 100),
        }),
      });
      setIsSubscribed(true);
      window.dispatchEvent(new Event('push-sub-changed'));
    } catch (err) {
      console.error('push subscription failed', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const unsubscribe = useCallback(async () => {
    if (!('serviceWorker' in navigator)) return;
    setIsLoading(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await apiFetch('/api/v1/push/unsubscribe', {
          method: 'DELETE',
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      }
      setIsSubscribed(false);
      window.dispatchEvent(new Event('push-sub-changed'));
    } catch (err) {
      console.error('push unsubscribe failed', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { permission, isSubscribed, isLoading, subscribe, unsubscribe };
}
