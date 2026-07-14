import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, BellOff, Download, Send, Sun, Moon, Monitor, KeyRound, Volume2 } from 'lucide-react';
import { PinInput } from '../components/PinInput';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { usePushSubscription } from '../hooks/usePushSubscription';
import { useInstallPrompt } from '../hooks/useInstallPrompt';
import { useDailyLoop } from '../hooks/useDailyLoop';
import { useTheme } from '../contexts/ThemeContext';
import { cn } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { Toggle } from '../components/ui/toggle';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ChangePinBody {
  current_pin: string;
  new_pin: string;
}

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

/** Explicit opt-in for the hosted/neural read-aloud voice (Batch 116). Off by
 *  default — the brief only ever reads aloud on-device (Batch 111, DECISIONS
 *  #179 / #184) unless this is switched on, which sends the brief's text to
 *  OpenAI's TTS API for a more natural voice. */
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
            Reads the brief aloud in a more natural voice via OpenAI. This sends the brief&apos;s text off-device;
            off by default, the brief reads aloud using your device&apos;s own voice instead.
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

// ── Change PIN section ────────────────────────────────────────────────────────

function ChangePinSection() {
  const [currentPin, setCurrentPin] = useState('');
  const [newPin, setNewPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');

  const mutation = useMutation({
    mutationFn: (body: ChangePinBody) =>
      apiFetch<void>('/api/v1/auth/me/pin', { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: () => {
      toast.success('PIN changed');
      setCurrentPin('');
      setNewPin('');
      setConfirmPin('');
    },
    onError: (err) => toast.error(String(err)),
  });

  const canSubmit =
    currentPin.length === 4 &&
    newPin.length === 4 &&
    confirmPin.length === 4 &&
    newPin === confirmPin &&
    !mutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    mutation.mutate({ current_pin: currentPin, new_pin: newPin });
  }

  return (
    <section aria-labelledby="pin-heading" className="space-y-3">
      <h2 id="pin-heading" className="text-sm font-semibold text-text-secondary uppercase tracking-wide font-sans">
        Change PIN
      </h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label className="text-xs text-text-secondary font-sans">Current PIN</label>
          <PinInput value={currentPin} onChange={setCurrentPin} autoComplete="current-password" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-text-secondary font-sans">New PIN</label>
          <PinInput value={newPin} onChange={setNewPin} autoComplete="new-password" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-text-secondary font-sans">Confirm new PIN</label>
          <PinInput value={confirmPin} onChange={setConfirmPin} autoComplete="new-password" />
          {confirmPin.length === 4 && newPin !== confirmPin && (
            <p className="text-xs text-error font-sans">PINs don't match</p>
          )}
        </div>
        <button
          type="submit"
          disabled={!canSubmit}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-primary text-on-primary text-sm font-sans font-medium disabled:opacity-50 press-down"
        >
          <KeyRound className="h-4 w-4" aria-hidden />
          {mutation.isPending ? 'Changing…' : 'Change PIN'}
        </button>
      </form>
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
      <ChangePinSection />
    </div>
  );
}
