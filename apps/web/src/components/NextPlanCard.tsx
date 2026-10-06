import { CalendarRange } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NEXT_PLAN_BUTTON, NEXT_PLAN_TITLE, nextPlanLine } from '@/lib/nextPlan';

interface NextPlanCardProps {
  /** The next plan's draft, while it waits for him; absent otherwise. */
  nextPlan: { planName: string; startDate: string; endDate: string } | null | undefined;
  /** Today, in his timezone (the daily loop's subject date). */
  today: string;
}

/** Batch 323: his next plan is ready; it leads to the plan builder, where he decides. */
export function NextPlanCard({ nextPlan, today }: NextPlanCardProps) {
  if (!nextPlan) return null;
  return (
    <Card className="border-primary/30 bg-primary/5" role="status">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarRange className="h-5 w-5 text-primary" aria-hidden />
          {NEXT_PLAN_TITLE}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        <p>{nextPlanLine(nextPlan.planName, nextPlan.startDate, today)}</p>
        <Button asChild>
          <Link to="/builder">{NEXT_PLAN_BUTTON}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
