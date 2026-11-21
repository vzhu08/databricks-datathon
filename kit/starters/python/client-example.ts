// Invoke from a server route. Do not expose internal container addresses to browsers.
import { TransformResultSchema } from '../../packages/contracts/src/index';
import { httpJson } from '../../packages/runtime/src/index';
export async function transformWithPython(
  text: string,
  baseURL = process.env.PYTHON_API_URL ?? 'http://127.0.0.1:8000',
  signal?: AbortSignal,
) {
  return httpJson(new URL('/transform', baseURL), TransformResultSchema, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text, operation: 'normalize' }),
    timeoutMs: 10_000,
    signal,
  });
}
