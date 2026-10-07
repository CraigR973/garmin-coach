import { useState } from 'react';
import type {
  GeneratedBlockWeek,
  GeneratedBlockWorkout,
  PlanChange,
  SessionEdits,
} from '@coach/shared';
import { AlertTriangle, ArrowRightLeft, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { selectClassName } from '@/components/plan-builder/styles';
import { sessionDay } from '@/lib/nextPlan';
import {
  ADD,
  ADD_TYPES,
  CANCEL,
  CHANGE,
  EFFORT_PCT,
  EFFORT_SECONDS,
  KEEP_IT,
  MINUTES,
  MOVE,
  MOVE_TO,
  NAME,
  NOTHING_PLANNED,
  RECOVERY_PCT,
  RECOVERY_SECONDS,
  REMOVE,
  REPS,
  SAVE,
  type AddType,
  addTo,
  hoursAndMinutes,
  matchingSets,
  minutesLabel,
  removeQuestion,
  weekDates,
  weekHeading,
} from '@/lib/planChanges';

/** Which panel is open on the page: one at a time. */
export type OpenPanel =
  | { kind: 'change' | 'move' | 'remove'; session: string }
  | { kind: 'add'; date: string }
  | null;

/** Every date of the plan, by week, for "Move to". */
export interface PlanWeekDates {
  weekNumber: number;
  label: string;
  dates: string[];
}

interface PlanWeekCardProps {
  week: GeneratedBlockWeek;
  sessionEdits: Record<string, SessionEdits>;
  planDates: PlanWeekDates[];
  overLongestLine: string | null;
  openPanel: OpenPanel;
  onOpenPanel: (panel: OpenPanel) => void;
  pending: boolean;
  onChanges: (changes: PlanChange[]) => Promise<void>;
}

/** "19–25 Oct", or "26 Oct–1 Nov" across a month. */
function shortSpan(startDate: string, endDate: string): string {
  const [, startDay, startMonth] = sessionDay(startDate).split(' ');
  const [, endDay, endMonth] = sessionDay(endDate).split(' ');
  return startMonth === endMonth
    ? `${startDay}–${endDay} ${endMonth}`
    : `${startDay} ${startMonth}–${endDay} ${endMonth}`;
}

/**
 * Batch 324: one week of the proposed plan, every day of it, and what he can change.
 *
 * Each session has Change (its name, and its minutes or its interval set's five numbers,
 * whichever the server says it has), Move (to any day of the plan) and Remove; each day has
 * Add. Every change goes to the server, which checks it and says what it did.
 */
export function PlanWeekCard({
  week,
  sessionEdits,
  planDates,
  overLongestLine,
  openPanel,
  onOpenPanel,
  pending,
  onChanges,
}: PlanWeekCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-base">
          <span>{weekHeading(week.weekNumber, week.label)}</span>
          <span className="text-xs font-normal text-text-muted">
            {shortSpan(week.startDate, week.endDate)}
            {typeof week.totalMin === 'number' ? ` · ${hoursAndMinutes(week.totalMin)}` : ''}
          </span>
        </CardTitle>
        {overLongestLine ? (
          <p className="flex items-start gap-1.5 text-xs text-warning-text" role="note">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{overLongestLine}</span>
          </p>
        ) : null}
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {weekDates(week.startDate).map((date) => {
            const sessions = week.workouts
              .filter((workout) => workout.workoutDate === date)
              .sort((a, b) => (a.slot ?? 0) - (b.slot ?? 0));
            const day = sessionDay(date);
            const adding = openPanel?.kind === 'add' && openPanel.date === date;
            return (
              <li key={date} className="space-y-2">
                {sessions.length === 0 ? (
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <p className="text-text-muted">
                      <span className="mr-2 text-xs">{day}</span>
                      {NOTHING_PLANNED}
                    </p>
                  </div>
                ) : (
                  sessions.map((workout) => (
                    <SessionRow
                      key={workout.id ?? `${date}-${workout.slot ?? 0}`}
                      workout={workout}
                      edits={workout.id ? sessionEdits[workout.id] : undefined}
                      planDates={planDates}
                      openPanel={openPanel}
                      onOpenPanel={onOpenPanel}
                      pending={pending}
                      onChanges={onChanges}
                    />
                  ))
                )}
                {adding ? (
                  <AddPanel
                    date={date}
                    pending={pending}
                    onCancel={() => onOpenPanel(null)}
                    onAdd={(sessionType, minutes) =>
                      onChanges([{ kind: 'add', date, sessionType, minutes }])
                    }
                  />
                ) : (
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label={addTo(day)}
                      onClick={() => onOpenPanel({ kind: 'add', date })}
                    >
                      <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
                      {ADD}
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function SessionRow({
  workout,
  edits,
  planDates,
  openPanel,
  onOpenPanel,
  pending,
  onChanges,
}: {
  workout: GeneratedBlockWorkout;
  edits: SessionEdits | undefined;
  planDates: PlanWeekDates[];
  openPanel: OpenPanel;
  onOpenPanel: (panel: OpenPanel) => void;
  pending: boolean;
  onChanges: (changes: PlanChange[]) => Promise<void>;
}) {
  const day = sessionDay(workout.workoutDate);
  const id = workout.id;
  const open = id && openPanel && 'session' in openPanel && openPanel.session === id;
  const panel = open ? openPanel.kind : null;

  return (
    <div className="rounded-lg border border-border px-3 py-2 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs text-text-muted">{day}</p>
          <p className="font-medium text-text-primary">{workout.title}</p>
          <p className="text-xs text-text-muted">
            {workout.plannedDurationMin ? `${workout.plannedDurationMin} min` : ''}
            {workout.plannedDurationMin && workout.intensityTarget ? ' · ' : ''}
            {workout.intensityTarget ?? ''}
          </p>
        </div>
        {id ? (
          <div className="flex shrink-0 gap-1">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`${CHANGE} ${workout.title} on ${day}`}
              onClick={() => onOpenPanel({ kind: 'change', session: id })}
            >
              <Pencil className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`${MOVE} ${workout.title} on ${day}`}
              onClick={() => onOpenPanel({ kind: 'move', session: id })}
            >
              <ArrowRightLeft className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`${REMOVE} ${workout.title} on ${day}`}
              onClick={() => onOpenPanel({ kind: 'remove', session: id })}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
          </div>
        ) : null}
      </div>
      {id && panel === 'change' ? (
        <ChangePanel
          workout={workout}
          session={id}
          edits={edits}
          pending={pending}
          onCancel={() => onOpenPanel(null)}
          onChanges={onChanges}
        />
      ) : null}
      {id && panel === 'move' ? (
        <MovePanel
          workout={workout}
          session={id}
          planDates={planDates}
          pending={pending}
          onCancel={() => onOpenPanel(null)}
          onChanges={onChanges}
        />
      ) : null}
      {id && panel === 'remove' ? (
        <div className="mt-2 space-y-2 border-t border-border pt-2">
          <p className="text-sm text-text-secondary">{removeQuestion(workout.title, day)}</p>
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() => onChanges([{ kind: 'remove', session: id }])}
            >
              {REMOVE}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => onOpenPanel(null)}>
              {KEEP_IT}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function numberOrNull(value: string): number | null {
  if (value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}

function ChangePanel({
  workout,
  session,
  edits,
  pending,
  onCancel,
  onChanges,
}: {
  workout: GeneratedBlockWorkout;
  session: string;
  edits: SessionEdits | undefined;
  pending: boolean;
  onCancel: () => void;
  onChanges: (changes: PlanChange[]) => Promise<void>;
}) {
  const intervals = edits?.intervals ?? null;
  const [title, setTitle] = useState(workout.title);
  const [minutes, setMinutes] = useState(String(workout.plannedDurationMin ?? ''));
  const [numbers, setNumbers] = useState({
    repeat: String(intervals?.repeat ?? ''),
    workSec: String(intervals?.workSec ?? ''),
    workPct: String(intervals?.workPct ?? ''),
    restSec: String(intervals?.restSec ?? ''),
    restPct: String(intervals?.restPct ?? ''),
  });

  const save = () => {
    const changes: PlanChange[] = [];
    const name = title.trim().replace(/\s+/g, ' ');
    if (name && name !== workout.title) changes.push({ kind: 'title', session, title: name });
    const length = numberOrNull(minutes);
    if (edits?.minutes && length !== null && length !== workout.plannedDurationMin) {
      changes.push({ kind: 'minutes', session, minutes: length });
    }
    if (intervals) {
      const block = {
        repeat: numberOrNull(numbers.repeat),
        workSec: numberOrNull(numbers.workSec),
        workPct: numberOrNull(numbers.workPct),
        restSec: numberOrNull(numbers.restSec),
        restPct: numberOrNull(numbers.restPct),
      };
      const complete = Object.values(block).every((value) => value !== null);
      const moved = (Object.keys(block) as (keyof typeof block)[]).some(
        (key) => block[key] !== intervals[key],
      );
      if (complete && moved) {
        changes.push({
          kind: 'intervals',
          session,
          repeat: block.repeat as number,
          workSec: block.workSec as number,
          workPct: block.workPct as number,
          restSec: block.restSec as number,
          restPct: block.restPct as number,
        });
      }
    }
    if (changes.length === 0) {
      onCancel();
      return;
    }
    void onChanges(changes);
  };

  const numberField = (key: keyof typeof numbers, label: string) => (
    <label className="space-y-1 text-xs text-text-secondary">
      <span className="block">{label}</span>
      <Input
        aria-label={label}
        inputMode="numeric"
        value={numbers[key]}
        onChange={(event) => setNumbers({ ...numbers, [key]: event.target.value })}
      />
    </label>
  );

  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      <label className="block space-y-1 text-xs text-text-secondary">
        <span className="block">{NAME}</span>
        <Input aria-label={NAME} value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      {edits?.minutes ? (
        <label className="block space-y-1 text-xs text-text-secondary">
          <span className="block">{minutesLabel(edits.minutes.min, edits.minutes.max)}</span>
          <Input
            aria-label={MINUTES}
            inputMode="numeric"
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
          />
        </label>
      ) : null}
      {intervals ? (
        <div className="space-y-2">
          <p className="text-xs text-text-muted">{intervals.label}</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {numberField('repeat', REPS)}
            {numberField('workSec', EFFORT_SECONDS)}
            {numberField('workPct', EFFORT_PCT)}
            {numberField('restSec', RECOVERY_SECONDS)}
            {numberField('restPct', RECOVERY_PCT)}
          </div>
          {intervals.matchingSets > 1 ? (
            <p className="text-xs text-text-secondary">{matchingSets(intervals.matchingSets)}</p>
          ) : null}
        </div>
      ) : null}
      {edits?.fixed ? <p className="text-xs text-text-muted">{edits.fixed}</p> : null}
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={pending} onClick={save}>
          {SAVE}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {CANCEL}
        </Button>
      </div>
    </div>
  );
}

function MovePanel({
  workout,
  session,
  planDates,
  pending,
  onCancel,
  onChanges,
}: {
  workout: GeneratedBlockWorkout;
  session: string;
  planDates: PlanWeekDates[];
  pending: boolean;
  onCancel: () => void;
  onChanges: (changes: PlanChange[]) => Promise<void>;
}) {
  const [toDate, setToDate] = useState(workout.workoutDate);
  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      <label className="block space-y-1 text-xs text-text-secondary">
        <span className="block">{MOVE_TO}</span>
        <select
          aria-label={MOVE_TO}
          className={selectClassName}
          value={toDate}
          onChange={(event) => setToDate(event.target.value)}
        >
          {planDates.map((week) => (
            <optgroup key={week.weekNumber} label={weekHeading(week.weekNumber, week.label)}>
              {week.dates.map((date) => (
                <option key={date} value={date}>
                  {sessionDay(date)}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={pending || toDate === workout.workoutDate}
          onClick={() => onChanges([{ kind: 'move', session, toDate }])}
        >
          {MOVE}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {CANCEL}
        </Button>
      </div>
    </div>
  );
}

function AddPanel({
  date,
  pending,
  onCancel,
  onAdd,
}: {
  date: string;
  pending: boolean;
  onCancel: () => void;
  onAdd: (sessionType: AddType, minutes: number | null) => Promise<void>;
}) {
  const [sessionType, setSessionType] = useState<AddType>('zone2');
  const [minutes, setMinutes] = useState('60');
  const choose = (next: AddType) => {
    setSessionType(next);
    const preset = ADD_TYPES.find((option) => option.type === next)?.minutes ?? null;
    setMinutes(preset === null ? '' : String(preset));
  };
  return (
    <div className="space-y-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm">
      <p className="text-xs font-medium text-text-secondary">{addTo(sessionDay(date))}</p>
      <div className="grid grid-cols-2 gap-2">
        <select
          aria-label={addTo(sessionDay(date))}
          className={selectClassName}
          value={sessionType}
          onChange={(event) => choose(event.target.value as AddType)}
        >
          {ADD_TYPES.map((option) => (
            <option key={option.type} value={option.type}>
              {option.label}
            </option>
          ))}
        </select>
        <Input
          aria-label={MINUTES}
          inputMode="numeric"
          placeholder={MINUTES}
          value={minutes}
          onChange={(event) => setMinutes(event.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={pending}
          onClick={() => void onAdd(sessionType, numberOrNull(minutes))}
        >
          {ADD}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {CANCEL}
        </Button>
      </div>
    </div>
  );
}
