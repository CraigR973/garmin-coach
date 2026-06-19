import { useCallback, useRef } from 'react';

interface UseLongPressOptions {
  onLongPress: () => void;
  onClick?: () => void;
  delayMs?: number;
  moveThresholdPx?: number;
}

interface UseLongPressHandlers {
  onPointerDown: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerCancel: (e: React.PointerEvent) => void;
  onPointerLeave: (e: React.PointerEvent) => void;
  onContextMenu: (e: React.MouseEvent) => void;
}

export function useLongPress({
  onLongPress,
  onClick,
  delayMs = 500,
  moveThresholdPx = 10,
}: UseLongPressOptions): UseLongPressHandlers {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const firedRef = useRef(false);
  const startRef = useRef<{ x: number; y: number } | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      firedRef.current = false;
      startRef.current = { x: e.clientX, y: e.clientY };
      clearTimer();
      timerRef.current = setTimeout(() => {
        firedRef.current = true;
        timerRef.current = null;
        onLongPress();
      }, delayMs);
    },
    [clearTimer, delayMs, onLongPress],
  );

  const onPointerUp = useCallback(() => {
    const fired = firedRef.current;
    clearTimer();
    startRef.current = null;
    if (!fired && onClick) onClick();
  }, [clearTimer, onClick]);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (startRef.current === null) return;
      const dx = Math.abs(e.clientX - startRef.current.x);
      const dy = Math.abs(e.clientY - startRef.current.y);
      if (dx > moveThresholdPx || dy > moveThresholdPx) clearTimer();
    },
    [clearTimer, moveThresholdPx],
  );

  const onPointerCancel = useCallback(() => {
    clearTimer();
    startRef.current = null;
  }, [clearTimer]);

  const onPointerLeave = useCallback(() => {
    clearTimer();
    startRef.current = null;
  }, [clearTimer]);

  const onContextMenu = useCallback((e: React.MouseEvent) => {
    // Suppress the context menu so long-press on mobile/desktop doesn't
    // open the browser's default menu after the handler fires.
    if (firedRef.current) e.preventDefault();
  }, []);

  return {
    onPointerDown,
    onPointerUp,
    onPointerMove,
    onPointerCancel,
    onPointerLeave,
    onContextMenu,
  };
}
