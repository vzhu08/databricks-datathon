# Ownership and integration record

2026-10-24 HUMAN-01: the lead owns the documentation, two generator strings,
profile guidance, targeted regression and implementation records listed in
[the task card](HUMAN_AI_WORKFLOW_TASK.md). The delegated reviewer has no writer
scope. Existing orchestration writers are finished; no teammate branch is changed.

HUMAN-01 implementation and targeted checks are complete. The lead owns the scoped
commit and draft PR update; no delegated writer is active.

ORCH-02 is implemented on feat/orchestration. The lead owns integration; isolated writer
scopes are in [the handoff task](ORCHESTRATION_HANDOFF_TASK.md). Earlier ORCH-01 writers
are finished; the new claims supersede their old snapshots for this task only.

ORCH-02 transport, chat, worker/docs and safety-test scopes are integrated; all
delegated writers have finished. Final evidence and the implementation are pushed
to draft PR #1. Main remains unchanged; no live task dispatch, merge or deployment occurred.

2026-10-24: ORCH-01 is active on feat/orchestration. The lead owns integration and
shared files. Exclusive isolated scopes are listed in [the task card](ORCHESTRATION_TASK.md).

The three delegated scopes are integrated and their writers have finished. The lead
owns final checks, branch sharing and the handoff. No merge/deployment is authorized.

The lead checkout is the authority for this build. The operator owns product/release decisions; the lead is responsible for integration and evidence. All delegated writing used separate branches/checkouts and exclusive scopes. Module changes and targeted repairs are integrated; no writers remain active.

| Scope                                                                              | Writer           | State                                                   |
| ---------------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------- |
| Root/config/locks/catalog/contracts/runtime/CLI/web/UI/compositions/final evidence | Lead             | Integrated; locally verified                            |
| Documents/retrieval/extraction/research/exports and Python starter                 | documents agent  | Integrated; Python bridge added by lead                 |
| AI/Supabase/realtime/jobs/integrations                                             | services agent   | Integrated; optional Supabase UI/local setup integrated |
| Recommendations/voice/media/maps/analytics                                         | experience agent | Integrated                                              |
| Developer-tool corrections and optional AI widget/route                            | experience agent | Integrated by lead                                      |
| Reusable prompts and detailed requirements mapping                                 | documents agent  | Integrated                                              |

Shared files had one integration steward. Agents returned scoped commits with tests, limitations and next steps. Code review findings on cancellation, citation truth, stale plans, credential-file export, symlink destinations, port defaults and actual reset behavior were repaired before handoff. Live accounts, production hosting and public release remain separate operator decisions.
