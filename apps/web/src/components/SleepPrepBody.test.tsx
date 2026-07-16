import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SleepPrepBody } from './SleepPrepBody';
import type { DailyLoopData } from '@/hooks/useDailyLoop';

type SleepProjection = NonNullable<DailyLoopData['sleepProjection']>;

const projection: SleepProjection = {
  status: 'personalized',
  tone: 'watch',
  headline: 'Seal the room earlier tonight',
  summary: 'Today adds evening load and the room ran warm.',
  evidence: [],
  prepActions: ['Seal curtains by 21:30 tonight.', 'Breathing at 20:00, bed 23:15.'],
  protocol: {},
};

describe('SleepPrepBody (Batch 129)', () => {
  it('marks prep actions with a neutral bullet, not a "done"-style green check', () => {
    const { container } = render(<SleepPrepBody projection={projection} />);
    const items = container.querySelectorAll('ul > li');
    expect(items).toHaveLength(2);
    // No lucide check icon (which reads as "already done").
    expect(container.querySelector('svg.lucide-check')).toBeNull();
    // Each item leads with a small round bullet.
    const bullet = items[0].querySelector('span[aria-hidden]');
    expect(bullet?.className).toContain('rounded-full');
    expect(bullet?.className).not.toContain('text-success');
  });
});
