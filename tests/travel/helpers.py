from datetime import datetime, timezone

from app.travel.tomtom import PRODUCT, TomTomRoutes, RoutesConfig
from app.travel.budget import Admission

NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)


class Budget:
    def __init__(self):
        self.used = 0
        self.reservations = []

    def acquire(self, account, product, now, *, profile, daily_limit, monthly_limit, run_id):
        self.reservations.append((account, product, now, profile, daily_limit, monthly_limit))
        if self.used >= daily_limit:
            return Admission(reason="daily_call_budget_exceeded")
        if self.used >= monthly_limit:
            return Admission(reason="monthly_call_budget_exceeded")
        self.used += 1
        return Admission(token=str(self.used))

    def finish(self, token, now, **kwargs):
        pass

    def status(self, account, product, now):
        return {"used": self.used}


def route(seconds=90.5, metres=800, **changes):
    return {"routes": [{"summary": {"travelTimeInSeconds": seconds, "lengthInMeters": metres, **changes}}]}


def no_route(code="NO_ROUTE_FOUND"):
    return {"detailedError": {"code": code, "message": "PRIVATE provider details must not escape"}}


def client(transport=None, **changes):
    config = RoutesConfig(**{**dict(enabled=True, api_key="SYNTHETIC-KEY", account_scope="synthetic-account",
                                    product=PRODUCT, deployment_mode="single_host", daily_calls=100, monthly_calls=500, verified_monthly_allowance=20000,
                                    query_calls=50, concurrency=1, max_retries=1), **changes})
    return TomTomRoutes(config, budget=Budget(), clock=lambda: NOW, sleep=lambda _: None,
                        transport=transport or (lambda *_: route()))


def campus(fid, longitude=75.81, **changes):
    return {"facility_id": fid, "latitude": 26.9, "longitude": longitude,
            "coordinate_status": "reviewed", "as_of": "2026-11-21",
            "services": {"mri": {"status": "yes", "source_date": "2026-11-20",
                                  "independent_families": ["SYNTHETIC"], "capabilities": {}}}, **changes}


def request(candidates, **changes):
    return {"service": "mri", "urgency": "highest", "as_of": "2026-11-21",
            "travel_metric": "travel_minutes", "travel_budget": 60, "candidates": candidates,
            "routing": {"provider": "tomtom", "origin":
                        {"latitude": 26.9, "longitude": 75.8, "kind": "coordinates"}}, **changes}
