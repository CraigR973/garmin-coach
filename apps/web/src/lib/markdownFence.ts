/**
 * A read stored wrapped whole in one code block (a "```markdown", "```md" or bare "```"
 * line first and a closing "```" last) renders as raw markdown in a code box. A ride read
 * was stored that way on 10 Nov 2026 by a repair call that passed every check (Decision
 * #501). The server now takes such a wrapper off before it keeps a repair
 * (`plain_words_repair.unfenced`, which this mirrors); this shows any read stored before
 * that as the markdown it is.
 */
const WHOLE_FENCE = /^```[ \t]*(?:markdown|md)?[ \t]*\n([\s\S]*)\n[ \t]*```$/i;

/** The markdown inside one fence round the whole text; anything else exactly as it is. */
export function unwrapWholeFence(markdown: string): string {
  const match = WHOLE_FENCE.exec(markdown.trim());
  if (!match || match[1].includes('```')) return markdown;
  return match[1].trim();
}
