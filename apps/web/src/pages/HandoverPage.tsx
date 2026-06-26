import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { handoverEnvelopeSchema } from '@coach/shared';
import { Download, FileText, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Markdown } from '@/components/Markdown';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';

type HandoverEnvelope = typeof handoverEnvelopeSchema._type;
type HandoverData = HandoverEnvelope['data'];

const BASE = '/api/v1/handover';

async function fetchHandover() {
  const response = await apiFetch<unknown>(BASE);
  return handoverEnvelopeSchema.parse(response);
}

async function runHandover() {
  const response = await apiFetch<unknown>(`${BASE}/run`, { method: 'POST' });
  return handoverEnvelopeSchema.parse(response);
}

function downloadMarkdown(data: HandoverData): void {
  // Download the deterministic, portable markdown the API already returned — no
  // extra round-trip, so it works offline-safe from cached data.
  try {
    const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `handover-${data.subjectDate}.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch {
    toast.error('Download is not supported in this browser.');
  }
}

export function HandoverPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['handover'], queryFn: fetchHandover });

  const runMutation = useMutation({
    mutationFn: runHandover,
    onSuccess: (envelope) => {
      queryClient.setQueryData(['handover'], envelope);
      if (envelope.errors.length > 0) {
        toast.error(envelope.errors[0]?.detail ?? 'Failed to generate the handover');
      } else {
        toast.success('Handover generated');
      }
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to generate the handover'),
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Handover" />

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Assembling the handover…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Handover unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error
                ? query.error.message
                : 'The handover could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <HandoverBody
          data={query.data.data}
          generating={runMutation.isPending}
          onGenerate={() => runMutation.mutate()}
        />
      )}
    </div>
  );
}

function HandoverBody({
  data,
  generating,
  onGenerate,
}: {
  data: HandoverData;
  generating: boolean;
  onGenerate: () => void;
}) {
  const { markdown, export: stored } = data;
  const [showRaw, setShowRaw] = useState(false);

  return (
    <div className="space-y-4">
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden />
            Full briefing for a new AI chat
          </CardTitle>
          <CardDescription>
            Everything your coach knows about you — profile, plan, baselines, reviews and what you&apos;re
            testing — in one document. Always up to date, ready to paste into a new AI chat.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => downloadMarkdown(data)}>
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Download
          </Button>
          <Button type="button" onClick={onGenerate} disabled={generating}>
            <Sparkles className="mr-2 h-4 w-4" aria-hidden />
            {stored ? 'Rewrite summary' : 'Write summary'}
          </Button>
        </CardContent>
      </Card>

      {stored ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden />
              Written summary
            </CardTitle>
            <CardDescription>Written {new Date(stored.generatedAtUtc).toLocaleString()}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-xl border border-border bg-bg px-4 py-3">
              <Markdown>{stored.markdown}</Markdown>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" aria-hidden />
              The document
            </CardTitle>
            <Button type="button" variant="ghost" size="sm" onClick={() => setShowRaw((v) => !v)}>
              {showRaw ? 'Show formatted' : 'View raw text'}
            </Button>
          </div>
          <CardDescription>Exactly what “Download” saves.</CardDescription>
        </CardHeader>
        <CardContent>
          {showRaw ? (
            <div className="max-h-[480px] overflow-auto rounded-xl border border-border bg-bg px-4 py-3 font-mono text-xs leading-5 text-text-primary whitespace-pre-wrap">
              {markdown}
            </div>
          ) : (
            <div className="max-h-[480px] overflow-auto rounded-xl border border-border bg-bg px-4 py-3">
              <Markdown>{markdown}</Markdown>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
