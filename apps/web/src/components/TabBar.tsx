import { useEffect, useId, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { MoreHorizontal } from 'lucide-react';
import { PRIMARY_TABS, SECONDARY_PATHS } from '@/lib/navConfig';
import { MoreMenu } from '@/components/MoreMenu';
import { cn } from '@/lib/utils';

function isTabActive(pathname: string, to: string): boolean {
  if (to === '/') return pathname === '/';
  return pathname === to || pathname.startsWith(`${to}/`);
}

const cellClass = cn(
  'relative flex-1 flex flex-col items-center justify-center gap-1 tap-target',
  'focus-visible:outline-none focus-visible:shadow-glow rounded-sm press-down',
);

export function TabBar() {
  const { pathname } = useLocation();
  const layoutId = useId();
  const [moreOpen, setMoreOpen] = useState(false);
  // Framer's layoutId spring is JS-driven, so the CSS prefers-reduced-motion
  // block doesn't cover it — gate it here so the indicator snaps instead of
  // sliding for reduced-motion users (Batch 137).
  const reduceMotion = useReducedMotion();
  const indicatorTransition = reduceMotion
    ? { duration: 0 }
    : { type: 'spring' as const, stiffness: 360, damping: 32 };

  // Close the More sheet whenever the route changes (e.g. after tapping an item).
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  const moreActive = SECONDARY_PATHS.some((to) => isTabActive(pathname, to));

  return (
    <>
      <nav
        aria-label="Primary"
        className={cn(
          'fixed bottom-0 inset-x-0 z-tabbar md:hidden',
          'bg-surface/95 backdrop-blur border-t border-border',
          'pb-safe',
        )}
      >
        <ul className="flex items-stretch justify-around h-[60px]">
          {PRIMARY_TABS.map(({ to, label, Icon }) => {
            const isCurrent = isTabActive(pathname, to);
            return (
              <li key={to} className="contents">
                <NavLink
                  to={to}
                  end={to === '/'}
                  aria-current={isCurrent ? 'page' : undefined}
                  className={cellClass}
                >
                  {isCurrent && (
                    <motion.span
                      layoutId={layoutId}
                      className="absolute inset-x-3 top-0 h-0.5 bg-primary rounded-full"
                      transition={indicatorTransition}
                    />
                  )}
                  <Icon
                    className={cn('h-5 w-5 transition-colors', isCurrent ? 'text-primary' : 'text-text-muted')}
                    aria-hidden
                  />
                  <span
                    className={cn(
                      'text-[10px] font-medium tracking-tight font-sans',
                      isCurrent ? 'text-primary' : 'text-text-muted',
                    )}
                  >
                    {label}
                  </span>
                </NavLink>
              </li>
            );
          })}

          <li className="contents">
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              aria-haspopup="dialog"
              aria-expanded={moreOpen}
              aria-current={moreActive ? 'page' : undefined}
              className={cellClass}
            >
              {moreActive && (
                <motion.span
                  layoutId={layoutId}
                  className="absolute inset-x-3 top-0 h-0.5 bg-primary rounded-full"
                  transition={indicatorTransition}
                />
              )}
              <MoreHorizontal
                className={cn('h-5 w-5 transition-colors', moreActive ? 'text-primary' : 'text-text-muted')}
                aria-hidden
              />
              <span
                className={cn(
                  'text-[10px] font-medium tracking-tight font-sans',
                  moreActive ? 'text-primary' : 'text-text-muted',
                )}
              >
                More
              </span>
            </button>
          </li>
        </ul>
      </nav>

      <MoreMenu open={moreOpen} onClose={() => setMoreOpen(false)} />
    </>
  );
}
