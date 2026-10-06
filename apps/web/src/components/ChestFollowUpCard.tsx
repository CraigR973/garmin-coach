import { useState } from 'react';
import type { ChestFollowUp, ChestFollowUpAnswer } from '@coach/shared';
import { HeartPulse } from 'lucide-react';
import { SymptomNotice } from '@/components/AcutePhysiologyNotice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAnswerChestFollowUp } from '@/hooks/useAnswerChestFollowUp';
import {
  CHEST_FOLLOW_UP_OPTIONS,
  chestFollowUpLine,
  chestFollowUpTitle,
} from '@/lib/chestFollowUp';
import { NOTES_ASK_UPDATING } from '@/lib/notesAsk';

interface ChestFollowUpCardProps {
  /** The follow-up the stored morning is in; absent when none is open. */
  followUp: ChestFollowUp | null | undefined;
  /** The day the answer is recorded against. */
  subjectDate: string;
}

/** Batch 315: after a chest or heart report, ask before hard work.
 *
 *  From the morning after he reports chest or heart symptoms, until he says they have
 *  gone and that he has spoken to his GP or 111, Home asks here and a hard session is an
 *  easy ride. One tap answers; "Still there" shows the chest-or-heart notice at once, as
 *  the check-in does. The regraded morning follows a few seconds later and takes the card
 *  away, or keeps it saying that hard sessions stay easy rides. */
export function ChestFollowUpCard({ followUp, subjectDate }: ChestFollowUpCardProps) {
  const [answered, setAnswered] = useState<ChestFollowUpAnswer | null>(null);
  const answer = useAnswerChestFollowUp({
    // No regraded morning arrived: ask again rather than leave him waiting.
    onSettled: (regraded) => {
      if (!regraded) setAnswered(null);
    },
  });
  if (!followUp) return null;

  const title = chestFollowUpTitle(followUp.reportedWeekday);
  const current = answered ?? followUp.answer ?? null;

  function choose(value: ChestFollowUpAnswer) {
    setAnswered(value);
    answer.mutate({ subjectDate, answer: value });
  }

  return (
    <Card className="border-amber-500/35 bg-amber-500/[0.06]" role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HeartPulse className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>{chestFollowUpLine(followUp.answer)}</p>
        <div role="group" aria-label={title} className="grid gap-2">
          {CHEST_FOLLOW_UP_OPTIONS.map((option) => {
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
        <SymptomNotice answer={answered === 'still_there' ? 'chest_heart' : null} />
      </CardContent>
    </Card>
  );
}
