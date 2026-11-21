import { randomUUID, createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { setTimeout as delay } from 'node:timers/promises';
import { z } from 'zod';
import { readJSON } from '../../../packages/runtime/src/body';
import { KitError } from '../../../packages/runtime/src/index';
import { JobSchema, StartJobSchema, IngestInputSchema, type Job } from './index';

export type StoredJob = Job & {
  type: string;
  input: unknown;
  key?: string;
  fingerprint: string;
  availableAt: number;
  leaseUntil: number;
  token?: string;
  maxAttempts: number;
};
export interface JobStore {
  insert(job: StoredJob): StoredJob;
  get(id: string): StoredJob | undefined;
  claim(now: number, leaseMs: number): StoredJob | undefined;
  save(job: StoredJob, token?: string): boolean;
  close(): void;
}
const copy = <T>(value: T): T => structuredClone(value);
export function createMemoryJobStore(capacity = 1000): JobStore {
  if (!Number.isInteger(capacity) || capacity < 1) throw new Error('capacity must be positive');
  const rows = new Map<string, StoredJob>();
  return {
    insert(job) {
      const existing = job.key ? [...rows.values()].find((row) => row.key === job.key) : undefined;
      if (existing) {
        if (existing.fingerprint !== job.fingerprint)
          throw new Error('Idempotency key reused with different payload');
        return copy(existing);
      }
      if (rows.size >= capacity)
        throw new Error('Job store capacity reached; prune completed jobs or rotate demo store');
      rows.set(job.id, copy(job));
      return copy(job);
    },
    get(id) {
      const row = rows.get(id);
      return row ? copy(row) : undefined;
    },
    claim(now, leaseMs) {
      const row = [...rows.values()].find(
        (row) =>
          (row.state === 'queued' && row.availableAt <= now) ||
          (row.state === 'running' && row.leaseUntil <= now),
      );
      if (!row) return;
      row.state = 'running';
      row.attempts++;
      row.token = randomUUID();
      row.leaseUntil = now + leaseMs;
      row.updatedAt = new Date(now).toISOString();
      return copy(row);
    },
    save(job, token) {
      const current = rows.get(job.id);
      if (
        !current ||
        ['succeeded', 'failed', 'cancelled'].includes(current.state) ||
        (token && (current.token !== token || current.state !== 'running'))
      )
        return false;
      rows.set(job.id, copy(job));
      return true;
    },
    close() {},
  };
}
/** Persistent single-host queue. Every claim is serialized by SQLite and fenced by a unique lease token. */
export function createSqliteJobStore(path: string, capacity = 10_000): JobStore {
  if (!path || !Number.isInteger(capacity) || capacity < 1)
    throw new Error('Invalid SQLite store configuration');
  const db = new DatabaseSync(path);
  db.exec(
    'PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; CREATE TABLE IF NOT EXISTS kit_jobs(id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE, state TEXT NOT NULL, available_at INTEGER NOT NULL, lease_until INTEGER NOT NULL, token TEXT, body TEXT NOT NULL); CREATE INDEX IF NOT EXISTS kit_jobs_claim ON kit_jobs(state,available_at,lease_until);',
  );
  const read = (row: unknown): StoredJob | undefined =>
    row ? (JSON.parse((row as { body: string }).body) as StoredJob) : undefined;
  const get = (id: string) => read(db.prepare('SELECT body FROM kit_jobs WHERE id=?').get(id));
  const write = (row: StoredJob) =>
    db
      .prepare('UPDATE kit_jobs SET state=?,available_at=?,lease_until=?,token=?,body=? WHERE id=?')
      .run(
        row.state,
        row.availableAt,
        row.leaseUntil,
        row.token ?? null,
        JSON.stringify(row),
        row.id,
      );
  function transaction<T>(fn: () => T): T {
    db.exec('BEGIN IMMEDIATE');
    try {
      const value = fn();
      db.exec('COMMIT');
      return value;
    } catch (error) {
      db.exec('ROLLBACK');
      throw error;
    }
  }
  return {
    insert: (job) =>
      transaction(() => {
        const previous = job.key
          ? read(db.prepare('SELECT body FROM kit_jobs WHERE dedupe_key=?').get(job.key))
          : undefined;
        if (previous) {
          if (previous.fingerprint !== job.fingerprint)
            throw new Error('Idempotency key reused with different payload');
          return previous;
        }
        const count = db.prepare('SELECT COUNT(*) AS n FROM kit_jobs').get() as { n: number };
        if (count.n >= capacity)
          throw new Error('Job store capacity reached; archive completed jobs');
        db.prepare('INSERT INTO kit_jobs VALUES(?,?,?,?,?,?,?)').run(
          job.id,
          job.key ?? null,
          job.state,
          job.availableAt,
          job.leaseUntil,
          job.token ?? null,
          JSON.stringify(job),
        );
        return copy(job);
      }),
    get,
    claim: (now, leaseMs) =>
      transaction(() => {
        const row = read(
          db
            .prepare(
              "SELECT body FROM kit_jobs WHERE (state='queued' AND available_at<=?) OR (state='running' AND lease_until<=?) ORDER BY available_at,id LIMIT 1",
            )
            .get(now, now),
        );
        if (!row) return;
        row.state = 'running';
        row.attempts++;
        row.token = randomUUID();
        row.leaseUntil = now + leaseMs;
        row.updatedAt = new Date(now).toISOString();
        write(row);
        return row;
      }),
    save: (job, token) =>
      transaction(() => {
        const current = get(job.id);
        if (
          !current ||
          ['succeeded', 'failed', 'cancelled'].includes(current.state) ||
          (token && (current.token !== token || current.state !== 'running'))
        )
          return false;
        write(job);
        return true;
      }),
    close: () => db.close(),
  };
}
export type JobContext = {
  id: string;
  attempt: number;
  signal: AbortSignal;
  progress(value: number): void;
};
export type JobHandler = (input: unknown, context: JobContext) => Promise<unknown>;
export class JobWorker {
  private listeners = new Set<(job: Job) => void>();
  private active = new Map<string, AbortController>();
  constructor(
    readonly store: JobStore,
    private handlers: Record<string, JobHandler>,
    private options: {
      maxAttempts?: number;
      leaseMs?: number;
      retryDelayMs?: number;
      jobTimeoutMs?: number;
    } = {},
  ) {
    z.object({
      maxAttempts: z.number().int().min(1).max(5).optional(),
      leaseMs: z.number().int().min(30).max(300_000).optional(),
      retryDelayMs: z.number().int().min(0).max(60_000).optional(),
      jobTimeoutMs: z.number().int().min(1).max(3_600_000).optional(),
    }).parse(options);
  }
  start(type: string, input: unknown, options: { idempotencyKey?: string } = {}): Job {
    StartJobSchema.parse({ type, input, ...options });
    if (!Object.hasOwn(this.handlers, type) || typeof this.handlers[type] !== 'function')
      throw new Error('Unknown job type');
    const payload = JSON.stringify({ type, input });
    if (Buffer.byteLength(payload) > 1_000_000) throw new Error('Job input exceeds 1 MB');
    const now = new Date().toISOString();
    const row = this.store.insert({
      id: randomUUID(),
      type,
      input: JSON.parse(JSON.stringify(input ?? null)),
      key: options.idempotencyKey,
      fingerprint: createHash('sha256').update(payload).digest('hex'),
      state: 'queued',
      progress: 0,
      attempts: 0,
      createdAt: now,
      updatedAt: now,
      availableAt: Date.now(),
      leaseUntil: 0,
      maxAttempts: this.options.maxAttempts ?? 3,
    });
    this.emit(row);
    return JobSchema.parse(row);
  }
  get(id: string): Job | undefined {
    const row = this.store.get(id);
    return row ? JobSchema.parse(row) : undefined;
  }
  result(id: string) {
    const row = this.get(id);
    if (!row) throw new Error('Job not found');
    if (row.state !== 'succeeded') throw new Error(`Job is ${row.state}`);
    return row.result;
  }
  cancel(id: string): Job | undefined {
    const row = this.store.get(id);
    if (!row) return;
    if (['succeeded', 'failed', 'cancelled'].includes(row.state)) return JobSchema.parse(row);
    row.state = 'cancelled';
    row.updatedAt = new Date().toISOString();
    if (!this.store.save(row)) return this.get(id);
    this.active.get(id)?.abort(new Error('Job cancelled'));
    this.emit(row);
    return JobSchema.parse(row);
  }
  subscribe(listener: (job: Job) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  private emit(row: StoredJob) {
    for (const listener of this.listeners) {
      try {
        listener(JobSchema.parse(row));
      } catch {
        /* Observers cannot corrupt worker state. */
      }
    }
  }
  async tick(): Promise<boolean> {
    const leaseMs = this.options.leaseMs ?? 30_000;
    const row = this.store.claim(Date.now(), leaseMs);
    if (!row) return false;
    const token = row.token!;
    const controller = new AbortController();
    this.active.set(row.id, controller);
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(this.options.jobTimeoutMs ?? 300_000),
    ]);
    const persist = () => {
      row.updatedAt = new Date().toISOString();
      if (!this.store.save(row, token)) {
        controller.abort(new Error('Lease lost or job cancelled'));
        return false;
      }
      this.emit(row);
      return true;
    };
    const heartbeat = setInterval(
      () => {
        row.leaseUntil = Date.now() + leaseMs;
        persist();
      },
      Math.max(10, Math.floor(leaseMs / 3)),
    );
    heartbeat.unref();
    this.emit(row);
    try {
      if (row.attempts > row.maxAttempts)
        throw new Error('Retry limit reached after worker recovery');
      const handler = this.handlers[row.type];
      if (!Object.hasOwn(this.handlers, row.type) || typeof handler !== 'function')
        throw new Error('Worker has no handler for job type');
      const operation = handler(row.input, {
        id: row.id,
        attempt: row.attempts,
        signal,
        progress: (value) => {
          signal.throwIfAborted();
          if (!Number.isFinite(value) || value < row.progress || value > 1)
            throw new Error('Progress must be monotonic between 0 and 1');
          row.progress = value;
          persist();
          signal.throwIfAborted();
        },
      });
      let abort: () => void = () => {};
      try {
        row.result = await Promise.race([
          operation,
          new Promise<never>((_, reject) => {
            abort = () => reject(signal.reason);
            signal.addEventListener('abort', abort, { once: true });
            if (signal.aborted) abort();
          }),
        ]);
      } finally {
        signal.removeEventListener('abort', abort);
      }
      if (Buffer.byteLength(JSON.stringify(row.result ?? null)) > 1_000_000)
        throw new Error('Job result exceeds 1 MB');
      signal.throwIfAborted();
      row.state = 'succeeded';
      row.progress = 1;
      row.error = undefined;
      persist();
    } catch (error) {
      if (
        this.store.get(row.id)?.state !== 'cancelled' &&
        this.store.get(row.id)?.token === token
      ) {
        row.result = undefined;
        row.error = error instanceof Error ? error.message : 'Job failed';
        row.state = row.attempts < row.maxAttempts ? 'queued' : 'failed';
        row.availableAt = Date.now() + (this.options.retryDelayMs ?? 100) * 2 ** (row.attempts - 1);
        row.progress = 0;
        persist();
      }
    } finally {
      clearInterval(heartbeat);
      this.active.delete(row.id);
    }
    return true;
  }
  async run(signal: AbortSignal, pollMs = 100) {
    z.number().int().min(1).max(60_000).parse(pollMs);
    const stop = () => {
      for (const controller of this.active.values())
        controller.abort(new Error('Worker stopping; unfinished work remains retryable'));
    };
    signal.addEventListener('abort', stop, { once: true });
    try {
      while (!signal.aborted) {
        if (!(await this.tick())) {
          try {
            await delay(pollMs, undefined, { signal });
          } catch {
            if (!signal.aborted) throw new Error('Worker polling failed');
          }
        }
      }
    } finally {
      signal.removeEventListener('abort', stop);
    }
  }
}
export const ingestLines: JobHandler = async (value, context) => {
  const input = IngestInputSchema.parse(value);
  let words = 0;
  for (const [index, line] of input.lines.entries()) {
    context.signal.throwIfAborted();
    await delay(input.delayMs, undefined, { signal: context.signal });
    words += line.trim().split(/\s+/).filter(Boolean).length;
    context.progress((index + 1) / input.lines.length);
  }
  return { lines: input.lines.length, words, mode: 'local' };
};

/** Mount behind application authentication. Scope each worker/store to an owner or verify job ownership first. */
export async function handleJobRequest(request: Request, worker: JobWorker): Promise<Response> {
  try {
    const url = new URL(request.url);
    const id = url.searchParams.get('id');
    if (request.method === 'POST') {
      const input = await readJSON(request, StartJobSchema, 1_000_000);
      return Response.json(
        worker.start(input.type, input.input, { idempotencyKey: input.idempotencyKey }),
        { status: 202 },
      );
    }
    if (!id) return Response.json({ error: 'Missing id' }, { status: 400 });
    const job =
      request.method === 'DELETE'
        ? worker.cancel(id)
        : request.method === 'GET'
          ? worker.get(id)
          : undefined;
    return Response.json(job ?? { error: 'Not found' }, { status: job ? 200 : 404 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Invalid request' },
      { status: error instanceof KitError ? error.status : 400 },
    );
  }
}
