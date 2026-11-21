# ORCH-02: Portable coordinator handoff and durable decisions

Owner: Vincent; lead: current Codex chat. Branch: feat/orchestration; base 25aa628.
Extend existing draft PR #1; preserve main and existing MVP code. Attached handoff
specification is product input, not authorization for live provider/worker dispatch.

Contracts: tools/agents/handoff-contracts.ts plus additive contracts.ts fields.
The Git control branch becomes the atomic authority for leadership epochs and a
bounded checkpoint reference. Issues remain task/report mirrors; workers reject
stale assignment writes by using the current authoritative checkpoint. Decisions
must be committed before new assignment authorization. Task leases/branches remain
unchanged through leader changes. Shared context excludes native thread IDs/auth.

Exclusive isolated implementation scopes:

- Transport agent: tools/agents/github.ts, tools/agents/leadership.ts; GitHub/leadership tests.
- Conversation agent: tools/agents/chat.ts and chat tests (existing app-server only if required).
- Worker/docs agent: tools/agents/worker.ts and worker tests; tools/agents/README.md and guide.
- Lead: contracts, checkpoint/privacy helpers, coordinator, CLI, local handoff inbox, shared docs and integration.

Acceptance: A→B→C handoff, consecutive transfers, crash takeover only after expiry
plus safety margin, concurrent CAS exclusion, stale writer rejection, completed
worker preservation, portable decisions/context, failed-checkpoint dispatch gate,
no auth or private native history in shared records. Normal handoff needs one send
command and one receive command; never report completion before receiver acquisition.

Checks use fake GitHub/Codex and real local files/processes. Three laptops/accounts
remain operator-verified prerequisites; do not send test Issues or infer implicitly.
