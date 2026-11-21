import { expect, it } from 'vitest';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

it('runs the actual HTTP worker, enforces auth, persists results across process restart and cancels work', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'kit-worker-http-'));
  const processes: ChildProcess[] = [];
  async function stop(child: ChildProcess) {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = new Promise<void>((resolve) => child.once('exit', () => resolve()));
    child.kill('SIGTERM');
    await exited;
  }
  async function boot() {
    const child = spawn(
      process.execPath,
      ['--import', 'tsx', fileURLToPath(new URL('../examples/worker.ts', import.meta.url))],
      {
        env: {
          ...process.env,
          JOB_DB: join(directory, 'queue.sqlite'),
          JOB_HOST: '127.0.0.1',
          JOB_PORT: '0',
          JOB_API_TOKEN: 'fixture-worker-token',
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    processes.push(child);
    return await new Promise<{ child: ChildProcess; url: string }>((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error('Worker boot timeout')), 5000);
      child.once('exit', (code) => {
        clearTimeout(timer);
        reject(new Error(`Worker exited before ready: ${code}`));
      });
      child.stdout!.on('data', (data) => {
        output += String(data);
        const url = output.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
        if (url) {
          clearTimeout(timer);
          resolve({ child, url });
        }
      });
      child.stderr!.on('data', () => {});
    });
  }
  const headers = {
    authorization: 'Bearer fixture-worker-token',
    'content-type': 'application/json',
  };
  try {
    const first = await boot();
    expect((await fetch(first.url)).status).toBe(401);
    const payload = {
      type: 'ingest',
      input: { lines: ['hello world'], delayMs: 0 },
      idempotencyKey: 'http-demo',
    };
    const created = await (
      await fetch(first.url, { method: 'POST', headers, body: JSON.stringify(payload) })
    ).json();
    expect(created.state).toBe('queued');
    let result;
    for (let i = 0; i < 100; i++) {
      result = await (await fetch(`${first.url}?id=${created.id}`, { headers })).json();
      if (result.state === 'succeeded') break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    expect(result.result.words).toBe(2);
    await stop(first.child);
    const second = await boot();
    const replay = await (
      await fetch(second.url, { method: 'POST', headers, body: JSON.stringify(payload) })
    ).json();
    expect(replay).toMatchObject({ id: created.id, state: 'succeeded', result: { words: 2 } });
    const slow = await (
      await fetch(second.url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          type: 'ingest',
          input: { lines: Array(20).fill('slow'), delayMs: 100 },
        }),
      })
    ).json();
    const cancelled = await (
      await fetch(`${second.url}?id=${slow.id}`, { method: 'DELETE', headers })
    ).json();
    expect(cancelled.state).toBe('cancelled');
  } finally {
    for (const child of processes) await stop(child);
    rmSync(directory, { recursive: true, force: true });
  }
}, 15_000);
