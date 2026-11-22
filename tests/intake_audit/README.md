# Independent intake audit

At corrected candidate `7afb714927346e5f26db4cd57740da75b20e4f62`, the same trusted-story conflict returned `invalid_input`, no care request, no finder result and zero ranker calls. All three valid controls continued to rank the expected service. Of the 52 frozen cases, 49 passed and three remain unrepresentable. There were zero state mismatches or unsafe recommendations among the 49 measured cases, zero forbidden ranker calls among the 46 expected-blocked final phases, and zero external attempts. The report records each observation and the separate test manifest used for the three pristine controls. [Independent result](results/7afb714.independent.json)

The published manifest contained exactly R’s seven reviewed editions. The seven journeys matched their expected states and results across 18 transitions, including five ranked and 13 blocked transitions. All three shipped fixture and call-count checks passed with zero external attempts. [Published release result](results/7afb714.shipped.json)

## Original failure

The independent replay at `e281752cca1673b199cfa35748d5cdde2a810724` found one routine MRI recommendation that the frozen policy expected to withhold. Of 52 fictional cases, 49 executed, 48 passed, one failed and three could not run through the public interface. The [case report](results/e281752.v1.json) contains every observation. The [packet receipt](https://github.com/vzhu08/databricks-datathon/issues/133#issuecomment-7074486311) and [adapter receipt](https://github.com/vzhu08/databricks-datathon/issues/133#issuecomment-7074681128) predate candidate execution.

| Observation | Result |
| --- | --- |
| State outside the allowed set | 1 of 49 measured final states |
| Unsafe recommendation | 1 of 49 measured final states |
| Ranker invoked when final routing should be blocked | 1 of 46 expected-blocked final phases |
| External calls attempted | 0 in 49 executed cases, including six preliminary success phases. Module loading also had zero attempts. |
| Valid controls | All three reached the intended fictional service with one ranker call each. |
| Stale result after edit or failure | All six first produced a valid MRI result, then returned no current finder result with zero further ranker calls. |
| Confirmation checks | The absent receipt, both client-forgery cases and the cross-scenario receipt withheld the request. |

All three violations came from `conflict_text_disagrees`. The trusted script stated “Current chest pain,” while the structured answer for that warning was `no`. The engine allowed summary confirmation and returned a routine MRI request. The bridge called the ranker once and returned fictional destinations. This case exercises the Python API with a contradictory script. Visitor input on the offline page is limited to predefined stories and choices. The owning issue tracks the scenario consistency fix and replay. [Regression handoff](https://github.com/vzhu08/databricks-datathon/issues/127#issuecomment-7074730995)

Three cases retain `NOT_RUN`. A mapping cannot retain two different entries for the same key. The public receipt exposes no operation to edit its revision or policy field. The separate two-source disagreement, changed inputs and changed engine policy cases did execute.

## Reproduce

From the audit checkout, run the harness checks with Python 3.9 or newer.

```sh
python3 -B -m unittest discover -s tests/intake_audit -t tests
```

Supply a local repository containing the named candidate commit and a fresh report path. The following command reproduces the historical nonzero exit. The runner writes all 52 outcomes before exiting.

```sh
python3 -E -s -B tests/intake_audit/run.py \
  --repo "$CANDIDATE_REPO" --sha e281752cca1673b199cfa35748d5cdde2a810724 \
  --packet tests/intake_audit/frozen/cases.v1.json \
  --driver tests/intake_audit/frozen/driver_v1.py --report "$NEW_REPORT"
```

The runner loads committed candidate files into a temporary directory. It measures what the public bridge returns and counts calls to the existing Python ranker, including calls through an import alias. A Python audit hook denies socket creation, network lookups and subprocess launches. The state-name translation and allowed outcome sets are explicit in the scorer and frozen packet. The packet contains deliberately selected software challenges for the fictional demo. Browser rendering has its own checks on [#136](https://github.com/vzhu08/databricks-datathon/issues/136).

## Replay with reviewed editions

For a candidate implementing [the scenario integrity fix](https://github.com/vzhu08/databricks-datathon/issues/203#issuecomment-7074765380), add `--independent-controls` to the audit command. The runner installs the [fixed three-entry manifest](frozen/control_editions.v1.json) in the temporary candidate tree before importing the public engine. Each report identifies the published and installed manifest digests. Run the seven shipped journeys separately with the published manifest and their own expected outcomes.

S prepared the three entries before replay from the pristine edition-1 control descriptions. Each uses the fixed story “Fictional adult for a software demonstration.” with empty script-supplied answers. Its matching simulated authority, routine urgency and explicit empty capability lists are bound to the same scenario ID and version. The complete canonical scenario determines its digest. The audit runner installs the same file for the entire replay. Challenge steps cannot add entries.


To reproduce the corrected candidate results, use two fresh report paths. The independent runner exits 1 because three cases remain `NOT_RUN`. The JSON summary distinguishes them from failures.

```sh
python3 -E -s -B tests/intake_audit/run.py \
  --repo "$CANDIDATE_REPO" --sha 7afb714927346e5f26db4cd57740da75b20e4f62 \
  --packet tests/intake_audit/frozen/cases.v1.json \
  --driver tests/intake_audit/frozen/driver_v1.py --independent-controls --report "$INDEPENDENT_REPORT"
python3 -E -s -B tests/intake_audit/run_shipped.py \
  --repo "$CANDIDATE_REPO" --sha 7afb714927346e5f26db4cd57740da75b20e4f62 --report "$SHIPPED_REPORT"
```
