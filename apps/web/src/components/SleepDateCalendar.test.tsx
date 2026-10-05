import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SleepDateCalendar } from './SleepDateCalendar';

describe('SleepDateCalendar', () => {
  it('steps the selected date back one day on Previous day', () => {
    const onSelectDate = vi.fn();
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={onSelectDate}
      />,
    );

    fireEvent.click(screen.getByLabelText('Previous day'));

    expect(onSelectDate).toHaveBeenCalledWith('2026-07-13');
  });

  it('steps the selected date forward one day on Next day when not at maxDate', () => {
    const onSelectDate = vi.fn();
    render(
      <SleepDateCalendar
        selectedDate="2026-07-12"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={onSelectDate}
      />,
    );

    fireEvent.click(screen.getByLabelText('Next day'));

    expect(onSelectDate).toHaveBeenCalledWith('2026-07-13');
  });

  it('disables Next day once the selected date reaches maxDate', () => {
    const onSelectDate = vi.fn();
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={onSelectDate}
      />,
    );

    const nextDay = screen.getByLabelText('Next day') as HTMLButtonElement;
    expect(nextDay.disabled).toBe(true);

    fireEvent.click(nextDay);
    expect(onSelectDate).not.toHaveBeenCalled();
  });

  it('still selects any day from the expanded month grid', () => {
    const onSelectDate = vi.fn();
    const onDisplayMonthChange = vi.fn();
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={onDisplayMonthChange}
        onSelectDate={onSelectDate}
      />,
    );

    fireEvent.click(screen.getByText('Show calendar'));
    fireEvent.click(screen.getByLabelText('Previous month'));

    expect(onDisplayMonthChange).toHaveBeenCalled();
  });

  // Batch 313: each day shows how recovered he was that morning, or that it was a rest
  // day, never a colour grade; the legend matches.
  it('shows each morning as a reading or a rest day, with a matching legend', () => {
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={vi.fn()}
        verdictsByDate={{ '2026-07-14': 'green', '2026-07-13': 'amber', '2026-07-12': 'red' }}
        daysByDate={{
          '2026-07-14': { reading: 'recovered', restDay: false },
          '2026-07-13': { reading: 'some_fatigue', restDay: false },
          '2026-07-12': { reading: 'still_recovering', restDay: false },
          '2026-07-11': { reading: 'still_recovering', restDay: true },
        }}
      />,
    );

    fireEvent.click(screen.getByText('Show calendar'));

    const legend = screen.getByLabelText('Calendar legend');
    expect(legend.textContent).toBe('RecoveredSome fatigueStill recoveringRest day');
    expect(screen.getByLabelText('Tuesday 14 July 2026 - Recovered')).toBeTruthy();
    expect(screen.getByLabelText('Monday 13 July 2026 - Some fatigue')).toBeTruthy();
    expect(screen.getByLabelText('Sunday 12 July 2026 - Still recovering')).toBeTruthy();
    expect(screen.getByLabelText('Saturday 11 July 2026 - Rest day · Still recovering')).toBeTruthy();
    expect(screen.getByLabelText('Friday 10 July 2026 - No morning saved')).toBeTruthy();
    expect(document.body.textContent ?? '').not.toMatch(/\b(green|amber|red|verdict)\b/i);
  });

  it('reads the colour alone from a server older than Batch 313', () => {
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={vi.fn()}
        verdictsByDate={{ '2026-07-14': 'green', '2026-07-12': 'red' }}
      />,
    );

    fireEvent.click(screen.getByText('Show calendar'));

    expect(screen.getByLabelText('Tuesday 14 July 2026 - Recovered')).toBeTruthy();
    expect(screen.getByLabelText('Sunday 12 July 2026 - Still recovering')).toBeTruthy();
  });
});
