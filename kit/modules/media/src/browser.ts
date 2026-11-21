import { z } from 'zod';
import { sampleFrameTimes, type PreparedImage, type VideoFrame } from './index';
export type ImageOptions = {
  maxDimension?: number;
  maxBytes?: number;
  quality?: number;
  signal?: AbortSignal;
};
function limits(options: ImageOptions) {
  return {
    dimension: z
      .number()
      .int()
      .min(64)
      .max(4096)
      .parse(options.maxDimension ?? 1280),
    bytes: z
      .number()
      .int()
      .min(1)
      .max(20_000_000)
      .parse(options.maxBytes ?? 8_000_000),
    quality: z
      .number()
      .min(0.1)
      .max(1)
      .parse(options.quality ?? 0.85),
  };
}
async function canvasImage(
  source: CanvasImageSource,
  width: number,
  height: number,
  originalBytes: number,
  options: ImageOptions,
): Promise<PreparedImage> {
  const l = limits(options);
  options.signal?.throwIfAborted();
  if (!width || !height || width * height > 40_000_000)
    throw new Error('Image dimensions invalid or exceed 40 megapixels');
  const scale = Math.min(1, l.dimension / Math.max(width, height)),
    outWidth = Math.max(1, Math.round(width * scale)),
    outHeight = Math.max(1, Math.round(height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = outWidth;
  canvas.height = outHeight;
  try {
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Canvas is not supported');
    context.fillStyle = '#fff';
    context.fillRect(0, 0, outWidth, outHeight);
    context.drawImage(source, 0, 0, outWidth, outHeight);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (value) => (value ? resolve(value) : reject(new Error('Image encoding failed'))),
        'image/jpeg',
        l.quality,
      ),
    );
    options.signal?.throwIfAborted();
    if (blob.size > l.bytes) throw new Error('Processed image exceeds byte limit');
    return { blob, width: outWidth, height: outHeight, mimeType: 'image/jpeg', originalBytes };
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}
export async function prepareImage(file: Blob, options: ImageOptions = {}): Promise<PreparedImage> {
  const l = limits(options);
  options.signal?.throwIfAborted();
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
    throw new Error('Unsupported image. Use JPEG, PNG or WebP.');
  if (!file.size || file.size > l.bytes) throw new Error('Image is empty or exceeds byte limit');
  if (typeof createImageBitmap === 'undefined')
    throw new Error('Image decoding is unsupported in this browser');
  const bitmap = await createImageBitmap(file);
  try {
    return await canvasImage(bitmap, bitmap.width, bitmap.height, file.size, options);
  } finally {
    bitmap.close();
  }
}
function waitMedia(
  video: HTMLVideoElement,
  event: 'loadedmetadata' | 'loadeddata' | 'seeked',
  action: () => void,
  signal?: AbortSignal,
) {
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer);
      video.removeEventListener(event, ready);
      video.removeEventListener('error', error);
      signal?.removeEventListener('abort', abort);
    };
    const ready = () => {
        cleanup();
        resolve();
      },
      error = () => {
        cleanup();
        reject(new Error('Unsupported or corrupted video'));
      },
      abort = () => {
        cleanup();
        reject(signal?.reason ?? new Error('Cancelled'));
      };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error('Video decoding timed out'));
    }, 10_000);
    video.addEventListener(event, ready, { once: true });
    video.addEventListener('error', error, { once: true });
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) {
      abort();
      return;
    }
    try {
      action();
    } catch (e) {
      cleanup();
      reject(e);
    }
  });
}
/** Samples completed browser-decodable video, never uploads the whole video. Timestamp is video time in seconds. */
export async function sampleVideo(
  file: Blob,
  options: ImageOptions & { frames?: number; maxDurationSeconds?: number } = {},
): Promise<VideoFrame[]> {
  if (!['video/mp4', 'video/webm'].includes(file.type))
    throw new Error('Unsupported video. Use MP4 or WebM.');
  if (!file.size || file.size > 50_000_000) throw new Error('Video is empty or exceeds 50 MB');
  const url = URL.createObjectURL(file),
    video = document.createElement('video');
  video.muted = true;
  video.preload = 'auto';
  video.playsInline = true;
  try {
    await waitMedia(
      video,
      'loadeddata',
      () => {
        video.src = url;
        video.load();
      },
      options.signal,
    );
    const times = sampleFrameTimes(
        video.duration,
        options.frames ?? 6,
        options.maxDurationSeconds ?? 120,
      ),
      frames: VideoFrame[] = [];
    let totalBytes = 0;
    for (const timestampSeconds of times) {
      options.signal?.throwIfAborted();
      if (Math.abs(video.currentTime - timestampSeconds) > 0.001)
        await waitMedia(
          video,
          'seeked',
          () => {
            video.currentTime = timestampSeconds;
          },
          options.signal,
        );
      const image = await canvasImage(
        video,
        video.videoWidth,
        video.videoHeight,
        file.size,
        options,
      );
      totalBytes += image.blob.size;
      if (totalBytes > 12_000_000) throw new Error('Sampled frames exceed 12 MB combined');
      frames.push({ timestampSeconds, image });
    }
    return frames;
  } finally {
    video.pause();
    video.removeAttribute('src');
    video.load();
    URL.revokeObjectURL(url);
  }
}
export async function captureFrame(video: HTMLVideoElement, options: ImageOptions = {}) {
  if (video.readyState < 2) throw new Error('Camera is not ready');
  return canvasImage(video, video.videoWidth, video.videoHeight, 0, options);
}
