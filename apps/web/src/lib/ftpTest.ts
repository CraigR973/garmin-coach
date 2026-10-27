/**
 * Batch 336.1 (CI330-02): his ramp test's result, offered on Home for 7 days.
 *
 * The app's number is three-quarters of the best minute Garmin recorded. Zwift works out
 * its own number from the same test and sets the trainer from its own FTP setting, so the
 * two must hold the same number: he takes the app's in one tap, enters Zwift's if it
 * differs, or keeps the FTP he has. Draft wording for Craig's sign-off
 * (docs/drafts/2026-10-28-batch-336-wording.md); the tests hold every line here to it.
 */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "20 Oct" from "2026-10-20". */
export function dayMonth(isoDate: string): string {
  const [, month, day] = isoDate.split('-').map(Number);
  return `${day} ${MONTHS[month - 1]}`;
}

export function ftpTestTitle(ftpWatts: number): string {
  return `Your ramp test: FTP ${ftpWatts} W`;
}

export function ftpTestLine(testDate: string, bestMinuteWatts: number, ftpWatts: number): string {
  return (
    `Your best minute on ${dayMonth(testDate)} was ${bestMinuteWatts} W, and your new FTP is ` +
    `three-quarters of it: ${ftpWatts} W.`
  );
}

export function ftpTestCurrentLine(currentFtpWatts: number | null): string | null {
  return currentFtpWatts === null ? null : `Your FTP in the app is ${currentFtpWatts} W now.`;
}

export const FTP_TEST_ZWIFT_LINE =
  "Zwift sets your trainer from its own FTP setting, and the app grades your rides from this one, so they need the same number. If Zwift gave you a different number for this test, use Zwift's.";

export function setFtpLabel(ftpWatts: number): string {
  return `Set my FTP to ${ftpWatts} W`;
}

export const ZWIFT_NUMBER_LABEL = 'Zwift gave a different number';
export const ZWIFT_NUMBER_FIELD = "Zwift's FTP (W)";
export const ZWIFT_NUMBER_SAVE = 'Set this FTP';

export function zwiftNumberRange(low: number, high: number): string {
  return `Between ${low} and ${high} W.`;
}

export function keepFtpLabel(currentFtpWatts: number | null): string {
  return currentFtpWatts === null ? 'Keep my FTP' : `Keep ${currentFtpWatts} W`;
}

export function ftpSetToast(ftpWatts: number): string {
  return `Your FTP is now ${ftpWatts} W. Check Zwift's FTP setting says ${ftpWatts} W too.`;
}

export function ftpKeptToast(ftpWatts: number | null): string {
  return ftpWatts === null ? 'Your FTP stays as it is.' : `Your FTP stays ${ftpWatts} W.`;
}
