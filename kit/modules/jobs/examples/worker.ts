import { createServer } from 'node:http';
import { JobWorker, createSqliteJobStore, ingestLines, handleJobRequest } from '../src/server';
const host = process.env.JOB_HOST ?? '127.0.0.1';
const port = Number(process.env.JOB_PORT ?? 8787);
const token = process.env.JOB_API_TOKEN;
if (!['127.0.0.1', 'localhost'].includes(host) && !token)
  throw new Error('JOB_API_TOKEN required for non-loopback worker');
const store = createSqliteJobStore(process.env.JOB_DB ?? '/tmp/kit-demo-jobs.sqlite');
const worker = new JobWorker(store, { ingest: ingestLines });
const stop = new AbortController();
const server = createServer(async (request, response) => {
  if (token && request.headers.authorization !== `Bearer ${token}`) {
    response.writeHead(401);
    response.end('Unauthorized');
    return;
  }
  try {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of request) {
      size += chunk.length;
      if (size > 1_000_000) {
        response.writeHead(413);
        response.end('Input too large');
        return;
      }
      chunks.push(Buffer.from(chunk));
    }
    const method = request.method ?? 'GET';
    const input = new Request(`http://${host}:${port}${request.url}`, {
      method,
      headers: { 'content-type': 'application/json' },
      body: ['GET', 'HEAD'].includes(method) ? undefined : Buffer.concat(chunks),
    });
    const result = await handleJobRequest(input, worker);
    response.writeHead(result.status, Object.fromEntries(result.headers));
    response.end(await result.text());
  } catch {
    response.writeHead(400);
    response.end('Invalid request');
  }
});
server.listen(port, host, () => {
  const address = server.address();
  console.log(
    `Durable single-host worker: http://${host}:${typeof address === 'object' && address ? address.port : port}; database ${process.env.JOB_DB ?? '/tmp/kit-demo-jobs.sqlite'}`,
  );
});
for (const event of ['SIGINT', 'SIGTERM'] as const)
  process.once(event, () => {
    stop.abort();
    server.close();
  });
try {
  await worker.run(stop.signal);
} catch (error) {
  if (!stop.signal.aborted) throw error;
} finally {
  store.close();
}
