import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, BellOff, Download, Send, Sun, Moon, Monitor, Volume2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { usePushSubscription } from '../hooks/usePushSubscription';
import { useInstallPrompt } from '../hooks/useInstallPrompt';
import { useDailyLoop } from '../hooks/useDailyLoop';
import { useTheme } from '../contexts/ThemeContext';
import { cn } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { Toggle } from '../components/ui/toggle';

// ── Theme section ─────────────────────────────────────────────────────────────

function ThemeSection() {
  const { mode, setMode } = useTheme();
  const options = [
    { value: 'light', label: 'Light', Icon: Sun },
    { value: 'dark', label: 'Dark', Icon: Moon },
    { value: 'system', label: 'System', Icon: Monitor },
  ] as const;

  return (
    <section aria-labelledby="theme-heading" className="space-y-3">
      <h2 id="theme-heading" className="text-sm font-semibold text-text-secondary uppercase tracking-wide font-sans">
        Appearance
      </h2>
      <div className="flex gap-2">
        {options.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => setMode(value)}
            className={cn(
              'flex-1 flex flex-col items-center gap-1.5 py-3 rounded-lg border text-sm font-sans transition-colors press-down',
              mode === value
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-surface text-text-secondary hover:border-primary/50',
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

// ── Notifications section ─────────────────────────────────────────────────────

function NotificationsSection() {
  const { isSubscribed, isLoading, subscribe, unsubscribe } = usePushSubscription();
  const { canInstall, prompt: triggerInstall } = useInstallPrompt();

  const pushSupported = typeof Notification !== 'undefined';

  const testMutation = useMutation({
    mutationFn: () =>
      apiFetch<void>('/api/v1/push/test', { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: () => toast.success('Test notification sent'),
    onError: (err) => toast.error(String(err)),
  });

  if (!pushSupported) return null;

  return (
    <section aria-labelledby="notif-heading" className="space-y-3">
      <h2 id="notif-heading" className="text-sm font-semibold text-text-secondary uppercase tracking-wide font-sans">
        Notifications
      </h2>
      <div className="space-y-2">
        {canInstall && (
          <button
            type="button"
            onClick={() => void triggerInstall()}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-surface text-text-primary hover:bg-surface-elevated press-down"
          >
            <Download className="h-4 w-4 text-text-secondary" aria-hidden />
            <span className="text-sm font-sans">Install app for notifications</span>
          </button>
        )}
        {!isSubscribed ? (
          <button
            type="button"
            onClick={() => void subscribe()}
            disabled={isLoading}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-primary bg-primary/5 text-primary hover:bg-primary/10 press-down"
          >
            <Bell className="h-4 w-4" aria-hidden />
            <span className="text-sm font-sans">{isLoading ? 'Enabling…' : 'Enable push notifications'}</span>
          </button>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-success/30 bg-success/5 text-success">
              <Bell className="h-4 w-4" aria-hidden />
              <span className="text-sm font-sans">Push notifications enabled</span>
            </div>
            <button
              type="button"
              onClick={() => void testMutation.mutateAsync()}
              disabled={testMutation.isPending}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-surface text-text-primary hover:bg-surface-elevated press-down"
            >
              <Send className="h-4 w-4 text-text-secondary" aria-hidden />
              <span className="text-sm font-sans">Send test notification</span>
            </button>
            <button
              type="button"
              onClick={() => void unsubscribe()}
              disabled={isLoading}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-surface text-text-secondary hover:bg-surface-elevated press-down"
            >
              <BellOff className="h-4 w-4" aria-hidden />
              <span className="text-sm font-sans">Disable notifications</span>
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Voice section ─────────────────────────────────────────────────────────────

/** Explicit opt-in for the hosted/neural read-aloud voice (Batch 116, engine
 *  swapped to self-hosted Piper in DECISIONS #190). Off by default — the
 *  brief only ever reads aloud on-device (Batch 111, DECISIONS #179 / #184)
 *  unless this is switched on, which generates the audio on our own server
 *  for a more natural voice instead of the platform default. */
function VoiceSection() {
  const queryClient = useQueryClient();
  const { data } = useDailyLoop();
  const consentEnabled = data?.data.hostedTtsConsent ?? false;

  const consentMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      apiFetch('/api/v1/tts/consent', { method: 'PUT', body: JSON.stringify({ enabled }) }),
    onSuccess: async (_data, enabled) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      toast.success(enabled ? 'Hosted voice enabled' : 'Hosted voice disabled');
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Could not update the voice setting'),
  });

  return (
    <section aria-labelledby="voice-heading" className="space-y-3">
      <h2 id="voice-heading" className="text-sm font-semibold text-text-secondary uppercase tracking-wide font-sans">
        Voice
      </h2>
      <div className="flex items-start gap-3 px-4 py-3 rounded-lg border border-border bg-surface">
        <Volume2 className="h-4 w-4 mt-0.5 text-text-secondary shrink-0" aria-hidden />
        <div className="flex-1 space-y-1">
          <p className="text-sm font-sans text-text-primary">Natural hosted voice</p>
          <p className="text-xs text-text-secondary font-sans">
            Reads the brief aloud in a more natural voice, generated on our own server (no third
            party). Takes a little longer to start than the default; off by default, the brief
            reads aloud using your device&apos;s own voice instead.
          </p>
        </div>
        <Toggle
          checked={consentEnabled}
          onCheckedChange={(checked) => consentMutation.mutate(checked)}
          disabled={consentMutation.isPending}
          aria-label="Enable hosted read-aloud voice"
        />
      </div>
    </section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function SettingsPage() {
  return (
    <div className="space-y-8 max-w-lg">
      <PageHeader title="Settings" />
      <ThemeSection />
      <NotificationsSection />
      <VoiceSection />
    </div>
  );
}
