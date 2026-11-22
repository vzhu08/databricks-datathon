# Find care app

`app.py` is the Streamlit screen for Databricks Apps. It takes a service and a location (city or
town, PIN code, or coordinates) and shows what the team's search returns: one facility, the exact
words from its record with the field they came from, its record sources, what is not confirmed, up
to two backups, and a referral note to copy or save. It follows the
[search contract](../docs/implementation/SEARCH_CONTRACT.md) and never ranks or filters on its own.
`find_care.py` holds the wording as pure functions.

## Run it

```
pip install -r app/requirements.txt
streamlit run app/app.py
```

With no configuration it runs on the six invented facilities in `contracts/fixtures/search.json`
and says so at the top of the screen.

## Run it on the real records

Set the variables described in [data_access/README.md](data_access/README.md):
`DATABRICKS_WAREHOUSE_ID` and `DATABRICKS_PREPARED_TABLE` (plus the host and credentials that
Databricks Apps supplies). The screen then calls `search_warehouse` and its header says it is
searching the Virtue Foundation records. If the table cannot be reached it says so and recommends
nothing.

To deploy, use `app/` as the app's source folder. `app.yaml` maps the SQL warehouse resource. The
operator adds `DATABRICKS_PREPARED_TABLE`. The demonstration facilities live outside `app/`, so a
deployed app without a table shows a configuration message instead of invented data.

Not done here: no deployment has been made and the screen has not been run against the real table.

## Checks

```
python -m unittest tests.find_care.test_find_care
```

Five wording tests run on the shared fixture. Four screen tests drive the app through Streamlit's
test harness and are skipped when Streamlit is not installed.
