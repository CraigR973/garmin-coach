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
import {
  BatteryCharging,
  BedDouble,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Gauge,
  type LucideIcon,
} from 'lucide-react';
import type { SleepCalendarDay } from '@coach/shared';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import READINGS from '@/lib/readingWords.json';

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
/** Batch 313: a day shows how recovered he was that morning (Recovered, Some fatigue,
 *  Still recovering) and whether it was a rest day, never a colour grade. Recovery and
 *  rest are a calm blue; red is kept for health warnings, which a calendar does not show. */
type DayKind = 'recovered' | 'some_fatigue' | 'still_recovering' | 'rest';

const DAY_STYLES: Record<DayKind, string> = {
  recovered: 'border-emerald-500/40 bg-emerald-500/12 text-emerald-100 hover:border-emerald-400/60 hover:bg-emerald-500/18',
  some_fatigue: 'border-amber-500/50 bg-amber-500/12 text-amber-100 hover:border-amber-400/70 hover:bg-amber-500/18',
  still_recovering: 'border-sky-500/50 bg-sky-500/12 text-sky-100 hover:border-sky-400/70 hover:bg-sky-500/18',
  rest: 'border-sky-500/50 bg-sky-500/12 text-sky-100 hover:border-sky-400/70 hover:bg-sky-500/18',
};

const DAY_SELECTED_STYLES: Record<DayKind, string> = {
  recovered: 'border-emerald-400 bg-emerald-500 text-emerald-950',
  some_fatigue: 'border-amber-300 bg-amber-400 text-amber-950',
  still_recovering: 'border-sky-300 bg-sky-400 text-sky-950',
  rest: 'border-sky-300 bg-sky-400 text-sky-950',
};

const DAY_ICONS: Record<DayKind, LucideIcon> = {
  recovered: CheckCircle2,
  some_fatigue: Gauge,
  still_recovering: BatteryCharging,
  rest: BedDouble,
};

const LEGEND: DayKind[] = ['recovered', 'some_fatigue', 'still_recovering', 'rest'];

function dayWords(kind: DayKind): string {
  return kind === 'rest' ? READINGS.restDay : READINGS.readings[kind];
}

/** One stored morning as the calendar reads it; a client older than Batch 313's API
 *  falls back to the colour alone. */
function dayKind(
  day: SleepCalendarDay | undefined,
  verdict: string | null | undefined,
): { kind: DayKind; label: string } | null {
  const reading = day?.reading ?? READING_BY_VERDICT[verdict ?? ''] ?? null;
  if (!reading || !(reading in READINGS.readings)) return null;
  const words = READINGS.readings[reading as Exclude<DayKind, 'rest'>];
  if (day?.restDay) return { kind: 'rest', label: `${READINGS.restDay} · ${words}` };
  return { kind: reading as DayKind, label: words };
}

const READING_BY_VERDICT: Record<string, string> = {
  green: 'recovered',
  amber: 'some_fatigue',
  red: 'still_recovering',
};

export function SleepDateCalendar({
  selectedDate,
  maxDate,
  displayMonth,
  onDisplayMonthChange,
  onSelectDate,
  verdictsByDate = {},
  daysByDate = {},
}: {
  selectedDate: string;
  maxDate: string;
  displayMonth: Date;
  onDisplayMonthChange: (month: Date) => void;
  onSelectDate: (date: string) => void;
  verdictsByDate?: Record<string, string | null | undefined>;
  daysByDate?: Record<string, SleepCalendarDay | undefined>;
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
            <div className="flex flex-wrap gap-2 text-xs text-text-secondary" aria-label="Calendar legend">
              {LEGEND.map((kind) => {
                const Icon = DAY_ICONS[kind];
                return (
                  <div
                    key={kind}
                    className={cn(
                      'inline-flex items-center gap-2 rounded-full border px-2.5 py-1',
                      DAY_STYLES[kind],
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    <span>{dayWords(kind)}</span>
                  </div>
                );
              })}
            </div>
            <div className="grid grid-cols-7 gap-1 text-center text-2xs uppercase tracking-[0.2em] text-text-muted">
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
                const shown = dayKind(daysByDate[iso], verdictsByDate[iso]);
                const kind = shown?.kind ?? null;
                const DayIcon = kind ? DAY_ICONS[kind] : null;
                return (
                  <button
                    key={iso}
                    type="button"
                    aria-label={`${format(day, 'EEEE d MMMM yyyy')} - ${shown?.label ?? 'No morning saved'}`}
                    disabled={disabled}
                    onClick={() => onSelectDate(iso)}
                    className={cn(
                      'flex min-h-12 flex-col items-center justify-center rounded-xl border px-1 py-2 text-sm transition',
                      selected
                        ? kind
                          ? DAY_SELECTED_STYLES[kind]
                          : 'border-primary bg-primary text-on-primary shadow-sm'
                        : kind
                          ? DAY_STYLES[kind]
                          : 'border-border bg-bg text-text-primary hover:border-primary/40 hover:bg-surface-elevated',
                      !inMonth && !selected ? 'text-text-muted/60' : '',
                      disabled
                        ? 'cursor-not-allowed border-border/60 bg-bg/60 text-text-muted/50 hover:border-border/60 hover:bg-bg/60'
                        : '',
                    )}
                  >
                    <span className="font-medium">{format(day, 'd')}</span>
                    <div className="mt-1 flex items-center gap-1 text-2xs">
                      <span
                        className={cn(
                          selected && !kind ? 'text-on-primary/80' : 'text-text-muted',
                          selected && kind ? 'text-current/75' : '',
                        )}
                      >
                        {isToday ? 'Today' : format(day, 'EEE')}
                      </span>
                      {DayIcon ? <DayIcon aria-hidden className="h-3 w-3" data-testid={`day-mark-${kind}`} /> : null}
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
