# Patient intake runtime checks

The Databricks Apps source directory is `app/` and its Streamlit entrypoint is `app.py`. For a local package check, create a copy of `app/` outside the checkout and install the server dependencies into a disposable environment. Start Streamlit from the copy so relative imports and resource paths use the same layout as deployment.

```sh
patient_stage=$(mktemp -d)
cp -R app "$patient_stage/source"
python3 -m venv "$patient_stage/venv"
"$patient_stage/venv/bin/python" -m pip install -r "$patient_stage/source/requirements.txt"
cd "$patient_stage/source"
"$patient_stage/venv/bin/python" -m streamlit run app.py \
  --server.headless true --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Use a local environment with no patient provider credentials for this check. A successful server start proves only that the package is installable. The patient intake check also has to exercise the entrypoint's unconfigured state and confirm that it offers no fabricated assessment or destination. The separate Find care demonstration can use `FIND_CARE_DATA=demo`. That setting is unrelated to patient provider approval.

From the repository root, the intake acceptance and standard discovery commands are:

```sh
python3 -m unittest discover -s tests/patient_intake_e2e
python3 -m unittest discover -s tests
```

Use only invented encounters and test provider responses for automated checks. Test transport is injected server side and stays in the test package. In the failure paths, verify that no stale assessment or downstream navigation remains after a timeout, rate limit, invalid reply, session expiry or edit. The no-reviewed-destination path must make zero TomTom calls. The app-only probe runs in a fresh Python process with a restricted environment and an audit guard for socket attempts.

A provider-backed smoke check requires a selected provider account, confirmation of permitted synthetic test inputs and an approved call budget. Before enabling patient access, record clinician-adjudicated validation for the intended population and languages, approval for consent and data handling, and explicit deployment and release decisions. Destination navigation also needs verified campus and service evidence and display permission. A passing local package or test run does not establish any of those approvals.

Databricks Apps verification covers an authenticated workspace deployment. For an external patient deployment, place the same Streamlit app behind a TLS reverse proxy on a separately approved host. Keep the backend port private and inject secrets into the server process from the host's secret manager. Set the access policy at the proxy and session owner boundary. If session state is in memory, use one replica for an approved limited environment until session affinity or an approved shared encounter store is verified. Check expiry, deletion and restart behavior on the chosen host before opening access.
