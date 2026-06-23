import { useId } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  CalendarCheck,
  ClipboardList,
  FileDown,
  FileText,
  FlaskConical,
  Hammer,
  Home,
  Settings as SettingsIcon,
  TrendingUp,
  Umbrella,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface TabDef {
  to: string;
  label: string;
  Icon: LucideIcon;
}

const TABS: ReadonlyArray<TabDef> = [
  { to: '/', label: 'Home', Icon: Home },
  { to: '/delivery', label: 'Plan', Icon: CalendarCheck },
  { to: '/builder', label: 'Builder', Icon: Hammer },
  { to: '/reviews', label: 'Reviews', Icon: FileText },
  { to: '/trends', label: 'Trends', Icon: TrendingUp },
  { to: '/experiments', label: 'Tests', Icon: FlaskConical },
  { to: '/handover', label: 'Handover', Icon: FileDown },
  { to: '/holiday', label: 'Holiday', Icon: Umbrella },
  { to: '/coach-state', label: 'Coach', Icon: ClipboardList },
  { to: '/settings', label: 'Settings', Icon: SettingsIcon },
];

function isActive(pathname: string, tab: TabDef): boolean {
  if (tab.to === '/') return pathname === '/';
  return pathname === tab.to || pathname.startsWith(`${tab.to}/`);
}

export function TabBar() {
  const { pathname } = useLocation();
  const layoutId = useId();

  const tabs = TABS.map((t) => ({ ...t, isCurrent: isActive(pathname, t) }));

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'fixed bottom-0 inset-x-0 z-tabbar md:hidden',
        'bg-surface/95 backdrop-blur border-t border-border',
        'pb-safe',
      )}
    >
      <ul className="flex items-stretch justify-around h-[60px]">
        {tabs.map(({ to, label, Icon, isCurrent }) => (
          <li key={label} className="contents">
            <NavLink
              to={to}
              end={to === '/'}
              aria-current={isCurrent ? 'page' : undefined}
              className={cn(
                'relative flex-1 flex flex-col items-center justify-center gap-1 tap-target',
                'focus-visible:outline-none focus-visible:shadow-glow rounded-sm press-down',
              )}
            >
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
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
