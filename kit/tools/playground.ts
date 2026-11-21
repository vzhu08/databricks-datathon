import { createServer, type IncomingMessage } from 'node:http';
import { parseArgs } from 'node:util';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { transformText } from '../packages/runtime/src/index';
import { FakeAI } from '../modules/ai/src/index';
import { configuredLiveAI } from './live-policy';
import { z } from 'zod';
import { TransformRequestSchema } from '../packages/contracts/src/index';
const { values } = parseArgs({
  options: {
    port: { type: 'string' },
    live: { type: 'boolean' },
    'confirm-usage': { type: 'boolean' },
  },
});
const port = Number(values.port ?? 4310);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid port');
const live = values.live
  ? configuredLiveAI({ enabled: true, confirmed: !!values['confirm-usage'], maxCalls: 3 })
  : null;
const fixture = new FakeAI();
async function body(req: IncomingMessage) {
  let bytes = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    const b = Buffer.from(chunk);
    bytes += b.length;
    if (bytes > 400_000) throw new Error('Request exceeds 400 KB');
    chunks.push(b);
  }
  return Buffer.concat(chunks).toString('utf8');
}
const html = await readFile(fileURLToPath(new URL('./playground.html', import.meta.url)), 'utf8');
const server = createServer(async (req, res) => {
  const id = crypto.randomUUID(),
    start = performance.now();
  res.setHeader('cache-control', 'no-store');
  res.setHeader('x-content-type-options', 'nosniff');
  res.setHeader('x-request-id', id);
  const allowedHosts = [`127.0.0.1:${port}`, `localhost:${port}`];
  if (
    !allowedHosts.includes(req.headers.host ?? '') ||
    (req.headers.origin && !allowedHosts.map((h) => 'http://' + h).includes(req.headers.origin))
  ) {
    res.writeHead(403);
    res.end('Loopback same-origin access only');
    return;
  }
  try {
    if (req.method === 'GET' && req.url === '/') {
      res.setHeader('content-type', 'text/html; charset=utf-8');
      res.end(html);
      return;
    }
    res.setHeader('content-type', 'application/json');
    if (req.method === 'GET' && req.url === '/config') {
      res.end(JSON.stringify({ liveEnabled: !!live, policy: live?.policy ?? null }));
      return;
    }
    if (req.method === 'POST' && (req.url === '/ai/fixture' || req.url === '/ai/live')) {
      if (!req.headers['content-type']?.startsWith('application/json'))
        throw new Error('Expected application/json');
      const input = z
        .object({ prompt: z.string().min(1).max(2000), confirmUsage: z.boolean().default(false) })
        .parse(JSON.parse(await body(req)));
      const adapter = req.url === '/ai/live' ? live : fixture;
      if (!adapter)
        throw new Error(
          'Live mode is disabled. Restart with --live --confirm-usage after authorizing charges.',
        );
      if (req.url === '/ai/live' && !input.confirmUsage)
        throw new Error('This request needs explicit paid-usage confirmation');
      const result =
        req.url === '/ai/live'
          ? await live!.generate(input.prompt)
          : await fixture.generate({ prompt: input.prompt });
      res.end(
        JSON.stringify({
          status: 200,
          result,
          mode: result.mode,
          timingMs: performance.now() - start,
          requestId: id,
        }),
      );
      return;
    }
    if (req.method === 'GET' && req.url === '/fixtures') {
      res.end(
        await readFile(
          fileURLToPath(new URL('../packages/contracts/fixtures/transform.json', import.meta.url)),
          'utf8',
        ),
      );
      return;
    }
    if (req.method === 'POST' && req.url === '/transform') {
      if (!req.headers['content-type']?.startsWith('application/json'))
        throw new Error('Expected application/json');
      const input = TransformRequestSchema.parse(JSON.parse(await body(req)));
      res.end(
        JSON.stringify({
          status: 200,
          mode: 'local',
          result: transformText(input),
          timingMs: performance.now() - start,
          requestId: id,
        }),
      );
      return;
    }
    res.writeHead(404);
    res.end(JSON.stringify({ error: 'Not found', requestId: id }));
  } catch (e) {
    res.writeHead(400);
    res.end(
      JSON.stringify({
        status: 400,
        error: e instanceof Error ? e.message : 'Invalid input',
        requestId: id,
        timingMs: performance.now() - start,
      }),
    );
  }
});
server.requestTimeout = 20_000;
server.headersTimeout = 10_000;
server.listen(port, '127.0.0.1', () =>
  console.log(
    `Local API playground: http://127.0.0.1:${port}; ${live ? 'LIVE ENABLED: at most 3 requests, 128 output tokens each; unknown cost' : 'fixture/local only'}, no recording.`,
  ),
);
for (const signal of ['SIGTERM', 'SIGINT'] as const)
  process.on(signal, () => server.close(() => process.exit(0)));
