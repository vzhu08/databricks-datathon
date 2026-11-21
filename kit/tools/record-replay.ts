import { z } from 'zod';
import { writeFile, readFile, mkdir, lstat } from 'node:fs/promises';
import path from 'node:path';
const blocked =
  /authorization|cookie|password|secret|token|api[-_]?key|email|phone|address|upload|transcript|prompt|content|document|audio|image|^text$|^body$/i;
export function sanitize(value: unknown, depth = 0): unknown {
  if (depth > 12) return '[depth limit]';
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    if (value.length > 2000) return '[large text omitted]';
    return value
      .replace(/\b(?:Bearer|Basic)\s+\S+/gi, '[credential redacted]')
      .replace(/\b(?:sk-|xox[baprs]-)[\w-]+/g, '[credential redacted]')
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email redacted]')
      .replace(/([?&](?:key|token|secret|api_key|access_token)=)[^&#\s]+/gi, '$1[redacted]');
  }
  if (Array.isArray(value)) return value.slice(0, 100).map((v) => sanitize(v, depth + 1));
  if (typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .slice(0, 100)
        .map(([k, v]) => [k, blocked.test(k) ? '[redacted]' : sanitize(v, depth + 1)]),
    );
  return '[unsupported]';
}
export const CassetteSchema = z.object({
  schemaVersion: z.literal(1),
  id: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/),
  createdAt: z.iso.datetime(),
  provenance: z.string().min(1),
  mode: z.literal('replay'),
  request: z.unknown(),
  response: z.unknown(),
});
export class Recorder {
  constructor(
    private directory: string,
    private options: { enabled: boolean; provenance: string },
  ) {}
  async record(id: string, request: unknown, response: unknown) {
    if (!this.options.enabled)
      throw new Error(
        'Recording is opt-in. Set enabled:true after reviewing the sanitization policy.',
      );
    const cassette = CassetteSchema.parse({
      schemaVersion: 1,
      id,
      createdAt: new Date().toISOString(),
      provenance: this.options.provenance,
      mode: 'replay',
      request: sanitize(request),
      response: sanitize(response),
    });
    await mkdir(this.directory, { recursive: true });
    const dest = path.join(this.directory, `${cassette.id}.json`);
    if ((await lstat(this.directory)).isSymbolicLink())
      throw new Error('Recording directory cannot be a symlink');
    await writeFile(dest, JSON.stringify(cassette, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    return cassette;
  }
  async replay(id: string) {
    z.string()
      .regex(/^[a-zA-Z0-9_-]{1,80}$/)
      .parse(id);
    return CassetteSchema.parse(
      JSON.parse(await readFile(path.join(this.directory, id + '.json'), 'utf8')),
    );
  }
}
