# Team message and task board

This board on `origin/main` is authoritative. Oliver's orchestrator maintains the board, contracts, fixtures, and integration queue. The human approved replacing the initial assignments with this evidence-acquisition sprint on November 21, 2026. Read the [plan](PLAN.md), [contract](ACQUISITION_CONTRACT.md), and [kickoffs](../KICKOFF_PROMPTS.md).

## Latest messages

| When (ET) | From | Applies to | Update |
| --- | --- | --- | --- |
| Nov 21 · acquisition takeover | Oliver / orchestrator | Everyone | Old DATA-01, RANK-01, APP-01, and EVAL-01 assignments are superseded. Preserve existing branches. Anyone already working on one must leave a branch/SHA handoff before switching; never reset someone else's checkout. |
| Nov 21 · approved scope | Oliver / orchestrator | A–E | Nationwide identity/location references, Rajasthan trauma evidence, and a small footprint check. Preserve Virtue Foundation rows. This sprint does not assert clinical quality, an authenticity probability, or live availability. |
| Nov 21 · execution | Oliver / orchestrator | A/D | A and D each get one separate Codex chat and isolated clone. Only their listed paths may be edited. No additional writers in their scope. |
| Nov 21 · human roles | Oliver / orchestrator | B/C | B and C are role labels, not inferred GitHub accounts. Claim your task issue with your handle and session before starting. |
| Nov 21 · research depth | Oliver / orchestrator | B | Plan first, then pursue the explicit completion goal in the [B plan](../tasks/ACQ-B01.md). Launch its five scoped research chats in your own account; synthesize and audit their outputs before handoff. |
| Nov 21 · small support task | Oliver / orchestrator | E | Ayuush is Developer E (`ayushrgupta906`). Check eight source links and prepare a short demo reference; no pipeline implementation or additional chats required. |
| Nov 21 · independent start | Oliver / orchestrator | Everyone | Public collection and fixture-based work can start immediately. Missing Marketplace access blocks live checks only. Report fixture/public/live evidence separately. No new recurring timer is required. |

## Active assignments

| ID | Executor | Branch | Exclusive write scope | First action | State |
| --- | --- | --- | --- | --- | --- |
| [ACQ-A01](../tasks/ACQ-A01.md) · [#3](https://github.com/vzhu08/databricks-datathon/issues/3) | Developer A · Codex; Oliver accountable | `codex/acq-a-collectors` | `research/acquisition/`, `tests/research/acquisition/`, `docs/handoffs/ACQ-A01.md` | Read v1 contract; implement OSM/NHP collectors and fixture tests | Ready |
| [ACQ-B01](../tasks/ACQ-B01.md) · [#4](https://github.com/vzhu08/databricks-datathon/issues/4) | Developer B · human lead; unclaimed | `codex/acq-b-trauma-evidence` | `research/trauma/`, `tests/research/trauma/`, `docs/handoffs/ACQ-B01.md` | Produce the planning checkpoint and launch five bounded research chats | Ready |
| [ACQ-C01](../tasks/ACQ-C01.md) · [#5](https://github.com/vzhu08/databricks-datathon/issues/5) | Developer C · human; unclaimed | `codex/acq-c-matching` | `research/matching/`, `research/geography/`, `tests/research/matching/`, `docs/handoffs/ACQ-C01.md` | Implement conservative matching on synthetic cases | Ready |
| [ACQ-D01](../tasks/ACQ-D01.md) · [#6](https://github.com/vzhu08/databricks-datathon/issues/6) | Developer D · Codex; Oliver accountable | `codex/acq-d-databricks` | `databricks/enrichment/`, `tests/databricks/enrichment/`, `docs/handoffs/ACQ-D01.md` | Build contract validation/import staging; inspect authorized workspace if available | Ready |
| [ACQ-E01](../tasks/ACQ-E01.md) · [#7](https://github.com/vzhu08/databricks-datathon/issues/7) | Developer E · Ayuush (`ayushrgupta906`) | `codex/acq-e-source-links` | `docs/source-checks/ACQ-E01.md`, `docs/handoffs/ACQ-E01.md` | Check eight source links and record a short demo reference | Ready |

Detailed task cards include the issue, deliverables, acceptance cases, commands, and handoff requirements. `Ready` means the independent first stage is ready; it does not assert live credentials or upstream data exist.

## Dependencies and integration queue

1. Orchestrator publishes v1 contract and synthetic fixtures. A/B/C/D use that revision. Existing `SEARCH_CONTRACT.md` and search fixtures stay unchanged.
2. A collects national identities; B collects Rajasthan identities and service evidence. C and D develop against fixtures while these run.
3. D supplies the real source schema, preserved base IDs, column mapping, and permitted artifact destinations. No Marketplace rows in Git.
4. C consumes A/B batches and D's mapping, proposes candidates, and records review decisions. B supplies campus/service adjudication, not automatic identity confirmation.
5. D validates and imports five additive tables. Publishing a completed run is gated by integrity checks. Never overwrite the original facilities or change app ranking in this sprint.
6. Orchestrator reviews exact heads, source provenance, scope, and tests; integrates compatible PRs; records local, public-source, and live results separately.

Shared files belong only to the orchestrator: `contracts/`, `docs/implementation/`, `docs/tasks/`, `docs/KICKOFF_PROMPTS.md`, `AGENTS.md`, root setup files. B may delegate only inside B's scope as specified in its task. Developers open PRs and do not merge, deploy, or reassign others.

## Claim and handoff protocol

Claim in your task issue: `task ID | @handle | coding session | branch | first action`. The orchestrator updates board state. Do not claim an already active task from another chat.

At substantive checkpoints post completed work, next action, blocker, artifact location, and exact checks/results classified as fixture, public-source, or live Databricks. No credentials or raw source records in issue bodies.

Review handoff: PR URL, head SHA, changed paths, exact commands/results, snapshot IDs/counts, unresolved cases, contract version, artifact locations, and remaining live dependencies. States are `Ready`, `In progress`, `Review`, `Verified`, `Blocked`. A PR is not verified merely because it exists.

## Superseded work

Initial DATA-01 (Ayush), RANK-01 (Vincent), APP-01 (Andrew), and EVAL-01 (Oliver) remain in Git history. Their existing code and search contract are preserved. They no longer authorize new work under this board; no mapping between those names and B/C is assumed.
