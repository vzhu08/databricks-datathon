# Opt-in TomTom driving estimates

ROUTE-01 adds traffic-aware car estimates to the normalized finder. The default
finder and fictional storm replay remain offline. This adapter is **disabled by
default**. The operator reported successful Jaipur API Explorer checks in
[#96](https://github.com/vzhu08/databricks-datathon/issues/96#issuecomment-7071349266);
this is separate from exercising this adapter with approved server credentials.
No live provider payload belongs in Git, fixtures, analytics or logs.

## Normal invocation and selection

```sh
python3 -m app.ranking app/travel/example_request.json
```

That wholly invented request opts in using:

```json
{
  "provider": "tomtom",
  "origin": {"latitude": 26.9, "longitude": 75.8, "kind": "city", "approximate": true},
  "shortlist_limit": 25,
  "fallback_distance_km": 40
}
```

This is the `routing` object within the existing normalized request. The root
`travel_metric` is `travel_minutes`; `travel_budget` is minutes. Fallback is
optional, uses its own positive kilometre budget and never mixes units. City/PIN
origins remain approximate even if a caller supplies `approximate:false`.
Coordinates are resolved by the caller; this adapter does not geocode or
transmit patient details.

Candidates retain the normalized, reviewed service/capability snapshot consumed
by `app.ranking.urgency`. Add `latitude`, `longitude` and
`coordinate_status:"reviewed"`. The existing ranker's eligibility rules run
before network access. Negative, unconfirmed, undated/future or mismatched
service snapshots and unmet required capabilities cannot qualify. Disputed,
unreviewed and invalid coordinates never go to TomTom.

Sort the eligible, reviewed coordinates by haversine distance and campus ID,
then route at most 25. The request may lower the backend bound. Score all usable
shortlisted times before selecting the top three. Geographic shortlisting is a
bounded heuristic, not a guarantee of the fastest campus nationwide. Every
input campus retains an outcome/exclusion reason. Ordinary car time establishes
neither ambulance travel time, admission nor current service availability.

## Response for the UI

The old ranker envelope is unchanged when `routing` is absent. With routing,
`routing.results` contains one row per stable `facility_id`, sorted by that ID,
regardless of request completion order. A **fictional** successful row includes:

```json
{
  "facility_id": "SYNTHETIC-CAMPUS-A",
  "provider": "tomtom",
  "mode": "car",
  "metric": "travel_minutes",
  "outcome": "ok",
  "reason": null,
  "requested_at": "2026-11-22T01:00:00Z",
  "departure_time": "2026-11-22T01:00:00Z",
  "departure_time_source": "request_time",
  "estimated_seconds": 90.5,
  "estimated_minutes": 1.5083333333333333,
  "road_metres": 800,
  "distance_km": 0.6,
  "evaluated": true,
  "exclusion_reasons": []
}
```

Seconds are converted to minutes exactly once. Missing/invalid measurements are
null, never zero. Explicit zero seconds and zero metres are valid. A valid
provider departure timestamp is normalized to UTC and marked `provider_summary`;
otherwise `request_time` identifies the local send time. Unsent rows have null
timestamps. `routing.requested_at` is the first actual attempt or null.

The routing envelope carries `schema_version:"1.0.0"`, `provider:"tomtom"`,
`product:"tomtom_maps_v1"` (null when unconfigured), `mode:"car"`,
`routing_preference:"fastest_traffic"`, `approximate_origin`,
`shortlist_metric:"haversine_km"`, `shortlist_limit`, `ranking_metric`,
`travel_budget`, `coverage_state` (`empty` or `available`), `counts`, `errors`, `usage`, `coalesced` and `attribution`.

| State | Meaning |
| --- | --- |
| `ok` | All shortlisted routes have usable times; the time budget may still exclude some/all. |
| `partial` | Some usable times. Rank those only; show unresolved rows separately. |
| `no_route` | Every shortlisted pair has a documented no-route result. |
| `unavailable` | No usable time; inspect individual sanitized reasons. |
| `fallback` | No usable time, provider outage and an explicit kilometre budget. Rank only outage-affected rows by straight-line distance. |
| `not_requested` | Nothing eligible with reviewed valid coordinates was shortlisted. |

Documented `NO_ROUTE_FOUND` and `MAP_MATCHING_FAILURE` produce `no_route`, with
`no_route_found` or `point_not_routable`. They never enter fallback. Missing
summaries and malformed successful responses stay unknown. Local budgets,
reservations, rate limits, cooldowns, unverified configuration and ledger
failures are also distinct from a provider outage and cannot trigger fallback.
Provider timeouts, connection failures, transient errors, auth failures and
quota errors have their own fixed categories. No upstream messages escape.

Counts: `considered` is all inputs, `eligible` passes service/capability rules,
`routing_eligible` also has reviewed valid coordinates, `shortlisted` additionally passes coordinate checks/geographic bound, `evaluated` is
unique campuses with an actual attempt, `timed` is usable routes, `omitted` is
eligible minus shortlisted (coordinate exclusions and outside the bound),
`provider_calls_attempted` includes retries, `scored` is the usable pool within
budget, `excluded` is considered minus scored, and `returned` is at most three.
`routing.results` explains those omitted or unresolved; these are not zero-time
alternatives. A coalesced response reports its shared batch's counts, not extra
calls attributable to the duplicate caller.

## Endpoint and operator configuration

The first adapter pins classic **TomTom Maps v1 Calculate Route**. It sends one
GET per campus to `api.tomtom.com/routing/1/calculateRoute/{locations}/json`, with
`routeType=fastest`, `traffic=true`, `travelMode=car`, `departAt=now`,
`maxAlternatives=0`, `routeRepresentation=summaryOnly`. It reads the first route's
summary seconds/metres. No matrix requests or route geometry are requested.
Orbis/Matrix entitlements do not silently select another endpoint. See the
[API reference](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/calculate-route).
Vincent’s current [national coordinate intake](https://github.com/vzhu08/databricks-datathon/issues/88#issuecomment-7071354676)
approved zero real destination points or approximate origins. Such inputs return
empty coverage, zero routing-eligible destinations and zero attempts, including
with fallback requested. Use invented points until approved provenance arrives.
The official [coverage table](https://docs.tomtom.com/routing-api/documentation/tomtom-maps/v1/product-information/market-coverage)
lists India for routing and real-time traffic; actual congestion coverage,
accuracy and app latency remain unmeasured.

Only trusted backend configuration supplies these values. No public request can
select a profile, supply keys, raise quotas or pass a reservation ID.

| Environment variable | Default / permitted value |
| --- | --- |
| `TOMTOM_ENABLED` | Absent/false. Set `true` only after operator verification. |
| `TOMTOM_API_KEY` | Absent; private server-side secret, never a CLI argument or client bundle. |
| `TOMTOM_PRODUCT` | Absent; explicitly `tomtom_maps_v1` after entitlement verification. |
| `TOMTOM_ACCOUNT_SCOPE` | Absent; one stable nonsecret account identifier shared by every key/worker using the allowance. |
| `TOMTOM_VERIFIED_MONTHLY_ALLOWANCE` | Absent/0; must equal the operator-verified `20000`. Unknown/changed allowance fails closed. |
| `TOMTOM_DEPLOYMENT_MODE` | Absent; only `single_host` is implemented. Multi-host needs a shared atomic store first. |
| `TOMTOM_BUDGET_DB` | Absent; one durable absolute SQLite path outside Git, shared by all backend processes. |
| `TOMTOM_PROFILE` | `routine`; trusted operator may select `demo` or `validation`. |
| `TOMTOM_DAILY_CALLS` | 0 (closed); routine at most 100. Other profiles at most their monthly allocation. |
| `TOMTOM_MONTHLY_CALLS` | 0 (closed); routine at most 500, demo 2000, validation 3000. |
| `TOMTOM_RUN_ID` | Required only for an approved, reserved validation run. |
| `TOMTOM_QUERY_CALLS` | 50; may only be lowered. |
| `TOMTOM_SHORTLIST_LIMIT` | 25; may only be lowered. |
| `TOMTOM_CONCURRENCY` | 2; may only be lowered. |
| `TOMTOM_MAX_RETRIES` | 1; may be 0. |
| `TOMTOM_TIMEOUT_SECONDS` | 5; positive and at most 10 per blocking socket operation. |
| `TOMTOM_RATE_WAIT_SECONDS` | 65; maximum cumulative admission wait per campus, including shared cooldown; may be lowered to 0. |

All HTTP goes to a fixed HTTPS host. Redirects are rejected. JSON bodies are
bounded at 1 MiB. Keys/coordinates appear in the required outbound URL, so
HTTP tracing and proxy/APM request capture must remain disabled/redacted. The
adapter itself never logs the URL, key, upstream message or payload. Its
exception categories and returned metadata are sanitized.

## Durable shared admission and reservations

Before first use, configure the approved account, product, allocation, deployment
mode and durable ledger path, then run `python3 -m app.travel.admin initialize`.
The parent directory must exist. The command creates the file exclusively for
the configured account and records the five Explorer attempts in the same
transaction as setup. It needs no API key and performs no provider requests.

Runtime, `status`, `reserve` and `release` require an existing recognized ledger.
A missing or invalid ledger, missing account scope or missing receipt causes
the adapter to report `budget_store_unavailable` before sending a request. For an
existing ledger made by the earlier adapter, stop its writers, back it up, then
run `python3 -m app.travel.admin adopt-legacy` with the same account settings.
This checks the previous schema and accounted Explorer usage before marking the
file for the new runtime. Counts, reservations and active permits stay intact.
If the storage is lost, restore the original volume or a ledger whose usage
the operator has reconciled through the last possible attempt before resuming.

The ledger reserves every attempt **before** I/O, including retries, failures
and ambiguous timeouts. Atomic SQLite transactions enforce at most 2 attempts
per rolling second, 60 per rolling minute and 2 in flight across processes on
one host. Finishing a call releases its in-flight token, never its usage/rate
charge. A crash retains active tokens until an operator confirms the old calls
ended and explicitly releases them with `ledger.finish(token, utc_now)`; never
delete/recreate the database as a recovery method. Failure to release a token
fails closed. Separate SQLite files or independent hosts cannot share limits.

The routine profile is capped at 100 per UTC day and 500 per UTC calendar month.
The protected monthly allocation is 2000 demo + 3000 deliberate validation,
with a 1000-call safety margin; the other 13,500 calls are unallocated and
unusable. Changing this allocation is an operator-reviewed code/config decision.
[Operator receipt and limits](https://github.com/vzhu08/databricks-datathon/issues/96#issuecomment-7071371612).
The public [pricing](https://docs.tomtom.com/pricing) separately lists Routing
20K and Matrix 2.5K; the adapter never spends the Matrix allowance or buys usage.

The Explorer receipt accounts for **2026-11-22 UTC**, including the invalid-input
attempt. Restarts and parallel workers reuse that receipt. The dashboard's lower
observed value cannot refund attempts. `usage` exposes used counts, routine
remaining, protected allocations, active run reservations, available per-profile
counts, unallocated allowance and active attempts. `validation_active_runs` is
a subset of `validation_remaining`, not an additional allocation.

One retry uses exponential backoff (0.25s with the current one-retry cap).
An HTTP 400 that rejects one campus pair leaves that campus unavailable and the
remaining pairs eligible. Each attempted pair uses one call.
Valid Retry-After seconds/HTTP dates are honored up to 5s. Two 429s without an
intervening successful response establish a durable account/product-wide 30s
cooldown. Admission waits have a finite bound; exhausted waits return local
limit/cooldown reasons without extra HTTP. No timer, animation or CI path calls
routing: only an explicit search/refresh should invoke the live finder.

For a larger validation, first calculate the worst case with **zero I/O**:

```sh
python3 -m app.travel.admin dry-run --campuses 25 --searches 20 --retries 1
```

This reports 1000 maximum calls. After deliberate operator approval, the same
command with `reserve` atomically reserves that number inside the validation
allocation. Set the returned run ID in trusted `TOMTOM_RUN_ID`, and use the
validation profile. Each attempt consumes one reserved call. `status` reads
usage; `release --run-id ID` releases only unsent reservations, never spent
calls. Open reservations cannot cross a UTC month. `reserve`/`release` require
the validation operator profile and verified account/product/deployment settings;
these commands make no HTTP calls and need no API key.

A backend should reuse one long-lived `TomTomRoutes` instance and call
`find_campuses(request, provider=client, request_scope=opaque_scope)`, where the
trusted scope binds the authenticated caller **and that search operation**.
Identical in-flight calls within that instance share one Future. No completed
response is cached, and different callers never share results. Route duplicate
submissions for an operation to the same backend instance; the ledger still
enforces caps across every process. Close the client on application shutdown.
The CLI creates/closes its own client and does not share results between runs.

## Terms, attribution and adoption gate

The current [Portal Terms](https://docs.tomtom.com/legal/terms-and-conditions)
were read in Chrome on November 22 UTC because the fetcher omitted the text.
Clauses 2.2/9.1 limit Evaluation use/credentials; 11.4 restricts storage/caching
and excludes using cached content to serve multiple users; 17.3 requires the
Copyright API when notices are not supplied automatically. Clause 11.6.9
excludes critical health/safety use. This is a fictional internal evaluation,
not patient navigation. Account-specific public demo permission is unresolved.
The [third-party terms](https://www.tomtom.com/en-gb/legal/third-party-product-terms/)
also apply; do not obscure supplied notices.

The response marks `attribution.method:"tomtom_copyright_api"`,
`display_status:"operator_terms_review_required"`, and storage as
`do_not_persist_provider_content`. The literal `TomTom` text is a provider label,
**not complete attribution**. Andrew must integrate the applicable Copyright
API notices and approved display before showing live results. Copyright calls
need their own verified entitlement/budget; none is made by this adapter.

Before adoption, Oliver must provision the approved backend secret and durable
ledger, confirm permission/attribution for the intended display, then exercise
this adapter with a few authorized public/synthetic Jaipur pairs. Verify stable
campus mapping, positive seconds/metres, runtime, charged attempts and effective
flags. Preserve only permitted aggregate verification, not raw responses or
request URLs. Existing Explorer success is not adapter verification. Keep live
mode disabled pending that handoff; the seeded storm uses fictional times.

## Offline verification

```sh
python3 -m unittest discover -s tests/travel -v
python3 -m unittest discover -s tests/ranking -v
python3 -m unittest discover -s tests/simulation -v
python3 -m unittest discover -s tests/routing_evaluation -v
```

Travel fixtures use fake HTTP and a controllable clock; ledger tests additionally
use real SQLite transactions from concurrent processes. They cover unit and
campus mapping, eligibility, partial/no-route/unknown states, retries, rate and
in-flight bounds, receipt idempotency, UTC rollover, finite reservations,
privilege rejection, same-operation deduplication and closed gates. Fixture
success, live-provider validation, deployment and submission are separate.

## Hosted Find care handoff

In the deployed app, import `demo_car_travel` from `travel.hosted`. In the repository, use `app.travel.hosted`. On a traffic submission, bind the selected scenario origin to the server-built synthetic snapshot:

```python
request, snapshot = demo_capacity_inputs(origin_id=origin_id)
travel = demo_car_travel(request, snapshot, origin_id=origin_id)
recommendation = recommend_capacity(request, {**snapshot, "travel": travel})
```

The snapshot must carry the matching `origin_id`. The adapter resolves points from the fictional Jaipur scenario and checks any supplied campus coordinates against that edition. Each campus has an observation with status, decimal minutes, source, outcome and reason. A successful duration describes an ordinary car driving between simulated places. An unavailable or no-route observation has null minutes. Use the entire returned map, including failures, before selecting a destination. For scarcity-aware allocation the route batch also measures reviewed pools that could supply the protected tool, even when the current request requires a different tool. The allocator alone decides request eligibility. An explicit provider no-route result (`no_route_found`) can exclude an unreachable spare. Failed map matching or missing observations leave its reachability uncertain. One process-scoped adapter owns the thread pool. Submit once per explicit search and retain no completed provider result across users.

**Hosted quota prerequisite.** Databricks Apps discards its local filesystem on restart. Replicas have separate local filesystems. The adapter therefore refuses instance-local SQLite in an Apps runtime even when configured as single-host. Copying SQLite to or from a Volume cannot coordinate concurrent admissions. Oliver can review a single durable admission service or a shared PostgreSQL ledger on Lakebase. A replacement must serialize admissions per account/product across workers, preserve charged attempts (including the five Explorer calls), reservations, rate windows, in-flight permits, cooldowns and the safety margin, and pass restart and two-replica tests before enabling hosted sends. [Databricks app state](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/key-concepts) · [Lakebase app resources](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase).

For an authorized single-host adapter smoke, the existing settings above still apply: a server-only TomTom secret, verified Maps v1 entitlement and account scope, explicit call caps, durable pre-provisioned ledger, and a reserved validation run. The hosted key alone cannot enable traffic. Oliver owns provisioning and account-specific Evaluation display clearance; Andrew owns attribution on the rendered result.
