import { useEffect } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

/**
 * Resets the window scroll to the top on a forward navigation (PUSH/REPLACE),
 * so opening a new route never lands mid-page. POP (browser back/forward) is
 * left alone — the browser restores the prior scroll position, which pairs with
 * PageTransition's backward slide for a natural "return where you were" feel.
 *
 * Renders nothing; mounted once inside the router.
 */
export function ScrollToTop() {
  const { pathname } = useLocation();
  const navType = useNavigationType();

  useEffect(() => {
    if (navType === 'POP') return;
    window.scrollTo(0, 0);
  }, [pathname, navType]);

  return null;
}
