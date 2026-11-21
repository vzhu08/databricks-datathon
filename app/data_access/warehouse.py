import logging
import math
import os
import re
from contextlib import ExitStack
from urllib.parse import urlsplit

if __package__ == "data_access":  # The Databricks deployment root is app/.
    from ranking.location import EARTH_RADIUS_KM
    from ranking.search import DEFAULT_RADIUS_KM, MAX_RESULTS, _response, search_from_source
else:
    from ..ranking.location import EARTH_RADIUS_KM
    from ..ranking.search import DEFAULT_RADIUS_KM, MAX_RESULTS, _response, search_from_source

LOGGER = logging.getLogger(__name__)

_COORDINATE_COLUMNS = "TRY_CAST(latitude AS DOUBLE) AS latitude, TRY_CAST(longitude AS DOUBLE) AS longitude"
_CITY_KEY = r"lower(trim(regexp_replace(city, r'(?U)\s+', ' ')))"
_CITY_SQL = f"""
SELECT city, state, {_COORDINATE_COLUMNS}
FROM IDENTIFIER(:prepared_table)
WHERE {_CITY_KEY} = :place
"""
_PIN_SQL = f"""
SELECT pin, {_COORDINATE_COLUMNS}
FROM IDENTIFIER(:prepared_table)
WHERE trim(pin) = :place
"""
_CANDIDATES_SQL = f"""
WITH prepared AS (
    SELECT facility_id, name, city, state, pin, {_COORDINATE_COLUMNS},
           description, capabilities, procedures, equipment, record_source_urls
    FROM IDENTIFIER(:prepared_table)
)
SELECT * FROM prepared
WHERE latitude BETWEEN :min_latitude AND :max_latitude
  AND longitude BETWEEN -180 AND 180
"""


class WarehouseError(RuntimeError):
    """The prepared table could not be read."""


def _table_identifier(value):
    parts = value.strip().split(".")
    if len(parts) != 3 or not all(re.fullmatch(r"[\w-]+", part) for part in parts):
        raise ValueError("Set DATABRICKS_PREPARED_TABLE to catalog.schema.table.")
    return ".".join(f"`{part}`" for part in parts)


def _connect_from_environment(environ):
    from databricks import sql
    from databricks.sdk.core import Config, oauth_service_principal

    host = urlsplit(environ["DATABRICKS_HOST"].strip())
    if host.scheme != "https" or not host.hostname or host.netloc.lower() != host.hostname or (
        host.path.strip("/") or host.query or host.fragment
    ):
        raise ValueError("Set DATABRICKS_HOST to the HTTPS URL of the workspace.")
    warehouse_id = environ["DATABRICKS_WAREHOUSE_ID"].strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", warehouse_id):
        raise ValueError("Set DATABRICKS_WAREHOUSE_ID using the app SQL warehouse resource.")

    def credentials():
        config = Config(
            host=f"https://{host.hostname}",
            auth_type="oauth-m2m",
            client_id=environ["DATABRICKS_CLIENT_ID"],
            client_secret=environ["DATABRICKS_CLIENT_SECRET"],
        )
        return oauth_service_principal(config)

    return sql.connect(
        server_hostname=host.hostname,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        credentials_provider=credentials,
    )


class _WarehouseRows:
    def __init__(self, stack, environ, connect):
        self.stack = stack
        self.environ = environ
        self.connect = connect
        self.connection = None
        self.table = None

    def _close(self):
        try:
            self.connection.close()
        except Exception as error:
            raise WarehouseError(type(error).__name__) from error

    def _query(self, statement, **parameters):
        try:
            if self.connection is None:
                self.table = _table_identifier(self.environ.get("DATABRICKS_PREPARED_TABLE", ""))
                self.connection = self.connect()
                self.stack.callback(self._close)
            with self.connection.cursor() as cursor:
                cursor.execute(statement, parameters={"prepared_table": self.table, **parameters})
                columns = [column[0] for column in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as error:
            raise WarehouseError(type(error).__name__) from error

    def load_place(self, kind, key):
        return self._query(_CITY_SQL if kind == "city" else _PIN_SQL, place=key)

    def load_candidates(self, origin, radius):
        # The latitude band includes the whole circle, including across the antimeridian.
        delta = math.degrees(min(radius / EARTH_RADIUS_KM, math.pi)) + 1e-9
        return self._query(
            _CANDIDATES_SQL, min_latitude=max(-90.0, origin[0] - delta),
            max_latitude=min(90.0, origin[0] + delta),
        )


def search_warehouse(service, location, *, radius_km=DEFAULT_RADIUS_KM, limit=MAX_RESULTS,
                     environ=None, connect=None):
    """Search the configured prepared table. An optional connection factory supports offline tests."""
    environ = os.environ if environ is None else environ
    if connect is None:
        def connect():
            return _connect_from_environment(environ)

    try:
        with ExitStack() as stack:
            rows = _WarehouseRows(stack, environ, connect)
            return search_from_source(
                service, location, load_place=rows.load_place, load_candidates=rows.load_candidates,
                radius_km=radius_km, limit=limit,
            )
    except WarehouseError as error:
        LOGGER.warning("Prepared facility warehouse query failed (%s)", error)
        return _response("unavailable", message="The facility warehouse is unavailable. Try again shortly.")
