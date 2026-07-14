import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Pause, Play, Square } from 'lucide-react';
import { markdownToSpeechText } from '@/lib/markdownSpeech';
import { selectBestVoice } from '@/lib/speechVoice';
import { apiFetchBlob } from '@/lib/api';
import { Button } from '@/components/ui/button';

type ListenState = 'idle' | 'loading' | 'playing' | 'paused' | 'unsupported';

function getSpeechSupport(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
}

/**
 * Reads a brief aloud. Default path is on-device `SpeechSynthesis` (Batch 106
 * / 111, DECISIONS #179 / #184) — brief text never leaves the browser. When
 * `hostedTtsConsent` is true (an explicit opt-in, Batch 116), a natural
 * hosted voice is tried first via `/api/v1/tts/synthesize`; any failure
 * (network, 403 stale consent, 503 unconfigured) falls back to the on-device
 * voice rather than failing silently.
 */
export function BriefListenControls({
  markdown,
  hostedTtsConsent = false,
}: {
  markdown: string;
  hostedTtsConsent?: boolean;
}) {
  const [state, setState] = useState<ListenState>(() => (getSpeechSupport() ? 'idle' : 'unsupported'));
  const synthRef = useRef<SpeechSynthesis | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const spokenText = useMemo(() => markdownToSpeechText(markdown), [markdown]);

  useEffect(() => {
    if (!getSpeechSupport()) {
      setState('unsupported');
      return;
    }

    const synth = window.speechSynthesis;
    synthRef.current = synth;

    const loadVoices = () => setVoices(synth.getVoices());
    loadVoices();
    synth.onvoiceschanged = loadVoices;

    return () => {
      synth.onvoiceschanged = null;
      synth.cancel();
      utteranceRef.current = null;
      stopHostedAudio();
    };
  }, []);

  useEffect(() => {
    if (utteranceRef.current || audioRef.current) {
      synthRef.current?.cancel();
      utteranceRef.current = null;
      stopHostedAudio();
      setState('idle');
    }
  }, [spokenText]);

  function stopHostedAudio() {
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.onpause = null;
      audioRef.current.onplay = null;
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }

  const startOnDeviceSpeaking = () => {
    if (!synthRef.current || !spokenText) {
      return;
    }

    synthRef.current.cancel();

    const utterance = new SpeechSynthesisUtterance(spokenText);
    utterance.lang = document.documentElement.lang || navigator.language || 'en-GB';
    utterance.rate = 0.95;
    utterance.pitch = 1;

    const bestVoice = selectBestVoice(voices, utterance.lang);
    if (bestVoice) {
      utterance.voice = bestVoice;
    }
    utterance.onend = () => {
      utteranceRef.current = null;
      setState('idle');
    };
    utterance.onerror = () => {
      utteranceRef.current = null;
      setState('idle');
    };
    utterance.onpause = () => setState('paused');
    utterance.onresume = () => setState('playing');

    utteranceRef.current = utterance;
    setState('playing');
    synthRef.current.speak(utterance);
  };

  const startHostedSpeaking = async (): Promise<boolean> => {
    try {
      const blob = await apiFetchBlob('/api/v1/tts/synthesize', {
        method: 'POST',
        body: JSON.stringify({ text: spokenText }),
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioUrlRef.current = url;
      audio.onplay = () => setState('playing');
      audio.onpause = () => {
        if (!audio.ended) setState('paused');
      };
      audio.onended = () => {
        stopHostedAudio();
        setState('idle');
      };
      audio.onerror = () => {
        stopHostedAudio();
        setState('idle');
      };
      audioRef.current = audio;
      await audio.play();
      return true;
    } catch {
      stopHostedAudio();
      return false;
    }
  };

  const startSpeaking = async () => {
    if (!spokenText) {
      return;
    }

    if (hostedTtsConsent) {
      setState('loading');
      const started = await startHostedSpeaking();
      if (started) {
        return;
      }
    }

    startOnDeviceSpeaking();
  };

  const handleListenToggle = () => {
    if (state === 'unsupported' || state === 'loading') {
      return;
    }

    if (state === 'playing') {
      if (audioRef.current) {
        audioRef.current.pause();
      } else {
        synthRef.current?.pause();
      }
      return;
    }

    if (state === 'paused') {
      if (audioRef.current) {
        void audioRef.current.play();
      } else {
        synthRef.current?.resume();
      }
      return;
    }

    void startSpeaking();
  };

  const handleStop = () => {
    stopHostedAudio();
    synthRef.current?.cancel();
    utteranceRef.current = null;
    setState('idle');
  };

  if (state === 'unsupported') {
    return (
      <Button type="button" size="sm" variant="outline" disabled aria-label="Listen unavailable on this browser">
        <Play className="h-4 w-4" aria-hidden />
        Listen unavailable
      </Button>
    );
  }

  const isPlaying = state === 'playing';
  const isPaused = state === 'paused';
  const isLoading = state === 'loading';

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={handleListenToggle}
        disabled={isLoading}
        aria-pressed={isPlaying || isPaused}
        aria-label={
          isLoading
            ? 'Loading brief audio'
            : isPlaying
              ? 'Pause brief audio'
              : isPaused
                ? 'Resume brief audio'
                : 'Listen to brief'
        }
      >
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : isPlaying ? (
          <Pause className="h-4 w-4" aria-hidden />
        ) : (
          <Play className="h-4 w-4" aria-hidden />
        )}
        {isLoading ? 'Loading…' : isPlaying ? 'Pause' : isPaused ? 'Resume' : 'Listen'}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={handleStop}
        disabled={state === 'idle'}
        aria-label="Stop brief audio"
      >
        <Square className="h-4 w-4" aria-hidden />
        Stop
      </Button>
    </div>
  );
}
