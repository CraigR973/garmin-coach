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

  it('shows verdict tint cues and an accessible legend', () => {
    render(
      <SleepDateCalendar
        selectedDate="2026-07-14"
        maxDate="2026-07-14"
        displayMonth={new Date(2026, 6, 1)}
        onDisplayMonthChange={vi.fn()}
        onSelectDate={vi.fn()}
        verdictsByDate={{ '2026-07-14': 'green', '2026-07-13': 'amber', '2026-07-12': 'red' }}
      />,
    );

    fireEvent.click(screen.getByText('Show calendar'));

    expect(screen.getByLabelText('Verdict legend')).toBeTruthy();
    expect(screen.getByLabelText('Tuesday 14 July 2026 - Green verdict')).toBeTruthy();
    expect(screen.getByLabelText('Monday 13 July 2026 - Amber verdict')).toBeTruthy();
    expect(screen.getByLabelText('Sunday 12 July 2026 - Red verdict')).toBeTruthy();
  });
});
