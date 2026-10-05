import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { TodaysCall } from '@coach/shared';
import { describe, expect, it } from 'vitest';
import { NOT_READY_CALL } from '@/lib/todaysCall';
import { TodaysCallHero } from './TodaysCallHero';

// Batch 313: the hero renders the stored call word for word, in its look. The words
// themselves are pinned on the server (test_batch_313_todays_call.py), which picks them.
const call = (overrides: Partial<TodaysCall>): TodaysCall => ({
  state: 1,
  key: 'green_light',
  headline: 'Green light',
  line: "You're recovered. Today's session is on as written. Make it count.",
  reading: 'recovered',
  readingWords: 'Recovered',
  look: 'go',
  ...overrides,
});

describe('TodaysCallHero', () => {
  it.each([
    ['go', call({})],
    [
      'adjust',
      call({
        state: 5,
        key: 'take_the_edge_off',
        headline: 'Take the edge off',
        line: "There's some fatigue about. Ride the full session with the hard efforts eased a zone; easy riding stays as planned.",
        reading: 'some_fatigue',
        readingWords: 'Some fatigue',
        look: 'adjust',
      }),
    ],
    [
      'recover',
      call({
        state: 8,
        key: 'recovery_day',
        headline: 'Recovery day',
        line: "Your body's still recovering. The hard session will do more for you on a fresher day — today, rest or an easy spin.",
        reading: 'still_recovering',
        readingWords: 'Still recovering',
        look: 'recover',
      }),
    ],
    [
      'warning',
      call({
        state: 11,
        key: 'no_training',
        headline: 'No training today',
        line: "The symptoms you've reported rule out training today.",
        reading: 'still_recovering',
        readingWords: 'Still recovering',
        look: 'warning',
      }),
    ],
  ])('renders a %s call word for word, with its reading as the chip', (look, shown) => {
    render(<TodaysCallHero call={shown} dateLabel="Wednesday 7 October" />);

    const hero = screen.getByRole('region', { name: "Today's call" });
    expect(hero.getAttribute('data-look')).toBe(look);
    expect(hero.getAttribute('data-state')).toBe(String(shown.state));
    expect(screen.getByText(shown.headline)).toBeTruthy();
    expect(screen.getByText(shown.line)).toBeTruthy();
    expect(screen.getByText(shown.readingWords)).toBeTruthy();
    expect(screen.getByTestId(`call-icon-${look}`)).toBeTruthy();
    expect(screen.getByTestId('call-mark-ring')).toBeTruthy();
    expect(hero.textContent ?? '').not.toMatch(/\b(amber|red|verdict)\b/i);
  });

  it('puts the greeting in front of the line on Home', () => {
    render(<TodaysCallHero call={call({})} lead="Good morning, Mark." />);

    expect(
      screen.getByText("Good morning, Mark. You're recovered. Today's session is on as written. Make it count."),
    ).toBeTruthy();
  });

  it('shows the not-ready call when no morning is stored', () => {
    render(<TodaysCallHero call={null} />);

    expect(screen.getByRole('region', { name: "Today's call" }).getAttribute('data-state')).toBe('17');
    expect(screen.getByText(NOT_READY_CALL.headline)).toBeTruthy();
    expect(screen.getByText("Today's call lands once your overnight data has synced.")).toBeTruthy();
    expect(screen.getByText('Waiting for data')).toBeTruthy();
  });

  it('keeps the date and the chip at the raised readable floor (Batch 127)', () => {
    render(<TodaysCallHero call={call({})} dateLabel="Saturday 20 June" />);

    expect(screen.getByText('Saturday 20 June').className).toContain('text-xs');
    expect(screen.getByText('Recovered').className).toContain('text-xs');
  });

  it('lets the insufficient-data message replace the line', () => {
    render(<TodaysCallHero call={call({})} line="Not enough overnight data to judge today." />);

    expect(screen.getByText('Not enough overnight data to judge today.')).toBeTruthy();
  });

  it('renders an optional feel recap inside the hero', () => {
    render(
      <MemoryRouter>
        <TodaysCallHero
          call={call({})}
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
    expect(screen.getByRole('link', { name: 'Change' }).getAttribute('href')).toBe('/check-in');
  });
});
