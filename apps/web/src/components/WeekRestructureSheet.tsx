import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet } from '@/components/ui/sheet';

interface RestructurePreviewChange {
  workoutDate: string;
  incomingTitle: string;
  outgoingTitle: string;
  reason: string;
}

interface WeekRestructureSheetProps {
  open: boolean;
  busy: boolean;
  loading: boolean;
  weekLabel: string;
  preview:
    | {
        changed: boolean;
        fatigued: boolean;
        reasons: string[];
        notes: string[];
        conflictsBefore: Array<[string, string]>;
        changes: RestructurePreviewChange[];
      }
    | null;
  onClose: () => void;
  onApply: () => void;
}

function reasonLabel(reason: string): string {
  if (reason === 'defer_fatigue') return 'Moved later for recovery';
  if (reason === 'no_stack') return 'Separates hard sessions';
  if (reason === 'reorder') return 'Rebalanced within the week';
  return reason.replace(/[_-]+/g, ' ');
}

function formatConflict(datePair: [string, string]): string {
  const [first, second] = datePair;
  return `${first} and ${second}`;
}

export function WeekRestructureSheet({
  open,
  busy,
  loading,
  weekLabel,
  preview,
  onClose,
  onApply,
}: WeekRestructureSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={`Rearrange ${weekLabel}`}>
      <div className="space-y-4">
        {loading ? <p className="text-sm text-text-secondary">Checking the week…</p> : null}

        {!loading && preview ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={preview.changed ? 'accent' : 'muted'}>
                {preview.changed ? 'Preview ready' : 'No changes needed'}
              </Badge>
              {preview.fatigued ? <Badge variant="error">Fatigue detected</Badge> : null}
            </div>

            {preview.reasons.length > 0 ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-text-primary">Why it wants to help</p>
                {preview.reasons.map((reason) => (
                  <p key={reason} className="text-sm text-text-secondary">
                    {reason}
                  </p>
                ))}
              </div>
            ) : null}

            {preview.changes.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-medium text-text-primary">Proposed reshuffle</p>
                {preview.changes.map((change) => (
                  <div key={`${change.workoutDate}-${change.incomingTitle}`} className="rounded-xl border border-border bg-bg px-3 py-3">
                    <p className="text-sm font-medium text-text-primary">
                      {change.workoutDate}: {change.incomingTitle}
                    </p>
                    <p className="text-sm text-text-secondary">
                      Replaces {change.outgoingTitle} on this day.
                    </p>
                    <p className="mt-1 text-xs text-text-secondary">{reasonLabel(change.reason)}</p>
                  </div>
                ))}
              </div>
            ) : null}

            {preview.notes.length > 0 ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-text-primary">Notes</p>
                {preview.notes.map((note) => (
                  <p key={note} className="text-sm text-text-secondary">
                    {note}
                  </p>
                ))}
              </div>
            ) : null}

            {preview.conflictsBefore.length > 0 ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-text-primary">Current hard-session clashes</p>
                {preview.conflictsBefore.map((pair) => (
                  <p key={pair.join('-')} className="text-sm text-text-secondary">
                    {formatConflict(pair)}
                  </p>
                ))}
              </div>
            ) : null}

            <Button type="button" className="w-full" disabled={busy || !preview.changed} onClick={onApply}>
              {busy ? 'Working…' : preview.changed ? 'Apply reshuffle' : 'No reshuffle needed'}
            </Button>
          </>
        ) : null}
      </div>
    </Sheet>
  );
}
