import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { holidayEnvelopeSchema, pauseEnvelopeSchema, resumeEnvelopeSchema } from '@coach/shared';
import { CalendarOff, CheckCircle2, PlayCircle, Umbrella } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { apiFetch } from '@/lib/api';

const BASE = '/api/v1/holiday';

async function fetchHoliday() {
  const response = await apiFetch<unknown>(BASE);
  return holidayEnvelopeSchema.parse(response);
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

export function HolidayPage() {
  const queryClient = useQueryClient();
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const query = useQuery({ queryKey: ['holiday'], queryFn: fetchHoliday });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['holiday'] });

  const pauseMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<unknown>(`${BASE}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ startDate, endDate }),
      });
      return pauseEnvelopeSchema.parse(response);
    },
    onSuccess: async (data) => {
      await invalidate();
      setStartDate('');
      setEndDate('');
      toast.success(
        `Plan paused — ${data.data.skippedCount} workout(s) marked as holiday rest`,
      );
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Failed to pause plan'),
  });

  const resumeMutation = useMutation({
    mutationFn: async () => {
      const response = await apiFetch<unknown>(`${BASE}/resume`, { method: 'POST' });
      return resumeEnvelopeSchema.parse(response);
    },
    onSuccess: async (data) => {
      await invalidate();
      toast.success(
        `Welcome back! ${data.data.continuationLabel} block generated for your return week.`,
      );
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : 'Failed to resume plan'),
  });

  if (query.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Holiday" eyebrow="Plan pause / resume" />
        <Card>
          <CardHeader>
            <CardTitle>Loading holiday status…</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Holiday" eyebrow="Plan pause / resume" />
        <Card>
          <CardHeader>
            <CardTitle>Holiday status unavailable</CardTitle>
            <CardDescription>
              {query.error instanceof Error ? query.error.message : 'Could not load holiday data.'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const { activeWindow, windows } = query.data.data;
  const pastWindows = windows.filter((w) => !w.isActive);
  const canPause = !activeWindow && startDate && endDate && startDate <= endDate;

  return (
    <div className="space-y-6">
      <PageHeader title="Holiday" eyebrow="Plan pause / resume" />

      {/* Info card */}
      <Card className="bg-surface-elevated/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarOff className="h-4 w-4 text-primary" aria-hidden />
            Holiday = recovery week
          </CardTitle>
          <CardDescription>
            Pausing the plan marks your planned workouts as holiday rest. On return the coach
            continues from the right place: Build1 before holiday → resumes at Build2; Build2 before
            holiday → repeats Build1.
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Active holiday */}
      {activeWindow ? (
        <Card className="border-warning/40 bg-warning/5">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Umbrella className="h-4 w-4 text-warning" aria-hidden />
                  Holiday active
                </CardTitle>
                <CardDescription className="mt-1">
                  {formatDate(activeWindow.startDate)} → {formatDate(activeWindow.endDate)}
                </CardDescription>
              </div>
              <Badge variant="warning">Active</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <Button
              type="button"
              onClick={() => resumeMutation.mutate()}
              disabled={resumeMutation.isPending}
              className="w-full sm:w-auto"
            >
              <PlayCircle className="mr-2 h-4 w-4" aria-hidden />
              {resumeMutation.isPending ? 'Resuming…' : 'Resume plan'}
            </Button>
          </CardContent>
        </Card>
      ) : (
        /* Pause form */
        <Card>
          <CardHeader>
            <CardTitle>Set holiday dates</CardTitle>
            <CardDescription>
              Workouts on these days will be marked as holiday rest and excluded from your plan.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="start-date">First day of holiday</Label>
                <input
                  id="start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-border bg-bg px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:shadow-glow"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="end-date">Last day of holiday</Label>
                <input
                  id="end-date"
                  type="date"
                  value={endDate}
                  min={startDate || undefined}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-border bg-bg px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:shadow-glow"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                type="button"
                onClick={() => pauseMutation.mutate()}
                disabled={!canPause || pauseMutation.isPending}
              >
                <CalendarOff className="mr-2 h-4 w-4" aria-hidden />
                {pauseMutation.isPending ? 'Pausing…' : 'Pause plan'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Past windows */}
      {pastWindows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Holiday history</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {pastWindows.map((w, i) => (
                <li
                  key={i}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
                >
                  <span className="text-text-primary">
                    {formatDate(w.startDate)} → {formatDate(w.endDate)}
                  </span>
                  <span className="flex items-center gap-1 text-success">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                    Resumed
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
