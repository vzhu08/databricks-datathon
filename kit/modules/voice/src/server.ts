import { z } from 'zod';
import { httpJson, KitError } from '../../../packages/runtime/src/index';
import { TranscriptSchema, validateAudio } from './index';
export type SpeechOptions = {
  apiKey: string;
  model: string;
  signal?: AbortSignal;
  fetcher?: typeof fetch;
  timeoutMs?: number;
};
function auth(options: SpeechOptions) {
  z.string().min(1).parse(options.model);
  return {
    Authorization: `Bearer ${z.string().min(1, 'OpenAI API key required').parse(options.apiKey)}`,
  };
}
function form(file: Blob, filename: string, model: string, streaming: boolean) {
  validateAudio(file, filename);
  const body = new FormData();
  body.append('file', file, filename);
  body.append('model', model);
  if (streaming) body.append('stream', 'true');
  return body;
}
export async function transcribe(file: Blob, filename: string, options: SpeechOptions) {
  const result = await httpJson(
    'https://api.openai.com/v1/audio/transcriptions',
    z.object({ text: z.string().max(100_000) }),
    {
      method: 'POST',
      body: form(file, filename, options.model, false),
      headers: auth(options),
      fetcher: options.fetcher,
      signal: options.signal,
      timeoutMs: options.timeoutMs ?? 60_000,
      maxResponseBytes: 500_000,
    },
  );
  return TranscriptSchema.parse({
    ...result,
    model: options.model,
    mode: 'live',
    kind: 'recorded-file',
  });
}
async function request(path: string, init: RequestInit, options: SpeechOptions) {
  const signal = AbortSignal.any([
    AbortSignal.timeout(options.timeoutMs ?? 60_000),
    ...(options.signal ? [options.signal] : []),
  ]);
  const response = await (options.fetcher ?? fetch)(`https://api.openai.com/v1/audio/${path}`, {
    ...init,
    headers: { ...auth(options), ...init.headers },
    signal,
  });
  if (!response.ok) {
    await response.body?.cancel();
    throw new KitError(
      'SPEECH_PROVIDER',
      `Speech provider returned HTTP ${response.status}`,
      502,
      response.status === 429 || response.status >= 500,
    );
  }
  if (!response.body)
    throw new KitError('EMPTY_AUDIO_RESPONSE', 'Provider returned an empty response body', 502);
  return response;
}
/** Streams transcript SSE for an already-completed file; this is not live microphone transcription. */
export async function* streamTranscription(
  file: Blob,
  filename: string,
  options: SpeechOptions,
): AsyncGenerator<{
  type: 'delta' | 'done';
  text: string;
  mode: 'live';
  kind: 'recorded-file-stream';
}> {
  const response = await request(
    'transcriptions',
    { method: 'POST', body: form(file, filename, options.model, true) },
    options,
  );
  const reader = response.body!.getReader(),
    decoder = new TextDecoder();
  let buffer = '',
    received = 0,
    doneEvent = false;
  function parse(frame: string) {
    const data = frame
      .split(/\r?\n/)
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trimStart())
      .join('\n');
    if (!data || data === '[DONE]') return null;
    const event = z
      .object({ type: z.string(), delta: z.string().optional(), text: z.string().optional() })
      .parse(JSON.parse(data));
    if (event.type === 'error')
      throw new KitError('TRANSCRIPTION_STREAM', 'Transcription stream reported an error', 502);
    if (event.type === 'transcript.text.delta')
      return {
        type: 'delta' as const,
        text: z.string().parse(event.delta),
        mode: 'live' as const,
        kind: 'recorded-file-stream' as const,
      };
    if (event.type === 'transcript.text.done') {
      doneEvent = true;
      return {
        type: 'done' as const,
        text: z.string().parse(event.text),
        mode: 'live' as const,
        kind: 'recorded-file-stream' as const,
      };
    }
    return null;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      received += value.length;
      if (received > 1_000_000) throw new Error('Transcription stream exceeded 1 MB');
      buffer += decoder.decode(value, { stream: true });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const event = parse(frame);
        if (event) yield event;
      }
    }
    if (buffer.trim()) {
      const event = parse(buffer);
      if (event) yield event;
    }
    if (!doneEvent)
      throw new KitError('INCOMPLETE_TRANSCRIPT', 'Stream ended without a final transcript', 502);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
export const SpeechInputSchema = z.object({
  text: z.string().trim().min(1).max(4096),
  voice: z.string().min(1).max(80).default('coral'),
  format: z.enum(['mp3', 'wav', 'pcm']).default('mp3'),
});
/** Binary chunk streaming. Return this body from an authenticated server endpoint with its content type. */
export async function streamSpeech(input: unknown, options: SpeechOptions) {
  const data = SpeechInputSchema.parse(input);
  const response = await request(
    'speech',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: options.model,
        input: data.text,
        voice: data.voice,
        response_format: data.format,
      }),
    },
    options,
  );
  const upstream = response.body!.getReader();
  let received = 0;
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { value, done } = await upstream.read();
        if (done) {
          if (!received) throw new Error('Provider returned no audio');
          controller.close();
          return;
        }
        received += value.length;
        if (received > 20_000_000) throw new Error('Audio response exceeded 20 MB');
        controller.enqueue(value);
      } catch (error) {
        await upstream.cancel().catch(() => undefined);
        controller.error(error);
      }
    },
    async cancel(reason) {
      await upstream.cancel(reason);
    },
  });
  return {
    stream,
    contentType:
      data.format === 'mp3' ? 'audio/mpeg' : data.format === 'wav' ? 'audio/wav' : 'audio/pcm',
    mode: 'live' as const,
    disclosure: 'AI-generated voice',
    format: data.format,
  };
}
export async function synthesizeSpeech(input: unknown, options: SpeechOptions) {
  const result = await streamSpeech(input, options);
  return {
    blob: await new Response(result.stream, {
      headers: { 'Content-Type': result.contentType },
    }).blob(),
    mode: result.mode,
    disclosure: result.disclosure,
  };
}
