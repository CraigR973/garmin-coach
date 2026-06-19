/**
 * AboutPage — full rules reference + how it was built.
 *
 * All scoring data (match rows, worked examples, specials, grand total) is
 * sourced from the shared scoringData module so it stays in sync with
 * ScoringGuide on the Predictions page.
 *
 * Specials reconciled: 6 types (tournament_winner, golden_boot,
 * player_of_tournament, top_scoring_team, young_player_of_tournament,
 * golden_glove) → 80 pts total. Grand total = 720 + 320 + 295 + 80 = 1,415.
 */

import { useEffect, useRef } from 'react';
import { ExternalLink } from 'lucide-react';
import { PageHeader } from '@/components/PageHeader';
import { markRulesRead } from '@/lib/checklist';
import { cn } from '@/lib/utils';
import {
  MATCH_SCORING_ROWS,
  WORKED_EXAMPLES,
  KNOCKOUT_WINNER_ROWS,
  KNOCKOUT_WINNER_TOTAL,
  SPECIAL_ROWS,
  SPECIALS_TOTAL,
  GRAND_TOTAL_ROWS,
  GRAND_TOTAL,
} from '@/lib/scoringData';

// ── Small helpers ──────────────────────────────────────────────────────────────

function Section({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-lg border border-border bg-surface p-5 space-y-3', className)}>
      <h2 className="text-base font-semibold text-text-primary font-sans tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function Pill({ children, accent = false }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <span
      className={cn(
        'inline-block px-2 py-0.5 rounded-full text-xs font-mono font-semibold leading-5',
        accent
          ? 'bg-accent/15 text-accent'
          : 'bg-primary/15 text-primary',
      )}
    >
      {children}
    </span>
  );
}

// ── Scoring tables ─────────────────────────────────────────────────────────────

function GroupScoringTable() {
  const rows = MATCH_SCORING_ROWS.filter((r) => !r.accent);
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm font-sans border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="text-left py-2 pr-3 text-text-muted font-medium text-xs uppercase tracking-wider">Criteria</th>
            <th scope="col" className="text-right py-2 text-text-muted font-medium text-xs uppercase tracking-wider w-12">Pts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-border/50">
              <td className="py-2.5 pr-3">
                <p className="text-text-primary font-medium">{r.label}</p>
                <p className="text-xs text-text-muted mt-0.5">{r.note}</p>
              </td>
              <td className="py-2.5 text-right">
                <Pill>{r.pts}</Pill>
              </td>
            </tr>
          ))}
          <tr className="bg-surface-elevated/50">
            <td className="py-2.5 pr-3 font-semibold text-text-primary">Maximum per match</td>
            <td className="py-2.5 text-right">
              <Pill accent>10</Pill>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function WorkedExamplesTable() {
  return (
    <div className="overflow-x-auto -mx-1">
      <p className="text-xs text-text-muted font-sans mb-2">
        Every achievable per-match total — points stack, they don&rsquo;t replace each other.
      </p>
      <table
        className="w-full text-sm font-sans border-collapse"
        aria-label="Scoring worked examples"
      >
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="text-left py-2 pr-2 text-text-muted font-medium text-xs uppercase tracking-wider">You predicted</th>
            <th scope="col" className="text-left py-2 pr-2 text-text-muted font-medium text-xs uppercase tracking-wider">Actual</th>
            <th scope="col" className="text-left py-2 text-text-muted font-medium text-xs uppercase tracking-wider">Breakdown</th>
            <th scope="col" className="text-right py-2 text-text-muted font-medium text-xs uppercase tracking-wider w-12">Pts</th>
          </tr>
        </thead>
        <tbody>
          {WORKED_EXAMPLES.map((ex) => (
            <tr
              key={ex.total}
              className={cn(
                'border-b border-border/50',
                ex.total === 10 && 'bg-accent/5',
                ex.total === 0 && 'opacity-60',
              )}
            >
              <td className="py-2.5 pr-2 font-mono text-text-primary">{ex.predicted}</td>
              <td className="py-2.5 pr-2 font-mono text-text-primary">{ex.actual}</td>
              <td className="py-2.5 text-xs text-text-muted">{ex.breakdown}</td>
              <td className="py-2.5 text-right">
                <Pill accent={ex.total === 10}>{ex.total}</Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KnockoutWinnerTable() {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm font-sans border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="text-left py-2 pr-3 text-text-muted font-medium text-xs uppercase tracking-wider">Round</th>
            <th scope="col" className="text-right py-2 px-2 text-text-muted font-medium text-xs uppercase tracking-wider">Per correct</th>
            <th scope="col" className="text-right py-2 text-text-muted font-medium text-xs uppercase tracking-wider">Round max</th>
          </tr>
        </thead>
        <tbody>
          {KNOCKOUT_WINNER_ROWS.map((r) => (
            <tr key={r.round} className="border-b border-border/50">
              <td className="py-2.5 pr-3 text-text-primary">{r.round}</td>
              <td className="py-2.5 px-2 text-right">
                <Pill>{r.pts}</Pill>
              </td>
              <td className="py-2.5 text-right text-text-secondary font-mono text-xs">{r.max}</td>
            </tr>
          ))}
          <tr className="bg-surface-elevated/50">
            <td className="py-2.5 pr-3 font-semibold text-text-primary">Total — 32 picks</td>
            <td className="py-2.5 px-2" />
            <td className="py-2.5 text-right">
              <Pill accent>{KNOCKOUT_WINNER_TOTAL}</Pill>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function SpecialsTable() {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm font-sans border-collapse">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="text-left py-2 pr-3 text-text-muted font-medium text-xs uppercase tracking-wider">Prediction</th>
            <th scope="col" className="text-right py-2 text-text-muted font-medium text-xs uppercase tracking-wider w-12">Pts</th>
          </tr>
        </thead>
        <tbody>
          {SPECIAL_ROWS.map((r) => (
            <tr key={r.prediction} className="border-b border-border/50">
              <td className="py-2.5 pr-3 text-text-primary">{r.prediction}</td>
              <td className="py-2.5 text-right">
                <Pill>{r.pts}</Pill>
              </td>
            </tr>
          ))}
          <tr className="bg-surface-elevated/50">
            <td className="py-2.5 pr-3 font-semibold text-text-primary">Total specials</td>
            <td className="py-2.5 text-right">
              <Pill accent>{SPECIALS_TOTAL}</Pill>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function MaximumBreakdown() {
  return (
    <div className="space-y-2">
      {GRAND_TOTAL_ROWS.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-sans text-text-primary font-medium truncate">{r.label}</p>
            <p className="text-xs font-sans text-text-muted">{r.detail}</p>
          </div>
          <span className="font-mono text-sm text-text-secondary shrink-0">{r.pts}</span>
        </div>
      ))}
      <div className="pt-2 border-t border-border flex items-center justify-between">
        <span className="text-sm font-sans font-semibold text-text-primary">Grand total</span>
        <Pill accent>{GRAND_TOTAL.toLocaleString()}</Pill>
      </div>
    </div>
  );
}

// ── Tournament flow section ────────────────────────────────────────────────────

function SubHead({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2 mt-5 first:mt-0">
      {children}
    </h3>
  );
}

function BulletList({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2.5">
          <span className="mt-[5px] shrink-0 w-1.5 h-1.5 rounded-full bg-primary/60" aria-hidden />
          <span className="text-sm font-sans text-text-secondary leading-relaxed">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function WhyCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface-elevated px-4 py-4 space-y-2">
      {children}
    </div>
  );
}

/** A captioned joke image. Files live in /public/about/ and are referenced as /about/<name>. */
function JokeFigure({
  src,
  alt,
  caption,
  className,
  imgClassName,
}: {
  src: string;
  alt: string;
  caption?: string;
  className?: string;
  imgClassName?: string;
}) {
  return (
    <figure className={cn('space-y-1.5', className)}>
      <img src={src} alt={alt} loading="lazy" className={cn('w-full rounded-lg border border-border', imgClassName)} />
      {caption && (
        <figcaption className="text-center text-xs font-sans italic text-text-muted">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function AboutPage() {
  const rulesEndRef = useRef<HTMLDivElement | null>(null);
  const hasMarkedReadRef = useRef(false);

  useEffect(() => {
    const node = rulesEndRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;

    const observer = new IntersectionObserver((entries) => {
      const reachedEnd = entries.some((entry) => entry.isIntersecting);
      if (!reachedEnd || hasMarkedReadRef.current) return;

      hasMarkedReadRef.current = true;
      markRulesRead();
      observer.disconnect();
    }, { threshold: 0.6 });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="max-w-xl space-y-6">
      <PageHeader title="About" eyebrow="Calcio" showBack />

      {/* U45.2 — Multi-league hero */}
      <div
        data-testid="about-multi-league-hero"
        className="rounded-xl border border-primary/30 bg-primary/5 px-5 py-4 space-y-1"
      >
        <p className="text-base font-semibold font-sans text-text-primary">
          Predict once &middot; compete in as many leagues as you like
        </p>
        <p className="text-sm font-sans text-text-secondary leading-relaxed">
          Like fantasy football — you make one set of predictions and they automatically count
          across every league you&rsquo;re in at the same time. Join your mates&rsquo; league, a
          work league, a public league — one set of picks covers all of them.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-surface-elevated px-4 py-3">
        <p className="text-sm font-sans leading-relaxed text-text-secondary">
          Scroll for the full rules. We only tick off &ldquo;Read the rules&rdquo; in the
          Pre-Tournament Checklist once you reach the end of the guide below.
        </p>
      </div>

      {/* What this is */}
      <Section title="What is this?">
        <p className="text-sm font-sans text-text-secondary leading-relaxed">
          Calcio is a prediction game for the 2026 FIFA World Cup. You make one set of predictions
          for the whole tournament — 72 group-stage matches and 32 knockout fixtures, from the Round
          of 32 to the Final. Your picks count across every league you join, with automatic locking,
          result fetching, and live leaderboard updates throughout the tournament.
        </p>
      </Section>

      {/* Deadlines */}
      <Section title="Deadlines — what's due when">
        <BulletList items={[
          <><strong className="text-text-primary font-semibold">Before the opening match kicks off:</strong> lock in your 6 Specials and your first-match pick — the only things due before the tournament starts.</>,
          <><strong className="text-text-primary font-semibold">Every match after that:</strong> predict any time before it kicks off — you never have to do them all at once. Each match locks at its own kickoff.</>,
          <><strong className="text-text-primary font-semibold">Knockout rounds:</strong> same as the group stage — every knockout match locks at its own kickoff, so you predict each one just before it starts, never a whole round up front.</>,
        ]} />
      </Section>

      {/* How scoring works */}
      <Section title="How scoring works">
        <div className="space-y-5">

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Group stage
            </h3>
            <GroupScoringTable />
            <p className="text-xs text-text-muted mt-2 font-sans">
              Points stack — a correct exact score is worth all three rows (2 + 3 + 5 = 10).
            </p>
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Worked examples
            </h3>
            <WorkedExamplesTable />
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Knockout score predictions
            </h3>
            <p className="text-sm text-text-secondary font-sans leading-relaxed">
              The same group-stage rules apply, but to the 90-minute score only. Extra time and
              penalties determine who advances, but don&rsquo;t affect points. A match that ends
              1–1 after 90 minutes (then decided on penalties) is scored as a 1–1 draw for
              prediction purposes. Maximum 10 pts per knockout match. That&rsquo;s exactly why
              who-advances is a <strong className="text-text-primary font-medium">separate</strong> pick
              (below) — a draw can&rsquo;t tell us who you reckon goes through on penalties.
            </p>
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Knockout winner picks
            </h3>
            <KnockoutWinnerTable />
            <p className="text-xs text-text-muted mt-2 font-sans">
              The points scale by round (above), but each pick locks at its own match&rsquo;s
              kickoff — you predict match by match, just before each one, never a whole round at once.
            </p>
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Special predictions
            </h3>
            <SpecialsTable />
            <p className="text-xs text-text-muted mt-2 font-sans">
              Submitted before the tournament begins. Awarded at the end of the tournament.
            </p>
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              Maximum possible points
            </h3>
            <div className="rounded-lg border border-border bg-surface-elevated p-4">
              <MaximumBreakdown />
            </div>
          </div>

          <div>
            <h3 className="text-xs font-mono font-semibold tracking-[0.2em] uppercase text-text-muted mb-2">
              How ties are broken
            </h3>
            <div className="rounded-lg border border-border bg-surface-elevated p-4 space-y-2">
              <p className="text-sm font-sans leading-relaxed text-text-secondary">
                League tables sort by total points first. If players are still level, we separate
                them in this order:
              </p>
              <BulletList items={[
                <>More <strong className="text-text-primary font-semibold">exact scores</strong>.</>,
                <>Then more <strong className="text-text-primary font-semibold">correct results</strong>.</>,
                <>Then more <strong className="text-text-primary font-semibold">correct goal totals</strong>.</>,
                <>Then more <strong className="text-text-primary font-semibold">special predictions correct</strong>.</>,
                <>Then more <strong className="text-text-primary font-semibold">knockout-winner picks correct</strong>.</>,
                'If two players are still inseparable after every step, the table marks it as a genuine tie and an admin settles it manually.',
              ]} />
            </div>
          </div>

        </div>
      </Section>

      {/* How it works through the tournament */}
      <Section title="How it works through the tournament">
        <div>
          <SubHead>Creating your account</SubHead>
          <BulletList items={[
            'Sign up yourself — email, your name, timezone and a 4-digit PIN. No admin needed.',
            <>Nobody — not even an admin — ever sees your PIN. Forgot it? Reset it in the app.</>,
            'Add a profile photo if you like (optional).',
            'Turn on notifications to get a reminder before kickoff so you never miss a deadline.',
          ]} />

          <SubHead>Getting into leagues</SubHead>
          <BulletList items={[
            <>Join a private league from an <strong className="text-text-primary font-semibold">invite link</strong> or by entering a <strong className="text-text-primary font-semibold">join code</strong> under Leagues → Join by code.</>,
            <>You can also <strong className="text-text-primary font-semibold">discover public leagues</strong> or <strong className="text-text-primary font-semibold">create your own</strong> and invite people in.</>,
            'Wherever you join, the same set of picks counts everywhere.',
          ]} />

          <SubHead>Group stage — 11–28 June</SubHead>
          <BulletList items={[
            'Predict each match\'s score any time before kickoff.',
            'Predictions lock automatically when the match kicks off.',
            'All kickoff times show in your own timezone (set at signup).',
            <>Results auto-fetch every 5 minutes from <span className="text-text-primary font-medium">football-data.org</span>.</>,
            'The leaderboard updates the moment a result lands.',
            'Nobody can see your predictions until a match locks — then you can compare head-to-head with any other player.',
          ]} />

          <SubHead>Knockout transitions</SubHead>
          <BulletList items={[
            <>After the group stage, the admin reviews standings (including the 8 best third-placed teams per FIFA rules) and triggers the advance to Round of 32.</>,
            'The 16 R32 matches appear in the app with kickoff times pulled from football-data.',
            <>For each knockout match you make <strong className="text-text-primary font-semibold">two</strong> predictions: the 90-minute <strong className="text-text-primary font-semibold">score</strong> and, separately, <strong className="text-text-primary font-semibold">who advances</strong>. Both lock at that match&rsquo;s own kickoff — predict each game just before it starts, not the whole round at once.</>,
            <>Winner-pick points climb with the stakes: <Pill>R32 = 5</Pill> <Pill>R16 = 10</Pill> <Pill>QF = 15</Pill> <Pill>SF = 20</Pill> <Pill>3rd = 10</Pill> <Pill>Final = 25</Pill>.</>,
            'Same flow repeats for R16, QF, SF, and the Final.',
          ]} />

          <SubHead>Special predictions — locked at the opening match</SubHead>
          <BulletList items={[
            <>Six special predictions submitted <strong className="text-text-primary font-semibold">before the tournament starts</strong>: Tournament Winner <Pill>20 pts</Pill>, Golden Boot <Pill>15 pts</Pill>, Player of the Tournament <Pill>15 pts</Pill>, Top Scoring Team <Pill>10 pts</Pill>, Young Player of the Tournament <Pill>10 pts</Pill>, Golden Glove <Pill>10 pts</Pill>.</>,
            'These lock at the kickoff of the opening match (11 June).',
            'Awarded by the admin at the end of the tournament once the final whistle goes — your predictions are safe until then.',
          ]} />

          <SubHead>Why predict as you go, not a bracket up front?</SubHead>
          <p className="text-sm font-sans text-text-secondary leading-relaxed mb-3">
            Some leagues ask you to fill your entire bracket before the tournament starts,
            March-Madness-style. Calcio does it match by match — each pick locks only at that
            game&rsquo;s kickoff. Here&rsquo;s why that&rsquo;s better:
          </p>
          <WhyCard>
            <BulletList items={[
              <><strong className="text-text-primary font-semibold">You're never out.</strong> Even if your favourite gets knocked out in R32, you're still competing in every remaining round.</>,
              <><strong className="text-text-primary font-semibold">More informed picks.</strong> You've seen the group stage form before you commit to R32 winners.</>,
              <><strong className="text-text-primary font-semibold">Joining late is fine.</strong> You can still play even if you missed some group matches.</>,
              <><strong className="text-text-primary font-semibold">More moments.</strong> Every round transition is a fresh set of predictions and fresh trash talk on the group chat.</>,
            ]} />
          </WhyCard>
        </div>
      </Section>

      {/* How it was built */}
      <Section title="How it was built">
        <p className="text-sm font-sans text-text-secondary leading-relaxed">
          Built by Lewis Steele and Craig Robinson. The frontend is a React 18 PWA hosted on
          Vercel; the backend is a FastAPI service running on Railway backed by a Supabase Postgres
          database. Match results are fetched automatically from{' '}
          <a
            href="https://www.football-data.org"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-2 hover:underline inline-flex items-center gap-0.5"
          >
            football-data.org
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
          . Push notifications use the Web Push / VAPID standard.
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          {['React 18', 'Vite', 'FastAPI', 'PostgreSQL', 'Vercel', 'Railway', 'Supabase', 'Workbox'].map((tag) => (
            <span
              key={tag}
              className="px-2.5 py-1 rounded-md bg-surface-elevated border border-border text-xs font-mono text-text-secondary"
            >
              {tag}
            </span>
          ))}
        </div>

        {/* Founders + executive sponsors */}
        <JokeFigure
          src="/about/founders-handshake.jpg"
          alt="The two founders shaking hands in an office, one wearing a blue bumbag — a tribute to The Office."
          className="pt-2"
        />
        <div>
          <SubHead>Executive Sponsors</SubHead>
          <div className="grid grid-cols-2 gap-3">
            <JokeFigure
              src="/about/man-of-steele.jpg"
              alt="A 'Man of Steele' logo — the Superman shield reworked with the word STEELE."
              caption="Lewis Steele"
              imgClassName="h-28 object-contain"
            />
            <JokeFigure
              src="/about/robinsons.png"
              alt="A 'Robinsons' logo, Craig Robinson's alter-ego brand."
              caption="Craig Robinson"
              imgClassName="h-28 object-contain"
            />
          </div>
        </div>
      </Section>

      {/* End-of-rules sentinel — triggers "Read the rules" checklist tick */}
      <div
        ref={rulesEndRef}
        data-testid="about-rules-end"
        className="rounded-lg border border-primary/20 bg-primary/5 px-5 py-4"
      >
        <p className="text-sm font-sans font-semibold text-text-primary">
          That&apos;s everything.
        </p>
        <p className="mt-1 text-sm font-sans leading-relaxed text-text-secondary">
          Use Predict → Specials for your pre-tournament bonus picks, and Predict for your match-by-match scores.
        </p>
      </div>

      {/* Footer credit */}
      <div className="space-y-2 pb-2">
        <p className="text-center text-sm font-sans text-text-secondary">Thanks for playing.</p>
        <JokeFigure
          src="/about/prestige-worldwide.jpg"
          alt="Two men in white suits on a yacht with champagne — a Prestige Worldwide tribute from Step Brothers."
        />
        <p className="text-center text-xs font-sans text-text-muted">
          A Prestige Worldwide LLC Application
        </p>
      </div>
    </div>
  );
}
