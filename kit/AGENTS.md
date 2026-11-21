# Working on Hackathon Kit

Read [agent start](docs/start-here/AGENT_START.md), then the selected module README and manifest. Inspect scoped AGENTS.md/CLAUDE.md explicitly; tools differ in nested instruction loading.

## Scope and ownership

- Preserve user work. Inspect branch, diff, task card, contracts and fixtures first.
- One active writer owns a file set; concurrent writers use isolated branches/checkouts.
- Use parallel subagents for independent implementation only after contracts are established. Every writer needs an exclusive scope and isolated checkout; the lead owns integration.
- Root manifests/lockfiles, catalog schema, shared contracts/runtime, global config, generated indexes and migration ordering are lead-stewarded. Request changes rather than editing them from a module task.
- Keep the current build plan in docs/implementation/PLAN.md and actual state in STATUS.md.
- The authoritative task board is docs/implementation/OWNERSHIP.md in the lead checkout. Branch copies are snapshots, not locks.

## Architecture

- Canonical capabilities: modules/<id>/{src,tests,fixtures,examples,README.md,module.json}.
- Shared runtime/schema: packages/runtime and packages/contracts. UI: packages/ui.
- Module dependencies must be declared and acyclic. Relative imports preserve the export layout. No unpublished workspace packages or absolute toolkit paths.
- Use Zod at runtime boundaries. Python wire contracts use packages/contracts/schema.json; shared fixture tests prevent drift.
- Server adapters stay in server.ts or explicit server-only files. Browser entrypoints must not import secrets, Node built-ins or server SDKs.
- Keep module installation optional; base web requires Node only. Fixture/live/replay results are visibly distinct. Never quietly replace live failures with fixtures.

## Checks

- npm ci; npm run check; npm test; npm run build
- npm run kit -- catalog check; npm run kit -- catalog build
- npm run test:exports; npm run test:browser (requires browser binary)
- Selected module: npx vitest run modules/<id>/tests
- Ordinary checks use local fixtures, never paid APIs. Live tests require explicit operator intent and configured test accounts.

## Delivery

- Include implementations, normal/failure/empty tests, fixtures, a runnable example, eight-question README and schema-valid module manifest.
- Preserve provenance, citations and exact offsets. Bound uploads, network requests, retries, tools and worker queues.
- Do not overwrite downstream modifications or agent instructions. Adoption is plan-first and explicit --apply.
- Never commit secrets, publish, deploy, send real messages or spend on API calls implicitly.
- Record actual checks, skipped prerequisites, source revision, limits and next action. Merged, locally verified and live verified are distinct.
- Original code is MIT, selected with operator authorization; preserve notices. Public publication still requires operator authorization.
