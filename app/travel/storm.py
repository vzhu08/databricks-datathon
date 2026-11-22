"""Request-local Pune Storm traffic observations for an explicit presenter action."""

import hashlib
import json
import os

from .hosted import _process_client
from .tomtom import RouteResults, timestamp, utc_now


# SHA-256 of sorted (planning ID, latitude, longitude) triples from the approved
# edition-1 roster, b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35.
# This authenticates the actual outbound points, independent of plan metadata.
_DESTINATION_DIGEST = "2267e34d9e2e9fff54d4255c46dba219eeb2820054813be5b9d01f32a45eb28b"
# Means of the western/eastern six roster sites, rounded half-even to six decimals.
_PICKUPS = (("PUNE-SIM-PICKUP-W", 18.519745, 73.821909),
            ("PUNE-SIM-PICKUP-E", 18.508386, 73.870893))
_SOURCE = "TomTom traffic-aware ordinary car"


def storm_pickups():
    return [dict(id=key, latitude=lat, longitude=lon) for key, lat, lon in _PICKUPS]


def _points(records, count):
    if not isinstance(records, (list, tuple)) or len(records) != count:
        raise ValueError("Expected the complete approved Storm point set")
    points = {}
    for row in records:
        if not isinstance(row, dict) or set(row) != {"id", "latitude", "longitude"}:
            raise ValueError("Expected only a local ID and coordinates")
        key, lat, lon = row["id"], row["latitude"], row["longitude"]
        if (not isinstance(key, str) or not key or key in points
                or type(lat) not in (float, int) or not -90 <= lat <= 90
                or type(lon) not in (float, int) or not -180 <= lon <= 180):
            raise ValueError("Invalid or repeated Storm point")
        points[key] = float(lat), float(lon)
    return points


def _observe(pairs, provider, attribution):
    if provider is None:
        if not all(attribution.values()):
            return RouteResults(errors=["missing_provider_attribution"])
        try:
            provider = _process_client()
        except ValueError:
            return RouteResults(errors=["invalid_operator_configuration"])
        if provider.config.deployment_mode != "databricks_delta":
            return RouteResults(errors=["unsupported_budget_deployment"])
    # A smaller operator shortlist leaves the remaining cells explicitly unavailable.
    limit = provider.config.shortlist_limit
    batch = provider._route_pairs({pair: pair for pair in pairs[:limit]})
    if len(pairs) > limit:
        batch.errors = sorted(set(batch.errors) | {"shortlist_limit"})
    return batch


def storm_car_matrix(*, pickups, destinations, provider=None):
    """Return both pickup rows from a single bounded action. No caching or network on import.

    Accept only the pinned venue-cleared coordinates. Inject a TomTomRoutes with
    fake transport for local rehearsal. The hosted path uses the existing binding
    and shared durable ledger. Keep the entire returned observation request-local.
    """
    origins = _points(pickups, 2)
    sites = _points(destinations, 12)
    if origins != {key: (lat, lon) for key, lat, lon in _PICKUPS}:
        raise ValueError("Unapproved Storm pickup coordinates or IDs")
    encoded = json.dumps(sorted((key, *point) for key, point in sites.items()),
                         separators=(",", ":"), allow_nan=False).encode("ascii")
    if hashlib.sha256(encoded).hexdigest() != _DESTINATION_DIGEST:
        raise ValueError("Unapproved Storm destination coordinates or IDs")

    # Several local IDs may refer to one coordinate. Only directed coordinate
    # pairs enter the worker; the ID mapping is applied after the transport ends.
    pairs = sorted({(origin, site) for origin in origins.values() for site in sites.values()})
    attribution = {"caption": os.environ.get("TOMTOM_COPYRIGHT_CAPTION", "").strip(),
                   "notices": os.environ.get("TOMTOM_COPYRIGHT_NOTICES", "").strip()}
    batch = _observe(pairs, provider, attribution)
    seconds, reasons = {}, {}
    for pair in pairs:
        observation = batch.results.get(pair, {})
        seconds[pair] = observation["estimated_seconds"] if observation.get("outcome") == "ok" else None
        reasons[pair] = observation.get("reason") if observation else (
            "shortlist_limit" if "shortlist_limit" in batch.errors else next(iter(batch.errors), "not_evaluated"))

    def local_rows(values):
        return {pickup_id: {site_id: values[origin, site] for site_id, site in sites.items()}
                for pickup_id, origin in origins.items()}

    usable = sum(value is not None for value in seconds.values())
    errors = sorted(set(batch.errors) | {reason for reason in reasons.values() if reason})
    return dict(travel_seconds=local_rows(seconds), reasons=local_rows(reasons), errors=errors,
                requested_at=batch.requested_at, observed_at=batch.requested_at,
                completed_at=timestamp(provider.clock() if provider is not None else utc_now()),
                source=_SOURCE, attribution=attribution, pickup_count=len(origins), site_count=len(sites),
                eligible_pairs=len(pairs), attempted_pairs=len(batch.evaluated_ids), usable_pairs=usable,
                unavailable_pairs=len(pairs) - usable, attempts=batch.calls_attempted,
                actual_attempts=batch.calls_attempted)
