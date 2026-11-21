# Offline storm replay

Run from the repository root with Python 3.10 or later. The default command writes the pinned fixture to standard output.

```sh
python3 -m app.simulation
python3 -m app.simulation --scenario overload --seed 25 --detour-minutes 5
python3 -m unittest discover -s tests/simulation
```

The six campuses, request origins, travel matrix, shift capacity and service requirements are invented. The same JSON works offline. No clinical or travel-time estimates are computed from the map. Each request arrives with its service, required tools, urgency and maximum acceptable travel time already supplied.

## Scenario and policy

One staffed slot is one appointment in this shared shift. Tools on a resource use the same pool. Every allocation consumes exactly one known, active slot. Unknown or stale counts remain unavailable for allocation. The optional loss event removes unbooked slots when it occurs. Previously assigned appointments stay booked in this scenario.

Both comparison policies process earlier arrivals first. Among requests announced at the same minute, highest urgency comes first, with original arrival order breaking priority ties. The nearest policy selects the fastest feasible campus. The scarcity policy can route within the configured detour cap to retain the last known locally reachable monitored dialysis slot for a future compatible request. This policy knows the specialist coverage and current slot inventory. It cannot consult upcoming arrivals. Highest urgency always takes its fastest feasible option. The 20-minute catchment for the protected profile and the detour cap are scenario assumptions. The optional `--include-fifo-control` adds a nearest-only run with strict arrival order as a separate scheduling comparison.

The default seed 17 demonstrates a four-minute detour for the first routine request. The next, urgent monitored request can then use campus A. Across the complete eight-request storm the nearest policy assigns seven and the scarcity policy assigns eight. The `no_surge` control exposes the same detour when it yields no benefit. The `overload`, `reversal`, `missing_capacity` and `resource_loss` controls illustrate shortage, arrival order, uncertainty and loss of an unbooked slot.

## Andrew's replay interface

Use `contracts/fixtures/storm_replay.json` as the initial offline fixture. `schema_version` is `storm-replay-v1`. Pins and all status displays inherit the top-level synthetic label. Origins and campuses carry latitude/longitude and stable IDs. Requests refer to an origin and supply their arrival minute. The travel matrix uses illustrative minutes. Draw straight links as illustrative connectors.

Drive both panels with one clock. At each minute, show newly announced requests, apply that policy's `capacity_events` up to the minute, then render its assignment `events` in the supplied order at that minute. Hide future requests, changes and final totals during playback. Each assignment includes the selected and nearest feasible campus, service/resource ID, travel, detour and the chosen pool's used/free counts before and after. The eligible campus list is deduplicated in travel order. Exclusions are counts of resource pools. Unknown/stale pools carry an explicit capacity status. Unassigned requests have a reason and null resource, location choice and travel fields.

Final metrics include requested, assigned, unassigned, within-window, unassigned reasons, detours, capacity violations and breakdowns by priority. Each detour is measured against that policy's own fastest feasible option at the time of assignment. Within-window counts use each request's supplied travel limit. Completion refers to a feasible assignment in the model. There is no modeled treatment outcome.
