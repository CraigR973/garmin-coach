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

/**
 * Single source of truth for navigation.
 *
 * Mark (the daily user) only needs a few screens, so the bottom bar carries
 * three primary tabs + "More"; the secondary/admin destinations live behind the
 * "More" menu. This replaced a 10-tab bottom bar (unusable on a phone) and a
 * 3-item desktop nav that left 7 destinations unreachable.
 */

export interface NavItem {
  to: string;
  label: string;
  Icon: LucideIcon;
  description?: string;
}

export interface NavGroup {
  heading: string;
  items: NavItem[];
}

export const PRIMARY_TABS: NavItem[] = [
  { to: '/', label: 'Home', Icon: Home },
  { to: '/delivery', label: 'Plan', Icon: CalendarCheck },
  { to: '/trends', label: 'Trends', Icon: TrendingUp },
];

export const MORE_GROUPS: NavGroup[] = [
  {
    heading: 'For you',
    items: [
      { to: '/reviews', label: 'Reviews', Icon: FileText, description: 'Weekly & monthly summaries' },
      { to: '/holiday', label: 'Holiday', Icon: Umbrella, description: 'Pause your plan while away' },
    ],
  },
  {
    heading: 'Coach tools',
    items: [
      { to: '/builder', label: 'Plan builder', Icon: Hammer, description: 'Generate a new 13-week block' },
      { to: '/experiments', label: 'Tests', Icon: FlaskConical, description: "What we're testing" },
      { to: '/handover', label: 'Handover', Icon: FileDown, description: 'Full briefing for a new AI chat' },
      { to: '/coach-state', label: 'Coach state', Icon: ClipboardList, description: 'Edit your saved context' },
    ],
  },
  {
    heading: 'App',
    items: [{ to: '/settings', label: 'Settings', Icon: SettingsIcon }],
  },
];

/** Flat list of every destination behind "More" — used to light the More tab as active. */
export const SECONDARY_PATHS: string[] = MORE_GROUPS.flatMap((g) => g.items.map((i) => i.to));
