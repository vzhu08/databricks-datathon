import { JobWorker, createMemoryJobStore, ingestLines } from '../src/server';
const worker = new JobWorker(createMemoryJobStore(), { ingest: ingestLines });
const unsubscribe = worker.subscribe((job) =>
  console.log({ mode: 'local', id: job.id, state: job.state, progress: job.progress }),
);
const job = worker.start(
  'ingest',
  {
    lines: ['A useful local worker.', 'Progress is observable.', 'Cancellation remains explicit.'],
    delayMs: 20,
  },
  { idempotencyKey: 'demo-ingestion' },
);
await worker.tick();
console.log(worker.result(job.id));
unsubscribe();
