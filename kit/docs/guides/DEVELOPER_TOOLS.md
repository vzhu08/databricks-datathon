# Inspect, evaluate and rehearse

Run these tools from the toolkit root. They are local developer tools; generated projects receive selected module code and instructions.

## API playground

`npm run playground` opens a loopback server at http://127.0.0.1:4310. Edit the JSON request, choose a local transformation or explicitly labeled AI fixture, submit, and inspect status, validated result, timing and request ID. Load shared fixtures to exercise normal/empty inputs. The tool does not record requests.

For an authorized bounded live session, configure AI_PROVIDER, AI_MODEL and the corresponding server API key, then run `npm run playground -- --live --confirm-usage`. Each live request also needs confirmUsage:true. Maximum three requests, 2,000 input characters and 128 output tokens each, concurrency one, no retries, 15-second deadline. Cost is unknown without current provider prices; configure account spending limits separately. An app subscription does not supply API credits. No live request runs simply because a key exists.

## Evaluation

`npm run eval` checks a tiny authored dataset for transforms, constraints, retrieval recall and citation validity. JSON and a readable report go to .kit/evaluations/local. Use `--max-cases 3` to reduce total work, including retrieval cases. This sanity dataset is not a general benchmark.

The deliberate live path is `npm run eval -- --live --confirm-usage --max-cases 3`; it classifies synthetic words using exact-label scoring, records model, token usage, latency and prompt version, and labels unknown monetary cost honestly. It never uses a model to judge itself. Live reports go to .kit/evaluations/live and are ignored by Git.

## Sanitized record/replay

Import Recorder from tools/record-replay.ts. Instantiate it with an isolated directory, enabled:true and a provenance note only after deciding what may be retained. Use record('case-id', requestMetadata, responseMetadata), then replay('case-id'). Existing cases are never overwritten. Files are written with mode 0600 and marked replay with creation time/provenance.

Sensitive-key fields (credentials, cookies, prompts, transcripts, documents, uploads, media and text bodies) are redacted by default. Obvious credential/email patterns in other strings are removed; large text and depth are bounded. Pattern filtering cannot identify arbitrary personal facts hidden in innocuous fields. Record an allowlisted metadata object and review the cassette before sharing it. No tool automatically records live traffic or private input. Module fixtures remain authored synthetic data.

## Doctor and reset

`npm run kit -- doctor --target /absolute/app --port 3000` checks runtime/package/lock presence, selected environment variable names, optional Python availability and local TCP reachability. Values of secrets are never printed. It reports system prerequisites and does not authenticate provider availability or establish Docker/OCR readiness.

Start the studio, then run `npm run demo:reset -- --url http://127.0.0.1:3001` to preview the exact request. Add `--apply` to clear actual local share links and in-memory jobs. For an exported document/media/full project use its loopback URL instead. The endpoint requires a same-origin confirmation header and a loopback host. No database or production reset is performed.

Reload browser pages to restore their synthetic local samples. Stop and restart `npm run realtime` to clear that separate process's rooms/votes. Fixture reload, memory-service reset and database reset are different operations. Follow the Supabase isolated-local seed guide for database data; the generic reset tool never touches it.
