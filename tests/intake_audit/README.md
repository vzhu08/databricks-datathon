# Independent intake audit

Developer S froze 52 fictional cases and their expected outcomes before viewing candidate outputs. The [freeze receipt](https://github.com/vzhu08/databricks-datathon/issues/133#issuecomment-7074486311) records their SHA-256 digest. S holds the packet and its Python adapter locally until Oliver identifies the integrated candidate commit on [#133](https://github.com/vzhu08/databricks-datathon/issues/133).

Run the harness checks from the audit checkout with Python 3.9 or newer.

```sh
python3 -B -m unittest discover -s tests/intake_audit -t tests
```

After candidate freeze, run the following in a fresh Python process. Supply a local repository containing the integrated commit and a new path for the report.

```sh
python3 -E -s -B tests/intake_audit/run.py \
  --repo "$CANDIDATE_REPO" --sha "$INTEGRATED_SHA" \
  --packet "$SEALED_PACKET" --driver "$AUDIT_DRIVER" --report "$NEW_REPORT"
```

The runner verifies the packet bytes and loads committed candidate files in a temporary directory. It records the input state, request and finder observations returned through the public Python interface. It counts calls to the existing Python ranker, including calls through an import alias. A Python audit hook denies socket creation, network lookups and subprocess launches. Use the normal restricted offline test environment for the run.

The JSON report includes the candidate SHA, packet and driver digests, case results and denominators. An edited-input case requires an initial confirmed result before its final phase can pass. The report records call attempts even when a later step raises. Unrepresentable steps carry an explicit reason. All 52 cases must pass for exit status zero. This suite observes what the bridge returns. The rendered page has its own browser checks on [#136](https://github.com/vzhu08/databricks-datathon/issues/136).
