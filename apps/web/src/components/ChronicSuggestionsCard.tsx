import { Check, CircleAlert, ListChecks } from 'lucide-react';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type ChronicSuggestions = NonNullable<DailyLoopData['chronicSuggestions']>;
type Suggestion = ChronicSuggestions['items'][number];

const toneClass: Record<Suggestion['tone'], string> = {
  watch: 'border-warning/40 bg-warning/10 text-warning',
  protect: 'border-destructive/40 bg-destructive/10 text-destructive',
};

function windowText(suggestions: ChronicSuggestions) {
  const window = suggestions.evidenceWindow;
  return `${window.nightsObserved}/${window.nightsRequired} nights · ${window.weeks} weeks`;
}

export function ChronicSuggestionsCard({
  suggestions,
}: {
  suggestions?: ChronicSuggestions | null;
}) {
  if (!suggestions) {
    return null;
  }

  if (suggestions.status === 'insufficient_history') {
    return (
      <Card className="border-dashed bg-surface/60">
        <CardContent className="space-y-2 pt-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ListChecks className="h-4 w-4 text-text-muted" aria-hidden />
            Pattern suggestions
          </div>
          <p className="text-sm text-text-secondary">{suggestions.summary}</p>
          <p className="text-[11px] text-text-muted">{windowText(suggestions)}</p>
        </CardContent>
      </Card>
    );
  }

  if (suggestions.status === 'clear') {
    return (
      <Card className="border-success/30 bg-success/10">
        <CardContent className="flex items-start gap-3 pt-4">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-text-primary">{suggestions.headline}</p>
            <p className="text-sm text-text-secondary">{suggestions.summary}</p>
            <p className="text-[11px] text-text-muted">{windowText(suggestions)}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-warning/35 bg-warning/5">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <CircleAlert className="h-4 w-4 text-warning" aria-hidden />
          {suggestions.headline}
        </CardTitle>
        <p className="text-xs text-text-muted">{windowText(suggestions)}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {suggestions.items.map((item) => (
          <SuggestionBlock key={item.id} item={item} />
        ))}
      </CardContent>
    </Card>
  );
}

function SuggestionBlock({ item }: { item: Suggestion }) {
  return (
    <div className="space-y-3 rounded-md border border-border bg-surface-elevated p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-normal',
                toneClass[item.tone],
              )}
            >
              {item.tone === 'protect' ? 'Protect' : 'Watch'}
            </span>
            <p className="text-sm font-semibold text-text-primary">{item.title}</p>
          </div>
          <p className="text-sm text-text-secondary">{item.summary}</p>
        </div>
      </div>

      <div className="space-y-2 text-xs text-text-secondary">
        {item.evidence.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>

      {item.actions.length > 0 && (
        <ul className="space-y-1.5 text-sm text-text-primary">
          {item.actions.map((action) => (
            <li key={action} className="flex gap-2">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
              <span>{action}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
