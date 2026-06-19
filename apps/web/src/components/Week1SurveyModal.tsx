import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { submitSurvey, WEEK1_SURVEY_KEY, type Week1Answers } from '@/lib/survey';
import feedbackPoster from '@/assets/survey-feedback.jpg';

type Choice<T extends string> = readonly (readonly [T, string])[];

const OVERALL: readonly (readonly [number, string])[] = [
  [1, '😖'],
  [2, '😐'],
  [3, '🙂'],
  [4, '😀'],
  [5, '😍'],
];
const FREQUENCY: Choice<Week1Answers['q3_frequency']> = [
  ['several_daily', 'Several times a day'],
  ['daily', 'About once a day'],
  ['few_days', 'Every few days'],
  ['barely', 'Barely since I made my picks'],
];
const NOTIFS: Choice<Week1Answers['q4_notifications']> = [
  ['about_right', 'About right'],
  ['too_many', 'Too many'],
  ['too_few', 'Too few'],
  ['turned_off', "I've turned them off"],
  ['none_received', "I don't get any"],
];
const MISSED: Choice<Week1Answers['q5_missed_deadline']> = [
  ['no', 'No'],
  ['forgot', 'Yes — I forgot'],
  ['time_confused', 'Yes — the kickoff time confused me'],
  ['other', 'Yes — something else'],
];
const ANNOYANCE: Choice<Week1Answers['q6_biggest_annoyance']> = [
  ['leaderboard', 'Finding myself / others on the leaderboard'],
  ['league_switching', 'Switching leagues / which one I am in'],
  ['live_scores', 'Following live scores during a match'],
  ['predictions', 'Making or editing predictions'],
  ['notifications', 'The notifications'],
  ['nothing', 'Honestly, nothing major'],
  ['other', 'Other'],
];

const INPUT_CLASS =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-primary ' +
  'placeholder:text-text-muted focus:outline-none focus-visible:shadow-glow';

function pill(active: boolean): string {
  return [
    'rounded-full border px-3 py-1.5 text-sm transition-colors press-down',
    active
      ? 'border-primary bg-primary/10 text-text-primary'
      : 'border-border text-text-secondary hover:border-primary/50',
  ].join(' ');
}

function Field({
  label,
  required,
  children,
}: {
  label: ReactNode;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-text-primary font-sans">
        {label}
        {required && <span className="text-primary"> *</span>}
      </p>
      {children}
    </div>
  );
}

function ChoiceField<T extends string>({
  label,
  required,
  options,
  value,
  onChange,
}: {
  label: string;
  required?: boolean;
  options: Choice<T>;
  value: T | null;
  onChange: (v: T) => void;
}) {
  return (
    <Field label={label} required={required}>
      <div className="flex flex-wrap gap-2">
        {options.map(([val, text]) => (
          <button
            key={val}
            type="button"
            aria-pressed={value === val}
            onClick={() => onChange(val)}
            className={pill(value === val)}
          >
            {text}
          </button>
        ))}
      </div>
    </Field>
  );
}

interface Props {
  /** Snooze for this session (returns next app launch). */
  onClose: () => void;
  /** Successfully submitted — caller marks the survey done. */
  onSubmitted: () => void;
}

export function Week1SurveyModal({ onClose, onSubmitted }: Props) {
  const [overall, setOverall] = useState<number | null>(null);
  const [frequency, setFrequency] = useState<Week1Answers['q3_frequency'] | null>(null);
  const [notifs, setNotifs] = useState<Week1Answers['q4_notifications'] | null>(null);
  const [missed, setMissed] = useState<Week1Answers['q5_missed_deadline'] | null>(null);
  const [annoyance, setAnnoyance] = useState<Week1Answers['q6_biggest_annoyance'] | null>(null);
  const [annoyanceOther, setAnnoyanceOther] = useState('');
  const [openText, setOpenText] = useState('');
  const [scotland, setScotland] = useState('');
  const [contactOk, setContactOk] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const complete =
    overall !== null && !!frequency && !!notifs && !!missed && !!annoyance;

  async function handleSubmit() {
    if (!complete || submitting) return;
    setSubmitting(true);
    try {
      await submitSurvey(
        WEEK1_SURVEY_KEY,
        {
          q2_overall: overall,
          q3_frequency: frequency,
          q4_notifications: notifs,
          q5_missed_deadline: missed,
          q6_biggest_annoyance: annoyance,
          q6_other:
            annoyance === 'other' && annoyanceOther.trim() ? annoyanceOther.trim() : null,
          q7_open: openText.trim() || null,
          q9_scotland: scotland.trim() || null,
        },
        contactOk,
      );
      toast.success('Thanks — that is a big help 🙌');
      onSubmitted();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not send — try again');
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <img
          src={feedbackPoster}
          alt="Uncle Sam pointing — we want your feedback for the World Cup Predictor app"
          className="mx-auto mb-4 h-64 w-auto rounded-lg border border-border shadow-sm"
        />
        <DialogHeader>
          <DialogTitle>⚽ One week in — how is it going?</DialogTitle>
          <DialogDescription>
            A 60-second pulse so we can fix the annoying stuff before the knockouts. All answers
            welcome — brutal ones especially.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <Field label="Honestly, how has the app been so far?" required>
            <div className="flex justify-between gap-2">
              {OVERALL.map(([v, emoji]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={overall === v}
                  aria-label={`Rating ${v} of 5`}
                  onClick={() => setOverall(v)}
                  className={pill(overall === v) + ' flex-1 text-xl'}
                >
                  {emoji}
                </button>
              ))}
            </div>
          </Field>

          <ChoiceField
            label="How often are you opening it?"
            required
            options={FREQUENCY}
            value={frequency}
            onChange={setFrequency}
          />
          <ChoiceField
            label="How are the match notifications feeling?"
            required
            options={NOTIFS}
            value={notifs}
            onChange={setNotifs}
          />
          <ChoiceField
            label="Have you ever missed a prediction deadline?"
            required
            options={MISSED}
            value={missed}
            onChange={setMissed}
          />
          <ChoiceField
            label="What is the most annoying thing right now?"
            required
            options={ANNOYANCE}
            value={annoyance}
            onChange={setAnnoyance}
          />
          {annoyance === 'other' && (
            <input
              className={INPUT_CLASS}
              placeholder="What is annoying you?"
              maxLength={500}
              value={annoyanceOther}
              onChange={(e) => setAnnoyanceOther(e.target.value)}
            />
          )}

          <Field label="Anything broken, confusing, or that you would love before the knockouts?">
            <textarea
              className={INPUT_CLASS + ' min-h-[80px]'}
              maxLength={2000}
              value={openText}
              onChange={(e) => setOpenText(e.target.value)}
              placeholder="The most useful box here — go for it."
            />
          </Field>

          <Field label="🏴󠁧󠁢󠁳󠁣󠁴󠁿 Bonus: how many goals will Scotland score against Morocco on Friday night?">
            <input
              className={INPUT_CLASS}
              maxLength={200}
              value={scotland}
              onChange={(e) => setScotland(e.target.value)}
              placeholder="Be honest. Or be hopeful."
            />
          </Field>

          <label className="flex items-start gap-2 text-sm text-text-secondary font-sans">
            <input
              type="checkbox"
              className="mt-1"
              checked={contactOk}
              onChange={(e) => setContactOk(e.target.checked)}
            />
            <span>
              Happy for us to follow up if you flagged a bug? This attaches your name to{' '}
              <em>this</em> response — otherwise it stays anonymous.
            </span>
          </label>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Later
          </Button>
          <Button onClick={handleSubmit} disabled={!complete || submitting}>
            {submitting ? 'Sending…' : 'Submit'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
