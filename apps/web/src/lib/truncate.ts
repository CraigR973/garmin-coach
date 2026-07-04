/**
 * Truncates `text` to at most `maxLength` characters, cutting at the last
 * word boundary rather than mid-word, and appends an ellipsis. Returns the
 * input unchanged when it already fits (Batch 54 — collapsed section
 * summaries used to hard-clip mid-word via CSS `truncate`).
 */
export function truncateWords(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  const slice = text.slice(0, maxLength);
  const lastSpace = slice.lastIndexOf(' ');
  const cut = lastSpace > 0 ? slice.slice(0, lastSpace) : slice;
  return `${cut.trimEnd()}…`;
}
