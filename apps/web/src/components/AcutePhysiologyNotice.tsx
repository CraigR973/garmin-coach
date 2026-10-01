import type { AcutePhysiology, SymptomAnswer } from '@coach/shared';
import { Info, ShieldAlert } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { symptomNotice } from '@/lib/symptoms';

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

// Batch 298: under the graded verdict a low HRV night or two mornings of raised resting
// heart rate is one thing a little off, already counted in the colour, not a cap. A head
// cold still caps the day, so it keeps the heading above. Signed off 1 Oct 2026.
export const GRADED_EASE_HEADING = "Counted in today's call";

function heading(boundary: AcutePhysiology, level: NoticeLevel): string {
  const symptomEases = boundary.escalations.some(
    (escalation) => escalation.kind === 'symptoms' && escalation.level === 'ease',
  );
  if (level === 'ease' && boundary.gradedWording === true && !symptomEases) {
    return GRADED_EASE_HEADING;
  }
  return HEADINGS[level];
}

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

/** The notice card itself: one heading for its most serious level, then each message. */
function NoticeCard({
  level,
  title = HEADINGS[level],
  messages,
}: {
  level: NoticeLevel;
  title?: string;
  messages: ReadonlyArray<{ key: string; text: string }>;
}) {
  const Icon = level === 'ease' ? Info : ShieldAlert;
  return (
    <Card
      className="border-amber-500/35 bg-amber-500/[0.06]"
      role={level === 'ease' ? 'status' : 'alert'}
    >
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon className="h-5 w-5 text-amber-600 dark:text-amber-300" aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-6 text-text-secondary">
        {messages.map((message) => (
          <p key={message.key}>{message.text}</p>
        ))}
      </CardContent>
    </Card>
  );
}

export function AcutePhysiologyNotice({ boundary }: AcutePhysiologyNoticeProps) {
  const escalations = boundary?.escalations ?? [];
  if (!boundary || escalations.length === 0) return null;

  const level = noticeLevel(boundary);
  return (
    <NoticeCard
      level={level}
      title={heading(boundary, level)}
      messages={escalations.map((escalation) => ({
        key: escalation.kind,
        text: escalation.message,
      }))}
    />
  );
}

/** Batch 301: a reported symptom's notice before, or without, a written brief.
 *
 *  The same card, heading and words Home shows on a written morning, so the advice
 *  does not wait for the paid brief: on the check-in the moment he picks the answer,
 *  and on Home and the brief page while today's brief is being written or after it
 *  failed. Renders nothing for None or for no answer. */
export function SymptomNotice({ answer }: { answer: SymptomAnswer | null | undefined }) {
  const notice = symptomNotice(answer);
  if (!notice) return null;
  return <NoticeCard level={notice.level} messages={[{ key: 'symptoms', text: notice.notice }]} />;
}

export function MedicalBoundaryFooter({ boundary }: AcutePhysiologyNoticeProps) {
  if (!boundary?.standingLine) return null;
  return (
    <p className="border-t border-border/70 pt-4 text-sm leading-6 text-text-muted">
      {boundary.standingLine}
    </p>
  );
}
