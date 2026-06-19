// Persistence for the one-time pre-tournament setup checklist (U20.4).
//
// A single localStorage key (`sss_checklist_v1`) holds the two client-owned
// facts the checklist can't derive from the server:
//   - rulesRead:  item 1 satisfied (reached the end of the rules on /about)
//   - dismissed:  hard latch — set on explicit Dismiss, or once all three
//                 items are complete, so the section never reappears.
//
// Items 2 (specials submitted) and 3 (first prediction made) are read live
// from the API and are monotonic, so they need no persistence here.

const KEY = 'sss_checklist_v1';

export interface ChecklistState {
  rulesRead: boolean;
  dismissed: boolean;
}

const EMPTY: ChecklistState = { rulesRead: false, dismissed: false };

export function readChecklist(): ChecklistState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...EMPTY };
    const parsed = JSON.parse(raw) as Partial<ChecklistState>;
    return { rulesRead: !!parsed.rulesRead, dismissed: !!parsed.dismissed };
  } catch {
    return { ...EMPTY };
  }
}

export function writeChecklist(patch: Partial<ChecklistState>): void {
  try {
    const next = { ...readChecklist(), ...patch };
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore — private mode / disabled storage */
  }
}

/** Mark the "Read the rules" item done. Called once the About page is read to the end. */
export function markRulesRead(): void {
  writeChecklist({ rulesRead: true });
}
