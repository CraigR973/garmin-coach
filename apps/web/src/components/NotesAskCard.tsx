import { useState } from 'react';
import type { SymptomAnswer } from '@coach/shared';
import { MessageCircleQuestion } from 'lucide-react';
import { SymptomNotice } from '@/components/AcutePhysiologyNotice';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAnswerSymptomQuestion } from '@/hooks/useAnswerSymptomQuestion';
import { NOTES_ASK_TITLE, NOTES_ASK_UPDATING, notesAskLine } from '@/lib/notesAsk';
import { SYMPTOM_OPTIONS } from '@/lib/symptoms';

interface NotesAskCardProps {
  ask: boolean | null | undefined;
  words: string | null | undefined;
  /** Batch 303: the question is holding today's hard session at an easy ride. */
  eases?: boolean | null;
  /** The day the question is about; the answer is recorded against its check-in. */
  subjectDate: string;
}

/** Batch 297: his note may name a symptom, so ask him rather than guess.
 *
 *  Batch 303: he answers here, in one tap, with the check-in's four answers. The button
 *  used to open the check-in, where None is already selected, and saving that form was
 *  his answer. A floor answer shows its notice at once, as the check-in does (Batch 301);
 *  the regraded morning follows a few seconds later and takes this card away. */
export function NotesAskCard({ ask, words, eases, subjectDate }: NotesAskCardProps) {
  const [answered, setAnswered] = useState<SymptomAnswer | null>(null);
  const answer = useAnswerSymptomQuestion({
    // No regraded morning arrived: ask again rather than leave him waiting.
    onSettled: (regraded) => {
      if (!regraded) setAnswered(null);
    },
  });
  if (ask !== true) return null;

  function choose(value: SymptomAnswer) {
    setAnswered(value);
    answer.mutate({ subjectDate, answer: value });
  }

  return (
    <Card className="border-amber-500/35 bg-amber-500/[0.06]" role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageCircleQuestion className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {NOTES_ASK_TITLE}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>{notesAskLine(words, eases === true)}</p>
        <div role="group" aria-label={NOTES_ASK_TITLE} className="grid gap-2">
          {SYMPTOM_OPTIONS.map((option) => {
            const chosen = answered === option.value;
            return (
              <Button
                key={option.value}
                type="button"
                aria-pressed={chosen}
                variant={chosen ? 'default' : 'outline'}
                disabled={answered !== null}
                className="h-auto w-full flex-col items-start gap-0.5 whitespace-normal px-3 py-2 text-left"
                onClick={() => choose(option.value)}
              >
                <span className="font-medium">{option.label}</span>
                {option.detail ? (
                  <span className="text-xs font-normal opacity-80">{option.detail}</span>
                ) : null}
              </Button>
            );
          })}
        </div>
        {answered !== null ? <p aria-live="polite">{NOTES_ASK_UPDATING}</p> : null}
        <SymptomNotice answer={answered} />
      </CardContent>
    </Card>
  );
}
