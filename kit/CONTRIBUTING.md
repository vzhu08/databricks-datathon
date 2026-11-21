# Contributing

Start from the current main branch and read AGENTS.md plus the module's minimalRead files. Claim one bounded scope in the lead's authoritative task board, name a human owner, and record base SHA, allowed files, dependencies and checks. Concurrent writers use separate branches/checkouts. The lead stewards contracts, catalog schema, root manifests/lockfile, styles and migration ordering.

A module lands with working local behavior, a real optional provider adapter when applicable, runtime validation, normal/failure/empty fixtures, behavior tests, a runnable example, and an eight-question README. Follow [module authoring](docs/guides/MODULE_AUTHORING.md). Put dependencies in module.json; request root dependency changes from the steward. Do not import server SDKs through a client entrypoint.

Before review run `npm run check`, `npm test`, `npm run build`, and affected exported/browser examples. Regenerate catalog after metadata edits. Provide the inspected commit, exact commands and output, skipped prerequisites, live status and limits. One ordered queue integrates changes against current main; rerun affected checks after conflicts or main changes. Fix or revert a broken core path before dependent merges. Merged and Verified are distinct.

After an event, propose reusable code with provenance, a generic contract, synthetic fixtures and removal of event secrets/branding. Keep local project customizations separate until their behavior is understood. Never publish a module or deploy a demo as a side effect of contributing.
