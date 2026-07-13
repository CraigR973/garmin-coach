import { describe, expect, it } from 'vitest';
import { markdownToSpeechText } from './markdownSpeech';

describe('markdownToSpeechText', () => {
  it('strips markdown markers into readable speech text', () => {
    const markdown = ['# Morning', '', '- **Green light** — keep the ride.', '', 'Read [Sleep](https://coach.test/sleep).'].join('\n');

    expect(markdownToSpeechText(markdown)).toBe('Morning\n\nGreen light — keep the ride.\n\nRead Sleep.');
  });

  it('turns tables into spoken rows without separator noise', () => {
    const markdown = ['| Metric | Last night |', '| --- | --- |', '| HRV | 51 |'].join('\n');

    expect(markdownToSpeechText(markdown)).toBe('Metric, Last night\nHRV, 51');
  });
});

