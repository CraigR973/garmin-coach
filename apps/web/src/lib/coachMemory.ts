/** Batch 346: the words Mark sees when the coach asks to remember something.
 *
 *  Kept in one place so the drafts doc for Craig's sign-off and the tests read the
 *  same strings the screens show. */

export const MEMORY_ASK_TITLE = 'Should the coach remember this?';
export const MEMORY_ASK_YES = 'Yes, remember it';
export const MEMORY_ASK_NO = 'No';
export const MEMORY_ASK_REMEMBERED = 'The coach will remember that.';
export const MEMORY_ASK_LEFT_OUT = 'The coach will leave that out.';
export const MEMORY_ASK_SEE_ALL = 'See everything the coach remembers';
export const MEMORY_FORGET = 'Forget this';
export const MEMORY_FORGOTTEN = 'The coach has forgotten that.';
export const MEMORY_PAGE_INTRO =
  'Each night the coach reads what you have told it and asks to remember anything you keep saying. ' +
  'Nothing is kept until you say yes, and nothing here changes how the coach makes the day’s call.';

/** How many asks Home shows at once; the rest wait on Coach memory. */
export const MEMORY_ASK_LIMIT = 3;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "10 Jun". */
export function dayMonth(isoDate: string): string {
  const [, month, day] = isoDate.split('-').map(Number);
  return `${day} ${MONTHS[month - 1]}`;
}

/** "You said on 10 Jun: “…”". */
export function memorySaidLine(sourceDate: string, quote: string): string {
  return `You said on ${dayMonth(sourceDate)}: “${quote}”`;
}

/** "2 more are waiting on Coach memory." */
export function memoryMoreLine(count: number): string {
  return count === 1 ? '1 more is waiting on Coach memory.' : `${count} more are waiting on Coach memory.`;
}
