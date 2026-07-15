import { useState } from 'react';
import {
  addDays,
  format,
  isAfter,
  isSameDay,
  isSameMonth,
  parseISO,
  subDays,
} from 'date-fns';
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
type VerdictTone = 'green' | 'amber' | 'red';

const VERDICT_STYLES: Record<VerdictTone, string> = {
  green: 'border-emerald-500/40 bg-emerald-500/12 text-emerald-100 hover:border-emerald-400/60 hover:bg-emerald-500/18',
  amber: 'border-amber-500/50 bg-amber-500/12 text-amber-100 hover:border-amber-400/70 hover:bg-amber-500/18',
  red: 'border-rose-500/50 bg-rose-500/12 text-rose-100 hover:border-rose-400/70 hover:bg-rose-500/18',
};

const VERDICT_SELECTED_STYLES: Record<VerdictTone, string> = {
  green: 'border-emerald-400 bg-emerald-500 text-emerald-950',
  amber: 'border-amber-300 bg-amber-400 text-amber-950',
  red: 'border-rose-300 bg-rose-400 text-rose-950',
};

const VERDICT_LABELS: Record<VerdictTone, string> = {
  green: 'Green verdict',
  amber: 'Amber verdict',
  red: 'Red verdict',
};

const VERDICT_MARKS: Record<VerdictTone, string> = {
  green: 'G',
  amber: 'A',
  red: 'R',
};

export function SleepDateCalendar({
  selectedDate,
  maxDate,
  displayMonth,
  onDisplayMonthChange,
  onSelectDate,
  verdictsByDate = {},
}: {
  selectedDate: string;
  maxDate: string;
  displayMonth: Date;
  onDisplayMonthChange: (month: Date) => void;
  onSelectDate: (date: string) => void;
  verdictsByDate?: Record<string, VerdictTone | null | undefined>;
}) {
  const [expanded, setExpanded] = useState(false);

  const maxDateObj = parseISO(maxDate);
  const selectedDateObj = parseISO(selectedDate);
  const nextDayDisabled = !isAfter(maxDateObj, selectedDateObj);
  const nextMonthDisabled = isAfter(
    new Date(displayMonth.getFullYear(), displayMonth.getMonth() + 1, 1),
    new Date(maxDateObj.getFullYear(), maxDateObj.getMonth(), 1),
  );
  const days = buildCalendarDays(displayMonth);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="h-4 w-4 text-primary" aria-hidden />
              Sleep calendar
            </CardTitle>
            <CardDescription>
              Pick a date to review that night&apos;s sleep and room history. Tonight&apos;s look-ahead stays on the
              Tonight tab.
            </CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Previous day"
              onClick={() => onSelectDate(format(subDays(selectedDateObj, 1), 'yyyy-MM-dd'))}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Next day"
              disabled={nextDayDisabled}
              onClick={() => onSelectDate(format(addDays(selectedDateObj, 1), 'yyyy-MM-dd'))}
            >
              <ChevronRight className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-text-primary">Selected: {format(parseISO(selectedDate), 'EEE d MMM')}</p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-expanded={expanded}
            aria-controls="sleep-calendar-grid"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? 'Hide calendar' : 'Show calendar'}
            <ChevronDown
              className={cn('h-4 w-4 transition-transform', expanded ? 'rotate-180' : '')}
              aria-hidden
            />
          </Button>
        </div>
        {expanded ? (
          <div id="sleep-calendar-grid" className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-text-primary">{format(displayMonth, 'MMMM yyyy')}</p>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  aria-label="Previous month"
                  onClick={() =>
                    onDisplayMonthChange(new Date(displayMonth.getFullYear(), displayMonth.getMonth() - 1, 1))
                  }
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  aria-label="Next month"
                  disabled={nextMonthDisabled}
                  onClick={() =>
                    onDisplayMonthChange(new Date(displayMonth.getFullYear(), displayMonth.getMonth() + 1, 1))
                  }
                >
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-text-secondary" aria-label="Verdict legend">
              {(['green', 'amber', 'red'] as const).map((tone) => (
                <div
                  key={tone}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-full border px-2.5 py-1',
                    VERDICT_STYLES[tone],
                  )}
                >
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-current/30 bg-bg/40 text-[10px] font-semibold">
                    {VERDICT_MARKS[tone]}
                  </span>
                  <span>{VERDICT_LABELS[tone].replace(' verdict', '')}</span>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1 text-center text-[11px] uppercase tracking-[0.2em] text-text-muted">
              {WEEKDAY_LABELS.map((label) => (
                <div key={label} className="py-1">
                  {label}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {days.map((day) => {
                const iso = format(day, 'yyyy-MM-dd');
                const disabled = isAfter(day, maxDateObj);
                const selected = isSameDay(day, selectedDateObj);
                const inMonth = isSameMonth(day, displayMonth);
                const isToday = isSameDay(day, maxDateObj);
                const verdict = verdictsByDate[iso] ?? null;
                const verdictLabel = verdict ? VERDICT_LABELS[verdict] : 'No stored verdict';
                return (
                  <button
                    key={iso}
                    type="button"
                    aria-label={`${format(day, 'EEEE d MMMM yyyy')} - ${verdictLabel}`}
                    disabled={disabled}
                    onClick={() => onSelectDate(iso)}
                    className={cn(
                      'flex min-h-12 flex-col items-center justify-center rounded-xl border px-1 py-2 text-sm transition',
                      selected
                        ? verdict
                          ? VERDICT_SELECTED_STYLES[verdict]
                          : 'border-primary bg-primary text-primary-foreground shadow-sm'
                        : verdict
                          ? VERDICT_STYLES[verdict]
                          : 'border-border bg-bg text-text-primary hover:border-primary/40 hover:bg-surface-elevated',
                      !inMonth && !selected ? 'text-text-muted/60' : '',
                      disabled
                        ? 'cursor-not-allowed border-border/60 bg-bg/60 text-text-muted/50 hover:border-border/60 hover:bg-bg/60'
                        : '',
                    )}
                  >
                    <span className="font-medium">{format(day, 'd')}</span>
                    <div className="mt-1 flex items-center gap-1 text-[10px]">
                      <span
                        className={cn(
                          selected && !verdict ? 'text-primary-foreground/80' : 'text-text-muted',
                          selected && verdict ? 'text-current/75' : '',
                        )}
                      >
                        {isToday ? 'Today' : format(day, 'EEE')}
                      </span>
                      {verdict ? (
                        <span
                          aria-hidden
                          className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-current/30 bg-bg/35 text-[9px] font-semibold"
                        >
                          {VERDICT_MARKS[verdict]}
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function buildCalendarDays(displayMonth: Date) {
  const start = new Date(displayMonth.getFullYear(), displayMonth.getMonth(), 1);
  const startOffset = (start.getDay() + 6) % 7;
  start.setDate(start.getDate() - startOffset);

  const days: Date[] = [];
  for (let index = 0; index < 42; index += 1) {
    days.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + index));
  }
  return days;
}
