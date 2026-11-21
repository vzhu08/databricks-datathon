# Authoritative task board

Board location/maintainer: [one live source]. Branch copies are snapshots, not distributed locks. States: Planned, Ready, Running, Review, Queued, Merged, Verified, Blocked.

| ID    | Outcome                   | Human   | Session        | Branch/base SHA    | Claimed paths      | Dependencies            | Acceptance/checks                      | State/result SHA |
| ----- | ------------------------- | ------- | -------------- | ------------------ | ------------------ | ----------------------- | -------------------------------------- | ---------------- |
| UX-01 | Inspect selected evidence | [owner] | [tool/session] | task/ux-01 / [SHA] | app/... named page | stable citation fixture | click source → exact highlighted range | Planned          |

Ready means sufficient stable inputs for independent implementation. Keep one or two Ready tasks ahead of each owner. Record a blocker precisely and switch to independent in-scope work. Release path claims only after handoff/integration. A reviewer who edits becomes a writer and needs a scope.
