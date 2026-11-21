# Observable contracts

Canonical TS source: packages/contracts/src/index.ts; generated packages/contracts/schema.json; examples packages/contracts/fixtures. `npm run kit -- catalog build` regenerates schemas with the input representation for request defaults. Types alone do not prove agreement; Python validates the same wire fixtures.

API error: `{error:{code,message,requestId,retryable,details?}}`. Safe public messages omit secrets and stack traces. Routes return x-request-id and no-store where user data is present. Pagination counts total records, uses 1-based pages and a bounded page size. Job progress is [0,1] with explicit queued/running/succeeded/failed/cancelled states; result and failure remain distinct.

Document segments retain stable IDs and exact source ranges. Citation quote must equal source.text.slice(start,end); unknown/missing support is never invented. Layout-sensitive PDF tables and OCR have limits recorded in the documents README. Modified reviews carry editor/note and must not be represented as machine-supported evidence.

A contract change lists consumers, fixtures and migration. The steward updates source/schema together; pause only affected tasks for breaking changes. Normal, empty and malformed cases are part of acceptance. Streams need cancellation, bounded buffers and explicit error handling; retries must not repeat outbound actions invisibly.
