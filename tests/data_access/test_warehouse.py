import json
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

from app.data_access import search_warehouse
from app.data_access.warehouse import _connect_from_environment
from app.ranking import search_facilities

ENV = {"DATABRICKS_PREPARED_TABLE": "test_catalog.test_schema.prepared"}
FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "search.json"


def fake_warehouse(*result_sets):
    connect = MagicMock()
    connection = connect.return_value
    cursors = []
    for rows in result_sets:
        columns = list(rows[0]) if rows else []
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.description = [(column,) for column in columns]
        cursor.fetchall.return_value = [tuple(row[column] for column in columns) for row in rows]
        cursors.append(cursor)
    connection.cursor.side_effect = cursors
    return connect, cursors


class WarehouseTests(unittest.TestCase):
    def test_city_binds_literal_and_matches_fixture_path(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        facilities = [dict(row, city="St. John's") for row in fixture["facilities"]]
        connect, (lookup, scan) = fake_warehouse(facilities, facilities)
        location = {"city": "  ST.\tJohn's ", "state": "Rajasthan"}
        result = search_warehouse("dialysis", location, environ=ENV, connect=connect)
        self.assertEqual(result, search_facilities("dialysis", location, facilities=facilities))

        (query,), arguments = lookup.execute.call_args
        self.assertIn("IDENTIFIER(:prepared_table)", query)
        self.assertIn("= :place", query)
        self.assertNotIn("john's", query)
        self.assertEqual(arguments["parameters"], {
            "prepared_table": "`test_catalog`.`test_schema`.`prepared`", "place": "st. john's",
        })
        (query,), arguments = scan.execute.call_args
        self.assertIn("BETWEEN :min_latitude AND :max_latitude", query)
        bounds = arguments["parameters"]
        self.assertAlmostEqual((bounds["min_latitude"] + bounds["max_latitude"]) / 2, 26.92)
        self.assertAlmostEqual((bounds["max_latitude"] - bounds["min_latitude"]) / 2, 0.44966, places=5)
        connect.assert_called_once_with()
        connect.return_value.close.assert_called_once()
        for cursor in (lookup, scan):
            cursor.__exit__.assert_called_once()

    def test_pin_keeps_leading_zero_and_unresolved_stops_after_one_query(self):
        connect, (lookup,) = fake_warehouse([])
        result = search_warehouse("mri", {"pin": " 001234 "}, environ=ENV, connect=connect)
        self.assertEqual(result["status"], "unresolved_location")
        (query,), arguments = lookup.execute.call_args
        self.assertIn("trim(pin) = :place", query)
        self.assertEqual(arguments["parameters"]["place"], "001234")
        connect.return_value.cursor.assert_called_once()

    def test_ambiguous_and_coordinate_searches_each_use_one_query(self):
        choices = [{"city": "Sample", "state": state} for state in ("B", "A")]
        connect, _ = fake_warehouse(choices)
        result = search_warehouse("mri", {"city": "Sample"}, environ=ENV, connect=connect)
        self.assertEqual(result["status"], "ambiguous_location")
        self.assertEqual([row["state"] for row in result["location_choices"]], ["A", "B"])
        connect.return_value.cursor.assert_called_once()

        connect, (scan,) = fake_warehouse([])
        result = search_warehouse("mri", {"latitude": 90, "longitude": 180}, environ=ENV, connect=connect)
        self.assertEqual(result["status"], "no_match")
        self.assertEqual(scan.execute.call_args[1]["parameters"]["max_latitude"], 90)
        connect.return_value.cursor.assert_called_once()

    def test_invalid_input_does_not_contact_warehouse(self):
        connect = Mock()
        result = search_warehouse("mri", {"latitude": 100, "longitude": 0}, environ={}, connect=connect)
        self.assertEqual(result["status"], "invalid_input")
        connect.assert_not_called()

    def test_missing_table_or_warehouse_error_is_visible_and_sanitized(self):
        connect = Mock(side_effect=RuntimeError("private workspace detail"))
        with self.assertLogs("app.data_access.warehouse", level="WARNING") as logs:
            missing = search_warehouse("mri", {"pin": "001234"}, environ={}, connect=connect)
            connect.assert_not_called()
            offline = search_warehouse("mri", {"pin": "001234"}, environ=ENV, connect=connect)
        self.assertEqual(missing, offline)
        self.assertEqual(offline["status"], "unavailable")
        self.assertEqual(offline["direct_results"], [])
        self.assertEqual(offline["indirect_leads"], [])
        self.assertIn("warehouse", offline["message"])
        self.assertNotIn("private workspace detail", str(offline) + str(logs.output))

    def test_query_failure_releases_cursor_and_connection(self):
        connect, (cursor,) = fake_warehouse([])
        cursor.execute.side_effect = RuntimeError("unreachable")
        with self.assertLogs("app.data_access.warehouse", level="WARNING"):
            result = search_warehouse("mri", {"pin": "001234"}, environ=ENV, connect=connect)
        self.assertEqual(result["status"], "unavailable")
        cursor.__exit__.assert_called_once()
        connect.return_value.close.assert_called_once()

    def test_connection_close_failure_is_visible(self):
        connect, _ = fake_warehouse([])
        connect.return_value.close.side_effect = RuntimeError("connection lost")
        with self.assertLogs("app.data_access.warehouse", level="WARNING"):
            result = search_warehouse("mri", {"pin": "001234"}, environ=ENV, connect=connect)
        self.assertEqual(result["status"], "unavailable")

    def test_oauth_uses_the_app_warehouse_resource(self):
        databricks = ModuleType("databricks")
        databricks.sql = Mock()
        sdk = ModuleType("databricks.sdk")
        core = ModuleType("databricks.sdk.core")
        core.Config = Mock()
        core.oauth_service_principal = Mock()
        modules = {"databricks": databricks, "databricks.sdk": sdk, "databricks.sdk.core": core}
        with patch.dict(sys.modules, modules):
            _connect_from_environment({
                "DATABRICKS_HOST": "https://workspace.example.invalid/",
                "DATABRICKS_WAREHOUSE_ID": "0abcdef123456789",
                "DATABRICKS_CLIENT_ID": "synthetic-app-id",
                "DATABRICKS_CLIENT_SECRET": "synthetic-app-secret",
            })
        options = databricks.sql.connect.call_args[1]
        self.assertEqual(options["server_hostname"], "workspace.example.invalid")
        self.assertEqual(options["http_path"], "/sql/1.0/warehouses/0abcdef123456789")
        self.assertIs(options["credentials_provider"](), core.oauth_service_principal.return_value)
        core.Config.assert_called_once_with(
            host="https://workspace.example.invalid", auth_type="oauth-m2m",
            client_id="synthetic-app-id", client_secret="synthetic-app-secret",
        )
