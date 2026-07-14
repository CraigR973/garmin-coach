import { useEffect, useMemo, useState } from 'react';
import {
  addDays,
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isAfter,
  isSameDay,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
  subDays,
  subMonths,
} from 'date-fns';
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function SleepDateCalendar({
  selectedDate,
  maxDate,
  onSelectDate,
}: {
  selectedDate: string;
  maxDate: string;
  onSelectDate: (date: string) => void;
}) {
  const [displayMonth, setDisplayMonth] = useState(() => startOfMonth(parseISO(selectedDate)));
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setDisplayMonth(startOfMonth(parseISO(selectedDate)));
  }, [selectedDate]);

  const maxDateObj = useMemo(() => parseISO(maxDate), [maxDate]);
  const selectedDateObj = useMemo(() => parseISO(selectedDate), [selectedDate]);
  const nextDayDisabled = !isAfter(maxDateObj, selectedDateObj);
  const nextMonthDisabled = isAfter(startOfMonth(addMonths(displayMonth, 1)), startOfMonth(maxDateObj));
  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(displayMonth), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(displayMonth), { weekStartsOn: 1 });
    return eachDayOfInterval({ start, end });
  }, [displayMonth]);

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
                  onClick={() => setDisplayMonth((current) => subMonths(current, 1))}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  aria-label="Next month"
                  disabled={nextMonthDisabled}
                  onClick={() => setDisplayMonth((current) => addMonths(current, 1))}
                >
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </Button>
              </div>
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
                const selected = isSameDay(day, parseISO(selectedDate));
                const inMonth = isSameMonth(day, displayMonth);
                const isToday = isSameDay(day, maxDateObj);
                return (
                  <button
                    key={iso}
                    type="button"
                    aria-label={format(day, 'EEEE d MMMM yyyy')}
                    disabled={disabled}
                    onClick={() => onSelectDate(iso)}
                    className={cn(
                      'flex min-h-12 flex-col items-center justify-center rounded-xl border px-1 py-2 text-sm transition',
                      selected
                        ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                        : 'border-border bg-bg text-text-primary hover:border-primary/40 hover:bg-surface-elevated',
                      !inMonth && !selected ? 'text-text-muted/60' : '',
                      disabled
                        ? 'cursor-not-allowed border-border/60 bg-bg/60 text-text-muted/50 hover:border-border/60 hover:bg-bg/60'
                        : '',
                    )}
                  >
                    <span className="font-medium">{format(day, 'd')}</span>
                    <span
                      className={cn('text-[10px]', selected ? 'text-primary-foreground/80' : 'text-text-muted')}
                    >
                      {isToday ? 'Today' : format(day, 'EEE')}
                    </span>
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
