# Decisions

- ADR-001: separate hackathon-kit repository because the chosen workspace is a parent folder containing unrelated repositories.
- ADR-002: Node 22+, npm workspaces + package-lock.json, TypeScript + Next App Router. npm is available and produces portable lockfiles without installing a global manager. Capability sources are vendored with their declared dependency closure; downstream apps have no workspace dependency on the toolkit.
- ADR-003: Zod boundary validation in TS; canonical JSON Schema and shared fixtures for Python. Imports use preserved relative paths. Required shared packages are small and dependency-light.
- ADR-004: Optional services never gate default local mode. Paid adapters require explicit configuration and intent. Tests use contract fixtures; live status is recorded separately.
- ADR-005: Conservative existing-project adoption supports npm + Next App Router and portable source import. It never rewrites existing routes or instruction files and refuses conflicts rather than guessing migrations.
- ADR-006: Python is optional, packaged with uv lock and a container path when tooling permits. Durable workers run separately; memory mode is demo-only. No serverless reliability claim for in-process jobs.
- ADR-007: Operator delegated the license choice; MIT selected for original code and synthetic fixtures, retaining third-party notices. Repository remains local with no remote publication.
