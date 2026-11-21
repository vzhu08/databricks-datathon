# RANK-01 integration handoff

## Search callables

From `app/app.py` when `app/` is the working directory or deployment root:

```python
from data_access import search_warehouse
from ranking import search_facilities

location = {"city": "Jaipur", "state": "Rajasthan"}
response = search_warehouse("dialysis", location, radius_km=50, limit=3)
# Synthetic mode, with the shared fixture's facilities already loaded:
response = search_facilities("dialysis", location, facilities=fixture["facilities"])
```

From the repository root, import from `app.data_access` and `app.ranking`. Both calls accept `dialysis`, `mri`, or `trauma_care`, plus a location containing `city` and optional `state`, a six-digit `pin` string, or `latitude` and `longitude`. The default radius is 50 km and the result limit is capped at three.

## Warehouse configuration

| Environment variable | Value |
| --- | --- |
| `DATABRICKS_WAREHOUSE_ID` | Warehouse ID. Map it to the configured warehouse resource with `valueFrom: sql-warehouse` in `app.yaml`, or use the actual resource key if it differs. |
| `DATABRICKS_PREPARED_TABLE` | Ayush's fully qualified Unity Catalog table as `catalog.schema.table`. |
| `DATABRICKS_HOST` | Workspace HTTPS URL. Databricks Apps supplies it. |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | App service principal OAuth credentials. Databricks Apps supplies them. |

Add `databricks-sql-connector>=3.0.0` and `databricks-sdk` to the live app requirements. The ranking core and offline tests use the Python standard library. Give the app service principal `CAN USE` on the warehouse and `USE CATALOG`, `USE SCHEMA`, and `SELECT` on the prepared table's hierarchy. The adapter binds the table identifier, location lookup key, and latitude bounds. It expects the v0 prepared columns. [Databricks warehouse resource](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/sql-warehouse) · [Python SQL connector](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector)

## UI responses

Every response includes `status`, `direct_results`, `indirect_leads`, `location_choices`, `approximate_location`, and `message`. Each card groups `city`, `state`, `pin`, `latitude`, and `longitude` under `location`. Display `distance_km` as approximate when `approximate_location` is true, use **Record sources** for the URLs, and display `availability` as unknown. Use a selected `location_choices` entry as the next request's `location`.

| State | Synthetic example | Result |
| --- | --- | --- |
| `ok` | Dialysis in Jaipur, Rajasthan | North and South campuses in `direct_results`, including the North Campus excerpt “The North Campus provides hemodialysis.” from `procedures`. |
| `needs_confirmation` | Dialysis near PIN `302001`, 2 km | `indirect_leads` contains the nephrology clinic. |
| `no_match` | Trauma care at `26.92, 75.82` | Empty results and a radius-specific message. |
| `ambiguous_location` | Dialysis in Jaipur without a state | `location_choices` contains Jaipur, Odisha and Jaipur, Rajasthan. |
| `invalid_input` | MRI at `100, 75.82` | Empty results and a coordinate validation message. |
| `unresolved_location` | MRI near PIN `999999` | Empty results and a message that the dataset has no coordinates for the PIN. |
| `unavailable` | Valid search with the warehouse missing or offline | Empty results and a warehouse error message. |

Run this Python example from the repository root to print complete synthetic responses for all seven states.

```python
import json
from pathlib import Path

from app.data_access import search_warehouse
from app.ranking import search_facilities

fixture = json.loads(Path("contracts/fixtures/search.json").read_text(encoding="utf-8"))
examples = {}
for case in fixture["cases"]:
    response = search_facilities(**case["query"], facilities=fixture["facilities"])
    examples.setdefault(response["status"], response)
examples["unresolved_location"] = search_facilities("mri", {"pin": "999999"}, facilities=fixture["facilities"])
examples["unavailable"] = search_warehouse("mri", {"pin": "302001"}, environ={})
print(json.dumps(examples, indent=2))
```

Run the synthetic and mocked warehouse regression suite with `python -m unittest discover -s tests -v`.
