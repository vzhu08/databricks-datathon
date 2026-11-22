"""Write the finder page's example responses from the real finder code and a fake provider.

Every response is produced by ``app.travel.finder.find_campuses`` with an in-process stand-in for
the provider, so no network call, credential or provider payload is involved. Campuses, the origin
and all times are invented. Run ``python -m app.storm_ui.build_finder`` to rewrite the file and add
``--check`` to verify that the committed copy is current.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "data" / "finder_examples.js"
NOW = datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)
ORIGIN = {"latitude": 26.9124, "longitude": 75.7873, "kind": "city", "approximate": True}

# (id, name shown on the page, latitude, longitude, changes to the candidate)
CAMPUSES = [
    ("SYNTHETIC-CAMPUS-A", "Campus A", 26.9300, 75.8000, {}),
    ("SYNTHETIC-CAMPUS-B", "Campus B", 26.8900, 75.8300, {}),
    ("SYNTHETIC-CAMPUS-C", "Campus C", 26.8500, 75.8000, {}),
    ("SYNTHETIC-CAMPUS-D", "Campus D", 26.9700, 75.8500, {}),
    ("SYNTHETIC-CAMPUS-E", "Campus E", 26.9000, 75.7400, {"coordinate_status": "unreviewed"}),
    ("SYNTHETIC-CAMPUS-F", "Campus F", 26.9400, 75.7600, {"service_status": "no"}),
    ("SYNTHETIC-CAMPUS-G", "Campus G", 27.2000, 76.1000, {}),
]
# Fictional driving seconds and road metres. A is nearest in a straight line but slower by road.
DRIVE = {"SYNTHETIC-CAMPUS-A": (1500, 6200), "SYNTHETIC-CAMPUS-B": (840, 7900),
         "SYNTHETIC-CAMPUS-C": (1320, 9800), "SYNTHETIC-CAMPUS-D": (1980, 12400)}


class _Budget:
    """Counts attempts and refuses once the invented daily limit is reached."""

    def __init__(self, used=0, refusal=None):
        self.used = used
        self.refusal = refusal

    def acquire(self, account, product, now, *, profile, daily_limit, monthly_limit, run_id):
        from app.travel.budget import Admission
        if self.refusal:
            return Admission(reason=self.refusal)
        if self.used >= daily_limit:
            return Admission(reason="daily_call_budget_exceeded")
        self.used += 1
        return Admission(token=str(self.used))

    def finish(self, token, now, **kwargs):
        pass

    def status(self, account, product, now):
        return {"used": self.used}


def _candidate(fid, latitude, longitude, changes):
    status = changes.get("service_status", "yes")
    return {"facility_id": fid, "latitude": latitude, "longitude": longitude,
            "coordinate_status": changes.get("coordinate_status", "reviewed"), "as_of": "2026-11-21",
            "services": {"dialysis": {"status": status, "source_date": "2026-11-20",
                                      "independent_families": ["SYNTHETIC-REGISTRY"], "capabilities": {}}}}


def _request(coordinate_status=None, fallback=None):
    candidates = []
    for fid, _, latitude, longitude, changes in CAMPUSES:
        if coordinate_status:
            changes = {**changes, "coordinate_status": coordinate_status}
        candidates.append(_candidate(fid, latitude, longitude, changes))
    routing = {"provider": "tomtom", "origin": dict(ORIGIN), "shortlist_limit": 4}
    if fallback is not None:
        routing["fallback_distance_km"] = fallback
    return {"service": "dialysis", "urgency": "time_sensitive", "as_of": "2026-11-21",
            "travel_metric": "travel_minutes", "travel_budget": 30, "candidates": candidates, "routing": routing}


def _provider(behaviour, daily_calls=100, already_used=0, refusal=None):
    """A TomTom client whose transport answers from ``behaviour`` keyed by campus."""
    from app.travel.tomtom import PRODUCT, RoutesConfig, TomTomRoutes, TransportFailure
    by_point = {(round(lat, 4), round(lon, 4)): fid for fid, _, lat, lon, _ in CAMPUSES}

    def transport(origin, destination, config):
        fid = by_point[(round(destination[0], 4), round(destination[1], 4))]
        answer = behaviour.get(fid, "drive")
        if answer == "drive":
            seconds, metres = DRIVE[fid]
            return {"routes": [{"summary": {"travelTimeInSeconds": seconds, "lengthInMeters": metres}}]}
        if answer == "no_route":
            return {"detailedError": {"code": "NO_ROUTE_FOUND", "message": "not shown"}}
        raise TransportFailure(answer)

    config = RoutesConfig(enabled=True, api_key="SYNTHETIC-KEY", account_scope="synthetic-account", product=PRODUCT,
                          deployment_mode="single_host", daily_calls=daily_calls, monthly_calls=500,
                          verified_monthly_allowance=20000, query_calls=50, concurrency=1, max_retries=0)
    return TomTomRoutes(config, budget=_Budget(already_used, refusal), clock=lambda: NOW, sleep=lambda _: None, transport=transport)


EXAMPLES = [
    ("timed", "Every shortlisted campus timed", {}, {}),
    ("partial", "Some campuses timed, some unresolved",
     {"behaviour": {"SYNTHETIC-CAMPUS-A": "provider_timeout", "SYNTHETIC-CAMPUS-D": "no_route"}}, {"fallback": 40}),
    ("fallback", "Provider unreachable, straight-line fallback",
     {"behaviour": {fid: "provider_timeout" for fid in DRIVE}}, {"fallback": 40}),
    ("local_limit", "Request limit reached part way", {"daily_calls": 2}, {"fallback": 40}),
    ("local_limit_all", "Request limit already reached", {"daily_calls": 2, "already_used": 2}, {"fallback": 40}),
    ("reserved_run", "Reserved request budget used up", {"refusal": "reserved_budget_exhausted"}, {"fallback": 40}),
    ("no_route", "No drivable route to any campus", {"behaviour": {fid: "no_route" for fid in DRIVE}}, {"fallback": 40}),
    ("unavailable", "Provider unreachable, no fallback requested",
     {"behaviour": {fid: "provider_connection_error" for fid in DRIVE}}, {}),
    ("no_coordinates", "No campus has reviewed coordinates", {}, {"coordinate_status": "unreviewed", "fallback": 40}),
]


def bundle():
    from app.travel.finder import find_campuses
    examples = []
    for key, title, provider_options, request_options in EXAMPLES:
        request = _request(**request_options)
        response = find_campuses(request, provider=_provider(provider_options.get("behaviour", {}),
                                                              provider_options.get("daily_calls", 100),
                                                              provider_options.get("already_used", 0),
                                                              provider_options.get("refusal")))
        examples.append({"key": key, "title": title, "request": {k: v for k, v in request.items() if k != "candidates"},
                         "response": response})
    return {"synthetic": True, "names": {fid: name for fid, name, *_ in CAMPUSES}, "examples": examples}


def render():
    body = json.dumps(bundle(), separators=(",", ":"), allow_nan=False)
    return ("// Generated by `python -m app.storm_ui.build_finder`. Do not edit.\n"
            "// Invented campuses, origin and times from the finder code with a stand-in provider.\n"
            f"window.FINDER_EXAMPLES = {body};\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the committed file is out of date")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        print("up to date" if current == text else "out of date: run python -m app.storm_ui.build_finder")
        return 0 if current == text else 1
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
