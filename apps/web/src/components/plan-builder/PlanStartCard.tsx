import { useEffect, useState } from 'react';
import { CalendarClock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { selectClassName } from '@/components/plan-builder/styles';
import { longDate } from '@/lib/nextPlan';
import { CHANGE_START, START_HEADING, START_LINE } from '@/lib/planChanges';

/** Batch 324: the Monday the plan starts on; everything, his changes too, moves with it. */
export function PlanStartCard({
  startDate,
  options,
  pending,
  onSave,
}: {
  startDate: string;
  options: string[];
  pending: boolean;
  onSave: (startDate: string) => void;
}) {
  const [chosen, setChosen] = useState(startDate);

  useEffect(() => setChosen(startDate), [startDate]);

  const choices = options.includes(startDate) ? options : [startDate, ...options];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4 text-primary" aria-hidden />
          {START_HEADING}
        </CardTitle>
        <CardDescription>{START_LINE}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-2">
        <select
          aria-label={START_HEADING}
          className={`${selectClassName} sm:max-w-xs`}
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
        >
          {choices.map((day) => (
            <option key={day} value={day}>
              {longDate(day)}
            </option>
          ))}
        </select>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={chosen === startDate || pending}
          onClick={() => onSave(chosen)}
        >
          {CHANGE_START}
        </Button>
      </CardContent>
    </Card>
  );
}
