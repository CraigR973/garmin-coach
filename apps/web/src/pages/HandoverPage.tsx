import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { handoverEnvelopeSchema } from '@coach/shared';
import { Download, FileText, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
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
      <PageHeader title="Handover" eyebrow="Auto-generated briefing" />

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

  return (
    <div className="space-y-4">
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden />
            Portable handover document
          </CardTitle>
          <CardDescription>
            Assembled from your living state — knowledge base, plan, baselines, reviews, trends,
            experiments and the strength brief. The markdown below is built deterministically and
            always reflects current state; the narrative is generated on demand.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => downloadMarkdown(data)}>
            <Download className="mr-2 h-4 w-4" aria-hidden />
            Download .md
          </Button>
          <Button type="button" onClick={onGenerate} disabled={generating}>
            <Sparkles className="mr-2 h-4 w-4" aria-hidden />
            {stored ? 'Regenerate narrative' : 'Generate narrative'}
          </Button>
        </CardContent>
      </Card>

      {stored ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" aria-hidden />
              Narrative handover
            </CardTitle>
            <CardDescription>
              Generated {new Date(stored.generatedAtUtc).toLocaleString()}
              {stored.modelName ? ` · ${stored.modelName}` : ''}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm leading-6 text-text-primary whitespace-pre-wrap">
              {stored.markdown}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" aria-hidden />
            Deterministic export preview
          </CardTitle>
          <CardDescription>
            Built without the model — this is exactly what “Download .md” saves.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-h-[480px] overflow-auto rounded-xl border border-border bg-bg px-4 py-3 text-xs leading-5 text-text-primary whitespace-pre-wrap font-mono">
            {markdown}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
