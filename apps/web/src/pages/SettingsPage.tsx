import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, BellOff, Download, Send, Check, Sun, Moon, Monitor, Info, Camera, Trash2, Globe, KeyRound } from 'lucide-react';
import { PinInput } from '../components/PinInput';
import { toast } from 'sonner';
import { apiFetch } from '../lib/api';
import { usePushSubscription } from '../hooks/usePushSubscription';
import { useInstallPrompt } from '../hooks/useInstallPrompt';
import { Skeleton } from '../components/ui/skeleton';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { cn } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { Avatar } from '../components/ui/avatar';
import {
  ALLOWED_AVATAR_TYPES,
  MAX_AVATAR_BYTES,
  resizeAvatar,
  uploadAvatarImage,
} from '../lib/image';

// ── Types ─────────────────────────────────────────────────────────────────────

interface NotificationPreferences {
  deadline_warning: boolean;
  predict_reminder: boolean;
  pick_confirmation: boolean;
  match_locked: boolean;
  result_detected: boolean;
  leaderboard_shift: boolean;
  round_complete: boolean;
  match_postponed: boolean;
  special_results: boolean;
  global_mute: boolean;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Array<{ key: keyof NotificationPreferences; label: string }> = [
  { key: 'deadline_warning', label: 'Deadline warning (15 min before kickoff)' },
  { key: 'predict_reminder', label: 'Daily prediction reminder' },
  { key: 'pick_confirmation', label: 'Pick confirmation (opt-in)' },
  { key: 'match_locked', label: 'Predictions locked' },
  { key: 'result_detected', label: 'Match result posted' },
  { key: 'leaderboard_shift', label: 'Leaderboard rank change' },
  { key: 'round_complete', label: 'Round complete' },
  { key: 'match_postponed', label: 'Match postponed' },
  { key: 'special_results', label: 'Special prediction results' },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5">
      <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight mb-4">{title}</h2>
      {children}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center justify-between cursor-pointer py-2">
      <span className="text-sm font-sans text-text-primary">{label}</span>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
          checked ? 'bg-primary' : 'bg-border'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </button>
    </label>
  );
}

// ── Push notifications section ────────────────────────────────────────────────

function PushSection() {
  const { permission, isSubscribed, isLoading, subscribe, unsubscribe } = usePushSubscription();
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    setTesting(true);
    try {
      await apiFetch('/api/v1/push/test', { method: 'POST' });
      toast.success('Test notification sent — check your device');
    } catch {
      toast.error('Failed to send test notification');
    } finally {
      setTesting(false);
    }
  };

  const notSupported =
    typeof window !== 'undefined' &&
    (!('serviceWorker' in navigator) || !('PushManager' in window));

  if (notSupported) {
    return (
      <p className="text-sm text-text-muted font-sans">
        Push notifications are not supported in this browser.
      </p>
    );
  }

  if (permission === 'denied') {
    const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
    const isIos = /iPhone|iPad|iPod/.test(ua);
    const isChrome = /Chrome/.test(ua) && !/Edg|OPR/.test(ua);
    const hint = isIos
      ? 'Go to iOS Settings → Safari → Notifications and allow this site.'
      : isChrome
        ? 'Click the lock icon in the address bar, set Notifications to "Allow", then reload.'
        : 'Open your browser settings and allow notifications for this site.';
    return (
      <div className="rounded-md bg-warning/10 border border-warning/30 px-4 py-3 space-y-1">
        <p className="text-sm font-sans font-medium text-warning">Notifications blocked</p>
        <p className="text-xs font-sans text-text-secondary">{hint}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-sans text-text-primary">
          {isSubscribed ? 'Notifications enabled' : 'Notifications disabled'}
        </p>
        <button
          onClick={isSubscribed ? unsubscribe : subscribe}
          disabled={isLoading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans transition-colors border border-border hover:bg-surface-elevated disabled:opacity-50"
        >
          {isSubscribed ? <BellOff size={14} /> : <Bell size={14} />}
          {isSubscribed ? 'Unsubscribe' : 'Subscribe'}
        </button>
      </div>
      {isSubscribed && (
        <button
          onClick={handleTest}
          disabled={testing}
          data-testid="test-push-btn"
          className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans border border-border hover:bg-surface-elevated disabled:opacity-50 transition-colors"
        >
          <Send size={14} />
          {testing ? 'Sending…' : 'Send test notification'}
        </button>
      )}
    </div>
  );
}

// ── PWA install section ───────────────────────────────────────────────────────

function InstallSection() {
  const { canInstall, isInstalled, isIosSafari, prompt } = useInstallPrompt();

  if (isInstalled) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary font-sans">
        <Check size={16} className="text-primary" />
        App is installed
      </div>
    );
  }

  if (isIosSafari) {
    return (
      <p className="text-sm text-text-secondary font-sans">
        Tap <strong>⋯</strong> → <strong>Share</strong> → <strong>Add to Home Screen</strong>.
      </p>
    );
  }

  if (!canInstall) {
    return (
      <p className="text-sm text-text-muted font-sans">
        Use your browser's install option if supported.
      </p>
    );
  }

  return (
    <button
      onClick={() => void prompt()}
      className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans border border-border hover:bg-surface-elevated transition-colors"
    >
      <Download size={14} />
      Install app
    </button>
  );
}

// ── Preferences section ───────────────────────────────────────────────────────

function PreferencesSection() {
  const queryClient = useQueryClient();

  const { data: prefs, isLoading } = useQuery<NotificationPreferences>({
    queryKey: ['notification-preferences'],
    queryFn: () => apiFetch('/api/v1/notifications/preferences'),
  });

  const mutation = useMutation({
    mutationFn: (patch: Partial<NotificationPreferences>) =>
      apiFetch<NotificationPreferences>('/api/v1/notifications/preferences', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['notification-preferences'], updated);
    },
    onError: () => toast.error('Failed to save preferences'),
  });

  const update = useCallback(
    (patch: Partial<NotificationPreferences>) => mutation.mutate(patch),
    [mutation],
  );

  if (isLoading || !prefs) {
    return (
      <div className="space-y-3" aria-label="Loading preferences">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  const muted = prefs.global_mute;

  return (
    <div className="space-y-1">
      <Toggle
        checked={!muted}
        onChange={(v) => update({ global_mute: !v })}
        label="Enable all notifications"
      />

      <div className={`pl-4 border-l border-border space-y-0 ${muted ? 'opacity-50' : ''}`}>
        {CATEGORY_LABELS.map(({ key, label }) => (
          <Toggle
            key={key}
            checked={prefs[key] as boolean}
            onChange={(v) => update({ [key]: v })}
            label={label}
            disabled={muted}
          />
        ))}
      </div>

      <div className="pt-3 border-t border-border">
        <p className="text-sm font-sans text-text-secondary mb-2">Quiet hours (no notifications)</p>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm font-sans text-text-secondary">
            From
            <input
              type="time"
              value={prefs.quiet_hours_start ?? ''}
              disabled={muted}
              onChange={(e) => update({ quiet_hours_start: e.target.value || '' })}
              className="rounded-md border border-border bg-surface-elevated px-2 py-1 text-sm font-mono text-text-primary disabled:opacity-50"
            />
          </label>
          <label className="flex items-center gap-2 text-sm font-sans text-text-secondary">
            To
            <input
              type="time"
              value={prefs.quiet_hours_end ?? ''}
              disabled={muted}
              onChange={(e) => update({ quiet_hours_end: e.target.value || '' })}
              className="rounded-md border border-border bg-surface-elevated px-2 py-1 text-sm font-mono text-text-primary disabled:opacity-50"
            />
          </label>
          {(prefs.quiet_hours_start || prefs.quiet_hours_end) && (
            <button
              onClick={() => update({ quiet_hours_start: '', quiet_hours_end: '' })}
              disabled={muted}
              className="text-xs text-text-muted hover:text-text-primary disabled:opacity-50"
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Change PIN section ────────────────────────────────────────────────────────

function ChangePinSection() {
  const [currentPin, setCurrentPin] = useState('');
  const [newPin, setNewPin] = useState('');
  const [saving, setSaving] = useState(false);

  const canSubmit = currentPin.length === 4 && newPin.length === 4 && currentPin !== newPin;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    try {
      await apiFetch('/api/v1/auth/me/pin', {
        method: 'PUT',
        body: JSON.stringify({ current_pin: currentPin, new_pin: newPin }),
      });
      setCurrentPin('');
      setNewPin('');
      toast.success('PIN changed successfully');
    } catch {
      toast.error('Current PIN is incorrect or request failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-text-secondary font-sans">
        <KeyRound size={14} aria-hidden />
        <span>Enter your current PIN, then choose a new 4-digit PIN.</span>
      </div>
      <div className="space-y-1">
        <label className="text-sm font-sans text-text-primary">Current PIN</label>
        <PinInput value={currentPin} onChange={setCurrentPin} maxLength={4} />
      </div>
      <div className="space-y-1">
        <label className="text-sm font-sans text-text-primary">New PIN</label>
        <PinInput value={newPin} onChange={setNewPin} maxLength={4} />
      </div>
      {currentPin.length === 4 && newPin.length === 4 && currentPin === newPin && (
        <p className="text-xs text-error font-sans">New PIN must differ from current PIN.</p>
      )}
      <button
        type="submit"
        disabled={!canSubmit || saving}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans border border-border bg-primary text-white hover:bg-primary/90 disabled:opacity-50 transition-colors"
      >
        <Check size={14} aria-hidden />
        {saving ? 'Saving…' : 'Change PIN'}
      </button>
    </form>
  );
}

// ── Theme switch ──────────────────────────────────────────────────────────────

function AppearanceSection() {
  const { mode, setMode } = useTheme();
  const options = [
    { value: 'light' as const, label: 'Light', Icon: Sun },
    { value: 'dark' as const, label: 'Dark', Icon: Moon },
    { value: 'system' as const, label: 'System', Icon: Monitor },
  ];
  return (
    <div>
      <p className="text-sm text-text-secondary font-sans mb-3">
        Choose how the app looks. System follows your device&apos;s dark-mode setting.
      </p>
      <div
        role="radiogroup"
        aria-label="Theme"
        className="inline-flex w-full max-w-sm gap-1 p-1 rounded-md bg-surface-elevated border border-border"
      >
        {options.map(({ value, label, Icon }) => {
          const active = mode === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setMode(value)}
              className={cn(
                'flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-sm text-sm font-medium font-sans transition-colors tap-target press-down focus-visible:outline-none focus-visible:shadow-glow',
                active
                  ? 'bg-surface text-text-primary shadow-sm'
                  : 'text-text-secondary hover:text-text-primary',
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Timezone section ──────────────────────────────────────────────────────────

const TIMEZONES = [
  'Europe/London',
  'Europe/Dublin',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Madrid',
  'Europe/Rome',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Toronto',
  'America/Vancouver',
  'America/Mexico_City',
  'Australia/Sydney',
  'Australia/Melbourne',
  'Pacific/Auckland',
  'UTC',
];

function TimezoneSection() {
  const { player, updatePlayer } = useAuth();
  const [tz, setTz] = useState(player?.timezone ?? 'UTC');
  const [saving, setSaving] = useState(false);

  const isDirty = tz !== player?.timezone;

  async function handleSave() {
    setSaving(true);
    try {
      await apiFetch('/api/v1/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ timezone: tz }),
      });
      updatePlayer({ timezone: tz });
      toast.success('Timezone updated');
    } catch {
      toast.error('Failed to update timezone');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-text-secondary font-sans">
        <Globe size={14} aria-hidden />
        <span>Used for kickoff times and notification scheduling.</span>
      </div>
      <select
        id="timezone"
        value={tz}
        onChange={(e) => setTz(e.target.value)}
        aria-label="Timezone"
        className="flex h-10 w-full items-center rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary font-sans focus:outline-none focus:ring-2 focus:ring-primary"
      >
        {TIMEZONES.map((t) => (
          <option key={t} value={t}>
            {t.replace(/_/g, ' ')}
          </option>
        ))}
      </select>
      {isDirty && (
        <button
          type="button"
          disabled={saving}
          onClick={handleSave}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans border border-border bg-primary text-white hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          <Check size={14} aria-hidden />
          {saving ? 'Saving…' : 'Save timezone'}
        </button>
      )}
    </div>
  );
}

// ── Avatar section ────────────────────────────────────────────────────────────

function AvatarSection() {
  const { player, updatePlayer } = useAuth();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const invalidateAvatarCaches = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['leaderboard'] });
    queryClient.invalidateQueries({ queryKey: ['league-members'] });
    if (player?.id) queryClient.invalidateQueries({ queryKey: ['stats', player.id] });
  }, [queryClient, player?.id]);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!fileRef.current) return;
      fileRef.current.value = '';

      if (!file) return;
      if (!ALLOWED_AVATAR_TYPES.includes(file.type)) {
        toast.error('Only JPEG, PNG, WebP, or GIF files are supported');
        return;
      }
      if (file.size > MAX_AVATAR_BYTES * 2) {
        // Rough guard before resize — the resized output is far smaller.
        toast.error('File too large. Please choose an image under 5 MB.');
        return;
      }

      setUploading(true);
      try {
        const blob = await resizeAvatar(file);
        if (blob.size > MAX_AVATAR_BYTES) {
          toast.error('Resized image is too large. Please choose a smaller photo.');
          return;
        }

        // Upload via the backend (service-role key → bypasses Storage RLS).
        const newUrl = await uploadAvatarImage(blob);
        updatePlayer({ avatarUrl: newUrl });
        invalidateAvatarCaches();
        toast.success('Avatar updated');
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Upload failed');
      } finally {
        setUploading(false);
      }
    },
    [updatePlayer, invalidateAvatarCaches],
  );

  const handleRemove = useCallback(async () => {
    if (!player) return;
    setUploading(true);
    try {
      await apiFetch('/api/v1/auth/me/avatar', {
        method: 'PATCH',
        body: JSON.stringify({ avatar_url: null }),
      });
      updatePlayer({ avatarUrl: null });
      invalidateAvatarCaches();
      toast.success('Avatar removed');
    } catch {
      toast.error('Failed to remove avatar');
    } finally {
      setUploading(false);
    }
  }, [player, updatePlayer, invalidateAvatarCaches]);

  if (!player) return null;

  return (
    <div className="flex items-center gap-4">
      <Avatar name={player.displayName} size="lg" src={player.avatarUrl} />

      <div className="flex flex-col gap-2">
        <input
          ref={fileRef}
          type="file"
          accept={ALLOWED_AVATAR_TYPES.join(',')}
          className="sr-only"
          aria-label="Upload avatar photo"
          onChange={handleFileChange}
        />
        <button
          type="button"
          disabled={uploading}
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans border border-border hover:bg-surface-elevated disabled:opacity-50 transition-colors"
          aria-label={player.avatarUrl ? 'Replace avatar photo' : 'Upload avatar photo'}
        >
          <Camera size={14} aria-hidden />
          {uploading ? 'Uploading…' : player.avatarUrl ? 'Replace photo' : 'Upload photo'}
        </button>

        {player.avatarUrl && (
          <button
            type="button"
            disabled={uploading}
            onClick={handleRemove}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-sans text-error border border-error/30 hover:bg-error/10 disabled:opacity-50 transition-colors"
            aria-label="Remove avatar photo"
          >
            <Trash2 size={14} aria-hidden />
            Remove photo
          </button>
        )}

        <p className="text-[11px] text-text-muted font-sans leading-tight">
          JPEG, PNG, WebP or GIF · cropped to square · max 5 MB
        </p>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function SettingsPage() {
  return (
    <div className="max-w-xl space-y-6">
      <PageHeader title="Settings" eyebrow="Account & device" />

      <SectionCard title="Profile Photo">
        <AvatarSection />
      </SectionCard>

      <SectionCard title="Change PIN">
        <ChangePinSection />
      </SectionCard>

      <SectionCard title="Timezone">
        <TimezoneSection />
      </SectionCard>

      <SectionCard title="Appearance">
        <AppearanceSection />
      </SectionCard>

      <SectionCard title="Push Notifications">
        <PushSection />
      </SectionCard>

      <SectionCard title="Notification Preferences">
        <PreferencesSection />
      </SectionCard>

      <SectionCard title="Install App">
        <InstallSection />
      </SectionCard>

      <Link
        to="/about"
        className="flex items-center gap-2 text-sm font-sans text-text-muted hover:text-text-primary transition-colors group"
      >
        <Info size={14} className="group-hover:text-primary transition-colors" aria-hidden />
        About &amp; scoring rules
      </Link>
    </div>
  );
}
