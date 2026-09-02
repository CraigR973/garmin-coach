import type { AcutePhysiology } from '@coach/shared';
import { ShieldAlert } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface AcutePhysiologyNoticeProps {
  boundary: AcutePhysiology | null | undefined;
}

export function AcutePhysiologyNotice({ boundary }: AcutePhysiologyNoticeProps) {
  const escalations = boundary?.escalations ?? [];
  if (escalations.length === 0) return null;

  const requiresBikeRest = boundary?.requiresBikeRest === true;
  return (
    <Card className="border-amber-500/35 bg-amber-500/[0.06]" role="alert">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {requiresBikeRest ? 'Why this needs rest' : 'A pattern worth checking'}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        {escalations.map((escalation) => (
          <p key={escalation.kind}>{escalation.message}</p>
        ))}
      </CardContent>
    </Card>
  );
}

export function MedicalBoundaryFooter({ boundary }: AcutePhysiologyNoticeProps) {
  if (!boundary?.standingLine) return null;
  return (
    <p className="border-t border-border/70 pt-4 text-sm leading-6 text-text-muted">
      {boundary.standingLine}
    </p>
  );
}
