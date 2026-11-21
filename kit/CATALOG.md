# Capability catalog

Generated from module manifests. Run `npm run kit -- inspect <id>` for prerequisites, contracts, examples and verification status. Only selected capabilities and their dependency closure are copied to a project.

| Capability | Purpose | Runtime | Dependencies |
|---|---|---|---|
| [ai](modules/ai/README.md) | Server-only OpenAI and Anthropic text, structured output, streaming, tools and embeddings with deterministic fixtures. | mixed | none |
| [analytics](modules/analytics/README.md) | CSV cleaning, statistics, chart data and exact bounded allocation optimization. | universal | none |
| [documents](modules/documents/README.md) | Normalize text, Markdown, PDF, DOCX and CSV with exact provenance and optional isolated OCR. | mixed | none |
| [exports](modules/exports/README.md) | Formula-safe CSV, evidence-linked PDF, QR codes and explicit expiring/revocable result links. | mixed | documents |
| [extraction](modules/extraction/README.md) | Configurable labeled fields with validated values, exact evidence, ambiguity states and review history. | universal | documents |
| [integrations](modules/integrations/README.md) | Local sinks plus Resend, Google Calendar OAuth, Slack posting, signed inbound events and deduplication. | mixed | none |
| [jobs](modules/jobs/README.md) | Bounded job worker with progress, retries, cancellation, idempotency and SQLite restart recovery. | node | none |
| [maps](modules/maps/README.md) | GeoJSON display, distance filtering, Mapbox geocoding and real travel routes. | mixed | none |
| [media](modules/media/README.md) | Bounded camera/upload processing, timestamped frame sampling and structured vision. | mixed | none |
| [realtime](modules/realtime/README.md) | Actual local WebSocket rooms, presence, shared votes, reconnect, dedupe and optional Supabase presence. | mixed | none |
| [recommendations](modules/recommendations/README.md) | Explainable filtering, weighted utility and deterministic group voting. | universal | none |
| [research](modules/research/README.md) | Safe source discovery and HTML extraction with DNS-pinned fetching, Tavily integration and local fixtures. | mixed | none |
| [retrieval](modules/retrieval/README.md) | Provenance-preserving chunking, lexical/vector retrieval, embeddings and optional Supabase vector persistence. | mixed | documents |
| [supabase](modules/supabase/README.md) | Separate browser/server clients, sign-in and OAuth routes, typed notes CRUD, private storage and owner RLS. | mixed | none |
| [voice](modules/voice/README.md) | Browser recording, turn state, recorded transcription and speech streaming. | mixed | none |

## Task-to-module map

- Generate structured results; Stream chat; Evaluate versioned prompts → [ai](modules/ai/README.md)
- CSV cleaning, statistics, chart data and exact bounded allocation optimization. → [analytics](modules/analytics/README.md)
- Upload a source corpus; Inspect exact evidence spans → [documents](modules/documents/README.md)
- Download reviewed results; Deliberately share a minimal result projection → [exports](modules/exports/README.md)
- Extract a structured project brief; Review supported values before exporting → [extraction](modules/extraction/README.md)
- Send explicit notifications; Schedule a timed event; Handle signed inbound events → [integrations](modules/integrations/README.md)
- Run long ingestion; Track media processing; Recover queued work after restart → [jobs](modules/jobs/README.md)
- GeoJSON display, distance filtering, Mapbox geocoding and real travel routes. → [maps](modules/maps/README.md)
- Bounded camera/upload processing, timestamped frame sampling and structured vision. → [media](modules/media/README.md)
- Shared group decision; Live room presence; Synchronize votes → [realtime](modules/realtime/README.md)
- Explainable filtering, weighted utility and deterministic group voting. → [recommendations](modules/recommendations/README.md)
- Gather cited source text; Develop research flows without paid queries → [research](modules/research/README.md)
- Search a document corpus; Produce supported extractive answers → [retrieval](modules/retrieval/README.md)
- Add sign in; Store user-owned notes; Upload private files → [supabase](modules/supabase/README.md)
- Browser recording, turn state, recorded transcription and speech streaming. → [voice](modules/voice/README.md)
