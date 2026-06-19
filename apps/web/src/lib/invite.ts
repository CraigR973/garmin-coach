import { toast } from 'sonner';

export interface InviteMessageParams {
  leagueName: string;
  joinCode: string;
  origin: string;
}

export function buildInviteMessage({ leagueName, joinCode, origin }: InviteMessageParams): string {
  return [
    `Join me on Calcio — World Cup 2026 predictions.`,
    ``,
    `Like fantasy football: you predict once and your picks count across every league you're in.`,
    ``,
    `New here? Install the app first:`,
    `${origin}`,
    `Then create an account and tap Leagues → Join by code.`,
    ``,
    `Already have the app? Open it and tap Leagues → Join by code.`,
    ``,
    `League: ${leagueName}`,
    `Join code: ${joinCode}`,
  ].join('\n');
}

export interface ShareInviteParams {
  message: string;
}

export async function shareInvite({ message }: ShareInviteParams): Promise<'shared' | 'copied' | 'cancelled'> {
  if (typeof navigator !== 'undefined' && navigator.share) {
    try {
      // Share text only — no url param. iOS renders the url as a separate
      // clickable link below the text, which clutters the preview and appears
      // adjacent to the "already have the app" line. The install URL is already
      // embedded in the message text so there's no information loss.
      await navigator.share({ text: message });
      return 'shared';
    } catch (err) {
      // AbortError = user dismissed/swiped the share sheet — not an error, stay silent
      if (err instanceof Error && err.name === 'AbortError') return 'cancelled';
      throw err;
    }
  }
  await navigator.clipboard.writeText(`${message}`);
  toast.success('Invite link copied to clipboard');
  return 'copied';
}
