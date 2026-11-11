import { describe, expect, it } from 'vitest';
import { unwrapWholeFence } from './markdownFence';

// Invented wording, shaped like a post-ride read.
const READ = '## Workout rating\n\n**Steady.** Your heart rate drifted 3.1% across the work.';

describe('unwrapWholeFence', () => {
  it.each(['markdown', 'md', '', 'Markdown', 'markdown '])(
    'takes off one "%s" fence round the whole read',
    (info) => {
      expect(unwrapWholeFence(`\n\`\`\`${info}\n${READ}\n\`\`\`\n`)).toBe(READ);
    },
  );

  it.each([
    READ,
    'Before it.\n\n```\nnot a wrapper\n```\n\nAfter it.',
    '```markdown\nOne.\n```\n\n```markdown\nTwo.\n```',
    `\`\`\`markdown\n${READ}\n\`\`\`\n\nA line after the fence.`,
    `A line before the fence.\n\n\`\`\`markdown\n${READ}\n\`\`\``,
    "```python\nprint('hello')\n```",
    `\`\`\`markdown\n${READ}`,
  ])('leaves anything else exactly as it is (%#)', (markdown) => {
    expect(unwrapWholeFence(markdown)).toBe(markdown);
  });
});
