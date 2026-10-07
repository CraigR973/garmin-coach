import { useEffect, useState } from 'react';
import type { PlanDays } from '@coach/shared';
import { CalendarDays } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  CANCEL,
  CHANGE_DAYS,
  DAYS_HEADING,
  DAYS_LINE,
  DAY_KEYS,
  DAY_LABELS,
  REBUILD,
  WEEKDAY_NAMES,
  rebuildWarning,
} from '@/lib/planChanges';
import { selectClassName } from '@/components/plan-builder/styles';

/**
 * Batch 324: his days, which day each kind of session is on, every week.
 *
 * Changing them rebuilds the plan from its table, so a change he made to a single session
 * goes with it: when there are any, the card says how many and asks again before it sends.
 */
export function PlanDaysCard({
  days,
  sessionChangesSinceRebuild,
  pending,
  onSave,
}: {
  days: PlanDays;
  sessionChangesSinceRebuild: number;
  pending: boolean;
  onSave: (days: PlanDays) => void;
}) {
  const [chosen, setChosen] = useState<PlanDays>(days);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    setChosen(days);
    setConfirming(false);
  }, [days]);

  const changed = DAY_KEYS.some((key) => chosen[key] !== days[key]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarDays className="h-4 w-4 text-primary" aria-hidden />
          {DAYS_HEADING}
        </CardTitle>
        <CardDescription>{DAYS_LINE}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {DAY_KEYS.map((key) => (
            <label key={key} className="space-y-1 text-sm text-text-secondary">
              <span className="block font-medium">{DAY_LABELS[key]}</span>
              <select
                aria-label={DAY_LABELS[key]}
                className={selectClassName}
                value={chosen[key]}
                onChange={(event) => setChosen({ ...chosen, [key]: Number(event.target.value) })}
              >
                {WEEKDAY_NAMES.map((name, index) => (
                  <option key={name} value={index}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        {confirming ? (
          <div className="space-y-2 rounded-md border border-border bg-surface/80 px-3 py-2">
            <p className="text-sm text-text-secondary" role="alert">
              {rebuildWarning(sessionChangesSinceRebuild)}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" disabled={pending} onClick={() => onSave(chosen)}>
                {REBUILD}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setConfirming(false)}
              >
                {CANCEL}
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!changed || pending}
            onClick={() =>
              sessionChangesSinceRebuild > 0 ? setConfirming(true) : onSave(chosen)
            }
          >
            {CHANGE_DAYS}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
