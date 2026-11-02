import { useState } from 'react';
import type { FeverFollowUp, FeverFollowUpAnswer } from '@coach/shared';
import { Thermometer } from 'lucide-react';
import { SymptomNotice } from '@/components/AcutePhysiologyNotice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAnswerChestFollowUp } from '@/hooks/useAnswerChestFollowUp';
import {
  FEVER_FOLLOW_UP_ASK,
  FEVER_FOLLOW_UP_OPTIONS,
  feverFollowUpTitle,
} from '@/lib/feverFollowUp';
import { NOTES_ASK_UPDATING } from '@/lib/notesAsk';

interface FeverFollowUpCardProps {
  /** The fever follow-up the stored morning is in; absent when none is open. */
  followUp: FeverFollowUp | null | undefined;
  /** The day the answer is recorded against. */
  subjectDate: string;
}

/** Batch 364 (HS361-02): after a fever, ask whether it has gone.
 *
 *  The chest or heart card's pattern (Batch 315): from the morning after he reports a
 *  fever, aches or a chest infection, until he says it has gone for a full day, Home asks
 *  here and riding stays easy. One tap answers; "Still there" shows the fever notice at
 *  once, as the check-in does. The regraded morning follows a few seconds later and takes
 *  the card away. */
export function FeverFollowUpCard({ followUp, subjectDate }: FeverFollowUpCardProps) {
  const [answered, setAnswered] = useState<FeverFollowUpAnswer | null>(null);
  const answer = useAnswerChestFollowUp({
    // No regraded morning arrived: ask again rather than leave him waiting.
    onSettled: (regraded) => {
      if (!regraded) setAnswered(null);
    },
  });
  if (!followUp) return null;

  const title = feverFollowUpTitle(followUp.reportedWeekday);
  const current = answered ?? followUp.answer ?? null;

  function choose(value: FeverFollowUpAnswer) {
    setAnswered(value);
    answer.mutate({ subjectDate, answer: value, kind: 'fever_aches' });
  }

  return (
    <Card className="border-amber-500/35 bg-amber-500/[0.06]" role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Thermometer className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>{FEVER_FOLLOW_UP_ASK}</p>
        <div role="group" aria-label={title} className="grid gap-2">
          {FEVER_FOLLOW_UP_OPTIONS.map((option) => {
            const chosen = current === option.value;
            return (
              <Button
                key={option.value}
                type="button"
                aria-pressed={chosen}
                variant={chosen ? 'default' : 'outline'}
                disabled={answered !== null}
                className="h-auto w-full whitespace-normal px-3 py-2 text-left font-medium"
                onClick={() => choose(option.value)}
              >
                {option.label}
              </Button>
            );
          })}
        </div>
        {answered !== null ? <p aria-live="polite">{NOTES_ASK_UPDATING}</p> : null}
        <SymptomNotice answer={answered === 'still_there' ? 'fever_aches' : null} />
      </CardContent>
    </Card>
  );
}
