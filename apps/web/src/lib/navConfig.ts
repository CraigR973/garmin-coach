import {
  CalendarCheck,
  ClipboardList,
  FileDown,
  FileText,
  FlaskConical,
  Hammer,
  Home,
  MoonStar,
  Settings as SettingsIcon,
  Thermometer,
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
 *
 * Batch 49 revised the primary bar from Home/Plan/Trends to Home/Week/Sleep.
 * Batch 101 extends that split with a dedicated Climate tab so Sleep can keep
 * the sleep story while Climate owns the room/fan controls.
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
  { to: '/delivery', label: 'Week', Icon: CalendarCheck },
  { to: '/sleep', label: 'Sleep', Icon: MoonStar },
  { to: '/environment', label: 'Climate', Icon: Thermometer },
];

export const MORE_GROUPS: NavGroup[] = [
  {
    heading: 'For you',
    items: [
      { to: '/reviews', label: 'Reviews', Icon: FileText, description: 'Weekly & monthly summaries' },
      { to: '/trends', label: 'Trends', Icon: TrendingUp, description: 'Long-range charts and history' },
      { to: '/holiday', label: 'Holiday', Icon: Umbrella, description: 'Pause your plan while away' },
    ],
  },
  {
    heading: 'Coaching',
    items: [
      { to: '/builder', label: 'New training block', Icon: Hammer, description: 'Generate a new 13-week block' },
      { to: '/experiments', label: 'Experiments', Icon: FlaskConical, description: "What we're testing" },
    ],
  },
  {
    heading: 'Setup',
    items: [
      { to: '/coach-state', label: 'Coach memory', Icon: ClipboardList, description: 'Edit your saved context' },
      { to: '/handover', label: 'Handover', Icon: FileDown, description: 'Full briefing for a new AI chat' },
      { to: '/settings', label: 'Settings', Icon: SettingsIcon },
    ],
  },
];

/** Flat list of every destination behind "More" — used to light the More tab as active. */
export const SECONDARY_PATHS: string[] = MORE_GROUPS.flatMap((g) => g.items.map((i) => i.to));
