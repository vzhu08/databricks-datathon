import { z } from 'zod';
export const TranscriptSchema = z.object({
  text: z.string().max(100_000),
  mode: z.enum(['fixture', 'live']),
  kind: z.enum(['recorded-file', 'sample']),
  model: z.string().optional(),
});
export type Transcript = z.infer<typeof TranscriptSchema>;
export const sampleTranscript: Transcript = {
  text: 'Please find an accessible activity for our group under 25 credits.',
  mode: 'fixture',
  kind: 'sample',
};
export type TurnState = {
  phase: 'idle' | 'recording' | 'transcribing' | 'thinking' | 'speaking' | 'error';
  transcript: string;
  reply: string;
  error?: string;
};
export type TurnEvent =
  | { type: 'record' }
  | { type: 'stop' }
  | { type: 'transcript'; text: string }
  | { type: 'reply'; text: string }
  | { type: 'played' }
  | { type: 'fail'; message: string }
  | { type: 'cancel' };
export const initialTurn: TurnState = { phase: 'idle', transcript: '', reply: '' };
export function turnReducer(state: TurnState, event: TurnEvent): TurnState {
  if (event.type === 'cancel') return { ...initialTurn };
  if (event.type === 'fail') return { ...state, phase: 'error', error: event.message };
  if (event.type === 'record' && ['idle', 'error'].includes(state.phase))
    return { ...initialTurn, phase: 'recording' };
  if (event.type === 'stop' && state.phase === 'recording')
    return { ...state, phase: 'transcribing' };
  if (event.type === 'transcript' && state.phase === 'transcribing')
    return { ...state, transcript: event.text, phase: event.text.trim() ? 'thinking' : 'idle' };
  if (event.type === 'reply' && state.phase === 'thinking')
    return { ...state, reply: event.text, phase: event.text.trim() ? 'speaking' : 'idle' };
  if (event.type === 'played' && state.phase === 'speaking') return { ...state, phase: 'idle' };
  throw new Error(`Invalid voice transition: ${state.phase} -> ${event.type}`);
}
export function validateAudio(file: Blob, filename: string) {
  if (!file.size) throw new Error('Audio is empty');
  if (file.size > 20_000_000) throw new Error('Audio exceeds kit limit of 20 MB');
  if (!/\.(mp3|mp4|mpeg|mpga|m4a|wav|webm)$/i.test(filename))
    throw new Error('Unsupported audio filename; use mp3, mp4, mpeg, mpga, m4a, wav or webm');
  if (
    file.type &&
    !/^(audio\/(mpeg|mp3|mp4|wav|wave|x-wav|webm)|video\/(webm|mp4))(;.*)?$/i.test(file.type)
  )
    throw new Error('Unsupported audio MIME type');
}
