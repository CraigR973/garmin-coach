import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

export interface DisputeFormCopy {
  trigger: string;
  prompt: string;
  placeholder: string;
  submit: string;
  sent: string;
}

interface DisputeFormProps {
  copy: DisputeFormCopy;
  onSubmit: (reason: string) => Promise<void>;
}

/**
 * Batch 274 — say that something is wrong, and have it recorded.
 *
 * Collapsed to one quiet link until Mark wants it. Sending records the dispute and
 * says plainly that it changes nothing on the screen: suppressing a contested
 * input is Batch 276, and promising more than the app does would be its own
 * dishonesty.
 */
export function DisputeForm({ copy, onSubmit }: DisputeFormProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (sent) {
    return (
      <p className="text-sm leading-6 text-text-secondary" role="status">
        {copy.sent}
      </p>
    );
  }
  if (!open) {
    return (
      <button
        type="button"
        className="text-sm font-medium text-text-secondary underline-offset-4 hover:text-text-primary hover:underline"
        onClick={() => setOpen(true)}
      >
        {copy.trigger}
      </button>
    );
  }

  const submit = async () => {
    if (!reason.trim()) {
      setError('Say what looks wrong first.');
      return;
    }
    setSending(true);
    setError(null);
    try {
      await onSubmit(reason.trim());
      setSent(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That did not send. Try again in a moment.');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-text-primary">
        {copy.prompt}
        <Textarea
          className="mt-1"
          value={reason}
          placeholder={copy.placeholder}
          maxLength={2000}
          onChange={(event) => {
            setReason(event.target.value);
            setError(null);
          }}
        />
      </label>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => void submit()} disabled={sending}>
          {sending ? 'Sending…' : copy.submit}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={sending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
