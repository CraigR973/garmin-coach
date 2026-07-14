import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SleepDateCalendar } from './SleepDateCalendar';

describe('SleepDateCalendar', () => {
  it('steps the selected date back one day on Previous day', () => {
    const onSelectDate = vi.fn();
    render(<SleepDateCalendar selectedDate="2026-07-14" maxDate="2026-07-14" onSelectDate={onSelectDate} />);

    fireEvent.click(screen.getByLabelText('Previous day'));

    expect(onSelectDate).toHaveBeenCalledWith('2026-07-13');
  });

  it('steps the selected date forward one day on Next day when not at maxDate', () => {
    const onSelectDate = vi.fn();
    render(<SleepDateCalendar selectedDate="2026-07-12" maxDate="2026-07-14" onSelectDate={onSelectDate} />);

    fireEvent.click(screen.getByLabelText('Next day'));

    expect(onSelectDate).toHaveBeenCalledWith('2026-07-13');
  });

  it('disables Next day once the selected date reaches maxDate', () => {
    const onSelectDate = vi.fn();
    render(<SleepDateCalendar selectedDate="2026-07-14" maxDate="2026-07-14" onSelectDate={onSelectDate} />);

    const nextDay = screen.getByLabelText('Next day') as HTMLButtonElement;
    expect(nextDay.disabled).toBe(true);

    fireEvent.click(nextDay);
    expect(onSelectDate).not.toHaveBeenCalled();
  });

  it('still selects any day from the expanded month grid', () => {
    const onSelectDate = vi.fn();
    render(<SleepDateCalendar selectedDate="2026-07-14" maxDate="2026-07-14" onSelectDate={onSelectDate} />);

    fireEvent.click(screen.getByText('Show calendar'));
    fireEvent.click(screen.getByLabelText('Previous month'));
    fireEvent.click(screen.getByLabelText('Sunday 21 June 2026'));

    expect(onSelectDate).toHaveBeenCalledWith('2026-06-21');
  });
});
