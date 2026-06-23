import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  experimentEvaluationEnvelopeSchema,
  experimentListEnvelopeSchema,
} from '@coach/shared';
import { FlaskConical, Gauge, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';

type ExperimentList = typeof experimentListEnvelopeSchema._type;
type Experiment = ExperimentList['data'][number];
type EvaluationEnvelope = typeof experimentEvaluationEnvelopeSchema._type;
type Evaluation = EvaluationEnvelope['data'];
type Recommendation = NonNullable<Evaluation['recommendation']>;

const BASE = '/api/v1/experiments';

async function fetchExperiments() {
  const response = await apiFetch<unknown>(BASE);
  return experimentListEnvelopeSchema.parse(response);
}

async function evaluateExperiment(id: string) {
  const response = await apiFetch<unknown>(`${BASE}/${id}/evaluate`);
  return experimentEvaluationEnvelopeSchema.parse(response);
}

async function concludeExperiment(id: string, outcome: Recommendation) {
  const response = await apiFetch<unknown>(`${BASE}/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status: 'concluded', outcome }),
  });
  return response;
}

function statusVariant(status: Experiment['status']): 'success' | 'warning' | 'muted' {
  if (status === 'active') return 'success';
  if (status === 'paused') return 'warning';
  return 'muted';
}

function recommendationVariant(
  rec: Recommendation,
): 'success' | 'error' | 'warning' {
  if (rec === 'supported') return 'success';
  if (rec === 'refuted') return 'error';
  return 'warning';
}

export function ExperimentsPage() {
  const query = useQuery({ queryKey: ['experiments'], queryFn: fetchExperiments });

  return (
    <div className="space-y-6">
      <PageHeader title="Experiments" eyebrow="Hypothesis evaluation" />

      {query.isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading experiments…</CardTitle>
          </CardHeader>
        </Card>
      ) : query.isError || !query.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Experiments unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error
                ? query.error.message
                : 'The experiments could not load.'}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : query.data.data.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No experiments yet</CardTitle>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-4">
          {query.data.data.map((experiment) => (
            <ExperimentCard key={experiment.id} experiment={experiment} />
          ))}
        </div>
      )}
    </div>
  );
}

function ExperimentCard({ experiment }: { experiment: Experiment }) {
  const queryClient = useQueryClient();
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);

  const evaluateMutation = useMutation({
    mutationFn: () => evaluateExperiment(experiment.id),
    onSuccess: (envelope) => {
      setEvaluation(envelope.data);
      if (envelope.data.evaluationStatus === 'insufficient_history') {
        toast.message('Not enough history yet to evaluate this hypothesis.');
      } else if (envelope.data.evaluationStatus === 'no_evaluator') {
        toast.message('No automatic evaluator applies to this experiment.');
      }
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to evaluate the experiment'),
  });

  const concludeMutation = useMutation({
    mutationFn: (outcome: Recommendation) => concludeExperiment(experiment.id, outcome),
    onSuccess: () => {
      toast.success('Experiment concluded');
      setEvaluation(null);
      void queryClient.invalidateQueries({ queryKey: ['experiments'] });
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to conclude the experiment'),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <FlaskConical className="h-4 w-4 text-primary" aria-hidden />
            {experiment.title}
          </CardTitle>
          <Badge variant={statusVariant(experiment.status)}>{experiment.status}</Badge>
        </div>
        <CardDescription>{experiment.hypothesis}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {evaluation ? (
          <EvaluationPanel
            evaluation={evaluation}
            concluding={concludeMutation.isPending}
            onConclude={(outcome) => concludeMutation.mutate(outcome)}
          />
        ) : null}
        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            onClick={() => evaluateMutation.mutate()}
            disabled={evaluateMutation.isPending}
          >
            <Gauge className="mr-2 h-4 w-4" aria-hidden />
            {evaluation ? 'Re-evaluate' : 'Evaluate evidence'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function EvaluationPanel({
  evaluation,
  concluding,
  onConclude,
}: {
  evaluation: Evaluation;
  concluding: boolean;
  onConclude: (outcome: Recommendation) => void;
}) {
  const { recommendation, reasons, sampleCount, evaluationStatus } = evaluation;

  return (
    <div className="rounded-xl border border-border bg-bg px-4 py-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium text-text-primary">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden />
          Recommendation
        </span>
        {recommendation ? (
          <Badge variant={recommendationVariant(recommendation)}>{recommendation}</Badge>
        ) : (
          <Badge variant="muted">{evaluationStatus}</Badge>
        )}
      </div>
      <ul className="mt-2 space-y-1 text-text-muted">
        {reasons.map((reason, index) => (
          <li key={index}>• {reason}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-text-muted">
        Based on {sampleCount} sample{sampleCount === 1 ? '' : 's'}. Advisory only — concluding is
        always your call.
      </p>
      {evaluation.canConclude && recommendation ? (
        <div className="mt-3 flex justify-end">
          <Button type="button" onClick={() => onConclude(recommendation)} disabled={concluding}>
            Conclude as {recommendation}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
