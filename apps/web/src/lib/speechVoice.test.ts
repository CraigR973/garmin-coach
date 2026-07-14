import { describe, expect, it } from 'vitest';
import { selectBestVoice, type VoiceLike } from './speechVoice';

describe('selectBestVoice', () => {
  it('ignores remote-service voices even when they outrank local ones by name', () => {
    const voices: VoiceLike[] = [
      { name: 'Daniel', lang: 'en-GB', localService: true },
      { name: 'Google UK English Female (Natural)', lang: 'en-GB', localService: false },
    ];

    expect(selectBestVoice(voices, 'en-GB')).toBe(voices[0]);
  });

  it('prefers an exact locale match over a same-language generic match', () => {
    const voices: VoiceLike[] = [
      { name: 'English', lang: 'en-US', localService: true },
      { name: 'English (UK)', lang: 'en-GB', localService: true },
    ];

    expect(selectBestVoice(voices, 'en-GB')).toBe(voices[1]);
  });

  it('prefers a quality-keyword voice over a plain voice at the same locale', () => {
    const voices: VoiceLike[] = [
      { name: 'English (UK)', lang: 'en-GB', localService: true },
      { name: 'Daniel (Enhanced)', lang: 'en-GB', localService: true },
    ];

    expect(selectBestVoice(voices, 'en-GB')).toBe(voices[1]);
  });

  it('returns null when no local voice matches the target language', () => {
    const voices: VoiceLike[] = [
      { name: 'Amélie', lang: 'fr-FR', localService: true },
      { name: 'Google UK English Female', lang: 'en-GB', localService: false },
    ];

    expect(selectBestVoice(voices, 'en-GB')).toBeNull();
  });

  it('returns null for an empty voice list', () => {
    expect(selectBestVoice([], 'en-GB')).toBeNull();
  });
});
