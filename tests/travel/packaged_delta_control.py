"""Executed in a subprocess with only the staged app directory on the project import path."""

import json
from unittest.mock import Mock, patch

from travel.budget import ALLOWANCE, EXPLORER_DAY, EXPLORER_RECEIPT, PRODUCT
from travel.delta_budget import BudgetStoreUnavailable, DeltaBudget
from travel.hosted import demo_car_travel
from travel.tomtom import from_environment


def check():
    scope = "synthetic-account"
    env = dict(DATABRICKS_APP_NAME="test", TOMTOM_ENABLED="true", TOMTOM_DEPLOYMENT_MODE="databricks_delta",
               TOMTOM_API_KEY="SYNTHETIC", TOMTOM_ACCOUNT_SCOPE=scope, TOMTOM_PRODUCT=PRODUCT,
               TOMTOM_BUDGET_WAREHOUSE_ID="a" * 16, TOMTOM_BUDGET_TABLE="fixture.budget.routing",
               TOMTOM_QUERY_CALLS="1", TOMTOM_MAX_RETRIES="0", TOMTOM_DAILY_CALLS="6",
               TOMTOM_MONTHLY_CALLS="6", TOMTOM_VERIFIED_MONTHLY_ALLOWANCE=str(ALLOWANCE))
    state = dict(version=1, allowance=ALLOWANCE, receipt=EXPLORER_RECEIPT, last_clock=0, strikes=0,
                 cooldown=0, daily={EXPLORER_DAY: {"routine": 5}}, active={}, completed=[], runs={})
    revision = "0" * 32
    # 2026-11-22 12:00 UTC, shared SQL clock for all fake app instances.
    tick = 1795348800000000

    def sql(warehouse, statement, params):
        nonlocal state, revision
        assert warehouse == env["TOMTOM_BUDGET_WAREHOUSE_ID"]
        assert "`fixture`.`budget`.`routing`" in statement
        if statement.lstrip().startswith("SELECT"):
            return [[scope, PRODUCT, revision, json.dumps(state), str(tick)]]
        assert statement.lstrip().startswith("UPDATE") and params["revision"] == revision
        state = json.loads(params["quota_state"])
        revision = params["new_revision"]
        return [["1"]]

    def transport(origin, point, config):
        assert state["daily"][EXPLORER_DAY]["routine"] == 6 and len(state["active"]) == 1
        assert origin == (26.936, 75.8) and point == (26.949, 75.791)
        return {"routes": [{"summary": {"travelTimeInSeconds": 91.5, "lengthInMeters": 100}}]}

    request = dict(service="dialysis", urgency="highest", max_travel_minutes=15, as_of=EXPLORER_DAY)
    campus = dict(facility_id="A", as_of=EXPLORER_DAY, services={"dialysis": {
        "status": "yes", "source_date": EXPLORER_DAY, "independent_families": ["synthetic"]}})
    snapshot = dict(mode="synthetic", origin_id="central", candidates=[campus], as_of=EXPLORER_DAY)

    with patch("travel.delta_budget._Statements", return_value=sql):
        client = from_environment(env)
        try:
            assert isinstance(client.budget, DeltaBudget)
            client.transport = Mock(side_effect=transport)
            def search():
                return demo_car_travel(request, snapshot, origin_id="central", provider=client)["A"]

            first = search()
            assert first["minutes"] == 91.5 / 60 and first["requested_at"] and not state["active"]
            assert search()["reason"] == "daily_call_budget_exceeded"
            client.budget._execute = Mock(side_effect=BudgetStoreUnavailable("fixture SQL failure"))
            assert search()["reason"] == "budget_store_unavailable"
            client.transport.assert_called_once()
        finally:
            client.close()

        # A new instance sees the same counters. Spend exactly one reserved
        # validation attempt with the operator's narrow smoke configuration.
        operator = DeltaBudget(env["TOMTOM_BUDGET_WAREHOUSE_ID"], env["TOMTOM_BUDGET_TABLE"],
                               account_scope=scope, verified_allowance=ALLOWANCE, execute=sql)
        run = operator.reserve_run(scope, PRODUCT, None, 1)
        smoke = from_environment(dict(env, TOMTOM_PROFILE="validation", TOMTOM_RUN_ID=run["run_id"],
                                      TOMTOM_DAILY_CALLS="1", TOMTOM_MONTHLY_CALLS="1"))
        try:
            smoke.transport = Mock(return_value={"routes": [{"summary": {
                "travelTimeInSeconds": 61.5, "lengthInMeters": 100}}]})
            observed = demo_car_travel(request, snapshot, origin_id="central", provider=smoke)
            assert observed["A"]["minutes"] == 61.5 / 60
            assert state["runs"][run["run_id"]]["remaining"] == 0
            assert operator.status(scope, PRODUCT, None)["used"] == 7
            smoke.transport.assert_called_once()
        finally:
            smoke.close()
