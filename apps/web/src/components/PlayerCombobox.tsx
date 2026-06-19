/**
 * PlayerCombobox — debounced typeahead for WC 2026 squad players.
 *
 * Uses shadcn Combobox pattern: @radix-ui/react-popover + cmdk.
 * Queries GET /api/v1/squad/search?q=<term> with 300 ms debounce.
 */

import { useEffect, useRef, useState } from 'react';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from 'cmdk';
import * as Popover from '@radix-ui/react-popover';
import type { SquadPlayerResult } from '../lib/types';
import { apiFetch } from '../lib/api';

interface PlayerComboboxProps {
  /** Currently selected player id (controlled) */
  value: string;
  /** Called when user selects a player; receives (id, displayName) */
  onChange: (id: string, displayName: string) => void;
  /** Display name for the current value — shown in trigger when closed */
  displayName: string;
  disabled?: boolean;
  placeholder?: string;
  'aria-label'?: string;
  /** Optional position filter passed to the API (e.g. "GK" for Golden Glove) */
  position?: string;
}

export function PlayerCombobox({
  value,
  onChange,
  displayName,
  disabled = false,
  placeholder = 'Search for a player…',
  'aria-label': ariaLabel,
  position,
}: PlayerComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SquadPlayerResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Scroll trigger into view when the virtual keyboard resizes the viewport.
  // Without this the trigger (and the popover above it) can end up behind the keyboard.
  useEffect(() => {
    if (!open) return;
    const vv = window.visualViewport;
    if (!vv) return;
    const onResize = () => {
      triggerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };
    vv.addEventListener('resize', onResize);
    return () => vv.removeEventListener('resize', onResize);
  }, [open]);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(false);
    debounceRef.current = setTimeout(async () => {
      try {
        const positionParam = position ? `&position=${encodeURIComponent(position)}` : '';
        const data = await apiFetch<SquadPlayerResult[]>(
          `/api/v1/squad/search?q=${encodeURIComponent(query)}&limit=20${positionParam}`,
        );
        setResults(data);
      } catch {
        setError(true);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // Capture-phase pointerdown listener — fires before any stopPropagation and
  // works on iOS Safari where Radix's dismissal layer may not detect outside taps.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      const target = e.target as Node;
      if (
        (contentRef.current && contentRef.current.contains(target)) ||
        (triggerRef.current && triggerRef.current.contains(target))
      ) return;
      setOpen(false);
      setQuery('');
    }
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [open]);

  function handleSelect(player: SquadPlayerResult) {
    onChange(player.id, player.full_name);
    setOpen(false);
    setQuery('');
  }

  function handleDismiss() {
    setOpen(false);
    setQuery('');
  }

  return (
    <Popover.Root open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQuery(''); }}>
      <Popover.Trigger asChild>
        <button
          ref={triggerRef}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel ?? 'Select player'}
          disabled={disabled}
          className="w-full flex items-center justify-between rounded-md border border-border bg-background text-text-primary font-sans text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span className={displayName ? 'text-text-primary' : 'text-text-muted'}>
            {displayName || placeholder}
          </span>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="ml-2 shrink-0 opacity-50"
            aria-hidden="true"
          >
            <path d="m7 15 5 5 5-5" />
            <path d="m7 9 5-5 5 5" />
          </svg>
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={4}
          ref={contentRef}
          onInteractOutside={handleDismiss}
          onEscapeKeyDown={handleDismiss}
          className="z-50 w-[var(--radix-popover-trigger-width)] min-w-[220px] rounded-md border border-border bg-surface shadow-lg outline-none"
        >
          <Command shouldFilter={false}>
            <div className="border-b border-border px-3 py-2">
              <CommandInput
                value={query}
                onValueChange={setQuery}
                placeholder={placeholder}
                autoFocus
                className="w-full bg-transparent text-base md:text-sm text-text-primary placeholder:text-text-muted outline-none"
                aria-label="Search player name"
              />
            </div>

            <CommandList className="max-h-60 overflow-y-auto py-1">
              {loading && (
                <div className="px-3 py-2 text-sm text-text-muted">Searching…</div>
              )}
              {error && !loading && (
                <div className="px-3 py-2 text-sm text-red-500">Search failed. Try again.</div>
              )}
              {!loading && !error && query.trim() && results.length === 0 && (
                <CommandEmpty className="px-3 py-2 text-sm text-text-muted">
                  No players found.
                </CommandEmpty>
              )}
              {!loading && !error && results.length > 0 && (
                <CommandGroup>
                  {results.map((player) => (
                    <CommandItem
                      key={player.id}
                      value={player.id}
                      onSelect={() => handleSelect(player)}
                      className="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer rounded hover:bg-surface-hover aria-selected:bg-surface-hover"
                    >
                      <span aria-hidden="true">{player.flag_emoji}</span>
                      <span className="flex-1 font-medium text-text-primary">{player.known_as}</span>
                      <span className="text-xs text-text-muted">{player.team_code}</span>
                      <span className="text-xs text-text-muted font-mono">{player.position}</span>
                      {value === player.id && (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <path d="M20 6 9 17l-5-5" />
                        </svg>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
