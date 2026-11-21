# Project architecture

Selected modules and source revision: kit.project.json and MODULE_SELECTION.md. Draw a small data flow with browser, server boundaries, persistence and external services. Record which operations are local, fixture/replay or live, and which data each service receives.

Example: browser upload → authenticated API → documents.normalize → retrieval/extraction → evidence-linked result → human review → exports. Credentials stay in server configuration. Browser entries never import server SDKs. Shared schemas live under packages/contracts; capability schemas live in modules/<id>/src. Every returned citation references an actual source range.

Persistence: identify owner keys, retention, RLS/policies and reset scope. Background processing: memory demo versus durable worker/volume. Deployment: web host, optional API/worker host, regions and callback/origin configuration. List the failure boundary, timeout and recovery for each external call. Record tradeoffs and rejected alternatives in DECISION_LOG.md.
