'use client';
import { useEffect, useRef, useState } from 'react';
import { captureFrame, prepareImage, sampleVideo } from './browser';
import {
  VisionResultSchema,
  type PreparedImage,
  type VideoFrame,
  type VisionResult,
} from './index';
function ImagePreview({ image, label }: { image: PreparedImage; label: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const url = URL.createObjectURL(image.blob);
    setUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);
  return url ? <img src={url} alt={label} style={{ maxWidth: '100%', maxHeight: 220 }} /> : null;
}
export function DetectionOverlay({ src, result }: { src: string; result: VisionResult }) {
  const parsed = VisionResultSchema.safeParse(result);
  if (!parsed.success) return <p role="alert">Invalid detection result.</p>;
  return (
    <figure>
      <figcaption>
        {result.mode} · {result.summary}
      </figcaption>
      <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
        <img src={src} alt={result.summary} style={{ display: 'block', maxWidth: '100%' }} />
        {result.detections.map((d, i) => (
          <div
            key={i}
            title={`${d.label}: ${Math.round(d.confidence * 100)}% model confidence`}
            style={{
              position: 'absolute',
              left: `${d.box.x * 100}%`,
              top: `${d.box.y * 100}%`,
              width: `${d.box.width * 100}%`,
              height: `${d.box.height * 100}%`,
              border: '2px solid #124f4a',
              boxSizing: 'border-box',
              pointerEvents: 'none',
            }}
          >
            <span style={{ color: '#fff', background: '#124f4a', fontSize: 12 }}>{d.label}</span>
          </div>
        ))}
      </div>
      {!result.detections.length && <p>No detections returned.</p>}
      <p>Model boxes are approximate and confidence scores are uncalibrated.</p>
    </figure>
  );
}
export function MediaInput({
  onImage,
  onFrames,
}: {
  onImage?: (image: PreparedImage, signal: AbortSignal) => Promise<void> | void;
  onFrames?: (frames: VideoFrame[], signal: AbortSignal) => Promise<void> | void;
}) {
  const [status, setStatus] = useState('idle'),
    [error, setError] = useState(''),
    [image, setImage] = useState<PreparedImage>(),
    [frames, setFrames] = useState<VideoFrame[]>([]);
  const video = useRef<HTMLVideoElement | null>(null),
    stream = useRef<MediaStream | null>(null),
    controller = useRef<AbortController | null>(null),
    generation = useRef(0);
  function stopCamera() {
    generation.current++;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
  }
  useEffect(
    () => () => {
      controller.current?.abort();
      stopCamera();
    },
    [],
  );
  async function run(work: (signal: AbortSignal) => Promise<void>) {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setStatus('processing');
    setError('');
    try {
      await work(c.signal);
      if (!c.signal.aborted) setStatus('ready');
    } catch (e) {
      if (!c.signal.aborted) {
        stopCamera();
        setError(e instanceof Error ? e.message : 'Media processing failed');
        setStatus('error');
      }
    }
  }
  async function camera() {
    stopCamera();
    const current = generation.current;
    setError('');
    setStatus('requesting camera');
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error('Camera requires HTTPS/localhost and browser support');
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1280 } },
        audio: false,
      });
      if (current !== generation.current) {
        s.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = s;
      if (video.current) {
        video.current.srcObject = s;
        await video.current.play();
      }
      if (current !== generation.current) return;
      setStatus('camera ready');
    } catch (e) {
      if (current !== generation.current) return;
      stopCamera();
      setStatus('error');
      setError(
        e instanceof DOMException && e.name === 'NotAllowedError'
          ? 'Camera permission denied. Enable camera access in browser site settings and retry.'
          : e instanceof Error
            ? e.message
            : 'Camera unavailable',
      );
    }
  }
  return (
    <section aria-label="Image and video input">
      <p>
        Images: JPEG, PNG or WebP up to 8 MB. Videos: MP4/WebM up to 50 MB and 120 seconds; six
        timestamped samples. Browser decoding support varies.
      </p>
      <label>
        Upload image{' '}
        <input
          aria-label="Upload image"
          type="file"
          disabled={['processing', 'requesting camera', 'camera ready'].includes(status)}
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              void run(async (signal) => {
                const prepared = await prepareImage(file, { signal });
                setImage(prepared);
                setFrames([]);
                await onImage?.(prepared, signal);
              });
            e.target.value = '';
          }}
        />
      </label>
      <label>
        Sample video{' '}
        <input
          aria-label="Sample video"
          type="file"
          disabled={['processing', 'requesting camera', 'camera ready'].includes(status)}
          accept="video/mp4,video/webm"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              void run(async (signal) => {
                const sampled = await sampleVideo(file, { signal });
                setFrames(sampled);
                setImage(undefined);
                await onFrames?.(sampled, signal);
              });
            e.target.value = '';
          }}
        />
      </label>
      <div>
        <button
          type="button"
          onClick={() => void camera()}
          disabled={['processing', 'requesting camera', 'camera ready'].includes(status)}
        >
          Open camera
        </button>
        <button
          type="button"
          disabled={status !== 'camera ready'}
          onClick={() =>
            void run(async (signal) => {
              const prepared = await captureFrame(video.current!, { signal });
              setImage(prepared);
              stopCamera();
              await onImage?.(prepared, signal);
            })
          }
        >
          Capture photo
        </button>
        <button
          type="button"
          onClick={() => {
            controller.current?.abort();
            stopCamera();
            setStatus('idle');
          }}
        >
          Cancel / close camera
        </button>
      </div>
      <video
        ref={video}
        muted
        playsInline
        aria-label="Camera preview"
        style={{
          maxWidth: '100%',
          maxHeight: 240,
          display: status === 'camera ready' ? 'block' : 'none',
        }}
      />
      <p role={error ? 'alert' : 'status'}>{error || status}</p>
      {image && (
        <ImagePreview image={image} label={`Prepared image ${image.width} × ${image.height}`} />
      )}
      {frames.map((f) => (
        <figure key={f.timestampSeconds}>
          <ImagePreview
            image={f.image}
            label={`Video frame at ${f.timestampSeconds.toFixed(2)} seconds`}
          />
          <figcaption>{f.timestampSeconds.toFixed(2)} seconds</figcaption>
        </figure>
      ))}
    </section>
  );
}
