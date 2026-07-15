import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { VerdictHero } from './VerdictHero';

describe('VerdictHero', () => {
  it.each([
    ['green', 'Good to go', 'Green verdict'],
    ['amber', 'Take it easier', 'Amber verdict'],
    ['red', 'Rest or substitute', 'Red verdict'],
  ])('renders the %s verdict copy with the branded mark ring', (verdict, label, cue) => {
    render(<VerdictHero verdict={verdict} dateLabel="Saturday 20 June" />);

    expect(screen.getByRole('region', { name: "Today's verdict" })).toBeTruthy();
    expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText(cue)).toBeTruthy();
    expect(screen.getByText('Saturday 20 June')).toBeTruthy();
    expect(screen.getByTestId('verdict-mark-ring')).toBeTruthy();
    expect(screen.getByTestId('logomark')).toBeTruthy();
  });

  it('renders the pending state without changing the a11y label', () => {
    render(<VerdictHero verdict={null} />);

    expect(screen.getByRole('region', { name: "Today's verdict" })).toBeTruthy();
    expect(screen.getByText('Not ready yet')).toBeTruthy();
    expect(screen.getByText('Verdict pending')).toBeTruthy();
    expect(screen.getByTestId('verdict-mark-ring')).toBeTruthy();
  });

  it('allows the plain-English line to be overridden', () => {
    render(<VerdictHero verdict="green" line="Sleep held steady despite the late finish." />);

    expect(screen.getByText('Sleep held steady despite the late finish.')).toBeTruthy();
  });

  it('renders an optional feel recap inside the hero', () => {
    render(
      <MemoryRouter>
        <VerdictHero
          verdict="green"
          recap={{
            title: 'How you feel today',
            text: 'You said: OK · a bit more tired',
            ctaLabel: 'Change',
            ctaTo: '/check-in',
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('How you feel today')).toBeTruthy();
    expect(screen.getByText('You said: OK · a bit more tired')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Change' }).getAttribute('href')).toBe('/check-in');
  });
});
