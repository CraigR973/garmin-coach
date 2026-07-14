import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BriefListenControls } from './BriefListenControls';

const apiFetchBlobMock = vi.fn();

vi.mock('@/lib/api', () => ({
  apiFetchBlob: (...args: unknown[]) => apiFetchBlobMock(...args),
}));

const speechSynthesisMock = {
  speak: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
  getVoices: vi.fn(() => [] as SpeechSynthesisVoice[]),
  onvoiceschanged: null as (() => void) | null,
};

class MockAudio {
  onplay: (() => void) | null = null;
  onpause: (() => void) | null = null;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ended = false;
  play = vi.fn(() => {
    this.onplay?.();
    return Promise.resolve();
  });
  pause = vi.fn(() => {
    this.onpause?.();
  });
  constructor(public src: string) {}
}

let lastAudio: MockAudio | null = null;

beforeEach(() => {
  apiFetchBlobMock.mockReset();
  lastAudio = null;
  speechSynthesisMock.speak.mockClear();
  speechSynthesisMock.pause.mockClear();
  speechSynthesisMock.resume.mockClear();
  speechSynthesisMock.cancel.mockClear();
  speechSynthesisMock.getVoices.mockClear();
  speechSynthesisMock.getVoices.mockReturnValue([]);
  speechSynthesisMock.onvoiceschanged = null;

  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: speechSynthesisMock,
  });
  Object.defineProperty(window, 'SpeechSynthesisUtterance', {
    configurable: true,
    value: class MockSpeechSynthesisUtterance {
      text: string;
      lang = '';
      pitch = 1;
      rate = 1;
      voice: SpeechSynthesisVoice | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onpause: (() => void) | null = null;
      onresume: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    },
  });

  vi.stubGlobal(
    'Audio',
    vi.fn((src: string) => {
      lastAudio = new MockAudio(src);
      return lastAudio;
    }),
  );
  (URL as unknown as { createObjectURL: (blob: Blob) => string }).createObjectURL = vi.fn(() => 'blob:mock-url');
  (URL as unknown as { revokeObjectURL: (url: string) => void }).revokeObjectURL = vi.fn();
});

describe('BriefListenControls', () => {
  it('reads on-device by default (no hosted consent)', async () => {
    const user = userEvent.setup();
    render(<BriefListenControls markdown="Train as planned today." />);

    await user.click(screen.getByRole('button', { name: 'Listen to brief' }));

    expect(apiFetchBlobMock).not.toHaveBeenCalled();
    expect(speechSynthesisMock.speak).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('button', { name: 'Pause brief audio' })).toBeTruthy();
  });

  it('plays the hosted voice when consent is given, without touching on-device speech', async () => {
    apiFetchBlobMock.mockResolvedValue(new Blob(['audio'], { type: 'audio/mpeg' }));
    const user = userEvent.setup();
    render(<BriefListenControls markdown="Train as planned today." hostedTtsConsent />);

    await user.click(screen.getByRole('button', { name: 'Listen to brief' }));

    await waitFor(() => expect(apiFetchBlobMock).toHaveBeenCalledWith('/api/v1/tts/synthesize', {
      method: 'POST',
      body: JSON.stringify({ text: 'Train as planned today.' }),
    }));
    expect(lastAudio?.play).toHaveBeenCalledTimes(1);
    expect(speechSynthesisMock.speak).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Pause brief audio' })).toBeTruthy();
  });

  it('falls back to the on-device voice when the hosted call fails', async () => {
    apiFetchBlobMock.mockRejectedValue(new Error('API error 403'));
    const user = userEvent.setup();
    render(<BriefListenControls markdown="Train as planned today." hostedTtsConsent />);

    await user.click(screen.getByRole('button', { name: 'Listen to brief' }));

    await waitFor(() => expect(speechSynthesisMock.speak).toHaveBeenCalledTimes(1));
    expect(lastAudio).toBeNull();
    expect(await screen.findByRole('button', { name: 'Pause brief audio' })).toBeTruthy();
  });

  it('stops hosted playback and releases the object URL on Stop', async () => {
    apiFetchBlobMock.mockResolvedValue(new Blob(['audio'], { type: 'audio/mpeg' }));
    const user = userEvent.setup();
    render(<BriefListenControls markdown="Train as planned today." hostedTtsConsent />);

    await user.click(screen.getByRole('button', { name: 'Listen to brief' }));
    await screen.findByRole('button', { name: 'Pause brief audio' });

    await user.click(screen.getByRole('button', { name: 'Stop brief audio' }));

    expect(lastAudio?.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
    expect(screen.getByRole('button', { name: 'Listen to brief' })).toBeTruthy();
  });
});
