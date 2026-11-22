# Hosted TomTom quota ledger

The hosted backend uses one managed Unity Catalog Delta table containing one
row for the provider account and product. Use the existing Serverless Starter
Warehouse. Bind the warehouse with **Can use** and the dedicated table with
**Can select and modify** for the app service principal. Verify the principal
also has USE CATALOG and USE SCHEMA. Use the app's injected OAuth credentials
and a server-owned opaque account scope shared by all keys on the allowance.

[Warehouse resource](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/sql-warehouse) ·
[Unity Catalog table resource](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tables)

## Provisioning and cutover

Keep provider traffic disabled while setting up or recovering the ledger.
Stop all previous writers on the same TomTom allowance, including local SQLite
and Explorer use. Reconcile through the last possible attempt. Keep the old
ledger available as evidence. If it has additional usage, active permits, a
cooldown, or reservations, preserve those in the new state and verify the
reconciliation before enabling traffic. SQLite usage can be transferred from
its UTC day counters, reservations from its existing operator run IDs and
balances, and active attempts from its current token IDs. Its seconds-based
timestamps must be converted to integer UTC microseconds. If any historical
rate window is still open, wait until it has elapsed after stopping the old
writers. The five-attempt seed below is valid only for a confirmed Explorer-only
history. A missing runtime table or row requires recovery of reconciled state.

Operator-only DDL for first provisioning. Create the table once in the
approved private schema. No schema-wide write grant is needed.

```sql
CREATE TABLE workspace.datathon_acquisition.tomtom_routing_budget (
  account_scope STRING NOT NULL,
  product STRING NOT NULL,
  revision STRING NOT NULL,
  quota_state STRING NOT NULL
)
USING DELTA
TBLPROPERTIES ('delta.isolationLevel' = 'Serializable');
```

Bind `:account_scope` to the approved nonsecret routing scope. The initial
insert must be executed by a single operator as a separate step.

```sql
INSERT INTO workspace.datathon_acquisition.tomtom_routing_budget
SELECT :account_scope, 'tomtom_maps_v1', replace(uuid(), '-', ''),
  '{"version":1,"allowance":20000,"receipt":"jaipur-explorer-2026-11-22-five-attempts","last_clock":0,"strikes":0,"cooldown":0,"daily":{"2026-11-22":{"routine":5}},"active":{},"completed":[],"runs":{}}';
```

Check for exactly one row for the account and Maps v1 product, a 32-character
lowercase hexadecimal revision, Serializable isolation, and the expected
counters. If the insert acknowledgment is uncertain, inspect before any further
write. The app treats zero, multiple or unrecognized rows as unavailable. Use
one authoritative table for all profiles and replicas. A separate synthetic
scratch table can exercise acceptance and must have its own test scope.

The environment contract with the hosted adapter is
`TOMTOM_DEPLOYMENT_MODE=databricks_delta`,
`TOMTOM_BUDGET_WAREHOUSE_ID` (the warehouse resource key via `valueFrom`),
`TOMTOM_BUDGET_TABLE` (the table's three-part name), and the existing trusted
account, product, verified allowance, profile and budget settings. Confirm
the live gate through the normal app entry after merging the adapter wiring.

## Commit and recovery behavior

Each decision reads one row and uses warehouse UTC time. A mutation replaces
the row's revision and state in the same Delta UPDATE. Concurrent changes
to this single row cannot both commit against the same revision. The client
recomputes its decision from durable state after an acknowledged zero-row
update or a known terminal Delta write conflict, up to three attempts total.
Only a complete successful UPDATE returning one affected row authorizes a
provider send. The SQL transport submits each statement once.

On a missing, canceled or ambiguous write acknowledgment, the caller receives
no permit. A possibly committed charge and active permit are retained. Each
active permit counts against concurrency and rate limits until released.
Completed attempts retain their rate slot from the recorded finish time.
When a known 429 strike and an active permit coexist, additional admission
waits for that permit to settle. Calls never refund on finish, and duplicate
finish cannot count a second strike. The ledger carries no request payloads,
coordinates, key material or route responses.

For lost acknowledgments, pause traffic and inspect the current row and Delta
history. Release a stranded permit with the scoped backend's `finish` only
after verifying the corresponding caller cannot still send and any request
has ended. Reconcile any uncertain 429 before reopening. Keep accounted
charges. Validation reservations use the same atomic ledger through the
scoped backend's `reserve_run` and `release_run` methods. A reservation with
a lost acknowledgment remains held until the operator identifies it and
explicitly releases its unspent balance.

[Delta isolation](https://docs.databricks.com/aws/en/optimizations/isolation/isolation-levels) ·
[Delta conflict conditions](https://docs.databricks.com/aws/en/optimizations/isolation/row-level-concurrency) ·
[Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/execute-statement)

## Pre-rollout verification

A successful attempt requires four SQL statements: a read and an update to
admit, and a read and an update to finish. The adapter also reads usage once
per batch. Conflicts and denied admissions add reads. Each statement waits
up to five seconds at the API, and a cold or busy warehouse can fail
admission. Measure stopped and warm warehouse latency with synthetic
admissions and a fake provider. For a normal search with three eligible
campuses, expect 13 SQL statements before any retries, or 25 if all three
provider calls retry once. Use measured end-to-end latency before activation.

In the approved synthetic table, race two separate clients for one remaining
call. Reconnect to verify one charge and an active permit. Verify raw
acknowledgments for one-row and stale-revision updates. Simulate losing the
reply after commit and verify zero fake sends from that caller, unchanged
usage on restart and no implicit replacement ledger. Test the app service
principal's permitted and denied paths. Record SQL timing and durable
verification separately from any later TomTom validation.

If per-attempt latency prevents an interactive demo, an alternative for
operator review is to prepay a small finite batch atomically and hold one
durable exclusive runner permit. That design would need to preserve the
global rates and cooldown during the batch, halt all callers on runner loss,
and keep unused precharges. It is outside the current backend.
