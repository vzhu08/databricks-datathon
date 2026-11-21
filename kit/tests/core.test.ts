import { describe, it, expect } from 'vitest';
import { readFile, mkdtemp, writeFile, rm, mkdir, symlink, rename } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {
  transformText,
  BoundedCache,
  httpJson,
  errorResponse,
  KitError,
} from '../packages/runtime/src/index';
import { TransformResultSchema } from '../packages/contracts/src/index';
import { dependencyClosure, readCatalog, walk, safePath } from '../tools/catalog';
import { planProject, applyPlan } from '../tools/project';
import { sanitize, Recorder } from '../tools/record-replay';
import { z } from 'zod';

it('matches shared normal/empty wire fixtures', async () => {
  const cases = JSON.parse(
    await readFile(
      new URL('../packages/contracts/fixtures/transform.json', import.meta.url),
      'utf8',
    ),
  );
  for (const c of cases)
    expect(TransformResultSchema.parse(transformText(c.input))).toEqual(c.expected);
  expect(() => transformText({ text: 4 })).toThrow();
});
it('isolates cache scopes and enforces LRU expiry/invalidation', () => {
  let now = 0;
  const c = new BoundedCache<number>(2, 10, () => now);
  c.set('a', 'x', 1);
  c.set('b', 'x', 2);
  expect(c.get('a', 'x')).toBe(1);
  c.set('a', 'y', 3);
  expect(c.get('b', 'x')).toBeUndefined();
  c.invalidate('a');
  expect(c.get('a', 'x')).toBeUndefined();
  c.set('b', 'z', 4);
  now = 11;
  expect(c.get('b', 'z')).toBeUndefined();
  expect(() => c.set('', 'x', 1)).toThrow();
});
it('retries bounded read requests and rejects mutation retries/oversized bodies', async () => {
  let attempts = 0;
  const fetcher = async () => {
    attempts++;
    return attempts === 1 ? new Response('busy', { status: 503 }) : Response.json({ ok: true });
  };
  expect(
    await httpJson('https://example.test', z.object({ ok: z.boolean() }), { fetcher, retries: 1 }),
  ).toEqual({ ok: true });
  expect(attempts).toBe(2);
  await expect(
    httpJson('https://example.test', z.unknown(), { method: 'POST', retries: 1, fetcher }),
  ).rejects.toThrow('read-only');
  await expect(
    httpJson('https://example.test', z.unknown(), {
      maxResponseBytes: 3,
      fetcher: async () => Response.json({ large: 'test' }),
    }),
  ).rejects.toThrow('byte limit');
});
it('public errors preserve IDs without internal details', async () => {
  const response = errorResponse(new Error('secret-token'), 'r-1');
  expect(response.status).toBe(500);
  expect(await response.text()).not.toContain('secret-token');
  const known = errorResponse(new KitError('TOO_LARGE', 'Too large', 413));
  expect(known.status).toBe(413);
});
it('catalog rejects cycles, missing IDs and unsafe paths', () => {
  const m: any = { id: 'a', dependencies: ['b'] },
    n: any = { id: 'b', dependencies: ['a'] };
  expect(() => dependencyClosure(['a'], [m, n])).toThrow('cycle');
  expect(() => dependencyClosure(['nope'], [])).toThrow('Unknown');
  for (const p of ['../escape', '/root', '.', 'a/../b', 'C:\\secret', 'a\\b', 'a//b'])
    expect(() => safePath('/tmp/root', p)).toThrow();
});
it('export walker excludes credentials and embedded repositories', async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'kit-files-'));
  try {
    await mkdir(path.join(temp, 'starter/.git'), { recursive: true });
    for (const [name, value] of Object.entries({
      '.env.local': 'DUMMY_SENTINEL',
      'secret.pem': 'DUMMY_KEY',
      '.npmrc': 'DUMMY_TOKEN',
      '.env.example': 'KEY=',
      'index.ts': 'export const ok=true;',
    }))
      await writeFile(path.join(temp, 'starter', name), value);
    await writeFile(path.join(temp, 'starter/.git/config'), 'dummy');
    expect(await walk(temp, 'starter')).toEqual(['starter/.env.example', 'starter/index.ts']);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
it('sanitizes recording, opts in, refuses overwrite and labels replay', async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'kit-replay-'));
  try {
    const r = new Recorder(temp, { enabled: true, provenance: 'synthetic regression' });
    await r.record(
      'test',
      {
        headers: { Authorization: 'Bearer abc', cookie: 'secret' },
        prompt: 'private',
        url: 'https://example.test/?token=abc',
      },
      { transcript: 'private speech', count: 2 },
    );
    const replay = await r.replay('test');
    expect(replay.mode).toBe('replay');
    expect(JSON.stringify(replay)).not.toContain('private speech');
    expect(JSON.stringify(replay)).not.toContain('Bearer abc');
    await expect(r.record('test', {}, {})).rejects.toThrow();
    await expect(
      new Recorder(temp, { enabled: false, provenance: 'test' }).record('nope', {}, {}),
    ).rejects.toThrow('opt-in');
    expect(sanitize({ email: 'private@example.com' })).toEqual({ email: '[redacted]' });
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

describe('adoption preserves existing work', () => {
  async function fixture() {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'kit-adopt-'));
    await mkdir(path.join(temp, 'app'));
    const root = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
    await writeFile(
      path.join(temp, 'package.json'),
      JSON.stringify({
        name: 'existing-app',
        type: 'module',
        dependencies: {
          next: root.dependencies.next,
          react: root.dependencies.react,
          'react-dom': root.dependencies['react-dom'],
        },
        scripts: { existing: 'echo preserved' },
      }),
    );
    await writeFile(
      path.join(temp, 'app/page.tsx'),
      'export default function Page(){return "original working route";}',
    );
    await writeFile(path.join(temp, 'AGENTS.md'), 'User-owned instructions\n');
    return temp;
  }
  it('plans without writes, applies, preserves routes/instructions, and is idempotent', async () => {
    const target = await fixture();
    try {
      const catalog = await readCatalog();
      const plan = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      expect(plan.conflicts).toEqual([]);
      await expect(
        readFile(path.join(target, 'modules/recommendations/src/index.ts')),
      ).rejects.toThrow();
      await applyPlan(plan);
      expect(await readFile(path.join(target, 'AGENTS.md'), 'utf8')).toBe(
        'User-owned instructions\n',
      );
      expect(await readFile(path.join(target, 'app/page.tsx'), 'utf8')).toContain(
        'original working route',
      );
      const again = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      expect(again.conflicts).toEqual([]);
      expect(again.changes.every((c) => c.action === 'unchanged')).toBe(true);
      await writeFile(path.join(target, 'modules/recommendations/src/index.ts'), 'customized');
      const conflict = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      expect(conflict.conflicts.join(' ')).toContain('exists and differs');
      await expect(applyPlan(conflict)).rejects.toThrow('Refusing writes');
      expect(
        await readFile(path.join(target, 'modules/recommendations/src/index.ts'), 'utf8'),
      ).toBe('customized');
    } finally {
      await rm(target, { recursive: true, force: true });
    }
  });
  it('refuses a stale plan and root symlink replacement without writing', async () => {
    const target = await fixture(),
      outside = await fixture();
    try {
      const catalog = await readCatalog();
      const stale = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      await writeFile(path.join(target, 'package.json'), '{"name":"changed"}');
      await expect(applyPlan(stale)).rejects.toThrow('changed after planning');
      await rename(target, target + '-original');
      await symlink(outside, target, process.platform === 'win32' ? 'junction' : 'dir');
      await expect(applyPlan(stale)).rejects.toThrow('symlink');
      await expect(
        readFile(path.join(outside, 'modules/recommendations/src/index.ts')),
      ).rejects.toThrow();
    } finally {
      await rm(target, { force: true, recursive: true });
      await rm(target + '-original', { force: true, recursive: true });
      await rm(outside, { force: true, recursive: true });
    }
  });
});
