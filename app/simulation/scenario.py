"""Seeded teaching scenarios. Locations, travel times and staffed slots are fictional."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

SERVICES = ("dialysis", "mri", "trauma_care")
URGENCY_ORDER = {"highest": 0, "time_sensitive": 1, "routine": 2}
SCENARIOS = ("storm", "no_surge", "overload", "reversal", "missing_capacity", "resource_loss")


@dataclass(frozen=True)
class Resource:
    """One pool of appointments shared by every listed capability this shift."""

    id: str
    service: str
    tools: tuple[str, ...]
    slots: int | None
    capacity_status: str = "known"


@dataclass(frozen=True)
class Campus:
    id: str
    latitude: float
    longitude: float
    resources: tuple[Resource, ...]


@dataclass(frozen=True)
class Origin:
    id: str
    latitude: float
    longitude: float
    travel_minutes: dict[str, int]


@dataclass(frozen=True)
class Request:
    id: str
    arrival_minute: int
    origin_id: str
    service: str
    urgency: str
    required_tools: tuple[str, ...]
    max_travel_minutes: int


@dataclass(frozen=True)
class CapacityChange:
    """Remove up to this many unbooked slots when the change is announced."""

    minute: int
    resource_id: str
    lost_free_slots: int


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    campuses: tuple[Campus, ...]
    origins: tuple[Origin, ...]
    requests: tuple[Request, ...]
    capacity_changes: tuple[CapacityChange, ...] = ()


def make_scenario(name: str = "storm", seed: int = 17) -> Scenario:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario {name!r}")
    campuses = (
        Campus("A", 26.949, 75.791, (
            Resource("A-dialysis", "dialysis", ("monitored",), 1),
            Resource("A-mri", "mri", (), 1),
        )),
        Campus("B", 26.932, 75.842, (Resource("B-dialysis", "dialysis", (), 2),)),
        Campus("C", 26.899, 75.810, (
            Resource("C-dialysis", "dialysis", (), 1),
            Resource("C-trauma", "trauma_care", (), 1),
        )),
        Campus("D", 26.972, 75.853, (Resource("D-mri", "mri", (), 2),)),
        Campus("E", 26.878, 75.764, (
            Resource("E-dialysis", "dialysis", (), None, "unknown"),
            Resource("E-trauma", "trauma_care", (), 2, "stale"),
        )),
        Campus("F", 26.977, 75.707, (
            Resource("F-dialysis", "dialysis", ("monitored",), 1),
            Resource("F-trauma", "trauma_care", (), 2),
        )),
    )
    origins = (
        Origin("central", 26.936, 75.800, dict(A=8, B=12, C=14, D=18, E=20, F=30)),
        Origin("east", 26.937, 75.858, dict(A=16, B=7, C=15, D=9, E=22, F=36)),
        Origin("south", 26.886, 75.802, dict(A=21, B=16, C=6, D=22, E=8, F=37)),
        Origin("west", 26.955, 75.730, dict(A=14, B=24, C=25, D=28, E=20, F=10)),
    )
    requests = [Request("r01", 0, "central", "dialysis", "routine", (), 25)]
    if name != "no_surge":
        requests.append(Request("r02", 5, "central", "dialysis", "highest", ("monitored",), 20))
        # Let the audience isolate the first two decisions before a larger mixed-service wave.
        rng = random.Random(seed)
        wave = [("mri", "routine"), ("trauma_care", "time_sensitive"),
                ("dialysis", "time_sensitive"), ("mri", "highest"),
                ("trauma_care", "routine"), ("mri", "routine")]
        rng.shuffle(wave)
        for index, (service, urgency) in enumerate(wave):
            origin_id = rng.choice(origins).id
            requests.append(Request(f"r{index + 3:02}", 12 + 4 * (index // 2),
                                    origin_id, service, urgency, (), 30))
        if name == "overload":
            for index in range(10):
                requests.append(Request(f"x{index + 1:02}", 24 + index // 2, "central",
                                        "dialysis", "highest", ("monitored",), 20))
    changes = ()
    if name == "reversal":
        requests[0], requests[1] = replace(requests[1], arrival_minute=0), replace(requests[0], arrival_minute=5)
    if name == "missing_capacity":
        a = campuses[0]
        dialysis = replace(a.resources[0], slots=None, capacity_status="unknown")
        campuses = (replace(a, resources=(dialysis, a.resources[1])), *campuses[1:])
    if name == "resource_loss":
        changes = (CapacityChange(5, "A-dialysis", 1),)
    return Scenario(name, seed, campuses, origins, tuple(requests), changes)
