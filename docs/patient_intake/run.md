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

The staged v2 check exercises explicit skip, per-item choices, group-wide unknown, units, and selection from a bound complete catalog. It separately tests anonymous resource creation, reverse-order disposal with a separate budget, mailbox saturation, and reset while a create is in flight. The transport doubles record intended requests without sending them. A late verified resource can be cleaned up after local reset. Unknown delivery remains unresolved. The in-process mailbox does not recover obligations after process loss.

## Server configuration

The patient provider is off by default. Keep `PATIENT_PROVIDER` unset for local packaging checks and for deployment until an operator explicitly approves activation. This runbook does not enable the provider or change `app.yaml`. `FIND_CARE_DATA` controls the separate Find care fixture or warehouse screen.

Builds that include the approved patient UI wiring read these settings from the server process. The screen names the experimental provider before asking for consent to send the description. Importing the app, saving a draft, or rerendering the screen does not send a provider request.

| Setting | Meaning |
| --- | --- |
| `PATIENT_PROVIDER` | Unset leaves assessment off. Use `databricks-experimental` for documentation. Builds with the differential screen can explicitly select `databricks-assessment-experimental` for an experimental assessment. |
| `PATIENT_PROVIDER_ENDPOINT` | Required when configured. Pin the approved endpoint to `databricks-gpt-oss-20b` or `databricks-gpt-oss-120b`. |
| `PATIENT_PROVIDER_LANE` | `demo` or `test`. Defaults to `demo` when omitted. |
| `PATIENT_PROVIDER_DEMO_ATTEMPTS` | Server worker's demo request cap, from 0 to 6. Defaults to 0. |
| `PATIENT_PROVIDER_TEST_ATTEMPTS` | Server worker's test request cap, from 0 to 2. Defaults to 0. |

The server factory `configured_databricks_provider(..., mode="assessment")` selects the experimental differential. Omitting `mode` or passing `mode="documentation"` preserves the documentation interview. The selected lane needs a nonzero cap. Both modes share the same worker cap across visits and reruns. Test and demo retain separate allowances. These limits are in process. A restart resets the in-memory counters and a second replica has its own counters. Keep the operator ledger outside the app and coordinate quotas separately before changing configuration, restarting a worker, or increasing replica count. A restart does not renew an approved allowance.

The Databricks SDK resolves the operator profile and credentials on the server. For an approved local OAuth profile that uses CLI auth, install the existing Databricks CLI on the process path or set `DATABRICKS_CLI_PATH` to its executable if it is installed elsewhere. Do not put credentials in this runbook, the UI, or a client bundle. Local profile authentication does not prove that a deployed app identity can query the same endpoint.

## Provider verification

Both Databricks modes request at most **1,024 output tokens per inference** for extraction and finalization. They validate the response locally and do not retry. Documentation mode proposes source-linked observations for review, asks one clarification, and ends with a fixed, non-routable message.

Assessment mode starts with a local warning question. An affirmative or unsure answer can escalate without a model call. The ordinary path is limited to reviewed input from adults ages 18–120 writing in English. After review and clarification, the model can suggest up to three possibilities from a fixed vocabulary of 18 labels, cite eligible reviewed observations, suggest urgency or abstain. Unrecognized symptoms and unresolved evidence can prevent a result. The vocabulary and validation checks cannot establish whether a suggested cause is clinically relevant or the urgency is safe.

The `experimental_assessment` state is terminal. It can display the experimental possibilities, uncertainty and suggested next step. It cannot issue a confirmation for navigation, invoke hospital handoff or supply a clinician order. The optional MGP adapter is separate and needs a trusted server binding for an encounter-owned survey.

- [Offline app-only UI and factory checks](https://github.com/vzhu08/databricks-datathon/issues/229#issuecomment-7077249759) verified default-off, named consent and shared quotas with injected exchanges. The [offline differential replay](https://github.com/vzhu08/databricks-datathon/issues/229#issuecomment-7079995117) verified shared caps across modes, warning and abstention behavior, and no handoff. These checks do not measure actual model behavior.
- [Live documentation-mode operator smoke](https://github.com/vzhu08/databricks-datathon/issues/223#issuecomment-7077123960) recorded two HTTP 200 responses and 1,122 total tokens at reviewed head `4ffc949`. It ended with a fixed terminal message and supplied no urgency, causes or destination.
- [Live assessment-mode operator smoke](https://github.com/vzhu08/databricks-datathon/issues/223#issuecomment-7080037677) recorded two HTTP 200 responses and **1,264 total tokens** on merged main `a96b5e2`. On one invented encounter with simulated patient responses, the model selected one label from the approved vocabulary and returned an experimental consultation suggestion with uncertainty. No destination lookup or route ran. This measured the SDK-backed operator path for one fixture. App identity, deployed browser behavior, diagnostic accuracy and clinical safety remain unverified.

The approved lifetime operator ledger is fully consumed at **seven physical calls**, and **all six demo attempts remain reserved**. Do not rerun a live smoke check. For a future separately approved check, use an authorized profile and invented inputs, allocate physical calls before dispatch, and record the attempts even if the first request fails. Before enabling patient access, record clinical validation for the intended population and languages, consent and data-handling approval, and explicit deployment and release decisions. Destination navigation also needs verified campus and service evidence and display permission. Passing local or operator checks does not grant those approvals.

Databricks Apps verification covers an authenticated workspace deployment. For an external patient deployment, place the same Streamlit app behind a TLS reverse proxy on a separately approved host. Keep the backend port private and inject secrets into the server process from the host's secret manager. Set the access policy at the proxy and session owner boundary. If session state is in memory, use one replica for an approved limited environment until session affinity or an approved shared encounter store is verified. Check expiry, deletion and restart behavior on the chosen host before opening access.
