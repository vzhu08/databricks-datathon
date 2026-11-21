# ORCH-01: Optional distributed orchestration

Human owner: Vincent; lead integration: this Codex chat. Branch: feat/orchestration.
Base: 8dbca44. Existing MVP and main remain unchanged. No live inference, GitHub
mutations, merge, deployment or public publication is authorized by the ZIP alone.

Contract: tools/agents/contracts.ts. Literal file/directory scopes, versioned plans,
fenced worker leases, authenticated GitHub identities, checks selected from locally
configured command IDs. Lead alone edits shared contracts, root config, CLI and docs.

Exclusive isolated implementation scopes:

- GitHub agent: tools/agents/github.ts and tests/orchestration/github.test.ts.
- Worker agent: tools/agents/runner.ts, tools/agents/worker.ts and their tests.
- Conversation agent: tools/agents/app-server.ts, tools/agents/chat.ts and their tests.
- Lead: all other files, integration, installer, coordinator and verification.

Acceptance: opt-in existing-project installation preserves application code and agent
instructions; three independent authenticated worker assignments; approval before
dispatch; no overlap or automatic stale-worker reassignment; persistent events and
blockers; bounded deterministic checks/commits/PRs; no implicit provider use.

Checks: npm ci; npm run check; npm test; npm run build; catalog check/build;
test:exports; test:browser; offline simulation. Separate accounts/laptops require
an explicitly started operator smoke test and must remain labeled unverified here.
