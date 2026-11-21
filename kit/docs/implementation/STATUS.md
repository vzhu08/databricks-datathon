# Current state

2026-10-24 HUMAN-01: the supplied human–AI workflow is integrated as a template
and exported automatically into new projects. Generated agent/quickstart documents
and kickoff/collaboration guides link it. Optional orchestrator instructions ask
for actual human accountability and approval owners independently of worker
accounts; technical controls remain authoritative. Minimal projects need no
orchestration, and later module adoption preserves customized workflow/instructions.

Verification: docs/check passed (116 Markdown files, 699 links), 27 core/generator/
chat tests and 5 preserving-installer tests passed. The real shipped profile loads.
An initial junction fixture failed under the Windows sandbox; the rerun with
junction access passed. See [workflow task and evidence](HUMAN_AI_WORKFLOW_TASK.md)
for changed files and checks not repeated. Prior handoff implementation and its
evidence are pushed to draft PR #1. Main and teammate branches remain unchanged.

2026-10-24 ORCH-02: safe cross-account coordinator handoff is implemented on the
existing `feat/orchestration` branch and draft PR #1. Shared checkpoints include
curated project context, answered questions, pending shared requests, plans, tasks
and explicit decisions with their rationale. No new lease may be authorized until
its dispatch rationale exists in the preceding durable checkpoint. Save failures
pause dispatch; unpublished assignments remain local drafts.

`handoff --to NAME`, `coordinate --resume` and `takeover` use epoch-numbered Git-ref
CAS leadership. Workers keep their task tokens/branches and heartbeat independently
of leader transitions. Native credentials/thread state stay local; incoming accounts
reconstruct context in fresh native threads. Local unshared drafts are backed up
before restore. Main and Oliver's saved MVP are unchanged.

Verification: 275 tests passed, one opt-in service check skipped; core checks,
formatting, base build, eight browser workflows and standalone optional export
passed. Final targeted regressions also passed. The existing Next.js security
advisory remains unchanged. See [handoff verification](ORCHESTRATION_HANDOFF_VERIFICATION.md)
and the [runbook](../guides/ORCHESTRATION.md). Live three-computer/account transfer
is not verified; no inference, remote dispatch, merge or deployment was performed.

2026-10-24 ORCH-01: optional distributed orchestration is implemented on
`feat/orchestration`, based on `8dbca44`. Kit `main` and Oliver's existing MVP are
unchanged. The add-on provides plan approval, GitHub task records and fenced leases,
local ChatGPT-authenticated workers, streaming app-server chat, persistent events,
blockers, deadlines and a preserving existing-project installer. Native worker
children are conservatively disabled. Arbitrary desktop chats are not synchronized.

Local evidence: 226 tests pass (one opt-in Supabase service test skipped), eight
Chromium workflows pass, deterministic evaluation passes, base/showcase builds
pass after the existing Next.js advisory reminder. Standalone add-on adoption,
clean install, local dependencies, help and offline simulation pass.
All five existing standalone recipes and preserving app adoption also pass their
clean install/type/test/build/HTTP checks. See the
[runbook](../guides/ORCHESTRATION.md) and [verification](ORCHESTRATION_VERIFICATION.md)
for exact evidence and remaining live prerequisites. No inference trial, remote
worker dispatch, merge or deployment was performed during implementation.

The pinned Next.js version reports a security advisory and recommends an upgrade;
dependency versions were preserved for this isolated feature. A separate security
upgrade is needed before treating the old web stack as production ready.

2026-10-09. The requested toolkit is implemented and locally verified. All 15 capabilities, both creation/adoption workflows, three integrated compositions, UI gallery, optional AI processing and Supabase sign-in/CRUD examples, Python companion, developer tools, templates, prompts and collaboration guidance are integrated.

Verification: 146 TypeScript tests passed and 1 opt-in Supabase service check skipped; 8 Chromium workflows passed; 5 Python tests passed both in this checkout and an external export. Five external project configurations plus existing-app adoption passed clean install/type/test/build/run. The exported Python UI and optional AI fixture UI also passed actual browser-to-server workflows. See VERIFICATION.md for scope, evidence and unverified prerequisites.

Original code uses MIT after the operator delegated the license decision. The repository is local with no remote or public deployment. No provider charges, account provisioning or messages were sent. Unrelated sibling projects are untouched. No implementation task is awaiting clarification.

Next team action: follow README.md, choose a small recipe, fill the generated project brief/ownership/task board, and rehearse the local workflow. Before using real providers or deployment, configure an isolated test account and run only the corresponding explicit integration checks. Docker/Supabase services, native OCR, physical devices, other operating systems and production hosting remain unverified. Three moderate dependency advisories are documented in THIRD_PARTY_NOTICES.md.
