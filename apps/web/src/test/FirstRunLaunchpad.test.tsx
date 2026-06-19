import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { FirstRunLaunchpad } from '@/components/FirstRunLaunchpad';

function renderLaunchpad(onClose = vi.fn()) {
  return {
    onClose,
    ...render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<FirstRunLaunchpad onClose={onClose} />} />
          <Route path="/about" element={<div>About route</div>} />
          <Route path="/predictions/specials" element={<div>Specials route</div>} />
          <Route path="/predictions" element={<div>Predictions route</div>} />
          <Route path="/leagues" element={<div>Leagues route</div>} />
        </Routes>
      </MemoryRouter>,
    ),
  };
}

beforeEach(() => {
  localStorage.clear();
});

describe('FirstRunLaunchpad', () => {
  it('routes to the full rules and marks the launchpad as seen', () => {
    const { onClose } = renderLaunchpad();

    fireEvent.click(screen.getByRole('button', { name: /read the full rules/i }));

    expect(onClose).toHaveBeenCalledOnce();
    expect(localStorage.getItem('sss_firstrun_launchpad_seen')).toBe('1');
    expect(screen.getByText('About route')).toBeTruthy();
  });

  it('routes to Specials and first-pick destinations', () => {
    const specials = renderLaunchpad();
    fireEvent.click(screen.getByRole('button', { name: /set your specials/i }));
    expect(specials.onClose).toHaveBeenCalledOnce();
    expect(screen.getByText('Specials route')).toBeTruthy();

    const firstPick = renderLaunchpad();
    fireEvent.click(screen.getByRole('button', { name: /make your first pick/i }));
    expect(firstPick.onClose).toHaveBeenCalledOnce();
    expect(screen.getByText('Predictions route')).toBeTruthy();
  });

  it('routes to join/create a league and marks the launchpad as seen', () => {
    const { onClose } = renderLaunchpad();
    fireEvent.click(screen.getByRole('button', { name: /join or create a league/i }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(localStorage.getItem('sss_firstrun_launchpad_seen')).toBe('1');
    expect(screen.getByText('Leagues route')).toBeTruthy();
  });
});
