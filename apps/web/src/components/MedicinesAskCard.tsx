import { useState } from 'react';
import { Pill } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { type MedicinesAnswer, useAnswerMedicines } from '@/hooks/useAnswerMedicines';
import {
  MEDICINES_ASK,
  MEDICINES_NO,
  MEDICINES_SAVE,
  MEDICINES_THANKS_NEW,
  MEDICINES_THANKS_NONE,
  MEDICINES_TITLE,
  MEDICINES_WHICH,
  MEDICINES_YES,
} from '@/lib/medicinesAsk';

interface MedicinesAskCardProps {
  /** Home asks today: his medication fact is a quarter old. */
  due: boolean | null | undefined;
  /** The day the answer is sent against. */
  subjectDate: string;
}

/** Batch 370.3: once a quarter, "Any new medicines?". "No" answers in one tap; "Yes" asks
 *  which (optional) and saves. The card stays to say thanks after the day stops asking. */
export function MedicinesAskCard({ due, subjectDate }: MedicinesAskCardProps) {
  const [saved, setSaved] = useState<MedicinesAnswer | null>(null);
  const [startedYes, setStartedYes] = useState(false);
  const [words, setWords] = useState('');
  const answer = useAnswerMedicines({ onError: () => setSaved(null) });
  if (due !== true && saved === null) return null;

  function send(value: MedicinesAnswer) {
    setSaved(value);
    answer.mutate({ subjectDate, answer: value, words: value === 'new' ? words : null });
  }

  return (
    <Card role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Pill className="h-5 w-5 text-text-secondary" aria-hidden />
          {MEDICINES_TITLE}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        {saved !== null ? (
          <p aria-live="polite">{saved === 'new' ? MEDICINES_THANKS_NEW : MEDICINES_THANKS_NONE}</p>
        ) : (
          <>
            <p>{MEDICINES_ASK}</p>
            {startedYes ? (
              <div className="grid gap-2">
                <label className="sr-only" htmlFor="medicines-which">
                  {MEDICINES_WHICH}
                </label>
                <input
                  id="medicines-which"
                  className="h-10 rounded-md border border-border bg-background px-3 text-text-primary"
                  placeholder={MEDICINES_WHICH}
                  maxLength={120}
                  value={words}
                  onChange={(event) => setWords(event.target.value)}
                />
                <Button type="button" onClick={() => send('new')}>
                  {MEDICINES_SAVE}
                </Button>
              </div>
            ) : (
              <div role="group" aria-label={MEDICINES_TITLE} className="grid gap-2">
                <Button type="button" variant="outline" onClick={() => send('none')}>
                  {MEDICINES_NO}
                </Button>
                <Button type="button" variant="outline" onClick={() => setStartedYes(true)}>
                  {MEDICINES_YES}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
