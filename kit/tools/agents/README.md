# Optional distributed orchestration

## 1. What problem does this solve, and when should I use it?

Coordinate up to three independently authenticated Codex workers on separate laptops
through one persistent lead conversation. The GitHub control branch carries the
authoritative checkpoint and leadership lease; Issues mirror task records and carry
authenticated reports. Branches and draft PRs carry changes. Leadership can move
between teammates without restarting healthy coding workers.
Use this after an existing MVP is saved, or when a team can agree shared contracts
and exclusive file ownership. Installation starts no background service.

## 2. What is the smallest working example?

From the kit checkout, run `npm run agents -- simulate --offline`. It uses synthetic
local workers and no provider or GitHub calls. This demonstrates coordination, not
live account access. Run `npm run agents -- --help` for the current command surface.

For the full three-computer setup, read `docs/guides/ORCHESTRATION.md` in this kit,
or `docs/ORCHESTRATION.md` in an application after optional installation.

## 3. How do I add it to a fresh or existing project?

Keep the kit on `feat/orchestration`. Save the application first, then run from the
kit checkout:

```sh
npm run kit -- agents add --target /path/to/hackathon-project
npm run kit -- agents add --target /path/to/hackathon-project --apply
```

The first command is a plan. The second applies only a conflict-free plan and checks
for intervening changes. It copies these optional tools, the role and guide, merges
missing dependencies and the `agents` script, and ignores `.kit/`. It does not rewrite
application routes, `AGENTS.md`, or `CLAUDE.md`. Review `npm install` and the lockfile
afterward. Existing conflicting dependencies or modified imported files stop adoption.

## 4. What does the API accept and return?

`contracts.ts` provides Zod schemas for configuration, plans, tasks, fenced worker
leases, reports, blockers and evidence. `Coordinator` implements `ChatBridge`;
`GitHubTransport` implements `QueueTransport`. `runChat(bridge, options)` streams
assistant text and real coordinator events while accepting queued human input.
`runWorker(config, { name, root, signal })` polls only its assigned trusted tasks.

The lead model can read status and propose a plan. A human must issue `/approve N`
for the current version before dispatch. Plan and technical decisions include an
explicit user-facing rationale. The coordinator must durably checkpoint those
decisions before authorizing new assignments; a checkpoint failure blocks dispatch.
An old plan missing `rationale` needs a revised, approved plan before new work.
Tasks reference locally configured check
IDs; issue text is never an arbitrary shell command interface. Scopes are literal
repository-relative files or directory prefixes, without globs. Task categories are
`feature` (default), `fix`, `verification`, or `demo`; new feature dispatch is blocked
in the final three hours. Dependencies wait for integrated verification. A dependent
task with a stale base SHA is blocked until a new approved plan uses the integrated
commit. Local test results, CI, merge and deployment are
separate evidence types; a successful model turn establishes none of them.

## 5. What prerequisites or credentials are needed?

Node 22.23+, npm, Git, GitHub CLI, Codex CLI 0.153+ and access to the shared private
application repository. Each teammate runs `codex login` with their own ChatGPT
account and `gh auth login` with their own GitHub account. Credentials stay in each
tool's normal local store. No teammate tokens or API keys belong in configuration.

`npm run agents -- doctor` checks prerequisites without inference. The explicit
`doctor --live-model` command makes one subscription trial turn using the configured
model, default `gpt-6-astra`. Run it on every computer; a model catalog listing is
not entitlement proof. There is no automatic model/account fallback. `init` requires
an actual deadline with timezone offset and `name:github-login` worker mappings.

## 6. What changes must I make to routes, schema, storage or UI?

No application route or database is required. Commit the nonsecret `orchestration.json`
and adopted source to the application. Review its command allowlist and reserved
paths. Run one lead `chat` process and one separate `worker` process per teammate;
the lead computer may also host a worker in another terminal and isolated worktree.

GitHub compare-and-swap control commits fence leadership with monotonically
increasing epochs. A bounded immutable checkpoint contains the current plan,
approvals, tasks, unresolved decisions, curated context and recent shared request
excerpts. Task Issues are mirrors, so a late write from an old coordinator cannot
authorize another assignment. Worker comments are accepted only from the configured
identity with the original matching run/task/assignment token. Healthy authenticated
heartbeats preserve that worker's reachability during transfer.

Ignored `.kit/` holds private local state, full local outboxes, receipts, logs and
worktrees. Native Codex thread IDs, credentials and private complete transcripts
are not portable checkpoint fields. Treat local state as private project data.

## 7. How do I verify it and handle expected failures?

Run the kit's `npm run check`, `npm test`, `npm run build` and relevant export/browser
checks; orchestration tests are under `tests/orchestration`. Offline tests never
call paid APIs. A Windows restricted sandbox may need TEMP/TMP pointing into a
writable workspace for Vitest caches. The local Codex app-server also needs its
normal writable Codex state directory.

Pause/cancel requests retain the old scope until the worker is confirmed stopped.
Stop the worker process before `release --task TASK --confirm-stopped`. Release
retains its branch and requires a new approved task ID for another attempt. Never
replace an unreachable writer solely because a heartbeat expired. See the guide
for coordinator stale-lock recovery, pending input and emergency manual operation.

For ordinary leadership transfer, the outgoing operator uses
`npm run agents -- handoff --to agent-b`; the incoming operator uses
`npm run agents -- coordinate --resume` with their own local logins. The first
command offers the transfer; completion is reported only after the receiving
coordinator acquires the lease. After a crash, `npm run agents -- takeover` rejects
a healthy lease and requires expiration plus a 60-second safety margin. Existing
task tokens, worktrees, branches and PRs remain unchanged.

## 8. What does it depend on, and what are its limits?

Node built-ins, Zod and `tsx`; GitHub CLI and locally authenticated Codex are optional
runtime prerequisites. Native worker children are disabled conservatively: the
worker runs alone instead of claiming unproven child/depth enforcement. One active
task writes per worker. Push and draft PR creation require `allowPush: true`; default
configuration permits local scoped commits only. Merge/deployment remain human gates.

This is a terminal interface, not a bridge that synchronizes arbitrary existing
ChatGPT/Codex desktop chats. The installed lead and worker processes share tasks
and portable project context through the application repository. A receiving
account starts a local Codex thread from the saved summary and decisions rather
than copying another account's native session. An offline lead conversation receives no worker
notifications until reconnected. The three-account/three-laptop live smoke test is
not performed by fixture tests; follow the guide before relying on live operation.
No production deployment or provider entitlement is implied by implementation.

Original implementation and synthetic tests: MIT. Official references:
[Codex app-server](https://developers.openai.com/codex/app-server),
[Codex authentication](https://developers.openai.com/codex/auth),
[GitHub CLI](https://cli.github.com/manual/).
