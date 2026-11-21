import { afterEach, describe, expect, it, vi } from 'vitest';
import { VisionResultSchema, sampleFrameTimes, sampleVisionResult } from '../src/index';
import { prepareImage, sampleVideo } from '../src/browser';
import { analyzeImage } from '../src/server';
const options = { apiKey: 'test-not-live', model: 'configured-vision-model' };
afterEach(() => vi.unstubAllGlobals());
describe('media', () => {
  it('bounds frame count/duration and includes ordered timestamps', () => {
    const times = sampleFrameTimes(10, 6);
    expect(times).toHaveLength(6);
    expect(times[0]).toBe(0);
    expect(times.at(-1)).toBeCloseTo(9.95);
    expect(sampleFrameTimes(10, 1)).toEqual([0]);
    expect(() => sampleFrameTimes(0)).toThrow();
    expect(() => sampleFrameTimes(121)).toThrow();
    expect(() => sampleFrameTimes(10, 13)).toThrow();
  });
  it('validates boxes including empty detections and rejects out-of-image boxes', () => {
    expect(VisionResultSchema.parse(sampleVisionResult).detections).toHaveLength(2);
    expect(
      VisionResultSchema.parse({ summary: '', mode: 'fixture', detections: [] }).detections,
    ).toEqual([]);
    expect(() =>
      VisionResultSchema.parse({
        ...sampleVisionResult,
        detections: [{ label: 'x', confidence: 2, box: { x: 0, y: 0, width: 1, height: 1 } }],
      }),
    ).toThrow();
    expect(() =>
      VisionResultSchema.parse({
        ...sampleVisionResult,
        detections: [{ label: 'x', confidence: 1, box: { x: 0.8, y: 0, width: 0.5, height: 1 } }],
      }),
    ).toThrow('fit');
  });
  it('resizes in browser, removes metadata by re-encoding and closes bitmap resources', async () => {
    const close = vi.fn(),
      drawImage = vi.fn();
    vi.stubGlobal('createImageBitmap', async () => ({ width: 2000, height: 1000, close }));
    vi.stubGlobal('document', {
      createElement: () => ({
        width: 0,
        height: 0,
        getContext: () => ({ fillStyle: '', fillRect: vi.fn(), drawImage }),
        toBlob: (callback: (blob: Blob) => void) =>
          callback(new Blob(['jpeg'], { type: 'image/jpeg' })),
      }),
    });
    const result = await prepareImage(new Blob(['input'], { type: 'image/png' }), {
      maxDimension: 1000,
    });
    expect(result).toMatchObject({
      width: 1000,
      height: 500,
      originalBytes: 5,
      mimeType: 'image/jpeg',
    });
    expect(close).toHaveBeenCalledOnce();
    expect(drawImage).toHaveBeenCalled();
  });
  it('rejects unsupported, empty, oversized or cancelled media', async () => {
    await expect(prepareImage(new Blob(['x'], { type: 'image/svg+xml' }))).rejects.toThrow(
      'Unsupported',
    );
    await expect(prepareImage(new Blob([], { type: 'image/png' }))).rejects.toThrow('empty');
    await expect(
      prepareImage(new Blob(['abcdef'], { type: 'image/png' }), { maxBytes: 2 }),
    ).rejects.toThrow('byte limit');
    await expect(
      prepareImage(new Blob(['x'], { type: 'image/png' }), { signal: AbortSignal.abort() }),
    ).rejects.toThrow();
    await expect(sampleVideo(new Blob(['x'], { type: 'video/quicktime' }))).rejects.toThrow(
      'Unsupported',
    );
  });
  it('samples decoded video at requested timestamps and cleans up its source', async () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL');
    class Video extends EventTarget {
      duration = 4;
      videoWidth = 640;
      videoHeight = 360;
      src = '';
      muted = false;
      preload = '';
      playsInline = false;
      time = 0;
      get currentTime() {
        return this.time;
      }
      set currentTime(time: number) {
        this.time = time;
        queueMicrotask(() => this.dispatchEvent(new Event('seeked')));
      }
      load() {
        if (this.src) queueMicrotask(() => this.dispatchEvent(new Event('loadeddata')));
      }
      pause = vi.fn();
      removeAttribute() {
        this.src = '';
      }
    }
    const video = new Video();
    vi.stubGlobal('document', {
      createElement: (tag: string) =>
        tag === 'video'
          ? video
          : {
              width: 0,
              height: 0,
              getContext: () => ({ fillStyle: '', fillRect: vi.fn(), drawImage: vi.fn() }),
              toBlob: (callback: (blob: Blob) => void) =>
                callback(new Blob(['jpeg'], { type: 'image/jpeg' })),
            },
    });
    const frames = await sampleVideo(new Blob(['video'], { type: 'video/mp4' }), { frames: 3 });
    expect(frames.map((f) => f.timestampSeconds)).toEqual([0, 1.975, 3.95]);
    expect(frames[0].image).toMatchObject({ width: 640, height: 360 });
    expect(video.pause).toHaveBeenCalled();
    expect(video.src).toBe('');
    expect(revoke).toHaveBeenCalledOnce();
    revoke.mockRestore();
  });
  it('uses Responses image input and strict structured output with configured model', async () => {
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.model).toBe('configured-vision-model');
      expect(body.store).toBe(false);
      expect(body.input[0].content[1].image_url).toMatch(/^data:image\/png;base64,/);
      expect(body.text.format.strict).toBe(true);
      return Response.json({
        status: 'completed',
        output: [
          {
            type: 'message',
            content: [
              { type: 'output_text', text: JSON.stringify({ summary: 'Shapes', detections: [] }) },
            ],
          },
        ],
      });
    });
    const result = await analyzeImage(
      new Blob(['test fixture bytes'], { type: 'image/png' }),
      'Describe visible shapes',
      { ...options, fetcher },
    );
    expect(result).toMatchObject({ summary: 'Shapes', detections: [], mode: 'live' });
  });
  it('reports provider errors, incomplete output, refusal and malformed detections', async () => {
    const image = new Blob(['test bytes'], { type: 'image/png' });
    await expect(
      analyzeImage(image, 'Describe', {
        ...options,
        fetcher: async () => new Response('', { status: 429 }),
      }),
    ).rejects.toThrow('429');
    for (const response of [
      { status: 'incomplete', output: [] },
      {
        status: 'completed',
        output: [{ type: 'message', content: [{ type: 'refusal', refusal: 'declined' }] }],
      },
      {
        status: 'completed',
        output: [
          {
            type: 'message',
            content: [{ type: 'output_text', text: '{"summary":"bad","detections":[{}]}' }],
          },
        ],
      },
    ])
      await expect(
        analyzeImage(image, 'Describe', {
          ...options,
          fetcher: async () => Response.json(response),
        }),
      ).rejects.toThrow();
  });
});
