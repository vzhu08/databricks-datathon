# API contract

Endpoint/owner/version: [method path human version]. Canonical schema: [actual source]. Normal fixture: [file]. Empty/failure fixture: [file]. Consumers: [pages/services].

Specify input/output fields, types, required/optional values, defaults, units, bounds and normalization. Record HTTP/error codes and retryability, pagination, stream event ordering/cancellation and persistence/idempotency behavior. Document source offsets use UTF-16 end-exclusive ranges; pages/rows are 1-based; job progress is 0–1.

Example: POST /api/transform accepts text (≤100,000 characters) and optional operation normalize|stats. Returns text, words, characters, mode=local. Empty input is valid. Invalid JSON/type returns a structured error with requestId. Both browser and server validate the wire representation. Python consumes the generated schema/fixtures; do not hand-maintain divergent types.

For a breaking change, list consumers and migration, coordinate through contract steward and pause affected tasks until accepted. Test representative data, not just compiler agreement.
