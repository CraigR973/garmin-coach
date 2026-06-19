import { type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useLocation, useNavigationType } from 'react-router-dom';

/**
 * Page transition wrapper.
 *
 * - PUSH/REPLACE navigations slide in from the right (forward feeling).
 * - POP (browser back) navigations slide in from the left (backward feeling).
 * - `useReducedMotion` callers see no motion — just a cross-fade.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const prefersReducedMotion = useReducedMotion();
  const location = useLocation();
  const navType = useNavigationType();

  const direction = navType === 'POP' ? -1 : 1;
  const offset = prefersReducedMotion ? 0 : 16 * direction;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, x: offset }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -offset }}
        transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
