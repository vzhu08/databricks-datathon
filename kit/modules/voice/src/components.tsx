'use client';
import { useEffect, useRef, useState } from 'react';
import { MicrophoneRecorder, type RecorderSnapshot } from './browser';
export function AudioPlayback({ blob, label }: { blob: Blob; label: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const source = URL.createObjectURL(blob);
    setUrl(source);
    return () => URL.revokeObjectURL(source);
  }, [blob]);
  return (
    <figure>
      <figcaption>{label}</figcaption>
      {url && (
        <audio controls src={url} aria-label={label}>
          Your browser does not support audio playback.
        </audio>
      )}
    </figure>
  );
}
export function VoiceRecorder({
  onRecorded,
}: {
  onRecorded?: (blob: Blob, signal: AbortSignal) => Promise<void> | void;
}) {
  const [snapshot, setSnapshot] = useState<RecorderSnapshot>({ status: 'idle' });
  const [processing, setProcessing] = useState(false);
  const recorder = useRef<MicrophoneRecorder | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new MicrophoneRecorder(setSnapshot);
    recorder.current = controller;
    return () => {
      request.current?.abort();
      controller.dispose();
    };
  }, []);
  async function processRecording() {
    if (!snapshot.blob || !onRecorded) return;
    const c = new AbortController();
    request.current = c;
    setProcessing(true);
    try {
      await onRecorded(snapshot.blob, c.signal);
    } catch (error) {
      if (!c.signal.aborted)
        setSnapshot((s) => ({
          ...s,
          status: 'error',
          message: error instanceof Error ? error.message : 'Audio processing failed. Retry.',
        }));
    } finally {
      if (request.current === c) setProcessing(false);
    }
  }
  const busy = ['recording', 'requesting'].includes(snapshot.status) || processing;
  return (
    <section aria-label="Microphone recorder">
      <p>
        Local microphone capture · maximum 60 seconds. Nothing is uploaded until you select Process
        recording.
      </p>
      <div>
        <button type="button" disabled={busy} onClick={() => void recorder.current?.start()}>
          Start recording
        </button>
        <button
          type="button"
          disabled={snapshot.status !== 'recording'}
          onClick={() => recorder.current?.stop()}
        >
          Stop recording
        </button>
        <button
          type="button"
          disabled={snapshot.status === 'idle' && !processing}
          onClick={() => {
            request.current?.abort();
            request.current = null;
            setProcessing(false);
            recorder.current?.cancel();
          }}
        >
          Discard recording
        </button>
      </div>
      <p role={snapshot.status === 'error' || snapshot.status === 'denied' ? 'alert' : 'status'}>
        {processing
          ? 'Processing recorded file…'
          : (snapshot.message ?? `Microphone: ${snapshot.status}`)}
      </p>
      {snapshot.blob && (
        <>
          <AudioPlayback blob={snapshot.blob} label="Your local recording" />
          {onRecorded && (
            <button type="button" disabled={processing} onClick={() => void processRecording()}>
              Process recording
            </button>
          )}
        </>
      )}
    </section>
  );
}
