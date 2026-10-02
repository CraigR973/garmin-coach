import { describe, expect, it } from 'vitest';
import type { DailyLoopData } from '@/hooks/useDailyLoop';
import { briefOnItsWay, briefState, noteUnread, storedMorning, type StoredMorning } from './storedMorning';

/** Batch 302: a morning is stored when it is graded, and its brief is written into it. */

const graded = {
  id: '22222222-2222-4222-8222-222222222222',
  verdict: 'red',
  outputMarkdown: '',
  notesReadingStatus: 'read',
} as unknown as StoredMorning;
const written = { ...graded, outputMarkdown: '**Verdict:** Red' } as StoredMorning;

type Fields = Pick<DailyLoopData, 'morningAnalysis' | 'gradedMorning' | 'briefGeneration'>;

function day(fields: Partial<Fields>): Fields {
  return { morningAnalysis: null, gradedMorning: null, briefGeneration: null, ...fields };
}

describe('the stored morning', () => {
  it('is the written brief when there is one, and the graded morning until then', () => {
    expect(storedMorning(day({ morningAnalysis: written }))).toBe(written);
    expect(storedMorning(day({ gradedMorning: graded }))).toBe(graded);
    expect(storedMorning(day({}))).toBeNull();
    expect(storedMorning(undefined)).toBeNull();
  });

  it('reads a payload from before the batch, which has no graded morning at all', () => {
    const before = { morningAnalysis: null, briefGeneration: null } as Fields;
    expect(storedMorning(before)).toBeNull();
    expect(briefState(before)).toBeNull();
    expect(briefOnItsWay(before)).toBe(false);
  });
});

describe('where the written brief is', () => {
  it('is written once the brief exists, whatever the status row says', () => {
    const stale = { status: 'failed' as const, reason: 'billing' };
    expect(briefState(day({ morningAnalysis: written, briefGeneration: stale }))).toBe('written');
  });

  it('is being written for a graded morning, until the status says it failed', () => {
    const generating = { status: 'generating' as const, reason: null };
    const failed = { status: 'failed' as const, reason: 'billing' };
    expect(briefState(day({ gradedMorning: graded, briefGeneration: generating }))).toBe('writing');
    expect(briefState(day({ gradedMorning: graded, briefGeneration: failed }))).toBe('failed');
    // No status row at all still means a brief is on its way: the server reads the
    // morning's own age and turns a wait that outlives its limit into a failure.
    expect(briefState(day({ gradedMorning: graded }))).toBe('writing');
  });

  it('has no brief state on a day with no stored morning', () => {
    const failed = { status: 'failed' as const, reason: 'inputs' };
    expect(briefState(day({ briefGeneration: failed }))).toBeNull();
    expect(briefState(null)).toBeNull();
  });
});

describe('his note', () => {
  it('is unread when the reader failed or never ran, and only then', () => {
    expect(noteUnread({ ...graded, notesReadingStatus: 'failed' })).toBe(true);
    expect(noteUnread({ ...graded, notesReadingStatus: 'not_read' })).toBe(true);
    expect(noteUnread({ ...graded, notesReadingStatus: 'read' })).toBe(false);
    expect(noteUnread({ ...graded, notesReadingStatus: 'no_notes' })).toBe(false);
    expect(noteUnread({ ...graded, notesReadingStatus: undefined })).toBe(false);
    expect(noteUnread(null)).toBe(false);
  });
});

describe('a brief on its way', () => {
  it('keeps a screen looking while the status says generating and no brief is written', () => {
    const generating = { status: 'generating' as const, reason: null };
    // Still syncing or grading: no morning yet.
    expect(briefOnItsWay(day({ briefGeneration: generating }))).toBe(true);
    // Graded: the colour is shown, the brief is being written.
    expect(briefOnItsWay(day({ gradedMorning: graded, briefGeneration: generating }))).toBe(true);
  });

  it('stops looking once the brief is written or has failed', () => {
    const generating = { status: 'generating' as const, reason: null };
    const failed = { status: 'failed' as const, reason: 'stale' };
    expect(briefOnItsWay(day({ morningAnalysis: written, briefGeneration: generating }))).toBe(false);
    expect(briefOnItsWay(day({ gradedMorning: graded, briefGeneration: failed }))).toBe(false);
    expect(briefOnItsWay(day({}))).toBe(false);
    expect(briefOnItsWay(undefined)).toBe(false);
  });
});
