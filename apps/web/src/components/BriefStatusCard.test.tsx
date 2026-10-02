import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  BRIEF_RETRY_LABEL,
  BRIEF_UNWRITTEN_CHECKIN_LINE,
  BRIEF_UNWRITTEN_LINE,
  BRIEF_UNWRITTEN_TITLE,
  BRIEF_UNWRITTEN_TOAST,
  BRIEF_WRITING_LINE,
  BRIEF_WRITING_TITLE,
  NOTE_UNREAD_LINE,
  SEE_TODAY_LABEL,
} from '@/lib/copy';
import { BriefStatusCard } from './BriefStatusCard';

/** Batch 302: the slot under the colour for a morning whose brief is not written. */

describe('BriefStatusCard', () => {
  it('says the brief is being written, and that the call and plan are already there', () => {
    render(<BriefStatusCard state="writing" />);

    const card = screen.getByRole('status', { name: 'Writing your brief' });
    expect(card.textContent).toContain('Writing your brief');
    expect(card.textContent).toContain(
      "Today's call and your plan are ready above. The written brief lands in a moment.",
    );
    // Nothing to retry while it is still on its way.
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('says the written brief did not finish, and tries again without leaving the page', async () => {
    const onRetry = vi.fn();
    render(<BriefStatusCard state="failed" onRetry={onRetry} />);

    const card = screen.getByRole('status', { name: 'Written brief did not finish' });
    expect(card.textContent).toContain("Couldn't finish your written brief");
    expect(card.textContent).toContain(
      "Today's call and your plan above are complete without it. Your check-in is saved.",
    );
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('offers no retry on a day that is over, and none twice while one is being sent', () => {
    const { rerender } = render(<BriefStatusCard state="failed" />);
    expect(screen.queryByRole('button')).toBeNull();

    rerender(<BriefStatusCard state="failed" onRetry={() => undefined} retrying />);
    expect((screen.getByRole('button', { name: 'Try again' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('says his note was not read, in either state, and only when it was not', () => {
    const line =
      "I couldn't read your note this morning, so today's call comes from your numbers and your answers alone.";
    const { rerender } = render(<BriefStatusCard state="failed" noteUnread />);
    expect(screen.getByText(line)).toBeTruthy();

    rerender(<BriefStatusCard state="writing" noteUnread />);
    expect(screen.getByText(line)).toBeTruthy();

    rerender(<BriefStatusCard state="writing" />);
    expect(screen.queryByText(line)).toBeNull();
  });

  it('uses the words Craig signed off, and no others', () => {
    // The draft is the record of the sign-off, so a reworded line fails here until the
    // draft, and so the sign-off, follows.
    const draft = readFileSync(
      resolve(__dirname, '../../../../docs/drafts/2026-10-02-batch-302-wording.md'),
      'utf8',
    )
      .replace(/\n>\s?/g, ' ')
      .replace(/\s+/g, ' ');

    expect(draft).toContain('signed off by Craig on Mark\'s behalf, 2 Oct 2026');
    for (const words of [
      BRIEF_WRITING_TITLE,
      BRIEF_WRITING_LINE,
      BRIEF_UNWRITTEN_TITLE,
      BRIEF_UNWRITTEN_LINE,
      BRIEF_UNWRITTEN_CHECKIN_LINE,
      BRIEF_UNWRITTEN_TOAST,
      BRIEF_RETRY_LABEL,
      SEE_TODAY_LABEL,
      NOTE_UNREAD_LINE,
    ]) {
      expect(draft, words).toContain(words);
    }
  });
});
