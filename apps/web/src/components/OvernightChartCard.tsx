import { useState } from 'react';
import { ChevronLeft, ChevronRight, LineChart } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { BedroomOvernightChart } from '@/components/BedroomOvernightChart';
import { useBedroomOvernight } from '@/hooks/useBedroomOvernight';
import { verdictBadgeVariant, verdictToneLabel } from '@/lib/copy';
import { friendlyDate } from '@/lib/dailyFlow';

/** The overnight temperature × fan × sleep hypnogram chart, with a room-verdict
 *  badge and a night pager (Batch 31). Extracted from the retired `/bedroom`
 *  page into the `/sleep` hub's "Last night" view (Batch 49). */
export function OvernightChartCard({
  night: controlledNight,
  captionDate,
  showPager = true,
}: {
  night?: string | null;
  captionDate?: string;
  showPager?: boolean;
} = {}) {
  const [night, setNight] = useState<string | null>(null);
  const activeNight = controlledNight ?? night;
  const query = useBedroomOvernight(activeNight);
  const data = query.data?.data;

  const nights = data?.nights ?? [];
  const index = data ? nights.indexOf(data.night) : -1;
  const olderNight = index >= 0 && index < nights.length - 1 ? nights[index + 1] : null;
  const newerNight = index > 0 ? nights[index - 1] : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <LineChart className="h-4 w-4 text-primary" aria-hidden />
              Overnight room &amp; fan
              {data?.summary ? (
                <Badge
                  variant={verdictBadgeVariant(data.summary.roomVerdict)}
                  className="shrink-0"
                  data-testid="overnight-room-verdict-badge"
                >
                  {verdictToneLabel(data.summary.roomVerdict)}
                </Badge>
              ) : null}
            </CardTitle>
            <CardDescription>
              {data ? friendlyDate(captionDate ?? data.night) : 'Room temperature, what the fan did, and your sleep.'}
            </CardDescription>
          </div>
          {showPager ? (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                size="icon"
                variant="outline"
                aria-label="Previous night"
                disabled={!olderNight}
                onClick={() => olderNight && setNight(olderNight)}
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                aria-label="Next night"
                disabled={!newerNight}
                onClick={() => newerNight && setNight(newerNight)}
              >
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {query.isLoading ? (
          <Skeleton className="h-72 w-full rounded-xl" />
        ) : query.isError || !data ? (
          <p className="py-8 text-center text-sm text-text-muted">
            {query.error instanceof Error ? query.error.message : 'Overnight data could not load.'}
          </p>
        ) : (
          <BedroomOvernightChart data={data} />
        )}
      </CardContent>
    </Card>
  );
}
