import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { buildInviteMessage, shareInvite } from '@/lib/invite';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const PARAMS = {
  leagueName: 'Test League',
  joinCode: 'ABC123',
  origin: 'https://example.com',
};

describe('buildInviteMessage', () => {
  it('contains the league name', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg).toContain('Test League');
  });

  it('contains the join code', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg).toContain('ABC123');
  });

  it('contains the app install URL (home, not a deep link)', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg).toContain('https://example.com');
    // The /join/ deep link is intentionally absent — links always open in browser
    expect(msg).not.toContain('/join/ABC123');
  });

  it('contains in-app navigation steps', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg).toContain('Leagues');
    expect(msg).toContain('Join by code');
  });

  it('puts install guidance before the league details so the url does not read like a code', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg.indexOf('Install the app first:')).toBeLessThan(msg.indexOf('League: Test League'));
    expect(msg.indexOf('https://example.com')).toBeLessThan(msg.indexOf('League: Test League'));
    expect(msg.indexOf('https://example.com')).toBeLessThan(msg.indexOf('Join code: ABC123'));
  });

  it('leads with the fantasy-football, predict-once hook', () => {
    const msg = buildInviteMessage(PARAMS).toLowerCase();
    expect(msg).toContain('fantasy football');
    expect(msg).toContain('predict once');
  });

  it('covers both new and existing app users', () => {
    const msg = buildInviteMessage(PARAMS).toLowerCase();
    expect(msg).toContain('create an account');
    expect(msg).toContain('already have the app');
  });

  it('mentions Calcio', () => {
    expect(buildInviteMessage(PARAMS)).toContain('Calcio');
  });

  it('stays slim — defers rules, Specials and lore to the in-app guide', () => {
    const msg = buildInviteMessage(PARAMS);
    expect(msg).not.toContain('spreadsheet');
    expect(msg.toLowerCase()).not.toContain('pre-tournament checklist');
    expect(msg).not.toContain('Specials');
    expect(msg.length).toBeLessThan(400);
  });
});

describe('shareInvite — navigator.share absent', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', {
      share: undefined,
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('falls back to clipboard and returns "copied"', async () => {
    const result = await shareInvite({ message: 'hello' });
    expect(result).toBe('copied');
    expect(navigator.clipboard.writeText).toHaveBeenCalled();
  });
});

describe('shareInvite — navigator.share present', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', {
      share: vi.fn().mockResolvedValue(undefined),
      clipboard: { writeText: vi.fn() },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('calls navigator.share with text only (no url param) and returns "shared"', async () => {
    const result = await shareInvite({ message: 'hello' });
    expect(result).toBe('shared');
    expect(navigator.share).toHaveBeenCalledWith({ text: 'hello' });
  });

  it('returns "cancelled" (not error) when user dismisses the share sheet', async () => {
    const abortErr = Object.assign(new Error('share cancelled'), { name: 'AbortError' });
    vi.mocked(navigator.share).mockRejectedValueOnce(abortErr);
    const result = await shareInvite({ message: 'hello' });
    expect(result).toBe('cancelled');
  });

  it('re-throws non-abort errors', async () => {
    const networkErr = new Error('network failure');
    vi.mocked(navigator.share).mockRejectedValueOnce(networkErr);
    await expect(shareInvite({ message: 'hello' })).rejects.toThrow('network failure');
  });
});
