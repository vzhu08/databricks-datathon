# Three-computer orchestration, preserving the current MVP

The optional add-on runs one lead Codex conversation and up to three workers with
separate ChatGPT and GitHub logins. They coordinate through the **hackathon project
repository**. The **hackathon-kit repository** supplies source and installation tools;
it is not the queue for the competition project unless that is deliberately chosen.
No VPN, inbound listener or shared credentials are required. The current
coordinator can offer leadership to another teammate, who resumes from a durable
team checkpoint using their own account. Healthy workers keep their existing tasks.

The source feature is isolated on `feat/orchestration`. Oliver can finish his current
one-shot using the old kit, save that result, and adopt this add-on on a separate
project branch. The kit feature does not need to be merged into kit `main` first.
Nothing here automatically joins existing desktop chats: teammates start the worker
commands below; the lead conversation is `npm run agents -- chat`.

## Assign human accountability

Generated kit projects include `docs/HUMAN_AI_TEAM_WORKFLOW.md`; consult it when
present. The optional add-on can also be installed into existing applications that
do not contain it. Ask for actual owners of three flexible human lanes:
technical/orchestrator lead, product/research lead, and demo/QA lead, including
approval owners and escalation backups. Human roles are independent of worker
accounts; moving the coordinator does not transfer human decision rights.

Workers build → demo lead tests → product lead evaluates → technical lead
prioritizes → orchestrator dispatches within the approved plan. The human playbook
provides context for checkpoints, evidence and blockers; existing technical controls
still govern dispatch, scopes, approvals, merging, spending and deployment. Its
suggested feature exceptions cannot bypass the runtime's freeze gate. Manual
coordination remains available without this add-on.

## Preserve Oliver's current work first

Let the current one-shot finish. Review and commit its application code, then share
that commit through the team's existing private GitHub project workflow. Preserve
the working application branch. Create an adoption branch in that application:

```sh
git status --short
git switch -c feat/orchestration-adoption
```

The kit owner must deliberately share the reviewed `feat/orchestration` branch with
teammates before they can clone it from GitHub. A local implementation branch alone
is not available on another laptop. Do not substitute kit `main` if the feature
branch has not yet been pushed. No kit merge, publication or deployment is implied.

Clone the feature separately from the application. On PowerShell:

```powershell
git clone --branch feat/orchestration https://github.com/oliverchennn/hackathon-kit.git hackathon-kit-orchestration
Set-Location hackathon-kit-orchestration
npm ci
npm run kit -- agents add --target "C:\path\to\hackathon-project"
# Inspect the complete file/dependency plan and resolve any reported conflicts.
npm run kit -- agents add --target "C:\path\to\hackathon-project" --apply
Set-Location "C:\path\to\hackathon-project"
npm install
git diff
```

On macOS/Linux:

```sh
git clone --branch feat/orchestration https://github.com/oliverchennn/hackathon-kit.git hackathon-kit-orchestration
cd hackathon-kit-orchestration
npm ci
npm run kit -- agents add --target "$HOME/projects/hackathon-project"
# Inspect the plan before applying.
npm run kit -- agents add --target "$HOME/projects/hackathon-project" --apply
cd "$HOME/projects/hackathon-project"
npm install
git diff
```

Installation requires an npm project with `type: "module"`. Review other project
formats manually. The installer preserves application routes and existing
`AGENTS.md`/`CLAUDE.md`; it refuses conflicting dependency versions, an existing
different `agents` script, modified imported files, symlinks and intervening edits.
It adds `tools/agents/`, `.codex/agents/orchestrator.toml`, this guide as
`docs/ORCHESTRATION.md`, `orchestration.install.json`, and the optional package script
and dependencies. `.kit/` is ignored. It installs no service and starts no inference.
Review the resulting application diff, run its existing checks and commit the
adoption branch. Keep the MVP checkpoint available for rollback.

## Prerequisites on all three computers

Install Git, Node **22.23+**, npm, GitHub CLI and Codex CLI **0.153+**. Teammates need
write access to the same private **application** repository. Use each person's own
accounts; do not copy `~/.codex`, GitHub credentials, browser sessions or API keys.

On Windows, Git/Node/GitHub CLI can be installed with the standard installers or
PowerShell package manager:

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id OpenJS.NodeJS.LTS -e
# Open a new PowerShell session after installation.
```

On macOS with Homebrew:

```sh
brew install git gh node
```

On Linux, install Git, Node and GitHub CLI using the tools approved for that machine.
Then, in each teammate's own terminal:

```sh
npm install -g @openai/codex@latest
node --version
git --version
gh --version
codex --version
codex login
codex login status
gh auth login
gh auth setup-git
gh auth status
```

Codex authentication uses each local ChatGPT subscription. The lead and workers
force ChatGPT login and do not silently fall back to an API-key provider. An exact
configured model, default `gpt-6-astra`, is required. Account access and quota may
differ, even when all three people see the same model name in a picker. The explicit
trial later verifies inference access for each account.

## Configure the shared project once

From the **application** checkout on computer A, choose the actual event deadline
with a timezone offset. Replace every identity/repository placeholder:

```sh
npm run agents -- init --repo OWNER/HACKATHON-PROJECT --coordinator LEAD-GITHUB-LOGIN --workers agent-a:ALICE-GITHUB,agent-b:OLIVER-GITHUB,agent-c:CAROL-GITHUB --deadline 2026-10-25T12:00:00-04:00
```

The date above is an example, not your event deadline. `init` writes local nonsecret
`orchestration.json` and refuses to overwrite an existing file. Inspect its repository,
run ID, identities, deadline, `checks`, and `reservedPaths`. Default checks reference
the application's `typecheck` and `test` npm scripts; adjust the configured command
IDs to the project's actual verification commands before approving work.

By default `allowPush` is false. Workers can create validated local task commits,
and a human shares them. To authorize automatic scoped task-branch pushes and draft
PR creation, use `--allow-push` with the initial `init`, or deliberately review and
commit `allowPush: true` in existing configuration. This does not authorize merge,
deployment, package publication, or other external messages. Every teammate should
review and pull the same committed configuration before starting.

Before enabling automatic worker PRs, ensure that the reviewed adoption/config
commit is present in the application's default integration branch: task PRs target
that repository's default branch. Keep the original MVP checkpoint available. This
does not require merging the toolkit feature into kit `main`.

Commit and share the add-on plus nonsecret configuration in the application using
the team's ordinary review process. On computers B/C, clone or update that project
and check out the adoption branch. Use `npm ci` after its reviewed lockfile is saved:

```sh
gh repo clone OWNER/HACKATHON-PROJECT
cd HACKATHON-PROJECT
git switch feat/orchestration-adoption
npm ci
```

Existing clones should save their own changes before changing branches. They do not
need to clone the kit after the add-on source is committed to the application.

## Check the three independent identities and model accounts

Run on computer A:

```sh
npm run agents -- doctor
npm run agents -- doctor --live-model
```

Run on B and C using their assigned names:

```sh
npm run agents -- doctor --name agent-b
npm run agents -- doctor --name agent-b --live-model
```

Use `agent-c` on C. Doctor without `--live-model` performs read-only prerequisite,
repository/permission and local login checks, with model inference labeled **NOT
RUN**. `--live-model` deliberately makes one authenticated subscription trial turn;
it uses allowance and must be started by the operator on each machine. It never
uses a separate paid API account. An unavailable model, wrong GitHub identity, quota
failure or missing repository access must be corrected before starting that worker.
Do not share someone else's login or change the model silently.

## Start one lead and three workers

Keep terminals open. Computer A runs two distinct processes; worker changes use
their own task worktrees:

| Computer | Terminal | Command                                                          |
| -------- | -------- | ---------------------------------------------------------------- |
| A        | Lead     | `npm run agents -- chat`                                         |
| A        | Worker A | `npm run agents -- worker --name agent-a --install-dependencies` |
| B        | Worker B | `npm run agents -- worker --name agent-b --install-dependencies` |
| C        | Worker C | `npm run agents -- worker --name agent-c --install-dependencies` |

`--install-dependencies` explicitly permits the runner's dependency setup in new
task worktrees. Review the project lockfile and install scripts first. Omit the flag
if dependencies are provisioned another way; missing dependencies fail visibly.
Native local children are currently disabled conservatively. Each worker implements
its task alone; the runtime does not claim it has enforced unproven child/depth caps.

There is one coordinator authority. A second lead cannot take a live GitHub lease.
Workers require their configured local GitHub identities and own ChatGPT accounts;
tasks and reports are schema-validated and fenced with run/version/lease tokens.
Allowlisted issue authors still do not gain a raw command execution interface.

The bootstrap coordinator, configured authorized actors and worker GitHub identities
are eligible coordinator identities. Keep the same reviewed `orchestration.json`
on each laptop: checkpoint restoration verifies the repository, run and policy
digest instead of accepting a different command/scope/deadline configuration.

Tell the lead what already exists, the critical judging demo, constraints and the
actual time available. It can read status, inspect the repository in a read-only
sandbox and propose a versioned plan with contracts, task dependencies, literal
write scopes, acceptance checks and a user-facing `rationale`. Inspect the proposal.
An old saved plan without its rationale must be revised before new dispatch;
missing historical reasons are not invented. Dispatch is gated by a
human terminal command:

```text
/approve 1
```

`/reject 1` rejects that proposal; `/replan Explain the desired change` asks for a new
one. Model tools cannot approve their own plans. New versions need new approval.
Active writers must be preserved during replanning; scope changes require stopping
the affected process and confirming release first.

Tasks declare `category`: `feature` (the default), `fix`, `verification`, or `demo`.
The coordinator blocks new `feature` dispatch during the final three hours; use
that time for actual stabilization, verification and rehearsal work. Do not relabel
a feature to bypass the freeze. A dependent task waits for integrated verification
and must use the approved integrated base SHA. A stale base becomes a blocker;
update the future task in a new approved plan instead of working against an older
application snapshot.

## Conversation, status and human decisions

Normal input remains accepted while a model turn runs. It is acknowledged as queued
locally and sent at the next valid turn boundary, with the current deterministic
snapshot. The client does not claim unsupported mid-turn steering. `/interrupt`
requests interruption of the acknowledged lead turn; it does not cancel workers.

| Input                             | Behavior                                                              |
| --------------------------------- | --------------------------------------------------------------------- |
| `/status`                         | Deterministic current tasks, worker evidence and deadline             |
| `/timeline`                       | Recent local journal, explicitly replayed                             |
| `/blockers`                       | Unresolved task questions                                             |
| `/pause [TASK]`, `/resume [TASK]` | Request run/task control; old writer scope remains reserved           |
| `/cancel TASK`                    | Request cancellation; no claim the process already stopped            |
| `/resolve TASK BLOCKER answer`    | Persist a human answer; a stopped attempt needs a new approved task   |
| `/approve N`, `/reject N`         | Human decision for exactly that plan version                          |
| `/allow REQUEST`, `/deny REQUEST` | Reply to that connected process approval only                         |
| `/answer REQUEST QUESTION answer` | Reply to a model clarification question                               |
| `/replan instructions`            | Queue a request for a new plan                                        |
| `/context`, `/remember TEXT`      | Inspect portable context or explicitly remember a safe shared summary |
| `/decision SUMMARY \| RATIONALE`  | Persist a human decision and its user-facing reason                   |
| `/private TEXT`                   | Queue private local input without publishing its text                 |
| `/handoff --to NAME`              | Offer leadership to the configured successor; workers keep running    |
| `/help`, `/quit`                  | Show controls or stop the lead chat                                   |

The lead's read-only sandbox remains subject to local Codex permissions. Process
approval prompts are separate from plan dispatch approval. Do not put credentials
into model answers; configure secrets locally outside conversation.

Project decisions must include a concise explanation of **why** that choice was
made. Architecture, clarification, priority, scope, plan and approval records are
durable team context. Before each new assignment, the coordinator checkpoints its
dispatch decision and then authorizes the assignment through the current control
commit. If the checkpoint cannot be written or verified, no new task is issued.

The context tools maintain a rolling project summary, requirements, priorities,
answered questions and recent shared request excerpts. `/context` shows what is
shared; `/remember TEXT` explicitly adds important context, and
`/decision SUMMARY | RATIONALE` records a human decision with its reason. Ordinary
project inputs contribute short scrubbed request excerpts; `/private TEXT` keeps
that input local. Full assistant transcripts, native hidden state, auth files and
environment variables are never copied into the team checkpoint. Review context
before including confidential project material. Redaction is a guard, not a reason
to paste credentials into conversation.

Credential-looking ordinary inputs are treated as private. Private pending,
in-flight or uncertain input blocks handoff until it finishes or the operator uses
`/remember` to acknowledge a safe summary for transfer. The raw private text stays
in the old laptop's ignored outbox; acknowledging a summary does not publish it.

Significant verified events appear when the next synchronization observes them,
normally within the configured 15-second polling interval. Heartbeats default to
60 seconds and mean reachability, not coding progress. Five-minute active-work
snapshots use deterministic state and no new LLM call. An alive but quiet process
is not a completed feature. Alerts at 12/6/3/1 hours remaining recommend cuts and
final stabilization; the runtime computes time from the configured deadline and
does not invent percentage completion or task ETAs. Humans choose promised scope
cuts; the model must not claim a deployed demo from a plan or cached fixture.

Blockers retain their attempted fixes, options, recommendation and impact. Independent
tasks can continue. If GitHub synchronization fails, the conversation stays usable,
polling backs off, and the interface says status is uncertain. It does not create a
second writer. When the model process fails, future input remains in the local
outbox; restart chat to reconnect. Previous uncertain sends are not blindly replayed.

## Evidence and integration

| State/evidence      | What is established                                        |
| ------------------- | ---------------------------------------------------------- |
| Planned/approved    | A human authorized the exact plan version                  |
| Assigned/Running    | Assignment exists / worker process reported starting       |
| Check evidence      | The deterministic runner recorded command, result and time |
| Review              | A scoped implementation passed required local checks       |
| Draft PR            | Changes were shared, if push was authorized                |
| Queued              | Observed CI checks passed for the current PR head          |
| Merged              | GitHub confirmed a human merge                             |
| Verified            | The confirmed integrated commit passed configured checks   |
| Deployment evidence | A separately observed deployment; never implied by CI      |

A model's success assertion is not check evidence. The runner validates the actual
diff, reserved/allowed paths, secrets and branch before scoped staging and commit.
It rechecks assignments before remote side effects. It does not push `main`, merge,
deploy or publish. Review draft PRs and the configured CI before a human merge.
No CI checks means pending/unverified, not an automatic green result.

After a confirmed human merge, use the CLI's integration verification command for
the exact merge SHA, from a stopped lead session:

```sh
npm run agents -- verify --task TASK-ID --sha FULL-40-CHARACTER-MERGE-SHA --install-dependencies
```

It runs deterministic configured checks in isolation and records integrated evidence
only after success. It does not approve a merge or replace the project's release
checks. Keep the main application demo working, and use human-approved deployment
and submission procedures independently.

## Transfer leadership between computers and accounts

Update all three laptops to the same handoff-capable orchestration source and
configuration before the first transfer. Save existing MVP and task changes normally;
do not delete worker receipts or worktrees. Each laptop keeps its own `codex login`
and `gh auth login`. Never copy `~/.codex`, credentials or local native thread state.

On computer A, while A is the current coordinator:

```sh
npm run agents -- handoff --to agent-b
```

The chat equivalent is `/handoff --to agent-b` (or `/handoff agent-b`). From another
terminal on A, the CLI uses a private local request/receipt inbox while the existing
chat owns the coordinator lock; it does not start a competing lead. It waits up to
120 seconds for an offer receipt. If there is no local lead, direct offering still
requires safe leadership acquisition; a healthy remote lease is not bypassed.
The sender's local GitHub identity must match the current leader.

This freezes **new assignment dispatch**,
persists the latest shared context and unresolved decisions, and atomically records
the designated successor. The response means the transfer is **offered**, not yet
completed. It gives the receiving command. Existing workers on A, B and C continue
their assigned task tokens, checks, commits and approved PR workflow. A's ordinary
coding worker is a separate process and is not stopped by lead handoff.

On computer B, in the same application checkout/configuration:

```sh
npm run agents -- coordinate --resume
```

B must be locally authenticated as the designated successor. The receiving process
acquires the lease through a Git ref compare-and-swap, increments the leadership
epoch, validates and restores the checkpoint, and reconciles tasks, reports, PRs and
blockers. Only then may it report that leadership transferred. The startup summary
uses actual worker/task/PR/blocker counts; it does not assume all three workers are
running. B's existing coding worker continues in its separate terminal.
`coordinate --resume --name agent-b` optionally labels/validates the receiving
worker identity; the two-command flow above does not require that flag.

The new local Codex thread receives the saved objective, summary, decisions and
answered questions. This reconstructs working conversation context across accounts;
it does not claim to copy private native conversation state or hidden model state.
Pending shared requests and unresolved decisions remain visible. Private or uncertain
input may require a focused clarification; it is not silently republished or replayed.

To transfer again from B to C, run `handoff --to agent-c` on B and
`coordinate --resume` on C. To return leadership to A, use `handoff --to agent-a`
from the current coordinator, then `coordinate --resume` on A. These commands work
in PowerShell and Unix shells. Use the worker names from the committed configuration.

After a transfer, run `npm run agents -- status` on either laptop. Inspect the current
coordinator/host, lease phase and expiration, active epoch, last checkpoint, task
counts and pending decisions. Confirm the receiving identity and larger epoch.
An old coordinator that reconnects cannot renew or write using its stale owner/epoch.
Issue labels or a stale task-body edit do not override the authoritative checkpoint.

### Crash, disconnect or usage-limit recovery

If the old operator can still use the terminal, prefer graceful handoff before
their account reaches its usage limit. Lease renewal and checkpointing are ordinary
code and consume no model turn. The runtime does not invent private quota access.

If the old coordinator cannot offer a transfer, an eligible teammate runs:

```sh
npm run agents -- takeover
```

Takeover rejects a healthy active lease. It permits recovery only after the stored
lease expires **plus a 60-second safety margin**, then competes through the same
non-force compare-and-swap. Two simultaneous attempts cannot both obtain dispatch
authority. The winner restores and reconciles the last complete checkpoint;
incomplete blob uploads never replace the previous valid checkpoint. A failed
candidate reports the conflict and must inspect status rather than force ownership.
No command force-takes a healthy coordinator lease.
`takeover --name agent-c` is the optional named form on C. A timeout, failed offer
receipt or failed acquisition is not a successful transfer; inspect `status`
before repeating the command.

Do not stop healthy coding workers merely to change coordinator. Their authenticated
heartbeats can preserve worker-lease reachability while the leader is transferring
or offline. Expired/unreachable tasks keep their scopes reserved. Takeover does not
restart those tasks, declare their results successful or assign a second writer.
Inspect uncertain tasks and use explicit stopped-worker recovery below if required.

| Failure                                                      | Action                                                                                                                                |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| Receiver is not the designated successor                     | Use the mapped GitHub login on the intended laptop; inspect status before another transfer.                                           |
| Lease is still healthy or within the safety margin           | Wait for the displayed lease deadline or ask the current operator to offer a graceful transfer.                                       |
| Checkpoint upload, digest, schema or policy validation fails | Dispatch remains stopped. Restore the same reviewed config and inspect the error; preserve the last valid checkpoint and local state. |
| Old coordinator reconnects                                   | It must inspect status and start a new authorized receive/takeover flow; it cannot reuse its old epoch.                               |
| Pending private input cannot be shared safely                | Finish it locally or record an explicit safe summary with `/remember`; do not copy the private outbox.                                |
| A worker completes during transfer                           | Keep its report/receipt and branch. The receiving coordinator reconciles the same assignment token.                                   |

## Recovery and manual fallback

Local state is under ignored `.kit/`: coordinator journal/lock, conversation outbox,
worker receipts, command logs and task worktrees. Do not commit it, delete it during
active work, or copy authentication stores between machines. The shared control
checkpoint holds portable project context and coordination state. Keep old local
state if you need its private native chat history or unshared inputs; another laptop
does not automatically receive those private transcripts.

For an ordinary lead restart, stop the old process and restart `npm run agents --
chat`. It restores the thread ID, event journal and unanswered task blockers. Old
server-process approval IDs are explicitly interrupted and must be reissued; stale
IDs cannot approve a different process request. Local input is queued only on that
computer, with uncertain delivery labeled rather than silently repeated.

For a crashed coordinator, use the takeover flow above. A same-computer restart
may also find a stale local coordinator lock. Confirm that old **lead** process is
stopped before `npm run agents -- recover --confirm-stopped`; do not remove a live
lock and do not stop unrelated healthy workers. This local lock operation does not
grant remote leadership or release task file ownership. Legacy task-only runs that
predate shared checkpoints need explicit reconciliation by the bootstrap coordinator
before new dispatch; the system cannot invent rationale that was never recorded.

When a newer shared checkpoint replaces older local state, the previous local
snapshot is retained as `local-before-resume-*.json` in the run directory. It is
private recovery data: inspect unshared drafts there rather than silently publishing
them. A receiving account starts a fresh native thread from shared project context.

If a local handoff request was interrupted before publication or cleanup, stop the
old lead and old handoff CLI process before `recover --confirm-stopped`. Recovery
archives the interrupted inbox for inspection; it does not grant remote leadership.
During preparation, new terminal input is retained locally and marked as outside
the transfer. A committed successor offer remains valid even if the sender's last
local journal/receipt write fails; check the shared `status` before retrying.

For an unreachable, paused, cancelled or blocked task, do not launch another writer
of its files. First request `/pause TASK` or `/cancel TASK`, stop its worker on the
owning laptop, inspect the retained worktree, and stop the lead before using the
standalone mutation CLI:

```sh
npm run agents -- release --task TASK --confirm-stopped
```

This revokes the task lease, retains its branch and marks the stopped attempt failed.
Use a **new task ID** in a reviewed/approved plan for another attempt. It does not
discard changes or silently recover a partially completed implementation. A worker
receipt can deliberately block restart of an uncertain prior attempt; inspect it
and use documented manual recovery instead of deleting it while processes run.

Emergency manual mode is always available: stop lead and worker processes, leave
their branches and PRs intact, appoint one human integration owner, record explicit
file ownership in the project's normal task board, and continue with ordinary
Git/Codex commands. Reconcile old assignments before restarting automation. If
infrastructure recovery threatens the demo, finish manually from the saved MVP.

## Verification checklist and limits

Fixture tests and offline simulation are local evidence. The implementation includes
mocked GitHub/app-server tests for coordination, authorization, event integrity,
recovery and chat responsiveness. Optional adoption into a fresh minimal npm ESM
project passed plan/apply preservation checks, clean `npm install` and `npm ci`, and
exported help/offline simulation using its own installed dependencies. Local
app-server initialization/account-read has
been checked on the implementation machine without inference. The **real three
accounts / three computers smoke test has not been run** by this implementation.
Do not report model entitlement, multi-machine recovery or deployment as verified
until operators perform and record those checks.

Before relying on live operation, deliberately run a low-risk rehearsal on an
operator-owned private test project:

1. Each of three people passes doctor, including the explicit local model trial.
2. Lead proposes three independent fixture tasks and waits for `/approve VERSION`.
3. Each assigned laptop reports the right identity, isolated branch, actual check
   results and one reviewed task commit; draft PRs appear only if push was authorized.
4. While workers run, ask a status question and queue new input. Verify real events,
   five-minute snapshots and immediate blocker presentation after synchronization.
5. Stop worker B, confirm its scope remains reserved, and exercise explicit stopped
   recovery. Prove no duplicate writer or stale-token result can replace it.
6. Restart the lead and verify event order, pending blocker/plan decisions, conversation
   resume and clear distinction between replayed/new events. Reissue interrupted
   process approvals rather than accepting stale IDs.
7. Review CI for the exact PR head, perform a human-approved merge, run integration
   verification, and separately check the real demo. Record commands, timestamps,
   commits, links and limitations without storing credentials.
8. While healthy workers run, transfer A→B→C→A with the two commands above. Verify
   increasing coordinator epochs, stable task tokens/branches and one model process
   per task. Confirm that an offered transfer is not called complete before receipt.
9. Rehearse a coordinator crash, rejected early takeover, simultaneous takeover
   attempts, stale old-leader writes and a worker result arriving during transfer.
   Validate the restored decision rationale, answered questions and pending shared
   requests. Check that a failed checkpoint blocks new assignments and that private
   context/credentials are absent from the shared checkpoint.

Native children are disabled; there is no cross-chat desktop synchronization, quota
sharing, automatic merge/deployment, unbounded retries, or guaranteed notification
to an offline user. GitHub permissions are the team trust boundary; all collaborators
must follow agreed ownership, and external branch/issue edits may require manual
reconciliation. Polling and transport limits are bounded and fail visibly rather
than silently treating incomplete pages as complete state.

## Rollback

Stop every orchestration process first. Preserve task branches, PRs, logs and any
unmerged code you need. Revert the application's adoption commit using its normal
review process, or remove only add-on files that still match
`orchestration.install.json` hashes. Restore the previous `agents` script/dependency
and `.gitignore` changes from the reviewed diff. Never delete a whole `.codex/`,
`tools/`, `docs/` or application directory: it may contain user-owned work.

Review dependency changes and regenerate the lockfile using the project's standard
workflow. Return to the saved MVP application checkpoint if needed. Kit `main` and
Oliver's pre-adoption one-shot remain independently usable; neither requires a
feature-branch merge. Retaining task PRs or issue records is harmless; cleanup is
a deliberate human repository action after the event.

Official references: [Codex app-server](https://developers.openai.com/codex/app-server),
[Codex authentication](https://developers.openai.com/codex/auth),
[Codex multi-agent configuration](https://developers.openai.com/codex/multi-agent),
[GitHub CLI manual](https://cli.github.com/manual/).
