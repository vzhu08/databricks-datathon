# Author a capability

Create modules/<stable-id> with src/, README.md, module.json, examples/, fixtures/ and tests/. Read catalog/manifest.schema.ts and [the implementation contract](../architecture-contract.md). Source and manifest paths are repository-relative; exports are restricted to the owned module and optional Python starter. No traversal paths or symlinks. Declare exact npm versions and required kit IDs; optional provider integrations belong in optionalIntegrations.

The manifest records source/entrypoints/minimalRead, runtime/environments, packages, env names, system requirements, integration steps/routes/migrations/assets, contracts, fixtures, checks, local/live modes, independent verification states, limits, costs, docs, license and provenance. Use an existing complete manifest as a validated example; [template](../templates/MODULE_MANIFEST.md) explains each field. Generated indexes must never be hand edited.

Implement runtime validation at untrusted boundaries. Keep browser code separate from server SDKs. Include a meaningful normal result, failure and empty/edge case; fixtures must be redistributable and labeled. Provide an example that executes the canonical implementation. Follow [README template](../templates/MODULE_README.md). Tests must measure observable behavior rather than repeat implementation constants.

Run module tests, root typecheck/lint, catalog build/check and the importing composition. Export the minimal closure outside the repository and run its checks. Record local and live verification independently. A fake provider response only establishes the request/response contract tested.
