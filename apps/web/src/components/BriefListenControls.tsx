import { useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play, Square } from 'lucide-react';
import { markdownToSpeechText } from '@/lib/markdownSpeech';
import { selectBestVoice } from '@/lib/speechVoice';
import { Button } from '@/components/ui/button';

type ListenState = 'idle' | 'playing' | 'paused' | 'unsupported';

function getSpeechSupport(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
}

export function BriefListenControls({ markdown }: { markdown: string }) {
  const [state, setState] = useState<ListenState>(() => (getSpeechSupport() ? 'idle' : 'unsupported'));
  const synthRef = useRef<SpeechSynthesis | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
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
    };
  }, []);

  useEffect(() => {
    if (utteranceRef.current) {
      synthRef.current?.cancel();
      utteranceRef.current = null;
      setState('idle');
    }
  }, [spokenText]);

  const startSpeaking = () => {
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

  const handleListenToggle = () => {
    if (state === 'unsupported') {
      return;
    }

    if (state === 'playing') {
      synthRef.current?.pause();
      return;
    }

    if (state === 'paused') {
      synthRef.current?.resume();
      return;
    }

    startSpeaking();
  };

  const handleStop = () => {
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

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={handleListenToggle}
        aria-pressed={isPlaying || isPaused}
        aria-label={isPlaying ? 'Pause brief audio' : isPaused ? 'Resume brief audio' : 'Listen to brief'}
      >
        {isPlaying ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
        {isPlaying ? 'Pause' : isPaused ? 'Resume' : 'Listen'}
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
