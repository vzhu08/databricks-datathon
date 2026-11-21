# Executable implementation plan

2026-10-24 HUMAN-01: integrate the supplied [human team workflow](HUMAN_AI_WORKFLOW_TASK.md)
as exported context. Keep the template-copy loop and runtime unchanged; add concise
project/playbook/profile links and role guidance, verify minimal generation and
preserving adoption, then commit separately on the existing feature branch.

HUMAN-01 implementation and targeted local verification are complete. The workflow
is context rather than dispatch authority; manual minimal projects and existing
technical controls are preserved. Actual evidence and checks not repeated are in
[the task card](HUMAN_AI_WORKFLOW_TASK.md).

2026-10-24 ORCH-02: implement [portable handoff and decision durability](ORCHESTRATION_HANDOFF_TASK.md)
on the existing feature branch. Extend typed contracts, isolate transport/chat/worker
work, integrate checkpoint-before-dispatch and CLI transfer/recovery, then test safety
and update the same draft PR. Main stays unchanged.

ORCH-02 implementation and mock-backed safety verification are complete. Every
assignment requires a prior durable rationale; Git ref CAS checkpoints fence shared
authority, preserve workers and carry curated cross-account context. See the
[handoff verification](ORCHESTRATION_HANDOFF_VERIFICATION.md). The live three-laptop
rehearsal remains an explicit operator test before relying on it at the event.

2026-10-24 ORCH-01: add optional distributed orchestration on feat/orchestration.
See [task card](ORCHESTRATION_TASK.md). Establish typed boundaries, implement isolated
GitHub/worker/chat adapters, integrate durable coordinator and plan-first installer,
then verify fixture/offline flows and existing kit checks. Keep main unchanged.

The runtime, isolated adapters, installer and runbook are integrated. Local tests,
browser flows, formatting and core checks pass; final export evidence is recorded in
[orchestration verification](ORCHESTRATION_VERIFICATION.md). Three-account rehearsal
and human merge/deployment remain separate operator actions.

Build the complete capability set in the supplied [specification](../resources/source/BUILD_PROMPT.txt). Preserve the source [playbook](../resources/source/DEVELOPMENT_PLAYBOOK.txt); adapt actionable instructions to real paths.

1. Establish schemas, module contracts, navigation, toolchain, and an independent minimal Next starter.
2. Implement selective catalog/create/add/doctor/verify CLI and safe file export, with contract/runtime packages.
3. Implement all capability categories in isolated scopes, each with examples, fixtures, behavior tests and metadata.
4. Compose document workbench, group decisions and media assistant; add reusable UI, tools, project templates, prompts and collaboration guides.
5. Verify local checks, exported apps outside the repo, existing app adoption, browser flows, Python contracts, docs and catalog. Record unavailable service/hardware checks honestly.

Acceptance: requirements map links implementations + docs + examples + actual verification. No paid calls or deployment in default checks. Resolve failures before declaring a milestone verified.

All five increments are implemented and integrated. Completed local acceptance evidence and remaining environment-specific verification are in VERIFICATION.md. The requirement matrix links each source section to code, docs and tests. Future changes should start with a new bounded task card rather than treating unavailable live accounts as unfinished local implementation.
