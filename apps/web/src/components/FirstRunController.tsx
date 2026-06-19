import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { isTourSeen, markTourSeen } from './IntroTour';
import { FirstRunLaunchpad } from './FirstRunLaunchpad';

type Step = 'launchpad' | 'done';

/**
 * First authenticated load for a brand-new account: show the FirstRunLaunchpad
 * — a one-shot modal that points the user at the three pre-tournament tasks
 * (read the rules, set Specials, make a first pick) and lets them start
 * wherever they like.
 *
 * This replaces the previous behaviour of force-redirecting first-run users to
 * /about, which dropped new joiners straight into the full rules reference
 * instead of a guided "what to do next" launchpad.
 *
 * Gated on the per-user tour-seen latch (isTourSeen(player.id)) so a second
 * account created on a shared device still gets its own launchpad. The latch is
 * written on every close path (an action card or "skip"), so the launchpad only
 * ever shows once per account.
 */
export function FirstRunController() {
  const { player, sessionUnlockRequired } = useAuth();
  // Start hidden; the effect below opens the launchpad for new accounts once
  // the player identity is known.
  const [step, setStep] = useState<Step>('done');

  // Re-check with the per-user key once player identity is known. This catches
  // a new account created on a device where a different account already exists.
  useEffect(() => {
    if (!player) return;
    if (!isTourSeen(player.id)) setStep('launchpad');
  }, [player?.id]);

  if (step !== 'launchpad' || !player || sessionUnlockRequired) return null;

  return (
    <FirstRunLaunchpad
      onClose={() => {
        markTourSeen(player.id);
        setStep('done');
      }}
    />
  );
}
