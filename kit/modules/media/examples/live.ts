import { readFile } from 'node:fs/promises';
import { analyzeImage } from '../src/server';
if (process.env.KIT_ALLOW_LIVE !== '1')
  throw new Error(
    'Live requests may incur usage; explicitly set KIT_ALLOW_LIVE=1 with a test account.',
  );
const apiKey = process.env.OPENAI_API_KEY,
  model = process.env.OPENAI_VISION_MODEL,
  path = process.argv[2];
if (!apiKey || !model || !path)
  throw new Error(
    'Set OPENAI_API_KEY and OPENAI_VISION_MODEL; provide a .png/.jpg/.webp image path',
  );
const mimeType = /\.png$/i.test(path)
  ? 'image/png'
  : /\.jpe?g$/i.test(path)
    ? 'image/jpeg'
    : /\.webp$/i.test(path)
      ? 'image/webp'
      : '';
if (!mimeType) throw new Error('Supported filename extensions: .png, .jpg, .jpeg, .webp');
console.log(
  await analyzeImage(
    new Blob([await readFile(path)], { type: mimeType }),
    'Describe the visible objects and their approximate boxes.',
    { apiKey, model },
  ),
);
