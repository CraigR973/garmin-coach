import type { AcutePhysiology } from '@coach/shared';
import { Info, ShieldAlert } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface AcutePhysiologyNoticeProps {
  boundary: AcutePhysiology | null | undefined;
}

type NoticeLevel = 'rest' | 'watch' | 'ease';

// Batch 293: the heading follows the most serious signal. A small rise in resting
// heart rate explains an Amber cap in plain words, so it reads as information, not
// an alert.
const HEADINGS: Record<NoticeLevel, string> = {
  rest: 'Why this needs rest',
  watch: 'A pattern worth checking',
  ease: 'Why today is capped',
};

function noticeLevel(boundary: AcutePhysiology): NoticeLevel {
  const levels = boundary.escalations.flatMap((escalation) =>
    escalation.level ? [escalation.level] : [],
  );
  // A packet stored before Batch 293 carries no levels: read it as it always was.
  if (levels.length === 0) return boundary.requiresBikeRest === true ? 'rest' : 'watch';
  if (levels.includes('rest')) return 'rest';
  if (levels.includes('watch')) return 'watch';
  return 'ease';
}

export function AcutePhysiologyNotice({ boundary }: AcutePhysiologyNoticeProps) {
  const escalations = boundary?.escalations ?? [];
  if (!boundary || escalations.length === 0) return null;

  const level = noticeLevel(boundary);
  const Icon = level === 'ease' ? Info : ShieldAlert;
  return (
    <Card
      className="border-amber-500/35 bg-amber-500/[0.06]"
      role={level === 'ease' ? 'status' : 'alert'}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {HEADINGS[level]}
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
