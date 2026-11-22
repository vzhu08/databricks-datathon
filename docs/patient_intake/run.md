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

The app-only test runs the actual session store, interview reducer, assessment service, neutral provider transport and handoff in an isolated Python process. The test package injects a provider and an HTTP exchange that use invented inputs. One journey confirms a proposed fact, answers a follow-up, confirms the current result and reaches `no_reviewed_destination` without a TomTom call. The same harness checks missing provider approval, timeout, rate limit, malformed reply, urgency mismatch, storage exhaustion, edits and session isolation/expiry. Test doubles do not ship with `app/`.

The patient runtime has no live provider environment variable contract yet. `FIND_CARE_DATA` controls only the legacy fixture/warehouse screen. The optional MGP survey adapter can consume an existing verified survey but cannot create one for a fresh symptom statement. Keep the patient app unconfigured until the provider supports the agreed input path and is approved. A provider-backed smoke command requires a selected account, approved invented inputs and a physical-call budget. Make any future invocation explicitly opt in, reserve the smallest approved budget before dispatch, turn off automatic retries, and report actual attempted calls. Before enabling patient access, record clinician-adjudicated validation for the intended population and languages, approval for consent and data handling, and explicit deployment and release decisions. Destination navigation also needs verified campus and service evidence and display permission. A passing local package or test run does not establish any of those approvals.

Databricks Apps verification covers an authenticated workspace deployment. For an external patient deployment, place the same Streamlit app behind a TLS reverse proxy on a separately approved host. Keep the backend port private and inject secrets into the server process from the host's secret manager. Set the access policy at the proxy and session owner boundary. If session state is in memory, use one replica for an approved limited environment until session affinity or an approved shared encounter store is verified. Check expiry, deletion and restart behavior on the chosen host before opening access.
