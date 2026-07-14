export interface VoiceLike {
  name: string;
  lang: string;
  localService: boolean;
}

const QUALITY_KEYWORDS = [/natural/i, /neural/i, /premium/i, /enhanced/i];

function languageScore(voiceLang: string, targetLang: string): number {
  const voice = voiceLang.toLowerCase();
  const target = targetLang.toLowerCase();

  if (voice === target) {
    return 2;
  }

  const voiceBase = voice.split(/[-_]/)[0];
  const targetBase = target.split(/[-_]/)[0];
  return voiceBase === targetBase ? 1 : 0;
}

/**
 * Picks the best on-device voice for a target language, ignoring any voice
 * whose `localService` is false. Chrome's default "Google UK English" style
 * voices report as SpeechSynthesisVoice but actually synthesize on Google's
 * servers, so honoring them would send the brief text off-device — the exact
 * privacy tradeoff Decision #179 chose the browser API to avoid. Returns null
 * (leave the browser's own default voice in place) when nothing local matches
 * the target language.
 */
export function selectBestVoice<T extends VoiceLike>(voices: T[], targetLang: string): T | null {
  let best: T | null = null;
  let bestScore = -1;

  for (const voice of voices) {
    if (!voice.localService) {
      continue;
    }

    const langScore = languageScore(voice.lang, targetLang);
    if (langScore === 0) {
      continue;
    }

    const qualityBonus = QUALITY_KEYWORDS.some((pattern) => pattern.test(voice.name)) ? 1 : 0;
    const score = langScore * 10 + qualityBonus;

    if (score > bestScore) {
      bestScore = score;
      best = voice;
    }
  }

  return best;
}
