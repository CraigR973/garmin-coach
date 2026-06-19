import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';

const ITEMS: ReadonlyArray<{ to: string; label: string; exact: boolean }> = [
  { to: '/predictions', label: 'All', exact: true },
  { to: '/predictions/group', label: 'Group', exact: false },
  { to: '/predictions/knockout', label: 'Knockout', exact: false },
  { to: '/predictions/specials', label: 'Specials', exact: false },
];

/**
 * Sub-nav shown at the top of every /predictions/* route so users can swap
 * between the three prediction surfaces without going back to Dashboard.
 * Matches the Leaderboard SubNav / Schedule StageFilter pill pattern.
 */
export function PredictionsSubNav() {
  return (
    <nav className="-mx-4 sm:-mx-0 mb-5 overflow-x-auto" aria-label="Predictions sections">
      <div className="flex gap-1.5 px-4 sm:px-0 min-w-max">
        {ITEMS.map(({ to, label, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              cn(
                'inline-flex items-center px-3.5 py-1.5 rounded-full text-xs font-medium font-sans whitespace-nowrap transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow',
                isActive
                  ? 'bg-primary/15 text-primary border border-primary/30'
                  : 'bg-surface text-text-secondary hover:bg-surface-elevated border border-border',
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
