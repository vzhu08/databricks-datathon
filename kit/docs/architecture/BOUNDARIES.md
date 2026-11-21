# Boundaries and data flow

The web starter depends only on small shared contracts/runtime and Next/React. Feature modules depend downward on shared packages and on their explicit acyclic module graph. Examples compose those sources. Tools consume manifests; generated applications vendor selected snapshots. No application reaches back into this toolkit.

A browser component imports only its capability's browser entry. Secrets and provider SDKs live behind a server entrypoint and validated route. User input flows through a schema, a bounded operation and a validated result. Citation offsets are UTF-16 code units, end-exclusive; page and row indexes are 1-based. Python uses generated JSON Schema and matching fixtures, including non-BMP text tests.

Local modes are honest implementations where possible (normalization, lexical ranking, constraint solving), or explicit fixtures for provider behavior. Live mode requires caller-selected model/provider and configuration. Replays are labeled. Unknown cost remains unknown without a dated configured price table. A fallback is an explicit policy, never an error hidden from the user.

Storage boundaries: bounded local cache is process-scoped and user-keyed; room/demo jobs are non-durable; SQLite queue survives process restart on one persistent host and uses leases; Supabase stores user-owned rows under RLS. Do not equate a process-global demo instance with multi-tenant persistence.

Read [contracts](CONTRACTS.md), [configuration](CONFIGURATION.md) and [decisions](../implementation/DECISIONS.md). Shared schema/manifest/lockfile changes go through the lead steward before concurrent work resumes.
