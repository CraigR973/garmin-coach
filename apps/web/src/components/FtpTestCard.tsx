import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Gauge } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import type { DailyLoopFtpTest } from '@coach/shared';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { apiFetch } from '@/lib/api';
import { friendlyError } from '@/lib/friendlyError';
import {
  FTP_TEST_ZWIFT_LINE,
  ZWIFT_NUMBER_FIELD,
  ZWIFT_NUMBER_LABEL,
  ZWIFT_NUMBER_SAVE,
  ftpKeptToast,
  ftpSetToast,
  ftpTestCurrentLine,
  ftpTestLine,
  ftpTestTitle,
  keepFtpLabel,
  setFtpLabel,
  zwiftNumberRange,
} from '@/lib/ftpTest';

interface Decision {
  choice: 'set' | 'keep';
  ftpWatts?: number;
}

/**
 * Batch 336.1 (CI330-02): after a ramp test, Home offers the new FTP in one tap, Zwift's
 * own number if it differs, or keeping the FTP he has. Nothing renders without a result.
 */
export function FtpTestCard({ ftpTest }: { ftpTest: DailyLoopFtpTest | null | undefined }) {
  const queryClient = useQueryClient();
  const [ownNumber, setOwnNumber] = useState<string | null>(null);
  const decide = useMutation({
    mutationFn: (decision: Decision) =>
      apiFetch<{ data: { ftpWatts: number | null } }>('/api/v1/ftp-test/decision', {
        method: 'POST',
        body: JSON.stringify({ plannedWorkoutId: ftpTest?.plannedWorkoutId, ...decision }),
      }),
    onSuccess: async (response, decision) => {
      await queryClient.invalidateQueries({ queryKey: ['daily-loop'] });
      const ftp = response.data.ftpWatts;
      toast.success(decision.choice === 'set' && ftp !== null ? ftpSetToast(ftp) : ftpKeptToast(ftp));
    },
    onError: (error) => toast.error(friendlyError(error, 'save')),
  });

  if (!ftpTest) return null;
  const current = ftpTestCurrentLine(ftpTest.currentFtpWatts);
  const typed = ownNumber === null ? null : Number(ownNumber);
  const typedOk =
    typed !== null &&
    Number.isInteger(typed) &&
    typed >= ftpTest.ownNumberMin &&
    typed <= ftpTest.ownNumberMax;
  return (
    <Card className="border-primary/30 bg-primary/5" role="status" data-testid="ftp-test">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="h-5 w-5 text-primary" aria-hidden />
          {ftpTestTitle(ftpTest.ftpWatts)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>
          {ftpTestLine(ftpTest.testDate, ftpTest.bestMinuteWatts, ftpTest.ftpWatts)}
          {current ? ` ${current}` : ''}
        </p>
        <p>{FTP_TEST_ZWIFT_LINE}</p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ choice: 'set' })}
          >
            {setFtpLabel(ftpTest.ftpWatts)}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ choice: 'keep' })}
          >
            {keepFtpLabel(ftpTest.currentFtpWatts)}
          </Button>
        </div>
        {ownNumber === null ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="px-0"
            onClick={() => setOwnNumber(String(ftpTest.ftpWatts))}
          >
            {ZWIFT_NUMBER_LABEL}
          </Button>
        ) : (
          <div className="space-y-2">
            <Label htmlFor="zwift-ftp">{ZWIFT_NUMBER_FIELD}</Label>
            <Input
              id="zwift-ftp"
              inputMode="numeric"
              value={ownNumber}
              onChange={(event) => setOwnNumber(event.target.value)}
            />
            <p className="text-xs">{zwiftNumberRange(ftpTest.ownNumberMin, ftpTest.ownNumberMax)}</p>
            <Button
              type="button"
              size="sm"
              disabled={!typedOk || decide.isPending}
              onClick={() => typed !== null && decide.mutate({ choice: 'set', ftpWatts: typed })}
            >
              {ZWIFT_NUMBER_SAVE}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
