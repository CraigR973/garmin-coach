import { useState, useId, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Home,
  CalendarDays,
  Pencil,
  Trophy,
  MoreHorizontal,
  GitBranch,
  Users,
  Settings as SettingsIcon,
  Info,
  Shield,
  LogOut,
  type LucideIcon,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { Sheet } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

interface TabDef {
  to: string;
  label: string;
  Icon: LucideIcon;
  matchPrefix?: string[];
}

const PRIMARY: ReadonlyArray<TabDef> = [
  { to: '/', label: 'Home', Icon: Home },
  { to: '/schedule', label: 'Schedule', Icon: CalendarDays },
  { to: '/predictions', label: 'Predict', Icon: Pencil, matchPrefix: ['/predictions'] },
  { to: '/leagues', label: 'Leagues', Icon: Trophy, matchPrefix: ['/leagues', '/players'] },
];

const SECONDARY: ReadonlyArray<TabDef> = [
  { to: '/groups', label: 'Groups', Icon: Users, matchPrefix: ['/groups'] },
  { to: '/bracket', label: 'Knockout', Icon: GitBranch },
  { to: '/settings', label: 'Settings', Icon: SettingsIcon },
  { to: '/about', label: 'About', Icon: Info },
];

const ADMIN: ReadonlyArray<TabDef> = [
  { to: '/admin', label: 'Admin Dashboard', Icon: Shield, matchPrefix: ['/admin'] },
  { to: '/admin/invites', label: 'Invites', Icon: Shield },
  { to: '/admin/players', label: 'Players', Icon: Shield },
];

function isActive(pathname: string, tab: TabDef): boolean {
  if (tab.to === '/') return pathname === '/';
  if (tab.matchPrefix) return tab.matchPrefix.some((p) => pathname.startsWith(p));
  return pathname === tab.to || pathname.startsWith(`${tab.to}/`);
}

export function TabBar() {
  const { pathname } = useLocation();
  const { player, logout } = useAuth();
  const navigate = useNavigate();
  const [moreOpen, setMoreOpen] = useState(false);
  const layoutId = useId();

  // Guarantee the More sheet closes whenever the route changes, regardless of
  // how the navigation happened (sheet button, swipe-back, deep link).
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  const isMoreActive = [...SECONDARY, ...(player?.role === 'admin' ? ADMIN : [])].some((t) =>
    isActive(pathname, t),
  );

  const tabs: ReadonlyArray<TabDef & { isCurrent: boolean }> = [
    ...PRIMARY.map((t) => ({ ...t, isCurrent: isActive(pathname, t) })),
    {
      to: '#more',
      label: 'More',
      Icon: MoreHorizontal,
      isCurrent: isMoreActive,
    },
  ];

  function handleSheetNav(to: string) {
    setMoreOpen(false);
    navigate(to);
  }

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
          {tabs.map((tab) => {
            const { to, label, Icon, isCurrent } = tab;
            const isOverflow = to === '#more';
            const content = (
              <>
                {isCurrent && (
                  <motion.span
                    layoutId={layoutId}
                    className="absolute inset-x-3 top-0 h-0.5 bg-primary rounded-full"
                    transition={{ type: 'spring', stiffness: 360, damping: 32 }}
                  />
                )}
                <Icon
                  className={cn(
                    'h-5 w-5 transition-colors',
                    isCurrent ? 'text-primary' : 'text-text-muted',
                  )}
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
              </>
            );
            const baseClass = cn(
              'relative flex-1 flex flex-col items-center justify-center gap-1 tap-target',
              'focus-visible:outline-none focus-visible:shadow-glow rounded-sm press-down',
            );
            return (
              <li key={label} className="contents">
                {isOverflow ? (
                  <button
                    type="button"
                    onClick={() => setMoreOpen(true)}
                    aria-haspopup="dialog"
                    aria-expanded={moreOpen}
                    className={baseClass}
                  >
                    {content}
                  </button>
                ) : (
                  <NavLink
                    to={to}
                    end={to === '/'}
                    className={baseClass}
                    aria-current={isCurrent ? 'page' : undefined}
                  >
                    {content}
                  </NavLink>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title="More">
        <div className="flex flex-col gap-1">
          {SECONDARY.map(({ to, label, Icon }) => (
            <button
              key={to}
              type="button"
              onClick={() => handleSheetNav(to)}
              className="flex items-center gap-4 px-3 py-3 rounded-md text-left text-text-primary hover:bg-surface-elevated press-down tap-target focus-visible:outline-none focus-visible:shadow-glow"
            >
              <Icon className="h-5 w-5 text-text-secondary" aria-hidden />
              <span className="font-sans text-sm">{label}</span>
            </button>
          ))}

          {player?.role === 'admin' && (
            <>
              <div className="px-3 pt-4 pb-1 text-[10px] font-mono uppercase tracking-[0.25em] text-text-muted">
                Admin
              </div>
              {ADMIN.map(({ to, label, Icon }) => (
                <button
                  key={to}
                  type="button"
                  onClick={() => handleSheetNav(to)}
                  className="flex items-center gap-4 px-3 py-3 rounded-md text-left text-text-primary hover:bg-surface-elevated press-down tap-target focus-visible:outline-none focus-visible:shadow-glow"
                >
                  <Icon className="h-5 w-5 text-text-secondary" aria-hidden />
                  <span className="font-sans text-sm">{label}</span>
                </button>
              ))}
            </>
          )}

          <div className="h-px bg-border my-3" />

          <button
            type="button"
            onClick={() => {
              setMoreOpen(false);
              void logout();
            }}
            className="flex items-center gap-4 px-3 py-3 rounded-md text-left text-error hover:bg-surface-elevated press-down tap-target focus-visible:outline-none focus-visible:shadow-glow"
          >
            <LogOut className="h-5 w-5" aria-hidden />
            <span className="font-sans text-sm">Sign out</span>
          </button>
        </div>
      </Sheet>
    </>
  );
}
