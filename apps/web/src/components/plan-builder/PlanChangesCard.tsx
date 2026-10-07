import { useState } from 'react';
import type { PlanChangeLogEntry } from '@coach/shared';
import { History, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  COACH_SUGGESTION,
  KEEP_THEM,
  RESET,
  RESET_CONFIRM,
  RESET_LINE,
  YOUR_CHANGES,
} from '@/lib/planChanges';

/**
 * Batch 324: what he has changed in the proposed plan, oldest first, in the words the
 * server logged each change in, and the way back to the plan as proposed.
 */
export function PlanChangesCard({
  changes,
  pending,
  onReset,
}: {
  changes: PlanChangeLogEntry[];
  pending: boolean;
  onReset: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-primary" aria-hidden />
          {YOUR_CHANGES}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ol className="list-decimal space-y-1 pl-5 text-sm leading-6 text-text-secondary">
          {changes.map((entry) => (
            <li key={entry.revision}>
              {entry.summary}
              {entry.by === 'coach' ? ` ${COACH_SUGGESTION}` : ''}
            </li>
          ))}
        </ol>
        {confirming ? (
          <div className="space-y-2 rounded-md border border-border bg-surface/80 px-3 py-2">
            <p className="text-sm text-text-secondary" role="alert">
              {RESET_LINE}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" disabled={pending} onClick={onReset}>
                {RESET_CONFIRM}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setConfirming(false)}
              >
                {KEEP_THEM}
              </Button>
            </div>
          </div>
        ) : (
          <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(true)}>
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
            {RESET}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
