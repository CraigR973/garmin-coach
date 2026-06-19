import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PinInput } from '../PinInput';

function renderPin(value = '', onChange = vi.fn(), maxLength?: number, label?: string) {
  return { onChange, ...render(<PinInput value={value} onChange={onChange} maxLength={maxLength} label={label} />) };
}

describe('PinInput (default 4 cells)', () => {
  it('renders 4 cells by default', () => {
    renderPin();
    expect(screen.getByLabelText('PIN digit 1')).toBeTruthy();
    expect(screen.getByLabelText('PIN digit 2')).toBeTruthy();
    expect(screen.getByLabelText('PIN digit 3')).toBeTruthy();
    expect(screen.getByLabelText('PIN digit 4')).toBeTruthy();
    expect(screen.queryByLabelText('PIN digit 5')).toBeNull();
  });

  it('auto-advances to next cell on digit input', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} />);
    const cell1 = screen.getByLabelText('PIN digit 1') as HTMLInputElement;
    fireEvent.change(cell1, { target: { value: '5' } });
    expect(onChange).toHaveBeenCalledWith('5');
  });

  it('fills all four digits correctly', () => {
    const onChange = vi.fn();
    const { rerender } = render(<PinInput value="" onChange={onChange} />);
    const cell1 = screen.getByLabelText('PIN digit 1') as HTMLInputElement;
    fireEvent.change(cell1, { target: { value: '1' } });
    rerender(<PinInput value="1" onChange={onChange} />);
    const cell2 = screen.getByLabelText('PIN digit 2') as HTMLInputElement;
    fireEvent.change(cell2, { target: { value: '2' } });
    expect(onChange).toHaveBeenLastCalledWith('12');
  });

  it('backspace on a filled cell clears it', () => {
    const onChange = vi.fn();
    render(<PinInput value="12" onChange={onChange} />);
    const cell2 = screen.getByLabelText('PIN digit 2') as HTMLInputElement;
    fireEvent.keyDown(cell2, { key: 'Backspace' });
    expect(onChange).toHaveBeenCalledWith('1');
  });

  it('backspace on an empty cell moves focus back and clears previous', () => {
    const onChange = vi.fn();
    render(<PinInput value="1" onChange={onChange} />);
    const cell2 = screen.getByLabelText('PIN digit 2') as HTMLInputElement;
    fireEvent.keyDown(cell2, { key: 'Backspace' });
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('paste of 4 digits fills all cells', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} />);
    const cell1 = screen.getByLabelText('PIN digit 1') as HTMLInputElement;
    fireEvent.paste(cell1, {
      clipboardData: { getData: () => '7391' },
    });
    expect(onChange).toHaveBeenCalledWith('7391');
  });

  it('paste strips non-digits', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} />);
    const cell1 = screen.getByLabelText('PIN digit 1');
    fireEvent.paste(cell1, {
      clipboardData: { getData: () => 'ab1234cd' },
    });
    expect(onChange).toHaveBeenCalledWith('1234');
  });

  it('paste clips to maxLength (4)', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} />);
    const cell1 = screen.getByLabelText('PIN digit 1');
    fireEvent.paste(cell1, {
      clipboardData: { getData: () => '12345678' },
    });
    expect(onChange).toHaveBeenCalledWith('1234');
  });
});

describe('PinInput (variable length)', () => {
  it('renders N cells when maxLength is provided', () => {
    renderPin('', vi.fn(), 6);
    for (let i = 1; i <= 6; i++) {
      expect(screen.getByLabelText(`PIN digit ${i}`)).toBeTruthy();
    }
    expect(screen.queryByLabelText('PIN digit 7')).toBeNull();
  });

  it('renders 8 cells with maxLength=8', () => {
    renderPin('', vi.fn(), 8);
    for (let i = 1; i <= 8; i++) {
      expect(screen.getByLabelText(`PIN digit ${i}`)).toBeTruthy();
    }
    expect(screen.queryByLabelText('PIN digit 9')).toBeNull();
  });

  it('paste fills up to maxLength=8', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} maxLength={8} />);
    const cell1 = screen.getByLabelText('PIN digit 1');
    fireEvent.paste(cell1, {
      clipboardData: { getData: () => '12345678' },
    });
    expect(onChange).toHaveBeenCalledWith('12345678');
  });

  it('paste clips to maxLength=6 even if more digits provided', () => {
    const onChange = vi.fn();
    render(<PinInput value="" onChange={onChange} maxLength={6} />);
    const cell1 = screen.getByLabelText('PIN digit 1');
    fireEvent.paste(cell1, {
      clipboardData: { getData: () => '123456789' },
    });
    expect(onChange).toHaveBeenCalledWith('123456');
  });

  it('backspace navigates across all N cells', () => {
    const onChange = vi.fn();
    render(<PinInput value="12345678" onChange={onChange} maxLength={8} />);
    const cell8 = screen.getByLabelText('PIN digit 8') as HTMLInputElement;
    fireEvent.keyDown(cell8, { key: 'Backspace' });
    expect(onChange).toHaveBeenCalledWith('1234567');
  });

  it('auto-advances within N cells', () => {
    const onChange = vi.fn();
    // cell 8 is empty; typing into it should call onChange
    render(<PinInput value="1234567" onChange={onChange} maxLength={8} />);
    const cell8 = screen.getByLabelText('PIN digit 8') as HTMLInputElement;
    fireEvent.change(cell8, { target: { value: '8' } });
    expect(onChange).toHaveBeenCalledWith('12345678');
  });

  it('uses autoComplete prop on first cell', () => {
    render(<PinInput value="" onChange={vi.fn()} autoComplete="new-password" />);
    const cell1 = screen.getByLabelText('PIN digit 1') as HTMLInputElement;
    expect(cell1.autocomplete).toBe('new-password');
  });

  it('defaults to current-password autoComplete on first cell', () => {
    render(<PinInput value="" onChange={vi.fn()} />);
    const cell1 = screen.getByLabelText('PIN digit 1') as HTMLInputElement;
    expect(cell1.autocomplete).toBe('current-password');
  });
});
