import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialTurn, turnReducer, validateAudio } from '../src/index';
import { MicrophoneRecorder, type RecorderSnapshot } from '../src/browser';
import { streamSpeech, streamTranscription, synthesizeSpeech, transcribe } from '../src/server';
const audio = new Blob(['test audio fixture bytes'], { type: 'audio/wav' });
const options = { apiKey: 'test-key-never-live', model: 'configured-model' };
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe('voice', () => {
  it('makes turn transitions explicit and handles silence/cancellation/failure', () => {
    const recording = turnReducer(initialTurn, { type: 'record' });
    const transcribing = turnReducer(recording, { type: 'stop' });
    expect(turnReducer(transcribing, { type: 'transcript', text: '' }).phase).toBe('idle');
    const thinking = turnReducer(transcribing, { type: 'transcript', text: 'Hello' });
    const speaking = turnReducer(thinking, { type: 'reply', text: 'Welcome' });
    expect(turnReducer(speaking, { type: 'played' }).phase).toBe('idle');
    expect(turnReducer(speaking, { type: 'cancel' })).toEqual(initialTurn);
    expect(turnReducer(speaking, { type: 'fail', message: 'Disconnected' }).phase).toBe('error');
    expect(() => turnReducer(initialTurn, { type: 'reply', text: 'bad order' })).toThrow('Invalid');
  });
  it('validates audio and submits multipart recorded-file transcription', async () => {
    const fetcher = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const form = init?.body as FormData;
      expect(form.get('model')).toBe('configured-model');
      expect(form.get('file')).toBeInstanceOf(Blob);
      expect((init?.headers as Record<string, string>).Authorization).toBe(
        'Bearer test-key-never-live',
      );
      return Response.json({ text: 'Hello from a mocked API' });
    });
    expect(await transcribe(audio, 'test.wav', { ...options, fetcher })).toMatchObject({
      text: 'Hello from a mocked API',
      mode: 'live',
      kind: 'recorded-file',
    });
    expect(() => validateAudio(new Blob([]), 'test.wav')).toThrow('empty');
    expect(() => validateAudio(audio, 'test.exe')).toThrow('Unsupported');
    await expect(
      transcribe(audio, 'test.wav', {
        ...options,
        fetcher: async () => new Response('', { status: 401 }),
      }),
    ).rejects.toThrow('401');
  });
  it('parses split UTF-8 SSE deltas and the final completed-file transcript', async () => {
    const raw = new TextEncoder().encode(
      'data: {"type":"transcript.text.delta","delta":"café"}\r\n\r\ndata: {"type":"transcript.text.done","text":"café"}\n\n',
    );
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        for (let i = 0; i < raw.length; i += 3) c.enqueue(raw.slice(i, i + 3));
        c.close();
      },
    });
    const events = [];
    for await (const event of streamTranscription(audio, 'test.wav', {
      ...options,
      fetcher: async () => new Response(stream),
    }))
      events.push(event);
    expect(events.map((e) => [e.type, e.text])).toEqual([
      ['delta', 'café'],
      ['done', 'café'],
    ]);
  });
  it('rejects incomplete or error transcription streams', async () => {
    for (const data of [
      'data: {"type":"transcript.text.delta","delta":"x"}\n\n',
      'data: {"type":"error"}\n\n',
    ]) {
      const consume = async () => {
        for await (const _event of streamTranscription(audio, 'test.wav', {
          ...options,
          fetcher: async () => new Response(data),
        })) {
          /* drain */
        }
      };
      await expect(consume()).rejects.toThrow();
    }
  });
  it('streams actual binary TTS chunks with cancellation and disclosure', async () => {
    const cancel = vi.fn();
    let n = 0;
    const upstream = new ReadableStream<Uint8Array>({
      pull(c) {
        c.enqueue(new Uint8Array([++n]));
      },
      cancel,
    });
    const result = await streamSpeech(
      { text: 'Hello', format: 'pcm' },
      {
        ...options,
        fetcher: async (_url, init) => {
          expect(JSON.parse(String(init?.body))).toMatchObject({
            model: 'configured-model',
            response_format: 'pcm',
            input: 'Hello',
          });
          return new Response(upstream);
        },
      },
    );
    expect(result.disclosure).toBe('AI-generated voice');
    const reader = result.stream.getReader();
    expect((await reader.read()).value).toEqual(new Uint8Array([1]));
    await reader.cancel('user cancelled');
    expect(cancel).toHaveBeenCalled();
    const complete = await synthesizeSpeech(
      { text: 'hello' },
      { ...options, fetcher: async () => new Response(new Uint8Array([1, 2, 3])) },
    );
    expect(complete.blob.size).toBe(3);
    await expect(synthesizeSpeech({ text: '' }, options)).rejects.toThrow();
  });
  it('reports unsupported recording and explicit permission denial', async () => {
    const notify = vi.fn();
    vi.stubGlobal('navigator', {});
    await new MicrophoneRecorder(notify).start();
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'unsupported' }));
    vi.stubGlobal('MediaRecorder', class {});
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: async () => {
          throw new DOMException('Denied', 'NotAllowedError');
        },
      },
    });
    await new MicrophoneRecorder(notify).start();
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'denied' }));
  });
  it('stops late streams when cancelled while microphone permission is pending', async () => {
    const stop = vi.fn(),
      notify = vi.fn();
    let resolve!: (stream: unknown) => void;
    vi.stubGlobal('MediaRecorder', class {});
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: () =>
          new Promise((r) => {
            resolve = r;
          }),
      },
    });
    const recorder = new MicrophoneRecorder(notify),
      pending = recorder.start();
    recorder.cancel();
    resolve({ getTracks: () => [{ stop }] });
    await pending;
    expect(stop).toHaveBeenCalledOnce();
    expect(notify).toHaveBeenLastCalledWith({ status: 'idle' });
  });
  it('records, bounds duration and releases all tracks', async () => {
    vi.useFakeTimers();
    const stop = vi.fn(),
      snapshots: RecorderSnapshot[] = [];
    class FakeRecorder {
      static isTypeSupported() {
        return true;
      }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable?: (e: { data: Blob }) => void;
      onstop?: () => void;
      onerror?: () => void;
      start() {
        this.state = 'recording';
      }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['bytes']) });
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop }] }) },
    });
    const recorder = new MicrophoneRecorder((s) => snapshots.push(s), 1);
    await recorder.start();
    expect(snapshots.at(-1)?.status).toBe('recording');
    vi.advanceTimersByTime(1000);
    expect(snapshots.at(-1)?.status).toBe('ready');
    expect(snapshots.at(-1)?.blob?.size).toBe(5);
    expect(stop).toHaveBeenCalled();
    recorder.dispose();
  });
});

it('ignores stale recorder events after cancellation and a new recording starts', async () => {
  const trackStops = [vi.fn(), vi.fn()];
  let streamCount = 0;
  class FakeRecorder {
    static instances: FakeRecorder[] = [];
    static isTypeSupported() {
      return true;
    }
    state = 'inactive';
    mimeType = 'audio/webm';
    ondataavailable?: (e: { data: Blob }) => void;
    onstop?: () => void;
    onerror?: () => void;
    constructor() {
      FakeRecorder.instances.push(this);
    }
    start() {
      this.state = 'recording';
    }
    stop() {
      this.state = 'inactive';
    }
  }
  vi.stubGlobal('MediaRecorder', FakeRecorder);
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: async () => {
        const stop = trackStops[streamCount++];
        return { getTracks: () => [{ stop }] };
      },
    },
  });
  const notify = vi.fn(),
    recorder = new MicrophoneRecorder(notify);
  await recorder.start();
  const stale = FakeRecorder.instances[0];
  recorder.cancel();
  await recorder.start();
  stale.onstop?.();
  stale.onerror?.();
  expect(trackStops[1]).not.toHaveBeenCalled();
  expect(FakeRecorder.instances[1].state).toBe('recording');
  expect(notify).toHaveBeenLastCalledWith({ status: 'recording' });
  recorder.dispose();
});
