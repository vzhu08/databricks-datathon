import { it, expect } from 'vitest';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { once } from 'node:events';
it('playground exercises real local and fixture routes, bounded errors and disabled live mode', async () => {
  const probe = createServer();
  probe.listen(0, '127.0.0.1');
  await once(probe, 'listening');
  const port = (probe.address() as { port: number }).port;
  await new Promise<void>((r) => probe.close(() => r()));
  const child = spawn(
    process.execPath,
    ['--import', 'tsx', 'tools/playground.ts', '--port', String(port)],
    { stdio: ['ignore', 'pipe', 'pipe'] },
  );
  let log = '';
  child.stderr.on('data', (v) => {
    log += v;
  });
  const url = `http://127.0.0.1:${port}`;
  try {
    let ready = false;
    for (let i = 0; i < 80; i++) {
      try {
        if ((await fetch(url + '/config')).ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 50));
    }
    expect(ready, log).toBe(true);
    const config = await (await fetch(url + '/config')).json();
    expect(config.liveEnabled).toBe(false);
    const post = (p: string, v: unknown) =>
      fetch(url + p, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(v),
      });
    const local = await post('/transform', { text: '  sample   text ' });
    expect((await local.json()).result.text).toBe('sample text');
    const fixture = await post('/ai/fixture', { prompt: 'Synthetic test' });
    expect((await fixture.json()).result.mode).toBe('fixture');
    expect((await post('/ai/live', { prompt: 'Synthetic test', confirmUsage: true })).status).toBe(
      400,
    );
    expect((await post('/transform', { text: 4 })).status).toBe(400);
    expect(
      (await fetch(url + '/config', { headers: { origin: 'https://example.com' } })).status,
    ).toBe(403);
  } finally {
    child.kill('SIGTERM');
    if (child.exitCode === null) await once(child, 'exit');
  }
});
