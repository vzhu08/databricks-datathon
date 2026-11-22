"""Independent assignment oracles for the offline shift-slot planner (#323)."""

from collections import Counter
from copy import deepcopy
from importlib.util import find_spec
from itertools import product
import math
import random
import unittest


PRIORITIES = ("highest", "time_sensitive", "routine")
ZERO = (0, 0, 0, 0)


def patient_cost(priority, seconds):
    if seconds is None:
        return tuple(int(priority == level) for level in PRIORITIES) + (0,)
    return (0, 0, 0, seconds)


def objective(priorities, routes, choices):
    costs = [patient_cost(priorities[p], routes[p].get(slot)) for p, slot in choices.items()]
    return tuple(map(sum, zip(ZERO, *costs)))


def feasible_choices(routes, capacities):
    """Enumerate only in tiny fixtures, with None as the unserved choice."""
    patients = list(routes)
    for slots in product(*[(None, *routes[p]) for p in patients]):
        used = Counter(slot for slot in slots if slot is not None)
        if all(count <= capacities[slot] for slot, count in used.items()):
            yield dict(zip(patients, slots))


def check_plan(priorities, routes, capacities, choices):
    if choices.keys() != priorities.keys():
        raise AssertionError("Every request must have exactly one outcome")
    used = Counter()
    for p, slot in choices.items():
        if slot is not None:
            if slot not in routes[p]:
                raise AssertionError(f"Infeasible assignment for {p} at {slot}")
            used[slot] += 1
    if any(count > capacities[slot] for slot, count in used.items()):
        raise AssertionError("Shared appointment bucket over capacity")


def improving_exchange(priorities, routes, capacities, choices):
    """Certify optimality of a feasible answer without running the producer's solver.

    Moving a patient from their current bucket to any legal alternative contributes
    the difference between their two objective tuples. A cycle swaps occupants.
    A path ending at spare capacity can move patients without a return swap, so a
    balance node connects spare buckets back to occupied ones. Feasible assignment
    differences decompose into such cycles. A strict improvement exists exactly
    when one cycle has lexicographically negative total cost.
    """
    check_plan(priorities, routes, capacities, choices)
    balance = object()
    used = Counter(choices.values())
    limits = {**capacities, None: len(priorities)}
    edges = []
    for p, current in choices.items():
        options = {**routes[p], None: None}
        old = patient_cost(priorities[p], options[current])
        for other, seconds in options.items():
            if current != other:
                new = patient_cost(priorities[p], seconds)
                delta = tuple(a - b for a, b in zip(new, old))
                edges.append((current, other, delta))
    for slot, limit in limits.items():
        if used[slot]:
            edges.append((balance, slot, ZERO))
        if used[slot] < limit:
            edges.append((slot, balance, ZERO))

    # Bellman-Ford with all distances initialized to zero reaches every component.
    distance = dict.fromkeys([balance, *limits], ZERO)
    for _ in range(len(distance)):
        changed = False
        for left, right, delta in edges:
            candidate = tuple(a + b for a, b in zip(distance[left], delta))
            if candidate < distance[right]:
                distance[right] = candidate
                changed = True
        if not changed:
            return False
    return True


class IndependentOracleTests(unittest.TestCase):
    def test_exchange_certificate_agrees_with_every_tiny_allocation(self):
        rng = random.Random(323)
        for _ in range(30):
            capacities = {slot: rng.randrange(3) for slot in ("a", "b", "c")}
            priorities = {p: rng.choice(PRIORITIES) for p in range(4)}
            routes = {p: {s: rng.randrange(4) for s in capacities if rng.randrange(3)}
                      for p in priorities}
            allocations = list(feasible_choices(routes, capacities))
            best = min(objective(priorities, routes, x) for x in allocations)
            for choices in allocations:
                self.assertEqual(improving_exchange(priorities, routes, capacities, choices),
                                 objective(priorities, routes, choices) > best)

    def test_120_requests_shared_bottleneck_and_travel_only_regression(self):
        capacities = {"general": 60, "monitored": 59}
        priorities = {p: ("highest" if p < 60 else "routine") for p in range(120)}
        routes = {p: ({"monitored": 20} if p < 60 else {"general": 30, "monitored": 5})
                  for p in priorities}
        best = {p: ("monitored" if p < 59 else None if p == 59 else "general")
                for p in priorities}
        self.assertEqual(objective(priorities, routes, best), (1, 0, 0, 2980))
        self.assertFalse(improving_exchange(priorities, routes, capacities, best))
        wrong_priority = {**best, 0: None, 60: "monitored"}
        self.assertTrue(improving_exchange(priorities, routes, capacities, wrong_priority))
        routes[59]["monitored"] = 19
        self.assertTrue(improving_exchange(priorities, routes, capacities, best))

def audit_policy(case, patients, facilities, travel_seconds, policy, *, exact):
    """Read the declared shift slots and patient-to-campus seconds independently."""
    requests = {p["id"]: p for p in patients}
    case.assertEqual(len(requests), len(patients), "Duplicate patient ID")
    priorities = {pid: row["priority"] for pid, row in requests.items()}
    case.assertTrue(set(priorities.values()) <= set(PRIORITIES))

    buckets = {}
    for f in facilities:
        for resource in f["resources"]:
            slot = resource["slot_id"]
            case.assertNotIn(slot, buckets)
            case.assertIs(type(resource["slots"]), int)
            case.assertGreaterEqual(resource["slots"], 0)
            buckets[slot] = (f, resource)
    limits = {slot: resource["slots"] for slot, (_, resource) in buckets.items()}

    edges = {}
    reasons = {}
    for pid, p in requests.items():
        edges[pid] = {}
        reasons[pid] = "no_matching_service_or_tools"
        fitting = timed = False
        for slot, (facility, resource) in buckets.items():
            if facility["precision"] == "area" or p["service"] != resource["service"]:
                continue
            if not set(p["required_tools"]).issubset(resource["tools"]):
                continue
            fitting = True
            seconds = travel_seconds.get(pid, {}).get(facility["id"])
            if seconds is None:
                continue
            timed = True
            case.assertIs(type(seconds), int)
            case.assertGreaterEqual(seconds, 0)
            if (p["arrival_minute"] * 60 + seconds <= resource["start_minute"] * 60
                    and resource["start_minute"] <= p["deadline_minute"]):
                edges[pid][slot] = seconds
        if edges[pid]:
            reasons[pid] = "compatible_slots_exhausted"
        elif timed:
            reasons[pid] = "outside_appointment_window"
        elif fitting:
            reasons[pid] = "modelled_travel_unknown"

    choices = {}
    for a in policy["assignments"]:
        pid, slot = a["patient"], a["slot_id"]
        case.assertIn(pid, requests)
        case.assertNotIn(pid, choices)
        case.assertIn(slot, edges[pid], f"Unreachable or incompatible bucket for {pid}")
        f, resource = buckets[slot]
        case.assertEqual((a["facility"], a["service"], a["slot_start_minute"], a["travel_seconds"]),
                         (f["id"], resource["service"], resource["start_minute"], edges[pid][slot]))
        choices[pid] = slot
    for row in policy["unserved"]:
        pid = row["patient"]
        case.assertIn(pid, requests)
        case.assertNotIn(pid, choices)
        case.assertEqual(row["reason"], reasons[pid])
        choices[pid] = None
    check_plan(priorities, edges, limits, choices)
    if exact:
        case.assertFalse(improving_exchange(priorities, edges, limits, choices),
                         "Feasible reassignment improves priority or total travel")
    else:
        remaining = limits.copy()
        for pid in sorted(requests, key=lambda p: (requests[p]["arrival_minute"], p)):
            available = [s for s in edges[pid] if remaining[s]]
            expected = min(available, default=None, key=lambda s: (
                edges[pid][s], buckets[s][1]["start_minute"], buckets[s][0]["id"], s))
            case.assertEqual(choices[pid], expected, f"Nearest free appointment for {pid}")
            if expected is not None:
                remaining[expected] -= 1

    if "metrics" in policy:
        metrics = policy["metrics"]
        by_priority = {level: {"assigned": 0, "unmet": 0} for level in PRIORITIES}
        for pid, slot in choices.items():
            by_priority[priorities[pid]]["unmet" if slot is None else "assigned"] += 1
        case.assertEqual(metrics["by_priority"], by_priority)
        case.assertEqual((metrics["assigned"], metrics["unmet"]),
                         (len(policy["assignments"]), len(policy["unserved"])))
        case.assertEqual(metrics["total_travel_seconds"], sum(a["travel_seconds"] for a in policy["assignments"]))
        case.assertEqual(metrics["unserved_reasons"], Counter(r["reason"] for r in policy["unserved"]))
        used = Counter(choices.values())
        case.assertCountEqual([(row["slot_id"], row["facility"], row["service"], row["slots"], row["used"])
                               for row in metrics["resources_used"]],
                              [(s, f["id"], resource["service"], limits[s], used[s])
                               for s, (f, resource) in buckets.items()])
    return objective(priorities, edges, choices)

def tiny_instance():
    # Routine can reach either bucket exactly on time at B. Highest needs A's tool.
    # The third patient's one-second late arrival at the slot is infeasible.
    patients = []
    for pid, priority, tools, arrival in (("r", "routine", [], 0),
                                          ("h", "highest", ["monitored"], 1),
                                          ("l", "time_sensitive", [], 9)):
        patients.append({"id": pid, "priority": priority, "service": "dialysis",
                         "required_tools": tools, "arrival_minute": arrival, "deadline_minute": 10})
    facilities = []
    for fid, tools, precision in (("a", ["monitored"], "point"), ("b", [], "point"),
                                  ("area", ["monitored"], "area")):
        slot = {"slot_id": fid + "-10", "resource_id": fid + "-pool", "service": "dialysis",
                "tools": tools, "start_minute": 10, "slots": 1}
        facilities.append({"id": fid, "label": "Synthetic campus " + fid,
                           "precision": precision, "resources": [slot]})
    travel = {"r": {"a": 120, "b": 600}, "h": {"a": 540, "b": 0, "area": 0},
              "l": {"a": 61, "b": 61}}
    return patients, facilities, travel


class PolicyAuditTests(unittest.TestCase):
    def test_tiny_bookings_and_corrupted_receipts(self):
        patients, facilities, travel = tiny_instance()
        highest = {"patient": "h", "facility": "a", "service": "dialysis", "slot_id": "a-10",
                   "slot_start_minute": 10, "travel_seconds": 540}
        routine = {**highest, "patient": "r", "facility": "b", "slot_id": "b-10", "travel_seconds": 600}
        late = {"patient": "l", "reason": "outside_appointment_window"}
        result = {"assignments": [routine, highest], "unserved": [late]}

        def audit(assignments, unserved):
            return audit_policy(self, patients, facilities, travel,
                                {"assignments": assignments, "unserved": unserved}, exact=True)

        self.assertEqual(audit(**result), (0, 1, 0, 1140))
        for name, changes in (
            ("duplicate patient", {"assignments": [routine, highest, routine]}),
            ("missing outcome", {"unserved": []}),
            ("double use of one pool", {"assignments": [highest, {**highest, "patient": "r",
                                                                   "travel_seconds": 120}]}),
            ("wrong tool", {"assignments": [routine, {**routine, "patient": "h", "travel_seconds": 0}]}),
            ("area endpoint", {"assignments": [routine, {**highest, "facility": "area",
                                                          "slot_id": "area-10", "travel_seconds": 0}]}),
            ("one second late", {"assignments": [routine, highest, {**highest, "patient": "l",
                                                                    "travel_seconds": 61}], "unserved": []}),
            ("misreported duration", {"assignments": [routine, {**highest, "travel_seconds": 539}]}),
            ("dropped feasible booking", {"assignments": [routine], "unserved": [late, {"patient": "h",
                                                                                        "reason": "unmet"}]}),
        ):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                audit(**{**result, **changes})


def geodesic_seconds(patient, facility, speed):
    """Central angle from unit-vector dot and cross products on a mean-radius sphere."""
    vectors = []
    for point in (patient, facility):
        lat, lon = map(math.radians, (point["latitude"], point["longitude"]))
        vectors.append((math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)))
    a, b = vectors
    cross = [a[i] * b[(i + 1) % 3] - a[(i + 1) % 3] * b[i] for i in range(3)]
    angle = math.atan2(math.hypot(*cross), sum(x * y for x, y in zip(a, b)))
    return math.ceil(angle * 6371.0088 * 3600 / speed)


@unittest.skipUnless(find_spec("app.simulation.batch_planner"), "requires #323 batch planner")
class PlannerIntegrationTests(unittest.TestCase):
    def test_solver_small_instances_against_enumeration(self):
        from app.simulation.batch_planner import solve

        patients, facilities, travel = tiny_instance()
        facilities = facilities[:2]
        travel["h"].pop("area")
        instance = {"patients": patients, "facilities": facilities, "travel_seconds": travel,
                    "geography": {"location_basis": "synthetic"}, "scenario": {"horizon_minutes": 10}}
        for seconds in (599, 600, 601):
            travel["r"]["b"] = seconds
            routes = {"r": {"a-10": 120}, "h": {"a-10": 540}, "l": {}}
            if seconds <= 600:
                routes["r"]["b-10"] = seconds
            priorities = {p["id"]: p["priority"] for p in patients}
            best = min(objective(priorities, routes, allocation)
                       for allocation in feasible_choices(routes, {"a-10": 1, "b-10": 1}))
            result = solve(instance)
            for name, policy in result["policies"].items():
                exact = name == "exact_optimum"
                score = audit_policy(self, patients, facilities, travel, policy, exact=exact)
                if exact:
                    self.assertEqual(score, best)

    def test_generated_shift_reproducibility_scope_metrics_and_optimality(self):
        from app.simulation.batch_planner import make_instance, solve

        instance = make_instance(seed=17)
        original = deepcopy(instance)
        result = solve(instance)
        self.assertEqual(instance, original)
        self.assertEqual(result, solve(make_instance(seed=17)))
        shuffled = deepcopy(instance)
        rng = random.Random(323)
        for name in ("patients", "facilities"):
            rng.shuffle(shuffled[name])
        for facility in shuffled["facilities"]:
            rng.shuffle(facility["resources"])
        self.assertEqual(result, solve(shuffled))

        self.assertEqual(result["schema_version"], "storm-plan-v1")
        self.assertEqual(result["geography"]["location_basis"], "synthetic")
        self.assertIn("synthetic", result["scenario"]["simulated"].lower())
        self.assertIn("synthetic", result["scenario"]["travel_basis"].lower())
        self.assertEqual(result["scenario"]["horizon_minutes"], 360)
        self.assertEqual(len(result["patients"]), 120)
        patients, facilities = instance["patients"], instance["facilities"]
        travel = {p["id"]: {f["id"]: geodesic_seconds(p, f, instance["scenario"]["speed_kmh"])
                            for f in facilities if f["precision"] == "point"} for p in patients}
        scores = {}
        self.assertEqual(set(result["policies"]), {"exact_optimum", "nearest_first"})
        for name, policy in result["policies"].items():
            self.assertIn("metrics", policy)
            scores[name] = audit_policy(self, patients, facilities, travel, policy, exact=name == "exact_optimum")
        self.assertLessEqual(scores["exact_optimum"], scores["nearest_first"])
