import { demoOrigin } from '../../../packages/runtime/src/demo-reset';
import {
  createMemoryJobStore,
  JobWorker,
  ingestLines,
  handleJobRequest,
} from '../../../modules/jobs/src/server';
import { KitError, errorResponse } from '../../../packages/runtime/src/index';
// Explicit local demo lifecycle: never exported as reliable serverless processing.
const globalStore = globalThis as typeof globalThis & {
  kitDemoJobs?: { worker: JobWorker; draining: boolean; pending: Set<string> };
};
let state = (globalStore.kitDemoJobs ??= {
  worker: new JobWorker(createMemoryJobStore(), { ingest: ingestLines }, { jobTimeoutMs: 10_000 }),
  draining: false,
  pending: new Set(),
});
async function drain(current = state) {
  if (current.draining) return;
  current.draining = true;
  const deadline = Date.now() + 60_000;
  try {
    while (current.pending.size && Date.now() < deadline) {
      await current.worker.tick();
      for (const id of current.pending) {
        const job = current.worker.get(id);
        if (!job || !['queued', 'running'].includes(job.state)) current.pending.delete(id);
      }
      if (current.pending.size) await new Promise((r) => setTimeout(r, 100));
    }
    for (const id of current.pending) current.worker.cancel(id);
    current.pending.clear();
  } catch {
    for (const id of current.pending) current.worker.cancel(id);
    current.pending.clear();
  } finally {
    current.draining = false;
  }
}
export function resetDemoJobs() {
  state = globalStore.kitDemoJobs!;
  for (const id of state.pending) state.worker.cancel(id);
  state.pending.clear();
  state = {
    worker: new JobWorker(
      createMemoryJobStore(),
      { ingest: ingestLines },
      { jobTimeoutMs: 10_000 },
    ),
    draining: false,
    pending: new Set(),
  };
  globalStore.kitDemoJobs = state;
}
export async function handle(request: Request) {
  state = globalStore.kitDemoJobs!;
  try {
    const url = new URL(request.url);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
      throw new KitError(
        'DEMO_ONLY',
        'Use the durable authenticated worker for deployed jobs; the memory demo is localhost-only.',
        403,
      );
    if (
      ['POST', 'DELETE'].includes(request.method) &&
      request.headers.get('origin') &&
      request.headers.get('origin') !== demoOrigin(request)
    )
      throw new KitError('ORIGIN', 'Same-origin action required', 403);
    const response = await handleJobRequest(request, state.worker);
    if (request.method === 'POST' && response.ok) {
      const job = await response.clone().json();
      state.pending.add(job.id);
      void drain();
    }
    return response;
  } catch (error) {
    return errorResponse(error);
  }
}
export const GET = handle,
  POST = handle,
  DELETE = handle;
