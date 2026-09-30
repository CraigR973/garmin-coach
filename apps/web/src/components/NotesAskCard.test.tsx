import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { NotesAskCard } from './NotesAskCard';
import { notesAskLine } from '@/lib/notesAsk';

// Batch 297: his note may name a symptom, so Home asks rather than guesses.
describe('notes ask card', () => {
  it('quotes his note and links to the symptom question', () => {
    render(
      <MemoryRouter>
        <NotesAskCard ask words="heartburn kept me awake" />
      </MemoryRouter>,
    );
    expect(screen.getByText('Any symptoms today?')).toBeTruthy();
    expect(
      screen.getByText(
        'Your note mentions “heartburn kept me awake”. If that’s a symptom, tell me, so today’s plan fits.',
      ),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Answer' }).getAttribute('href')).toBe('/check-in');
  });

  it('shows nothing when the note asks nothing, or on a read stored before the reader', () => {
    const { container } = render(
      <MemoryRouter>
        <NotesAskCard ask={false} words="anything" />
        <NotesAskCard ask={undefined} words={undefined} />
      </MemoryRouter>,
    );
    expect(container.textContent).toBe('');
  });

  it('has a line for a note with no quotable words', () => {
    expect(notesAskLine(null)).toBe(
      'Something in your note might be a symptom. If it is, tell me, so today’s plan fits.',
    );
  });
});
