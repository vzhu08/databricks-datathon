# Storm shift planner

Run the wholly synthetic control from the repository root.

```sh
python3 -m app.simulation.batch_planner --seed 17 > /tmp/storm-plan-synthetic.json
```

The same source imports as `simulation.batch_planner` when only `app/` is
packaged. The checked eight-case replay and the online single-request preview
keep their existing entry points.

The optional real geography input is an operator-cleared source-only roster.
Maintain its source and clearance receipt separately. Never put real facility
rows into Git. The pinned CSV must be Vincent's four-column
`facility_id,facility_name,latitude,longitude` format. The accompanying JSON
supplies `geography` directly, with `location_basis: "public_source"`,
`name`, `selection`, `source`, `verification`, the approved `roster_sha256`
and `attribution` entries with `text` and `url`. The planner checks the bytes
against that supplied pin. This is an integrity check under the operator's
separate source approval.

```sh
python3 -m app.simulation.batch_planner --roster /path/to/facility-locations.csv \
  --geography /path/to/approved-geography.json --seed 17 > /tmp/storm-plan.json
```

The generator picks up to eight usable sites by stable source ID. This is a
planning sample. Real point coordinates retain the publisher's supported
precision. An area marker supplies no travel endpoint or resource pool.
Demand locations, arrivals, priorities, tools, appointment deadlines and
staffed slots are simulated. Modelled travel is geodesic displacement divided
by a constant synthetic 30 km/h, rounded up to whole seconds. An appointment
must be reachable from arrival and start no later than the patient's simulated
deadline within this six-hour shift. Each resource/start bucket has one shared
stock across the compatible patient profiles. No transfer or booking occurs.

`solve(instance)` also accepts a self-contained instance. Pass the geography
metadata, scenario with integer `horizon_minutes`, facility and patient rows,
and optionally a nested `travel_seconds` map of patient ID to facility ID to
integer seconds or null. The explicit matrix can reproduce a cleared neutral
instance without real coordinates. Either way, the two policies use identical
feasible patient-slot edges. For field shapes see the output of the command
and the planner tests. Each booked row includes the stable patient, facility
and appointment slot IDs, start minute and travel seconds. Each policy reports
assigned and unmet by priority, unserved reasons, and per-bucket stock used.

Arrival-order nearest-first chooses the lowest travel option with capacity
at each request. Equal times use appointment time, facility ID and slot ID.
The full-batch solver sees the shift's synthetic demand in advance. It minimizes
unmet highest, time-sensitive and routine patients in lexicographic order,
followed by total travel seconds. For N patients and maximum feasible travel M,
one unit of unmet routine demand costs N×M+1. Time-sensitive and highest costs
multiply that by N+1 and (N+1)² respectively. This makes every higher objective
component dominate every possible lower cost. Integer min-cost flow yields an
exact feasible optimum for this declared objective and these inputs. Equal
costs are resolved deterministically by the ordered graph.
