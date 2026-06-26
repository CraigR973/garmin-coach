import { NavLink } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { Sheet } from '@/components/ui/sheet';
import { MORE_GROUPS } from '@/lib/navConfig';

/**
 * The "More" bottom sheet for mobile — the secondary/admin destinations that
 * don't belong in Mark's primary three-tab bar.
 */
export function MoreMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} title="More">
      <div className="space-y-5">
        {MORE_GROUPS.map((group) => (
          <div key={group.heading}>
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.25em] text-text-muted">
              {group.heading}
            </p>
            <ul className="space-y-1">
              {group.items.map(({ to, label, Icon, description }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    onClick={onClose}
                    className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-3 press-down hover:bg-surface-elevated focus-visible:outline-none focus-visible:shadow-glow"
                  >
                    <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-text-primary">{label}</span>
                      {description && (
                        <span className="block text-xs text-text-muted">{description}</span>
                      )}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Sheet>
  );
}
