import { describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  JobWorker,
  createMemoryJobStore,
  createSqliteJobStore,
  ingestLines,
  handleJobRequest,
} from '../src/server';
describe('job worker', () => {
  it('rejects inherited handler names both on enqueue and when dispatching persisted work', async () => {
    const store = createMemoryJobStore();
    const worker = new JobWorker(store, { allowed: async () => 'ok' }, { maxAttempts: 1 });
    expect(() => worker.start('constructor', { injected: true })).toThrow('Unknown job type');
    const queued = worker.start('allowed', null);
    const row = store.get(queued.id)!;
    store.save({ ...row, type: 'constructor' });
    await worker.tick();
    expect(worker.get(queued.id)).toMatchObject({
      state: 'failed',
      error: 'Worker has no handler for job type',
    });
  });
  it('bounds chunked request bytes before allocating the complete body and rejects aborted reads', async () => {
    const worker = new JobWorker(createMemoryJobStore(), { ingest: ingestLines });
    let chunks = 0;
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (++chunks <= 20) controller.enqueue(new Uint8Array(256_000));
        else controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });
    const response = await handleJobRequest(
      new Request('http://localhost/jobs', { method: 'POST', body, duplex: 'half' } as RequestInit),
      worker,
    );
    expect(response.status).toBe(413);
    expect(chunks).toBeLessThan(20);
    expect(cancelled).toBe(true);
    const abort = new AbortController();
    const stalled = new Request('http://localhost/jobs', {
      method: 'POST',
      body: new ReadableStream(),
      signal: abort.signal,
      duplex: 'half',
    } as RequestInit);
    const reading = handleJobRequest(stalled, worker);
    abort.abort();
    expect((await reading).status).toBe(408);
  });
  it('stops an active worker cleanly and retains unfinished work for retry', async () => {
    const worker = new JobWorker(createMemoryJobStore(), {
      slow: async () => new Promise(() => {}),
    });
    const job = worker.start('slow', null);
    const stop = new AbortController();
    const running = worker.run(stop.signal, 1);
    stop.abort();
    await running;
    expect(worker.get(job.id)?.state).toBe('queued');
  });
  it('starts, progresses, returns results and deduplicates identical requests', async () => {
    const worker = new JobWorker(createMemoryJobStore(), { ingest: ingestLines });
    const progress: number[] = [];
    const unsub = worker.subscribe((job) => progress.push(job.progress));
    const job = worker.start(
      'ingest',
      { lines: ['one two', 'three'], delayMs: 0 },
      { idempotencyKey: 'ingest-1' },
    );
    expect(
      worker.start(
        'ingest',
        { lines: ['one two', 'three'], delayMs: 0 },
        { idempotencyKey: 'ingest-1' },
      ).id,
    ).toBe(job.id);
    expect(() => worker.start('ingest', { lines: [] }, { idempotencyKey: 'ingest-1' })).toThrow(
      'different payload',
    );
    await worker.tick();
    expect(worker.result(job.id)).toMatchObject({ words: 3, lines: 2 });
    expect(progress).toContain(0.5);
    unsub();
    expect(await worker.tick()).toBe(false);
  });
  it('retries transient errors and exhausts the bounded retry limit', async () => {
    let attempts = 0;
    const worker = new JobWorker(
      createMemoryJobStore(),
      {
        transient: async () => {
          if (++attempts < 2) throw new Error('try again');
          return 'ok';
        },
        fail: async () => {
          throw new Error('bad');
        },
      },
      { retryDelayMs: 0, maxAttempts: 2 },
    );
    const success = worker.start('transient', null);
    await worker.tick();
    expect(worker.get(success.id)?.state).toBe('queued');
    await worker.tick();
    expect(worker.get(success.id)?.attempts).toBe(2);
    const failed = worker.start('fail', null);
    await worker.tick();
    await worker.tick();
    expect(worker.get(failed.id)).toMatchObject({ state: 'failed', error: 'bad', attempts: 2 });
    expect(await worker.tick()).toBe(false);
  });
  it('cancels queued and running jobs and never overwrites cancellation', async () => {
    const worker = new JobWorker(createMemoryJobStore(), {
      slow: async (_, context) =>
        new Promise((resolve, reject) => {
          context.signal.addEventListener('abort', () => reject(context.signal.reason));
          setTimeout(resolve, 20);
        }),
    });
    const queued = worker.start('slow', null);
    worker.cancel(queued.id);
    expect(await worker.tick()).toBe(false);
    const active = worker.start('slow', null);
    const running = worker.tick();
    worker.cancel(active.id);
    await running;
    expect(worker.get(active.id)?.state).toBe('cancelled');
    expect(worker.cancel('missing')).toBeUndefined();
  });
  it('bounds inputs, capacity, invalid progress and execution timeout', async () => {
    const worker = new JobWorker(
      createMemoryJobStore(2),
      {
        invalid: async (_, context) => context.progress(2),
        hang: async () => new Promise(() => {}),
      },
      { maxAttempts: 1, jobTimeoutMs: 10 },
    );
    const invalid = worker.start('invalid', null);
    await worker.tick();
    expect(worker.get(invalid.id)?.state).toBe('failed');
    const hang = worker.start('hang', null);
    await worker.tick();
    expect(worker.get(hang.id)?.state).toBe('failed');
    expect(() => worker.start('hang', null)).toThrow('capacity');
    expect(() => worker.start('unknown', null)).toThrow('Unknown');
  });
  it('handles an empty long-operation input and the request interface', async () => {
    const worker = new JobWorker(createMemoryJobStore(), { ingest: ingestLines });
    const response = await handleJobRequest(
      new Request('http://localhost/jobs', {
        method: 'POST',
        body: JSON.stringify({ type: 'ingest', input: { lines: [] } }),
      }),
      worker,
    );
    expect(response.status).toBe(202);
    const job = await response.json();
    await worker.tick();
    expect(worker.result(job.id)).toMatchObject({ words: 0, lines: 0 });
    expect(
      (await handleJobRequest(new Request(`http://localhost/jobs?id=${job.id}`), worker)).status,
    ).toBe(200);
  });
});
describe('SQLite durability', () => {
  it('survives reopen, atomically excludes other workers, reclaims expired leases, fences stale writes, and remembers idempotency', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'kit-jobs-'));
    const path = join(dir, 'queue.sqlite');
    let store = createSqliteJobStore(path);
    const handlers = { ingest: ingestLines };
    const worker = new JobWorker(store, handlers);
    const job = worker.start(
      'ingest',
      { lines: ['persist me'], delayMs: 0 },
      { idempotencyKey: 'persistent' },
    );
    const claim = store.claim(Date.now(), 1000)!;
    const second = createSqliteJobStore(path);
    expect(second.claim(Date.now(), 1000)).toBeUndefined();
    const newClaim = second.claim(Date.now() + 2000, 1000)!;
    expect(newClaim.id).toBe(job.id);
    expect(newClaim.token).not.toBe(claim.token);
    expect(store.save({ ...claim, state: 'succeeded' }, claim.token)).toBe(false);
    second.save({ ...newClaim, state: 'queued', availableAt: Date.now() }, newClaim.token);
    second.close();
    store.close();
    store = createSqliteJobStore(path);
    const resumed = new JobWorker(store, handlers);
    expect(
      resumed.start(
        'ingest',
        { lines: ['persist me'], delayMs: 0 },
        { idempotencyKey: 'persistent' },
      ).id,
    ).toBe(job.id);
    await resumed.tick();
    expect(resumed.get(job.id)?.state).toBe('succeeded');
    store.close();
    rmSync(dir, { recursive: true, force: true });
  });
  it('limits repeated crash recovery attempts', async () => {
    const store = createMemoryJobStore();
    const worker = new JobWorker(store, { test: async () => 'done' }, { maxAttempts: 1 });
    const job = worker.start('test', null);
    const claim = store.claim(Date.now(), 1)!;
    store.save({ ...claim, leaseUntil: 0 }, claim.token);
    await worker.tick();
    expect(worker.get(job.id)).toMatchObject({ state: 'failed', attempts: 2 });
  });
});
