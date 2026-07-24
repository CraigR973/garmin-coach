import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Sheet } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

interface MoveWorkoutDayOption {
  date: string;
  label: string;
  detail: string;
  isToday: boolean;
  isCurrent: boolean;
  isPast: boolean;
}

interface MoveWorkoutSheetProps {
  open: boolean;
  workoutTitle: string;
  busy: boolean;
  days: MoveWorkoutDayOption[];
  onClose: () => void;
  onSelect: (targetDate: string) => void;
}

export function MoveWorkoutSheet({ open, workoutTitle, busy, days, onClose, onSelect }: MoveWorkoutSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={`Move ${workoutTitle}`}>
      <div className="space-y-3">
        <p className="text-sm text-text-secondary">Choose a day in the current plan window.</p>
        <div className="space-y-2">
          {days.map((day) => (
            <Button
              key={day.date}
              type="button"
              variant="outline"
              disabled={busy || day.isCurrent || day.isPast}
              className={cn(
                'h-auto w-full justify-start rounded-xl px-4 py-3 text-left',
                (day.isCurrent || day.isPast) && 'opacity-60',
              )}
              onClick={() => onSelect(day.date)}
            >
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">{day.label}</span>
                  {day.isToday && <Badge variant="default">Today</Badge>}
                  {day.isCurrent && <Badge variant="muted">Current day</Badge>}
                  {day.isPast && <Badge variant="muted">Past day</Badge>}
                </span>
                <span className="mt-1 block text-xs text-text-secondary">
                  {day.isPast ? `${day.detail} · unavailable for moves` : day.detail}
                </span>
              </span>
            </Button>
          ))}
        </div>
      </div>
    </Sheet>
  );
}
