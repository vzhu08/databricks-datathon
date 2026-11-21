# Test plan

| Flow/boundary   | Normal fixture      | Failure/empty case   | Command/manual action       | Expected behavior                 | Owner    |
| --------------- | ------------------- | -------------------- | --------------------------- | --------------------------------- | -------- |
| Base transform  | labeled text        | empty/invalid JSON   | npm run check + browser     | normalized response or safe error | Platform |
| Selected module | module fixture path | meaningful edge case | module README command       | observable contract               | Core     |
| Judge path      | exact demo input    | unavailable service  | fresh browser on deployment | useful result + honest recovery   | Product  |

Record actual results in ACCEPTANCE.md. Typechecks, build, local contracts, browser/hardware and live services are separate scopes. Default tests use fixtures/local sinks; live tests require test accounts, explicit intent and usage bounds. Do not count skipped prerequisites as passes. Generated/adopted app checks must preserve the original working route.
