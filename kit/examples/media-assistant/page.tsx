'use client';
import { useEffect, useRef, useState } from 'react';
import { VoiceRecorder, AudioPlayback } from '../../modules/voice/src/components';
import { sampleTranscript } from '../../modules/voice/src/index';
import { MediaInput, DetectionOverlay } from '../../modules/media/src/components';
import { sampleImageSvg, sampleVisionResult } from '../../modules/media/src/index';
import { JobProgress, Status, MetricCard } from '../../packages/ui/src/index';
import { JobSchema, type Job } from '../../packages/contracts/src/index';
export default function MediaAssistant() {
  const [audio, setAudio] = useState<Blob>(),
    [transcript, setTranscript] = useState(''),
    [image, setImage] = useState<string>(),
    [sample, setSample] = useState(false),
    [job, setJob] = useState<Job>(),
    [error, setError] = useState('');
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (poll.current) clearTimeout(poll.current);
    };
  }, []);
  useEffect(
    () => () => {
      if (image?.startsWith('blob:')) URL.revokeObjectURL(image);
    },
    [image],
  );
  async function refresh(id: string) {
    try {
      const r = await fetch(`/api/kit/jobs?id=${encodeURIComponent(id)}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error ?? 'Job not found');
      if (!alive.current) return;
      const parsed = JobSchema.parse(data);
      setJob(parsed);
      if (['queued', 'running'].includes(parsed.state))
        poll.current = setTimeout(() => void refresh(id), 250);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : 'Could not read job');
    }
  }
  async function processTranscript() {
    setError('');
    try {
      const r = await fetch('/api/kit/jobs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          type: 'ingest',
          input: { lines: transcript.split('\n').filter(Boolean), delayMs: 250 },
          idempotencyKey: crypto.randomUUID(),
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error ?? 'Job failed');
      const parsed = JobSchema.parse(data);
      setJob(parsed);
      void refresh(parsed.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start job');
    }
  }
  return (
    <div className="composition">
      <div className="page-heading">
        <div>
          <p className="eyebrow">REFERENCE / MEDIA ASSISTANT</p>
          <h1>
            More ways to
            <br />
            <em>bring an idea in.</em>
          </h1>
          <p>Record, upload, or explore a sample. Every result tells you where it came from.</p>
        </div>
        <span className="badge">Local media · explicit sample analysis</span>
      </div>
      <div className="metrics">
        <MetricCard
          label="Audio input"
          value={audio ? 'Ready' : 'Not recorded'}
          detail="Microphone stays on your device"
        />
        <MetricCard
          label="Image input"
          value={image ? 'Ready' : 'Choose a source'}
          detail="Bounded browser preprocessing"
        />
        <MetricCard
          label="Processing"
          value={job?.state ?? 'Idle'}
          detail="Real local worker · non-durable demo"
        />
      </div>
      <div className="composition-grid">
        <section className="panel">
          <h2>Say it, or start with a sample.</h2>
          <p className="panel-note">
            Recording produces a local audio file. Transcription uses a configured live adapter; the
            sample transcript below is separate synthetic text.
          </p>
          <VoiceRecorder onRecorded={(blob) => setAudio(blob)} />
          {audio && <AudioPlayback blob={audio} label="Your local recording" />}
          <div className="divider" />
          <div className="panel-heading">
            <h3>Transcript workspace</h3>
            <button className="secondary" onClick={() => setTranscript(sampleTranscript.text)}>
              Load sample transcript
            </button>
          </div>
          <label>
            Synthetic sample or your own text
            <textarea
              aria-label="Transcript workspace"
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              rows={6}
            />
          </label>
          <button
            disabled={!transcript.trim() || (!!job && ['queued', 'running'].includes(job.state))}
            onClick={() => void processTranscript()}
          >
            Process text in worker ↗
          </button>
          {job && (
            <>
              <JobProgress
                state={job.state}
                progress={job.progress}
                onCancel={() =>
                  void fetch(`/api/kit/jobs?id=${job.id}`, { method: 'DELETE' }).then(() =>
                    refresh(job.id),
                  )
                }
              />
              {job.state === 'succeeded' && (
                <div className="local-result">
                  <p className="eyebrow">LOCAL WORKER RESULT</p>
                  <pre>{JSON.stringify(job.result, null, 2)}</pre>
                </div>
              )}
            </>
          )}
          {error && <Status kind="error" title={error} onRetry={() => void processTranscript()} />}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>A picture, with context.</h2>
            <button
              className="secondary"
              onClick={() => {
                setImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(sampleImageSvg)}`);
                setSample(true);
              }}
            >
              Load sample image
            </button>
          </div>
          <MediaInput
            onImage={(prepared) => {
              setImage(URL.createObjectURL(prepared.blob));
              setSample(false);
            }}
          />
          {image ? (
            sample ? (
              <>
                <span className="badge">Fixture detections · authored sample</span>
                <DetectionOverlay src={image} result={sampleVisionResult} />
              </>
            ) : (
              <>
                <span className="badge">Your image · preprocessed locally</span>
                <img className="media-preview" src={image} alt="Your preprocessed upload" />
                <p className="panel-note">
                  No detections invented: connect the vision adapter for live analysis.
                </p>
              </>
            )
          ) : (
            <Status title="A fresh perspective awaits">
              Upload an image, allow the camera, or load the synthetic sample.
            </Status>
          )}
        </section>
      </div>
    </div>
  );
}
