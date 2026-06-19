import { NavLink, Link } from 'react-router-dom';
import { Moon, Sun, User, Settings, Info, LogOut } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/contexts/ThemeContext';
import { Brand } from '@/components/Brand';
import { Avatar } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

const DESKTOP_NAV = [
  { to: '/', label: 'Home', exact: true },
  { to: '/schedule', label: 'Schedule', exact: false },
  { to: '/predictions', label: 'Predict', exact: false },
  { to: '/bracket', label: 'Knockout', exact: false },
  { to: '/groups', label: 'Groups', exact: false },
  { to: '/leagues', label: 'Leagues', exact: false },
  { to: '/settings', label: 'Settings', exact: false },
  { to: '/about', label: 'About', exact: false },
];

export function TopBar() {
  const { player, logout } = useAuth();
  const { resolved, setMode } = useTheme();
  function toggleTheme() {
    setMode(resolved === 'dark' ? 'light' : 'dark');
  }

  const themeToggle = (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className="tap-target inline-flex items-center justify-center rounded-md text-text-secondary hover:text-text-primary press-down focus-visible:outline-none focus-visible:shadow-glow"
    >
      {resolved === 'dark' ? (
        <Sun className="h-4 w-4" aria-hidden />
      ) : (
        <Moon className="h-4 w-4" aria-hidden />
      )}
    </button>
  );

  const avatarMenu = player ? (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`Account menu (${player.displayName})`}
        className="inline-flex items-center gap-2 press-down rounded-full focus-visible:outline-none focus-visible:shadow-glow"
      >
        <span className="hidden sm:inline text-sm text-text-secondary font-sans">
          {player.displayName}
        </span>
        <Avatar name={player.displayName} size="sm" src={player.avatarUrl} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to={`/players/${player.id}`}>
            <User className="h-4 w-4" aria-hidden />
            Profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <Settings className="h-4 w-4" aria-hidden />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/about">
            <Info className="h-4 w-4" aria-hidden />
            About / How it works
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut className="h-4 w-4" aria-hidden />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  ) : null;

  return (
    <header
      className={cn(
        'sticky top-0 z-header',
        'bg-surface/90 backdrop-blur-md border-b border-border',
        'pt-[calc(env(safe-area-inset-top,0px)+1rem)] md:pt-safe',
      )}
    >
      <div className="max-w-6xl mx-auto px-4 h-16 md:h-14 flex items-center gap-4">
        {/* ── Mobile layout (< md): toggle | centred brand | avatar ── */}
        <div className="relative flex md:hidden items-center w-full justify-between">
          {themeToggle}
          <NavLink
            to="/"
            aria-label="Home"
            className="press-down absolute inset-y-0 left-1/2 -translate-x-1/2 flex items-center"
          >
            <Brand variant="compact" size={46} />
          </NavLink>
          {avatarMenu}
        </div>

        {/* ── Desktop layout (md+): brand | nav | toggle + badge + avatar ── */}
        <NavLink to="/" aria-label="Home" className="press-down hidden md:block shrink-0">
          <Brand variant="compact" size={46} />
        </NavLink>

        <nav aria-label="Main navigation" className="hidden md:flex items-center gap-1 flex-1">
          {DESKTOP_NAV.map(({ to, label, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) =>
                cn(
                  'px-3 py-1.5 rounded-sm text-sm font-medium font-sans tracking-tight transition-colors press-down',
                  'focus-visible:outline-none focus-visible:shadow-glow',
                  isActive
                    ? 'bg-primary/15 text-primary'
                    : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated',
                )
              }
            >
              {label}
            </NavLink>
          ))}
          {player?.role === 'admin' && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                cn(
                  'ml-2 px-3 py-1.5 rounded-sm text-sm font-medium font-sans tracking-tight transition-colors press-down',
                  'focus-visible:outline-none focus-visible:shadow-glow',
                  isActive
                    ? 'bg-accent/15 text-accent'
                    : 'text-accent/80 hover:text-accent hover:bg-surface-elevated',
                )
              }
            >
              Admin
            </NavLink>
          )}
        </nav>

        <div className="hidden md:flex items-center gap-3">
          {themeToggle}
          {player?.role === 'admin' && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-accent/15 text-accent text-[10px] font-mono uppercase tracking-[0.2em]">
              Admin
            </span>
          )}
          {avatarMenu}
        </div>
      </div>
    </header>
  );
}
