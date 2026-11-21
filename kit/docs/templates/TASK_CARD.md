# Task card

Task ID/title: [bounded outcome]. Human owner: [name]. Tool/session: [identifier]. Branch/check-out: [branch and absolute path]. Base SHA: [actual SHA]. Dependencies: [IDs or none]. Allowed files: [narrow paths/globs]. Reserved files: [shared files and others' claims]. Read first: [AGENTS, schema, fixture, relevant source].

Outcome: [observable behavior and why it matters to demo]. Acceptance: [normal input/result, meaningful failure/empty case, latency/size/permission constraints]. Checks: [exact commands and required manual flow]. Non-goals: [no unrelated refactor/provider changes]. Handoff: [commit, files, actual evidence, limits]. Integration authority: [who may merge/deploy; no implied authority].

Example CORE-03: implement source-backed extraction under modules/extraction/src and tests against agreed document/citation fixtures. It may not change routes, shared contracts, dependencies or env files. Invalid output must fail visibly and logs must not contain uploads/secrets. Ask the steward for a concrete shared change; continue independent work in scope.
