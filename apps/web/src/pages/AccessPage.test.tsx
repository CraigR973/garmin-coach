import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AccessPage } from './AccessPage';

describe('AccessPage', () => {
  it('offers device activation without a PIN fallback', () => {
    render(<AccessPage />);

    expect(screen.getByTestId('logomark')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Set up this device' })).toBeTruthy();
    expect(screen.getByText(/one-time activation link/i)).toBeTruthy();
    expect(screen.queryByLabelText('PIN')).toBeNull();
    expect(screen.queryByRole('button', { name: /sign in/i })).toBeNull();
  });
});
