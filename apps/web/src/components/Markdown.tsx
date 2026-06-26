import { memo } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

/**
 * Themed markdown renderer for AI output (morning verdict, post-workout, reviews,
 * trends, handover narrative).
 *
 * The coaching prompt asks Claude to **bold each bullet headline** and emit a
 * metrics-vs-baselines table (ARCHITECTURE §4). Until now `outputMarkdown` was
 * dumped into a `whitespace-pre-wrap` div, so bold showed as literal `**` and
 * tables as raw `| pipes |`. This renders it properly, styled to the design
 * tokens. GFM (remark-gfm) gives tables, strikethrough and task lists.
 *
 * react-markdown does not render raw HTML by default, so this is XSS-safe.
 */

const components: Components = {
  h1: ({ children }) => (
    <h1 className="mt-5 mb-2 text-lg font-semibold tracking-tight text-text-primary first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-5 mb-2 text-base font-semibold tracking-tight text-text-primary first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-4 mb-1.5 text-sm font-semibold tracking-tight text-text-primary first:mt-0">
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-4 mb-1.5 text-sm font-semibold text-text-secondary first:mt-0">{children}</h4>
  ),
  p: ({ children }) => <p className="my-2 leading-6 text-text-primary first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-text-primary">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="my-2 ml-4 list-disc space-y-1 marker:text-text-muted">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 ml-4 list-decimal space-y-1 marker:text-text-muted">{children}</ol>,
  li: ({ children }) => <li className="leading-6 text-text-primary">{children}</li>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-primary underline underline-offset-2 hover:text-primary-dark"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-accent/40 pl-3 text-text-secondary italic">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-border" />,
  code: ({ children }) => (
    <code className="rounded bg-surface-elevated px-1.5 py-0.5 font-mono text-[0.85em] text-text-primary">
      {children}
    </code>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-xl border border-border">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-elevated">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-border px-3 py-2 text-left font-semibold text-text-secondary">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border px-3 py-2 text-text-primary last:border-0">{children}</td>
  ),
};

interface MarkdownProps {
  children: string;
  className?: string;
}

export const Markdown = memo(function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn('text-sm text-text-primary', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
});
