# Optional orchestration verification

Date: 2026-10-24. Source baseline: `8dbca44f8480b6d9375f56d0e18392e66b1325dd`.
Feature branch: `feat/orchestration`; main is not merged or modified.
Verified implementation revision: `62b2122e9bc3e5d8b59b8f8acafb651d22517e6d`
(final documentation-only handoff follows this revision).

Input archive: `hackathon_kit_astra_orchestration_package.zip`, SHA256
`481e0214c5d9bf1eb7334a33d99a285f99ae414dc5328e9c4ea41620d54870d8`.
The Markdown specification and companion TOML are retained under
`docs/resources/orchestration/`. Their embedded role/build prompts are reference
requirements, not permission to invoke providers, dispatch real workers or deploy.

Environment: Windows, Node 24.12.0, Codex CLI 0.155.1, GitHub CLI 2.101.0.
Windows filesystem/process checks needed execution outside the restricted sandbox;
temporary state stayed under the workspace's ignored `.kit/` directory.

## Actual local evidence

- `npm ci --no-audit --no-fund`: passed from the committed dependency lock.
- `npm test`: 226 passed; one opt-in Supabase service test skipped.
- `npm run check`: typecheck, ESLint, catalog and documentation links passed.
- `npm run format:check`: passed; formatter accepts Windows/Unix line endings.
- `npm run kit -- catalog build` and `catalog check`: passed, 15 existing modules.
- `npm run build` and `npm run build:showcase`: passed on retry after Next's existing
  one-time security reminder. Dependency versions were not upgraded.
- `npm run test:browser`: all eight Chromium workflows passed. The headless browser
  downloaded into `.kit/browsers/`; optional FFmpeg download was interrupted by Wi-Fi,
  and these workflows did not require it.
- `npm run test:exports`: all five standalone recipes (`web`, `document-python`,
  `group`, `media`, `full`) plus preserving existing-app adoption passed clean
  dependency install, type/test/build and actual local HTTP smoke checks. Final
  evidence is retained locally in `.kit/verification/exports.json`. The final run
  used the downloaded npm cache while Wi-Fi was interrupted.
- `npm run eval`: all eight authored local cases passed; no provider requests.
- `npm run agents -- simulate --offline`: approval, three isolated assignments,
  blocker, timed snapshot, expired lease reservation and restart passed.
- Standalone optional adoption: a fresh npm ESM app retained its sentinel MVP file
  and `AGENTS.md`; clean `npm install`/`npm ci`, exported help and offline simulation
  passed using the target's own Zod/tsx dependencies, with no checkout symlink.
- Local native app-server: initialize, ChatGPT account/read and ephemeral thread
  creation with typed planning tools and exact Astra selection passed. No inference
  turn was sent; model entitlement is not verified by thread creation.

The orchestration suite uses mocked GitHub/Codex plus real local subprocess/Git
fixtures. It covers approval, DAGs, exclusive scopes, actors/last-editor integrity,
single-leader CAS, fencing, bounded uncertain-create recovery, conversation outbox,
model mismatch/errors, clean-merge verification, cancellation and feature freeze.
Final affected regressions also passed: 17 coordinator tests preserve cancelled
leases across replans and refresh future-task contracts without changing an active
writer; five adoption tests include the MIT notice without replacing app licensing.

## Existing kit portability repairs

Windows npm execution uses npm's JavaScript entrypoint with argument arrays.
Directory-symlink tests use Windows junctions; jobs test cleanup recognizes a
signal-terminated child. Catalog checks normalize CRLF. ESLint ignores generated
browser reports. These changes preserve application/module behavior and dependency
versions. Generated Next declarations were restored after builds.

## Limits and next operator action

Real three-account/three-computer inference, task dispatch, remote PR/CI recovery,
quota failures, native local subagents and production deployment are unverified.
Native worker children are deliberately disabled; restart retains task branches
and requires reviewed stopped-process recovery/new task IDs rather than blindly
starting another writer. See the [three-computer runbook](../guides/ORCHESTRATION.md).

The pinned Next.js release emits a security advisory recommending an upgrade.
The export harness repeats the identical local check once after that reminder and
keeps the warning visible; this is not a security remediation. Review that upgrade
separately before production use. Merge and deployment remain human decisions.

Next action: Oliver saves the existing MVP; adopt on a separate application branch,
configure each teammate's local accounts and explicit deadline, run the low-risk
private three-computer smoke test, then consider merging the kit feature.
