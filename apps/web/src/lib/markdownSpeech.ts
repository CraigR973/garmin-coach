function cleanInlineMarkdown(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/~~(.*?)~~/g, '$1')
    .replace(/^\s*>\s?/g, '')
    .trim();
}

function isMarkdownTableSeparator(line: string): boolean {
  return /^[:\-|\s]+$/.test(line) && line.includes('-');
}

export function markdownToSpeechText(markdown: string): string {
  const lines = markdown
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```/g, '').trim())
    .split('\n');

  const spokenLines: string[] = [];

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();

    if (!trimmed) {
      if (spokenLines.at(-1) !== '') {
        spokenLines.push('');
      }
      continue;
    }

    if (isMarkdownTableSeparator(trimmed)) {
      continue;
    }

    const withoutPrefix = trimmed
      .replace(/^#{1,6}\s+/, '')
      .replace(/^[-*+]\s+/, '')
      .replace(/^\d+\.\s+/, '')
      .replace(/^\[[ xX]\]\s+/, '');

    if (withoutPrefix.includes('|')) {
      const cells = withoutPrefix
        .split('|')
        .map((cell) => cleanInlineMarkdown(cell))
        .filter(Boolean);

      if (cells.length > 0) {
        spokenLines.push(cells.join(', '));
      }
      continue;
    }

    const cleaned = cleanInlineMarkdown(withoutPrefix);
    if (cleaned) {
      spokenLines.push(cleaned);
    }
  }

  return spokenLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

