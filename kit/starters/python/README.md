# Optional Python backend

## 1. What problem does this solve, and when should I use it?

A separate FastAPI service shares the TypeScript wire contracts and provides local text transformation and bounded UTF-8 upload normalization. Add it for Python-specific processing or optional OCR; ordinary web projects do not require Python or Docker.

## 2. What is the smallest working example?

From the generated project/repository root:

```sh
cd starters/python
uv sync --frozen
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/transform -H 'content-type: application/json' -d '{"text":"  Hello   team  "}'
curl -s 'http://127.0.0.1:8000/documents/text?filename=brief.txt' -H 'content-type: text/plain' --data-binary 'Budget: $20'
```

`client-example.ts` is a contract-compatible server-side web call. The document-python recipe mounts route-example.ts at /api/kit/python and component-example.tsx below /kit. Start this service and select Normalize with Python in the web UI. Unavailable service errors stay visible; no TypeScript fallback hides a failed connection. For manual adoption, mount the same route/component explicitly.

## 3. How do I add it to a fresh project or an existing project?

Use `kit create <target> --starter document-python`. For manual adoption copy starters/python and packages/contracts including generated schema.json and shared fixtures. `uv.lock` pins complete resolution including optional OCR/dev dependencies. Run `uv sync --frozen` after moving the project; do not copy a .venv. Install uv separately according to its official instructions; no global environment mutation is required by the starter.

## 4. What does the API accept and return?

POST /transform accepts the canonical TransformRequest and returns TransformResult. POST /documents/text accepts a raw UTF-8 body with a filename query and returns the canonical Document. Pydantic RootModel boundaries validate the generated JSON Schema from TypeScript ($defs); Python does not maintain a competing wire schema. Default normalize operation and word/UTF-16 character behavior match shared fixtures. Normalized document source offsets are UTF-16 end-exclusive, even though Python strings use code points. /health is liveness; /ready confirms loaded schema and reports that OCR is separate. Errors use ApiError and request IDs.

## 5. What prerequisites, environment variables, or credentials are needed?

Python 3.12–3.13 and uv. No credentials. Copy .env.example settings into your process manager or use `uv run uvicorn ... --env-file .env.example`; the application does not auto-load arbitrary env files. KIT_CORS_ORIGINS is an explicit comma-separated origin allowlist (empty by default), KIT_MAX_UPLOAD_BYTES defaults to 1 MB, KIT_WORKER_CONCURRENCY to 2 (max 8), KIT_REVISION identifies deployment. Override KIT_CONTRACT_SCHEMA only when placing the generated schema elsewhere.

For OCR: `uv sync --frozen --extra ocr`, install system Tesseract, then invoke `uv run python app/ocr_worker.py /absolute/input.pdf`. The optional worker uses PDFium/Pillow/Tesseract, page/pixel/input/output limits and per-page OCR timeouts. The document module's pythonOCR adapter adds whole-process timeout/cancellation and temporary-file cleanup. Native OCR is not part of the default request path.

## 6. What changes must I make to routes, schema, storage, or UI?

Server web routes use PYTHON_API_URL reachable from the server/container; direct browser calls use a public browser-reachable URL and explicit CORS. `localhost` inside a container names that container. No login/database wall is added. In production place the private Python API behind your authenticated web service or gateway. Do not expose arbitrary document bytes through a public unauthenticated service. Bound request bodies at the reverse proxy too.

Upload reads raw chunks under a 15-second deadline and a byte limit before parsing, avoiding multipart buffering. CPU normalization runs in a bounded thread pool/semaphore. It is short local work; durable expensive OCR/document jobs should be handed to the toolkit jobs adapter and a separate worker process. API handlers do not start background tasks that pretend to survive restart. The optional OCR CLI is a separate process responsibility.

Container build from repository/generated project root:

```sh
docker build -f starters/python/Dockerfile -t hackathon-kit-python .
docker run --rm -p 127.0.0.1:8000:8000 -e KIT_REVISION=local hackathon-kit-python
```

The image uses a non-root user, frozen uv install, healthcheck and bounded Uvicorn connections. Base Python image is tagged; production should pin an organization-reviewed digest for full image reproducibility. The default image does not install OCR binaries.

## 7. How do I verify it and handle expected failures?

```sh
cd starters/python
uv run pytest -q
```

Tests load the same TypeScript transform/error fixtures and schema, verify Unicode offsets, malformed/oversized uploads, invalid payloads, no default permissive CORS and health/readiness. Regenerate packages/contracts/schema.json after modifying Zod definitions and run both language checks. The JSON Schema uses input semantics for TransformRequest so omitted default operation remains accepted.

Implementation: implemented. Local: lock resolved, isolated environment installed, 5 API/contract tests passed on 2026-10-09. FastAPI 0.143.0/Starlette 1.7.0 emits an upstream httpx test-client deprecation warning; tests remain passing. Container build/native OCR: not run by module author; require Docker/Tesseract. Live deployment/provider: not run. Logs contain method/path/status/duration/request ID, never request bodies or secret values. Source revision: base 0fcd52a plus implementation commit.

## 8. What does it depend on, and what are its limits?

FastAPI, Uvicorn, jsonschema, pydantic-settings; uv.lock records exact versions and hashes. pytest/httpx are dev-only; OCR dependencies are an extra. Python upload route supports UTF-8 text/Markdown; PDF/DOCX/CSV parsing is the canonical TypeScript documents capability. Threads do not isolate hostile native libraries; use constrained worker containers for those workloads. Runtime schema validation cannot by itself validate semantic citation truth; use the shared span invariants. The service has no persistence or automatic job queue. Original code/fixtures: MIT.

Official references verified 2026-10-09: [FastAPI concurrency](https://fastapi.tiangolo.com/async/), [uv FastAPI integration](https://docs.astral.sh/uv/guides/integration/fastapi/), [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/).
