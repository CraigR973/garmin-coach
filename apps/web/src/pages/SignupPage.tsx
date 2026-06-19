import { useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Camera } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PinInput } from '@/components/PinInput';
import { Brand } from '@/components/Brand';
import { Avatar } from '@/components/ui/avatar';
import {
  ALLOWED_AVATAR_TYPES,
  MAX_AVATAR_BYTES,
  resizeAvatar,
  uploadAvatarImage,
} from '@/lib/image';

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

export function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inviteToken = searchParams.get('invite');

  const [email, setEmail] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [pin, setPin] = useState('');
  const [pinConfirm, setPinConfirm] = useState('');
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  function handleAvatarSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (avatarInputRef.current) avatarInputRef.current.value = '';
    if (!file) return;
    if (!ALLOWED_AVATAR_TYPES.includes(file.type)) {
      toast.error('Photo must be a JPEG, PNG, WebP or GIF.');
      return;
    }
    if (file.size > MAX_AVATAR_BYTES * 2) {
      toast.error('Photo too large — please choose one under 10 MB.');
      return;
    }
    setAvatarFile(file);
    setAvatarPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (pin.length !== 4) {
      setError('PIN must be exactly 4 digits.');
      return;
    }
    if (pin !== pinConfirm) {
      setError('PINs do not match.');
      return;
    }

    setIsLoading(true);
    try {
      await signup({ email: email.trim(), first_name: firstName.trim(), last_name: lastName.trim(), pin, timezone });

      // Optional profile photo — uploaded after the account exists (so we're
      // authenticated). A failure here must not block account creation.
      if (avatarFile) {
        try {
          await uploadAvatarImage(await resizeAvatar(avatarFile));
        } catch {
          toast.error('Account created, but your photo could not be uploaded. Add it later in Settings.');
        }
      }

      if (inviteToken) {
        navigate(`/join/${inviteToken}`, { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Signup failed';
      if (msg.toLowerCase().includes('already')) {
        setError('An account with that email already exists.');
      } else {
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-10">
          <Brand variant="splash" />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-center text-text-primary">Create account</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="flex flex-col items-center gap-2 pb-1">
                <input
                  ref={avatarInputRef}
                  type="file"
                  accept={ALLOWED_AVATAR_TYPES.join(',')}
                  className="sr-only"
                  aria-label="Add a profile photo"
                  onChange={handleAvatarSelect}
                />
                <button
                  type="button"
                  onClick={() => avatarInputRef.current?.click()}
                  className="relative rounded-full press-down focus-visible:outline-none focus-visible:shadow-glow"
                  aria-label="Add a profile photo"
                >
                  <Avatar name={firstName || 'You'} size="lg" src={avatarPreview ?? undefined} />
                  <span className="absolute -bottom-0.5 -right-0.5 inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white border-2 border-surface">
                    <Camera className="h-3.5 w-3.5" aria-hidden />
                  </span>
                </button>
                <p className="text-xs font-sans text-text-muted">
                  {avatarFile ? 'Photo added — tap to change' : 'Add a photo (optional)'}
                </p>
              </div>

              <div className="space-y-1">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="firstName">First name</Label>
                  <Input
                    id="firstName"
                    type="text"
                    autoComplete="given-name"
                    required
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Alice"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="lastName">Last name</Label>
                  <Input
                    id="lastName"
                    type="text"
                    autoComplete="family-name"
                    required
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="Smith"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <Label htmlFor="timezone">Your timezone</Label>
                <select
                  id="timezone"
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="flex h-10 w-full items-center rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary font-sans focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <Label>Choose a 4-digit PIN</Label>
                <PinInput value={pin} onChange={setPin} maxLength={4} autoComplete="new-password" />
              </div>

              <div className="space-y-1">
                <Label>Confirm PIN</Label>
                <PinInput value={pinConfirm} onChange={setPinConfirm} maxLength={4} autoComplete="new-password" label="Confirm PIN" />
              </div>

              {error && <p role="alert" className="text-xs text-error font-sans">{error}</p>}

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? 'Creating account…' : 'Create account'}
              </Button>

              <p className="text-xs font-sans text-text-muted text-center">
                Already have an account?{' '}
                <Link to="/login" className="text-primary hover:underline">
                  Sign in
                </Link>
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
