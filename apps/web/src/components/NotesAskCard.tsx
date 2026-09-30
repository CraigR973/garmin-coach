import { MessageCircleQuestion } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NOTES_ASK_BUTTON, NOTES_ASK_TITLE, notesAskLine } from '@/lib/notesAsk';

interface NotesAskCardProps {
  ask: boolean | null | undefined;
  words: string | null | undefined;
}

/** Batch 297: his note may name a symptom, so ask him rather than guess. */
export function NotesAskCard({ ask, words }: NotesAskCardProps) {
  if (ask !== true) return null;
  return (
    <Card className="border-amber-500/35 bg-amber-500/[0.06]" role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageCircleQuestion className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {NOTES_ASK_TITLE}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>{notesAskLine(words)}</p>
        <Button asChild size="sm">
          <Link to="/check-in">{NOTES_ASK_BUTTON}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
