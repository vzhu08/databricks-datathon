---
title: 'Hackathon Kit | Astra Orchestrator'
subtitle: '24-hour distributed Codex system - implementation specification and three-computer runbook | Revised edition'
author: 'Engineering handoff | 24 October 2026'
date: '24 October 2026'
lang: en-US
geometry: margin=0.74in
fontsize: 9.5pt
mainfont: DejaVu Sans
monofont: DejaVu Sans Mono
colorlinks: true
linkcolor: NavyBlue
urlcolor: NavyBlue
---

> **HAND THIS GUIDE TO THE CODEX IMPLEMENTER.** Build and verify the functionality before using the commands in the runbook. The proposed `npm run agents -- ...` commands are **not in the existing repository yet**. The companion `orchestrator.toml` is a ready-to-install behavior template, **not** a substitute for the orchestration runtime.

**Repository:** <https://github.com/oliverchennn/hackathon-kit> (private; each teammate needs access).  
**Intended result:** You talk to one responsive, persistent **Astra** orchestrator. It clarifies consequential ambiguities, plans the fastest path to a polished demo, sends tasks to **three separately authenticated Codex accounts on three computers**, optionally lets each worker use bounded local subagents, streams accurate progress, immediately escalates true blockers, and coordinates automated tests/commits/PRs. People approve plans, merges and deployment. The default event window is **24 hours**.

# 1. Operating decisions

| Component           | Decision / default                                                                                                                                                        |
| :------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Lead interface      | **Interactive Codex-like chat** with streaming text, persistent context, commands, job logs, interruption and approval prompts; use Codex **app-server**.                 |
| Lead model          | `gpt-6-astra`, `high` reasoning for architecture, decomposition and major replanning. Model is configurable, but **do not silently substitute a different one**.          |
| Worker models       | Three independent local `gpt-6-astra` Codex CLI sessions; `medium` reasoning for ordinary bounded implementation; elevate to `high` when justified.                       |
| Worker subagents    | Up to **2 local child subagents per worker**; **no grandchildren**; spawn only for independently useful reasoning/work. Astra remains the model by default.               |
| Cross-machine queue | GitHub Issues for task state; branches/PRs for code; CI for integration. No VPN or continuously exposed inbound ports.                                                    |
| Who commits/tests?  | **Deterministic scripts**, not agents: targeted checks, branch setup, validated `git add/commit/push`, PR creation, CI polling.                                           |
| Progress            | **Event-driven updates immediately**, a concise **5-minute active-work status** even without milestones, immediate actionable blocker alerts, silent/no-model heartbeats. |
| Real blockers       | Ask a focused question with options and recommended action; keep other independent workers productive; do not invent progress.                                            |
| Release             | Working demo early, checkpoints throughout, final feature freeze and human-approved merge/deploy.                                                                         |
| Installation        | Optional add-on in `hackathon-kit`; must preserve all existing behavior and tests.                                                                                        |

**Model note:** OpenAI's published Codex model slug is **`gpt-6-astra`** (not simply `astra`). Astra requires **Codex CLI >= 0.153.0** and account-level availability. The model picker is not a sufficient entitlement check: run a small authenticated inference on each account. Astra may consume subscription allowance faster than other models; monitor local limits. Do not introduce an API key or secretly bill a separate API account.

## The distinction between agent judgment and engineering automation

Use Astra for interpreting ambiguous requirements, selecting high-value features, designing interfaces, implementing complex code, debugging and reasoning about tradeoffs. Use ordinary code for polling, timestamps, heartbeats, tests, formatting, commits, safe pushes, GitHub labels, state transitions, notifications and deployment checks. A successful Git command is **not** proof of a successful feature; status and quality come from verified evidence.

# 2. Existing repository - preserve and extend

The inspected repo already has `AGENTS.md`, `CLAUDE.md`, `tools/kit.ts`, `tools/project.ts`, `docs/playbooks/COLLABORATION.md`, `docs/playbooks/DEVELOPMENT_PLAYBOOK.md`, `docs/templates/TASK_CARD.md`, `docs/templates/TASK_BOARD.md`, `docs/implementation/OWNERSHIP.md`, reusable modules/contracts, and `.github/workflows/check.yml`. It requires **Node >= 22.23.0** and already runs `npm run check`, `npm test`, `npm run build`, `npm run test:browser` and `npm run eval`.

**Do not replace the kit's task discipline or rewrite its project generator.** Extend its existing ownership, task, API-contract and handoff conventions. Add a **plan-first, opt-in** orchestration module; do not install background services or paid providers in the minimal starter. Suggested new paths:

```
tools/agents/                  # CLI, coordinator, GitHub, event bus, scheduler, workers
packages/orchestration/        # optional typed state/actions, if worthwhile
tests/orchestration/           # mocked Codex/GitHub, state, security, timing
.codex/agents/orchestrator.toml # customizable Astra role (provided separately)
docs/guides/ORCHESTRATION.md    # setup, chat UX, troubleshooting, recovery
```

The **lead computer** should be able to serve both orchestrator and worker A using _distinct processes and worktrees_. Worker B and worker C operate on their own computers, their own ChatGPT/Codex accounts and their own GitHub identities. Workers do not need to reach one another directly.

# 3. Required live experience

```
                         YOU
             one familiar, live Codex chat
         (streaming, interruptible, resumable)
                          |
                          v
          ASTRA LEAD / CONVERSATIONAL ORCHESTRATOR
   clarify -> tradeoffs -> task DAG -> approval -> dispatch
        ^                 |              ^
        |         typed coordinator        |
  progress + blockers    service         |
        |                 |                |
        +---------- GitHub task queue -----+
                          |
               +----------+----------+
               |          |          |
          COMPUTER A  COMPUTER B  COMPUTER C
          worker A    worker B    worker C
          Astra       Astra       Astra
          optional <=2 local native subagents per worker
               |          |          |
          tests +    tests +    tests +
          commit     commit     commit     <-- deterministic programs
               |          |          |
                +--- branches / PRs ---+
                          |
                CI / reviews / merge gate
                          |
             working deployed judge demo
```

**Conversation and status are separate concerns.** The chat layer interprets and responds; a deterministic event service collects real task, process, test and GitHub data, so the interface remains responsive while workers run. The UI must not claim the lead is actively processing when the chat process is offline or blocked on human input.

## Exact progress reporting behavior

The implementation must meet this **observable contract**:

- **Immediately on real events**: task dispatched/started, implementation checkpoint, test pass/fail, PR opened, CI change, assignment/reassignment, worker loss/reconnect, contract conflict, approval requested, merge/deploy confirmed. Include worker/task ID and evidence link/command outcome.
- **Every 5 minutes while work is active**, even when no milestone changes: show a succinct snapshot covering current objective, each worker's last verified stage, active/blocked/waiting tasks, elapsed time, next expected checkpoint and remaining time to deadline. Build this snapshot _without a fresh LLM call_ whenever possible. Never invent percentages or ETAs.
- **Heartbeat every ~60 seconds** via lightweight worker metadata. Heartbeat means _process reachable_, not code progress. If the worker is alive but quiet, say so; do not fabricate activity.
- **Actionable blocker immediately** after a definitive permission/architecture/secret/deployment dependency, or after **at most two bounded recoveries** of a transient error. Present: what failed, attempted fixes, exact decision or information needed, recommendation, options, deadline impact, and which independent work continues.
- **Potential stall**: classify sustained absence of task/log/heartbeat activity separately from a normal long-running command; warn and run safe diagnostics. Do not automatically create a second concurrent writer of the same scope.
- **Deadline notices** at 12h, 6h, 3h and 1h remaining, plus milestone misses; show recommended cuts and protect final testing/demo time. Adapt to an entered actual deadline, rather than assuming it starts when the chat opens.
- **On demand**: the user can ask "What are all three agents doing?", "What was tested?", "What is blocked?", "Why isn't B finished?", "What changed in the last 20 minutes?" and receive evidence-based answers.
- **After restart**: restore conversation, event sequence and open blocker queue; do not repeat resolved requests or lose pending approvals. Clearly label replayed vs new events.

**Display guidance:** Keep the chat readable like ordinary Codex: streamed reasoning-free user-facing explanations; live tool/worker activity panel or compact annotated terminal lines; pinned outstanding decisions; details/logs on demand. Avoid dumping every command line or a wall of status messages into the conversation. Actual verification output stays accessible.

### Example of an active session

```text
YOU> Build a source-backed scientific research MVP. We have 24 hours.
ASTRA> The judging demo should take precedence over feature count.
        Two decisions change the design: PDF input or LaTeX first?
        And are paid APIs permitted by the event?
YOU> PDF first. No paid APIs. Keep it demo-ready.
ASTRA> Plan: (A) upload/dashboard, (B) text extraction/API,
        (C) claim verification/evaluation; one shared response schema.
        MVP milestone: deployed input -> source-backed report.
        Approval needed to dispatch three tasks. [Approve / Revise]
YOU> Approve.
SYSTEM> A/UX-01 started. B/API-01 started. C/CORE-01 started.
SYSTEM> B/API-01 targeted tests passed (13/13); PR #8 opened.
STATUS> 18h 40m left. A implementing upload view; B awaiting CI;
        C fixing false-positive evaluation fixture. No blockers.
BLOCKED> C/CORE-01 requires a sample PDF with redistribution rights.
         Recommendation: use provided authored fixture; meanwhile C
         continues local logic tests. [Approve fixture / Supply file]
YOU> Use authored fixture. Cut any noncritical export work.
ASTRA> Approved. Export tasks removed from critical path; other
        workers continue. Next milestone is the deployed report flow.
```

Do not generate a freeform "progress" message that invents worker work: all status statements must derive from process events or GitHub artifacts.

# 4. Master implementation prompt - paste into Codex

> The block below is the **authoritative build specification**. It incorporates the supplied orchestrator concept but upgrades it from a passive planning subagent to a working, conversational, 24-hour **root coordinator** with distributed agents and deterministic controls.

## BEGIN IMPLEMENTATION PROMPT

**You are implementing the optional Astra distributed-orchestration feature inside `oliverchennn/hackathon-kit`. You are not merely writing a custom prompt. Deliver running code, tests, docs and a three-computer runbook.**

### Mission and environment

Three human teammates have three computers, each with an independent ChatGPT-authenticated Codex CLI and GitHub identity. They want one single, ongoing, _Codex-like_ conversation with a lead **GPT-6 Astra** orchestrator, which clarifies requirements, makes a deadline-aware plan, dispatches parallel feature work to all three machines, coordinates worker-local subagents, and turns verified changes into PRs. The orchestrator must **actively inform humans what is happening, escalate genuine blockers, and accept new instructions mid-run without corrupting in-progress work**. Optimize for an impressive, actually working MVP at a 24-hour hackathon.

**Model:** `gpt-6-astra`. Lead reasoning: `high` for initial architecture, task splitting and hard replans; ordinary worker task reasoning: `medium`; elevate complex tasks to `high`. All model use is local ChatGPT/Codex subscription authentication (unless the operator explicitly authorizes a different provider). The exact model must be validated by a successful local trial turn on each machine; do not silently fall back to another model or account.

**First:** inspect `AGENTS.md`, project state/diff, `README.md`, `package.json`, `tools/kit.ts`, `tools/project.ts`, contracts, task/ownership templates, `docs/playbooks/COLLABORATION.md`, and `.github/workflows/check.yml`. Follow repository rules. Preserve current functionality, uncommitted human changes and modules. Make this feature opt-in and plan-first for generated/adopted projects.

### A. Lead orchestration persona - behavior requirements

Adapt the provided named-orchestrator prompt into a **top-level** session role with these principles:

1. **Analyze** the user's real objective, demo value, deadline, existing code and constraints. Ask _at most a few focused clarifying questions_ only when answers materially change architecture, high-risk actions or success criteria. Otherwise state assumptions and proceed.
2. **Plan before dispatch:** return a short outcome-focused architecture, the critical judge demo path, shared contracts/fixtures, task DAG, estimated relative workload, ownership, priority, and the work that can safely run in parallel. Obtain human authorization to dispatch a newly proposed plan. Once approved, execute autonomously within its permissions.
3. **Delegate intelligently:** select workers according to actual capability, task dependency and file ownership, not hardcoded frontend/backend labels. Give each clear acceptance tests, allowed paths, non-goals, stable API interfaces and context. Replenish their ready queues; keep critical-path work moving.
4. **Maintain context:** store decisions and the current contract in one authoritative place. Preserve user instructions across the conversation, restarts and dispatch cycles. Do not make agents reconstruct entire project history from long chat transcripts.
5. **Stay conversational:** respond to normal text questions at any time. Users can ask for progress or explain design ideas, change priorities, pause a feature, cut scope, revisit an assumption, or request a new feature. Stage edits to future tasks; safely interrupt or cancel an active task only when needed. Never silently overwrite active writers.
6. **Report truthfully:** immediate significant events, regular 5-minute statuses, task-specific evidence and linkable PR/check status. Never claim success from a model's assertion alone. Clearly separate planned, coding, local-tested, PR-open, CI-verified, merged and deployed.
7. **Request human help when really blocked:** identify the exact missing decision, permission, credential configuration, breaking change, or repeated failure. Offer a recommended next action and at most 2-3 options. Continue unrelated work. Persist outstanding questions until answered; do not repeatedly pester or claim an offline user was notified.
8. **Optimize the clock:** prioritize one working end-to-end demo path, integrate continually, avoid ornamental extra features, prefer reuse and existing modules, cut weak scope early, freeze features with adequate time to verify and rehearse. Do not maximize agent count, number of tasks, or complexity.
9. **Protect quality:** verify interfaces, fixtures and actual integration. Delegate bounded review or investigations where helpful. Preserve the existing kit's code standards, source provenance and event-specific prebuilt-code disclosure obligations.
10. **Finish clearly:** explain what's working, what was tested, open defects, remaining hours, demo steps and the human decisions still required.

**Important:** The original sample prompt's rule "ask the parent to spawn an agent" applies only when this role is being _spawned as a subagent_. Here, the principal orchestrator is the **root lead conversation** and owns coordination through explicit, validated coordinator tools. Do not have the lead recursively spawn a second orchestrator.

### B. App-server conversation and responsive UX

Implement `npm run agents -- chat` with official **Codex app-server** as the preferred engine, using a retained thread/turn lifecycle, streamed assistant content, approval handling, cancellation, safe interruption, resume after restart and local ChatGPT CLI authentication. If a specific app-server feature cannot be made to work, use the official SDK with a documented feature-equivalent test, not ad-hoc shell transcript scraping. Do not implement unofficial authentication token-sharing.

The chat must **not block on slow worker jobs or GitHub polling**. Deterministic coordinator events should appear in a compact live activity pane/line while the user can keep typing. Use a reliable queue for user input, action requests and worker notifications; when a model turn cannot accept an interruption immediately, acknowledge safely and apply at the next valid boundary. Expose `status`, `timeline`, `blockers`, `pause`, `resume`, `cancel`, `approve`, `reject`, `replan`, and `help` affordances. Do not fabricate mid-turn steering capability if the chosen protocol cannot provide it.

Save thread IDs, coordinator run IDs, plan/approval versions and minimal event cursors locally in an ignored state directory. Keep team-wide decisions and tasks in the project issue/contract records. Protect credentials and private transcripts. Explicitly report whether messages are posted in chat, queued for reconnection, or only logged locally.

### C. Deterministic coordinator + GitHub state machine

Use GitHub Issues as the distributed task queue and PRs for code. Add an explicit single coordinator writer; poll GitHub with sane rate-limits/backoff and persist task/worker event journal. Worker assignments must be idempotent and authenticated. GitHub labels/comments **alone are not atomic locks**: assign only from the coordinator with versioned task records, unique run IDs, lease/heartbeat semantics, branch isolation and confirm-before-reassignment logic. Reconcile after crash, timeout, internet failure, duplicate events or human edits.

Task records must include task ID, project/run ID, assigned worker, ordered dependencies, base SHA, exclusive allowed writes, reserved paths, acceptance checks, expected artifacts, timestamps, retry budget, blocker history, exact state, branch/PR and evidence links. Use a validated state transition DAG (`Planned`, `Ready`, `Assigned`, `Running`, `Review`, `Queued`, `Merged`, `Verified`, plus `Blocked`, `Paused`, `Failed`, `Cancelled`). Be explicit whether `Verified` refers to local, CI or integrated result.

Preserve shared contract schema/fixtures; appoint the coordinator or human integration steward as owner of package manifests, lockfiles, migrations, shared contracts and deployment config. Do not dispatch overlapping file write scopes. Never execute GitHub Issue comments as raw shell instructions; accept task creation/mutations only from allowlisted authorized actors and schema-valid, policy-authorized commands. Reconcile branch/PR contents against task scope.

### D. Three independently authenticated worker runtimes

Implement `npm run agents -- worker --name agent-a` (and B/C) with real local `codex exec` support, model/effort selection, bounded task/job limits, useful streaming progress metadata, and locally authenticated `gh`. No shared ChatGPT sessions, tokens, or API keys. Each worker:

1. Fetches only its assigned, trusted tasks and validates scope/dependencies/lease.
2. Creates a dedicated worktree and branch for each active task; never writes to another worker's checkout.
3. Runs Astra Codex on a bounded objective with repository instructions, contracts, staged artifacts and an explicit context budget.
4. Allows up to **two** _local native_ Codex subagents only if work splits meaningfully, with independent file paths or read-only tasks. **No grandchildren**. Check actual availability; if not available, run the parent worker alone and disclose the limitation.
5. Reports actual progress checkpoints (not invented percentages), timeout/stall signals, and the exact error when blocked.
6. Runs deterministic local checks, validates changed-file scope and secrets, creates scoped Git commits and pushes, and opens a PR via ordinary code. It must not delegate `git add`, `git commit`, `git push`, formatting or repeated simple tests to expensive LLM agents.
7. Records actual checks and CI status, never claiming a worker has deployed/merged unless confirmed externally.
8. Releases leases on success/failure, supports retry/recovery and restores work safely after restart.

Local subagent specialties include `explorer` (read-only investigation), `implementer` (isolated component), `tester` (test design, not merely invoking an existing test command), `reviewer` (read-only code review), `debugger` (independent hypothesis) and domain specialists (frontend, backend, AI, data). **Select based on the problem rather than spawning all roles by default.** Subagent outputs must be scoped findings/patches plus evidence, aggregated by the root worker. Do not have several children write the same directory or coordinate independently with other computers.

**Worker budget defaults:** one worker root per computer, `max_children=2`, no recursive spawning, no simultaneous conflicting writers, no more than one active code-writing task per worker until tests demonstrate safe isolation. Do not force children for tasks shorter than a few minutes. Allow explicit disable/override, and show each account's observed quota failures rather than assuming unlimited Astra usage.

### E. Automated checks and Git mechanics (zero extra AI calls for routine actions)

Implement deterministic scripts for checkout/worktree, dependency installs (only when needed), lint/format, targeted tests, typecheck/build, secret/path/diff validation, commit, push, draft PR/open PR and CI polling. Use platform-safe child process APIs; do not rely on interpolated shell strings or Unix-only tools. Store test stdout/stderr, elapsed time, exit code and changed files in bounded logs. Stage only task-allowed paths. **Do not commit or push secrets, unrelated files or failed/out-of-scope changes.** Preserve the user's work.

Testing policy for speed: run fast targeted checks after a material implementation increment; run broader tests at PR boundary; rely on CI for full integration checks; rerun failed or affected checks after fixes. Do not run an enormous test suite after every edit. Allow a limited auto-repair loop when a check fails; escalate after bounded attempts. These scripts are allowed to commit only **inside explicitly authorized task branches**, never push directly to `main`. Human approval is still required for merge, production deployment, publishing and external communication.

### F. 24-hour critical-path controller

Require an event deadline in local timezone and optionally a judging/demo deadline and a submission deadline. Compute remaining time from clock, not number of prompts. Use these default checkpoints, adjustable for venue/event rules:

| Time elapsed | Goal                                                                                    |
| :----------- | :-------------------------------------------------------------------------------------- |
| 0-45 min     | Decide killer judge demo, MVP definition, contracts and tasks. Deploy a skeleton.       |
| 45 min-3 h   | Show a real end-to-end input to meaningful real result; first integrated PRs.           |
| 3-10 h       | Implement differentiating feature and evidence, maintain working deployed path.         |
| 10-17 h      | Evaluate, fix bottlenecks, improve UX, add only high-value supporting features.         |
| 17-21 h      | Integration, edge cases, stable deployment, fallback and polish.                        |
| Last 3 h     | **Freeze new features**, rehearse, prepare pitch/screenshots/backup, verify submission. |

This is a planning baseline, not fabricated actual estimates. Track critical-path tasks and demo readiness, not just completion counts. Prefer independently deliverable 15-45-minute tasks where useful. Re-evaluate task ordering after blocked dependencies. At 6h/3h/1h remaining propose concrete scope cuts and escalate risks; do not silently cancel major user-promised features unless preauthorized. Preserve the ability to switch to a manual mode if the coordinator itself breaks.

### G. Updates, blocker protocol and human approval

Make progress reporting a **tested product feature**:

- Emit a compact event immediately on dispatch/start/test outcome/PR/CI/merge/failure/dependency release/worker disconnect.
- Emit a deterministic **5-minute status** during active work with worker snapshots, concrete last evidence, blockers, outstanding questions and time remaining. Never use a new LLM turn just to say "still working".
- Keep lightweight **60-second heartbeats** that are not misrepresented as code progress.
- Surface genuine blockers immediately (not after waiting for the next interval); include one action request with exact alternatives, recommendation and consequences. Deduplicate repeated errors/alerts.
- Persist an inbox of pending decisions; reconnecting users see the latest state and unanswered questions.
- If the human is unavailable, continue other scoped tasks, obey existing policy and stop at the blocked gate.
- If work is paused/replanned, acknowledge what was cancelled versus still running, then safely reconcile. Never report that a request took effect before it did.
- Provide simple natural-language chat queries, a concise event timeline, and an option to inspect full worker logs.

**Example status payload** (schema can differ but information must be equivalent):

```json
{
  "runId": "RUN-2026-01",
  "remainingMinutes": 820,
  "demoStatus": "deployed skeleton; real pipeline pending",
  "workers": [
    {
      "id": "agent-a",
      "task": "UX-02",
      "state": "Running",
      "lastVerified": "UI build passed",
      "lastEventAt": "..."
    },
    {
      "id": "agent-b",
      "task": "API-01",
      "state": "Review",
      "lastVerified": "PR #8; CI pending",
      "lastEventAt": "..."
    },
    {
      "id": "agent-c",
      "task": "CORE-03",
      "state": "Blocked",
      "lastVerified": "fixture validation failed",
      "lastEventAt": "..."
    }
  ],
  "blockers": [
    {
      "task": "CORE-03",
      "question": "Use authored fixture?",
      "recommended": "approve",
      "requiresHuman": true
    }
  ],
  "nextCheckpoint": "integrated report flow"
}
```

### H. Mandatory permissions, reliability and event integrity

Respect `AGENTS.md`, actual process sandbox, local account authorization, GitHub scopes and hackathon rules. The root chat has no license to override worker permissions. Stage/writes/commands restricted by task policy. Protect `.env*`, `~/.codex`, GitHub auth stores and other users' checkouts. Never expose an unauthenticated network command interface or tunnel sensitive tokens. No unauthorized inference API spending; no auto-merge/deploy; no silent package registry publishing, external email, or repo publication. Preserve source provenance and pre-existing code history; do not misrepresent reused work as created during the event.

Allow a documented emergency **manual fallback**: stop coordinator, leave existing task branches and PRs intact, human assigns files/branches and continues coding. No worker should be held hostage by orchestration infrastructure failure during a hackathon.

### I. CLI, project export, tests and acceptance

Implement and document commands with behavior equivalent to:

```bash
npm run agents -- doctor                         # checks CLI version, auth, model trial, gh, repo, permissions
npm run agents -- init --repo OWNER/PROJECT --workers agent-a,agent-b,agent-c
npm run agents -- chat                           # live lead conversation + activity + decisions
npm run agents -- worker --name agent-a           # separate instance on each computer
npm run agents -- status
npm run agents -- timeline
npm run agents -- blockers
npm run agents -- pause
npm run agents -- resume
npm run agents -- simulate --offline              # no real provider calls
npm run kit -- agents add --target /path/to/app    # plan only
npm run kit -- agents add --target /path/to/app --apply
```

Provide useful `--help`, on-screen errors, Windows PowerShell and Unix setup instructions, and **explicit startup/run controls**. `init` makes version-controlled nonsecret configuration; no worker credentials belong in git. Do not change existing kit commands except optional safe extension. The exact interface may differ only with a documented reason and matching runbook.

**Test automatically with mocked Codex/GitHub**: event ordering and 5-minute reports; immediate blocker escalation; clarification and dispatch approval gate; conversation persistence/restart; task DAG; 3-worker assignment; subagent caps/unavailable fallback; `gpt-6-astra` selection and missing-entitlement error; scope ownership; trusted issue authors; GitHub race/disconnect/retry; no false progress; auto-commits only on scoped task branches after checks; no secret commits; timed phase/deadline transitions; safe pause/replan; offline/manual recovery. Run `npm run check`, `npm test`, `npm run build`, and relevant browser/CI checks without real paid API calls. Then provide an operator-approved **real three-computer smoke test**; do not claim that is tested until actually performed.

Implement in working increments: (1) typed coordinator/mocks + CLI + check/commit scripts; (2) persistent Astra chat/streaming/status/blocker UI; (3) real workers/GitHub/subagents/PRs; (4) resilience, deadline engine, full docs/testing. Run checks after increments. Keep implementation minimal; no speculative SaaS dashboard or always-on cloud hosting in V1.

**Deliver:** implementation PR with source, native Astra role file, updated README, `docs/guides/ORCHESTRATION.md`, tests and actual results, full 3-computer setup, acceptance checklist, open limitations, and a safe rollback. If an external permission or model entitlement blocks real testing, identify the exact operator action and continue mock-covered independent work. **Do not stop at a plan.**

## END IMPLEMENTATION PROMPT

# 5. Companion custom-agent profile

An `orchestrator.toml` file accompanies this guide. It follows the user's supplied pattern (`name`, `description`, `model`, `model_reasoning_effort`, `nickname_candidates`, `developer_instructions`) but is customized for **root-lead conversation, progress reporting, blocker escalations, Astra and 24-hour deadlines**. Copy it into `.codex/agents/orchestrator.toml` to make the _named subagent_ available in supporting Codex sessions.

**Crucial architecture distinction:** A custom subagent file alone cannot run three remote computers, create a persistent chat UI, or implement the GitHub coordinator. The _main conversation_ should load the same role instructions into the **top-level app-server thread**. The named subagent is optional for compatibility/manual workflows; **do not recursively spawn orchestrators**. Codex parent sandbox/approval controls take precedence; a custom role file is not a security boundary.

```toml
name = "orchestrator"
description = "Conversational Astra lead for time-critical, distributed multi-agent hackathon projects."
model = "gpt-6-astra"
model_reasoning_effort = "high"
nickname_candidates = ["Orchestrator"]
# Full role instructions are supplied in the companion orchestrator.toml.
```

For real operations, do not overwrite everyone's global `~/.codex/config.toml`; doctor should validate the current CLI's actual native-subagent settings and report the required manual/optional changes. Start with **2 children per worker maximum**, no grandchildren, regardless of underlying system defaults.

# 6. Three-computer installation, after implementation

**These commands are prospective until Codex has implemented and merged them.** The kit's `kit create` command exists now, but `agents` and `kit agents add` do not yet exist in the source inspected for this guide.

## Step A: prerequisites on every computer

Install Git, GitHub CLI (`gh`), Node.js **22.23.0+**, npm and the latest Codex CLI. On Windows use PowerShell (`winget` if available). macOS Homebrew commands are below. On Linux install using your distro and GitHub CLI's official instructions.

**Windows PowerShell:**

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id OpenJS.NodeJS.LTS -e
# Restart PowerShell when installation finishes.
```

**macOS:**

```bash
brew install git gh node
```

**All computers** (in the native shell):

```bash
npm install -g @openai/codex@latest
node --version
git --version
gh --version
codex --version             # must be >= 0.153.0 for Astra
codex login                 # EACH teammate uses THEIR OWN ChatGPT account
codex login status
gh auth login               # EACH teammate uses THEIR OWN GitHub account
gh auth setup-git
gh auth status
```

Authenticate and **successfully run a tiny test prompt using `gpt-6-astra` on each account**; the orchestrator doctor command must verify actual inference access, not just model metadata. If Astra is unavailable, stop that worker and report a specific access/version issue; do not hide model substitution or log into a teammate's account. Subscription usage is plan-limited, and Codex does not confer unrelated application API credits.

## Step B: implement the add-on once on Computer A

```bash
gh repo clone oliverchennn/hackathon-kit
cd hackathon-kit
npm ci
git switch -c feat/astra-distributed-orchestration
codex -m gpt-6-astra
```

Paste **Section 4** into Codex or supply this guide and request full implementation of Sections 3-7. Open a PR, review actual tests and merge the feature. Make sure the lead role/config is included. Do not claim runtime commands work until they are merged.

## Step C: create a fresh MVP project (Computer A)

From the updated kit root:

```bash
npm run kit -- create ../my-hack-project --starter web
npm run kit -- agents add --target ../my-hack-project --apply
cd ../my-hack-project
npm ci
git init -b main
# If the project already has a Git repo, skip git init.
git add .
git commit -m "Initialize hackathon project"
gh repo create OWNER/my-hack-project --private --source=. --remote=origin --push
```

Invite both teammates to the _new private project repository_ with write permissions. Treat the toolkit repository and the competition project repository as different objects.

**Computer A:**

```bash
npm run agents -- doctor
npm run agents -- init --repo OWNER/my-hack-project --workers agent-a,agent-b,agent-c
git add -A
git commit -m "Configure three-machine orchestration"
git push
```

**Computers B and C:**

```bash
gh repo clone OWNER/my-hack-project
cd my-hack-project
npm ci
npm run agents -- doctor
```

## Step D: start the conversational lead and three workers

| Computer | Terminal | Command                                   |
| :------- | :------- | :---------------------------------------- |
| A        | 1        | `npm run agents -- chat`                  |
| A        | 2        | `npm run agents -- worker --name agent-a` |
| B        | 1        | `npm run agents -- worker --name agent-b` |
| C        | 1        | `npm run agents -- worker --name agent-c` |

The lead chat/coordinator must be the **only active assignment authority**. After restart, resume state rather than initializing an unrelated new run. Start by entering your deadline and a project idea in ordinary language, not a giant mandatory command-line prompt. The lead should ask consequential questions, show the plan and wait for explicit dispatch authorization, then provide continuous verified status and work with all three agents.

**First live test prompt:** "We have 24 hours. Build a tiny app with a landing page, a health API, and a testable validation function. Ask necessary clarifying questions, propose a three-lane plan and do not dispatch until I approve it. Keep giving accurate updates and request help if blocked."

# 7. Acceptance gate - do not rely on mocks alone

1. Three separate GitHub identities and three separate ChatGPT/Codex accounts all complete a verified Astra turn.
2. Multi-turn lead chat streams text, remembers constraints across restart, asks a relevant question, and **does not dispatch before approval**.
3. User approves a plan; precisely three independent bounded tasks are assigned to unique workers without overlapping file ownership.
4. Each worker runs on its own computer and produces scoped code/verification evidence, deterministic commits and a PR.
5. At least one worker uses a native local subagent for independent implementation or read-only review, with no accidental shared file writes; another can run in no-subagent fallback.
6. Targeted tests, broad PR checks and CI results are reflected accurately, with distinct statuses (not just "done").
7. Every major event arrives promptly; automatic five-minute updates occur while active even if no event arrives; heartbeat is not represented as actual feature progress.
8. A simulated hard blocker immediately asks for a decision with a recommendation; unrelated workers keep running. A disconnected lead queues the question for return.
9. Replanning while work is active safely applies scope changes, never silently overwriting an active branch or unresolved approval.
10. A worker crash or dropped connection neither loses work nor duplicates an active writer; recovered tasks retain real state.
11. Clock/deadline and last-3-hour freeze rules are tested; the lead recommends cutting a low-priority feature if the demo path slips.
12. Existing hackathon-kit functions still pass normal checks without running orchestrator processes or paying for model calls.
13. All merges, deployments, publishing and consequential external actions remain behind the configured human approval gate.
14. Manual fallback works: coordinator can stop safely and humans can use existing PRs/branches and task docs.

# 8. Readiness and caveats

The **companion profile and this PDF are specifications**, not a deployed orchestration implementation. The repository was inspected but not edited by this document. The local scripts must be written, run and reviewed before the advertised commands are available. A custom TOML subagent is not a cross-computer orchestrator. The real lead must be the root Codex chat, while deterministic coordinator code performs actions and surfaces evidence.

Performance tradeoff: **Astra on three worker accounts plus local children may exhaust usage faster**. Start with three parents, allow at most two children each, and only spawn them when independent reasoning is likely to reduce the critical path. Do not burn time or allowance on AI agents that merely run tests, format files or commit code.

Respect all event-specific rules on preparatory code, AI use, attribution and source provenance. Do not rewrite history to misrepresent the timing or origin of reused material.

# 9. Technical references (verified 24 October 2026)

- OpenAI, _ChatGPT Work and Codex_ - Astra requires Codex CLI **0.153.0+**; availability and plan usage: <https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex>.
- OpenAI Codex source model catalog - `gpt-6-astra` and reasoning levels: <https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json>.
- OpenAI, _Codex as a platform_ - SDK, app-server, thread/turn and approval event patterns: <https://developers.openai.com/blog/codex-as-a-platform>.
- OpenAI/ChatGPT, _Subagents_ - local custom TOML agents, inherited permissions: <https://learn.chatgpt.com/docs/agent-configuration/subagents>.
- OpenAI, _GPT-6 Astra model_ - correct model ID and reasoning-effort support: <https://developers.openai.com/api/docs/models/gpt-6-astra>.
- GitHub CLI, _gh auth login_ - local credential setup: <https://cli.github.com/manual/gh_auth_login>.
- Repo (private): `AGENTS.md`, `tools/kit.ts`, `tools/project.ts`, `docs/playbooks/COLLABORATION.md`, `docs/templates/TASK_CARD.md`, `.github/workflows/check.yml` (inspected and left unchanged).

---

**Explicit handoff:** Implement, test, review and merge the optional capability once; then run the three-computer installation; only declare the system ready after actual authenticated cross-machine testing. Focus the system on a strong, working 24-hour hackathon demo, not elaborate infrastructure for its own sake.
