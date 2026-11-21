import { readFile, writeFile } from 'node:fs/promises';
import { transcribe, synthesizeSpeech } from '../src/server';
if (process.env.KIT_ALLOW_LIVE !== '1')
  throw new Error(
    'Live requests may incur usage; explicitly set KIT_ALLOW_LIVE=1 with a test account.',
  );
const apiKey = process.env.OPENAI_API_KEY,
  model = process.env.OPENAI_TRANSCRIBE_MODEL,
  ttsModel = process.env.OPENAI_TTS_MODEL;
if (!apiKey || !model || !ttsModel)
  throw new Error('Set OPENAI_API_KEY, OPENAI_TRANSCRIBE_MODEL and OPENAI_TTS_MODEL');
const path = process.argv[2];
if (!path) throw new Error('Provide a local .wav file recorded with permission');
if (!path.toLowerCase().endsWith('.wav'))
  throw new Error(
    'This minimal example accepts .wav; the adapter supports other documented audio formats',
  );
const transcript = await transcribe(
  new Blob([await readFile(path)], { type: 'audio/wav' }),
  'recording.wav',
  { apiKey, model },
);
console.log(transcript);
if (transcript.text.trim()) {
  const audio = await synthesizeSpeech(
    { text: transcript.text.slice(0, 4096), voice: 'coral' },
    { apiKey, model: ttsModel },
  );
  await writeFile('voice-live-output.mp3', Buffer.from(await audio.blob.arrayBuffer()));
  console.log('Saved voice-live-output.mp3. AI-generated voice.');
}
