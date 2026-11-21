# Background jobs

## 1. What problem does this solve, and when should I use it?

Run long operations with start/status/result/cancel, explicit states, progress subscriptions, bounded retries, idempotency and crash recovery. Use the memory store for a single-process demo and SQLite for a durable single-host worker with persistent disk. Browser-safe schemas are in `src/index.ts`; Node implementations are in `src/server.ts`.

## 2. What is the smallest working example?

`node --import tsx modules/jobs/examples/demo.ts` ingests three lines, prints progress and returns word counts. It is local and non-durable. `node --import tsx modules/jobs/examples/worker.ts` starts the durable SQLite worker and loopback HTTP interface at port 8787. POST `{"type":"ingest","input":{"lines":["hello world"]},"idempotencyKey":"demo-1"}`; GET `/?id=JOB_ID`; DELETE the same URL to cancel. No credentials or paid services are involved on loopback.

## 3. How do I add it to a fresh project or an existing project?

Select `jobs` and preserve the shared contracts package. Register handlers as a closed name-to-function map. Instantiate one queue store per application ownership scope, or add an owner field and enforce authorization before exposing the HTTP handler. Run the worker as an always-running process. Do not start a fire-and-forget task inside a serverless request.

## 4. What does the API accept and return?

`new JobWorker(store,handlers,options)` exposes `start(type,input,{idempotencyKey})`, `get(id)`, `result(id)`, `cancel(id)`, `subscribe(listener)`, `tick()` and `run(signal)`. Shared `Job` states are queued/running/succeeded/failed/cancelled. Progress is 0–1 and must be monotonic within an attempt; retry resets it. Handlers receive `{id,attempt,signal,progress}`. `tick` processes one claim and returns false when idle. `subscribe` returns unsubscribe. Request bodies are bounded to 1 MB while streaming, before JSON decoding; oversized bodies return 413 and cancelled/timed-out reads return 408. Results/inputs are bounded to 1 MB; keys are 1–200 characters. Same key and serialized payload returns the same job; reuse with a different payload fails. Keep a stable serialization when constructing repeated requests.

Memory capacity defaults to 1000, SQLite to 10000. Completed rows are retained so idempotency survives retries; explicitly archive/rotate the application's completed queue when full. Retry count is 1–5 (3 default), exponential delay starts at 100ms, job timeout defaults to 5 minutes. Cancellation is terminal; workers cannot overwrite it with a late success.

## 5. What prerequisites, environment variables, or credentials are needed?

Node >=22.13 for `node:sqlite`, Zod, shared contracts. Node 22.23.2 was used locally; its SQLite API still emits an experimental warning. `JOB_DB` points to the SQLite file, `JOB_HOST` defaults to 127.0.0.1, `JOB_PORT` to 8787, and `JOB_API_TOKEN` is required if binding beyond loopback. Memory mode needs no filesystem. Container execution requires Docker and an operator-owned persistent volume; Docker was not available/tested during this build.

## 6. What changes must I make to routes, schema, storage, or UI?

Register `handleJobRequest(request,worker)` behind application authentication. The example worker's bearer token represents one trusted application scope; it is not multi-user authorization. Poll GET for UI progress or connect `subscribe` to an application event transport. Hide result until succeeded; provide cancel only for queued/running. SQLite creates a namespaced `kit_jobs` table/index, enables WAL and busy timeout, and atomically claims work using `BEGIN IMMEDIATE`. Unique lease tokens fence stale writers. Expired leases are reclaimable after restart, and a heartbeat renews active leases.

Deployable option: build from the project root with `docker build -f modules/jobs/Dockerfile -t kit-worker .`; run with a persistent `/data` volume and injected `JOB_API_TOKEN`, mapping port 8787 through your protected service network. Back up the database and its WAL correctly using SQLite backup tooling. Do not put the file on an ephemeral serverless disk or assume safe operation on an arbitrary network filesystem. The Dockerfile is a deployment recipe, not an already deployed service.

## 7. How do I verify it and handle expected failures?

`node node_modules/vitest/vitest.mjs run modules/jobs/tests`. Some tests open temporary loopback listeners and need permission in restricted sandboxes. Tests cover progress/result, empty ingestion, cancel during execution, replay/conflicting idempotency, retry exhaustion, capacity, invalid progress, timeout, durable reopen, two-store claims, stale-token fencing, expired-lease recovery, and the actual authenticated HTTP process across restart. Unknown handlers, full stores, malformed input and premature result reads fail explicitly. Subscribe exceptions do not corrupt job state. Ensure the process can write its database directory; check disk space and queue retention when capacity is reached.

## 8. What does it depend on, and what are its limits?

Node built-ins, Zod, shared contracts and the shared bounded request reader. Memory queues are non-durable. SQLite is a durable **single-host** option, not a managed multi-region queue. Delivery is at least once after crashes; external effects must use the job ID as a downstream idempotency key. Cancellation/timeout rejects the worker operation and stops lease renewal, but cannot undo remote effects or stop arbitrary CPU code; handlers must obey AbortSignal and checkpoint progress. Avoid synchronous CPU-heavy work on the event loop. Retry/error messages are operator-visible and must not contain secrets. [Node SQLite documentation](https://nodejs.org/api/sqlite.html). Original source and synthetic fixtures: MIT.

Implementation: implemented. Local verification: unit and durable restart tests passed. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Deployment/live verification: not run; no remote service was started.

Verification record (2026-10-09, Node 22.23.2): 11 module tests passed, strict TypeScript and scoped ESLint passed, and the local demo ran successfully. Loopback permission was granted for the actual socket/process tests.
