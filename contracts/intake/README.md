# Fictional intake v1

The [schema](v1.schema.json) describes three distinct JSON records. The visitor supplies the payload. The application selects the matching scenario from its trusted, versioned fictional catalogue. The Python engine returns the assessment. Keep scenario and confirmation arguments outside the visitor-controlled payload.

```python
from app.intake import SCHEMA_VERSION, assess_intake, confirm_intake

payload = {"schema_version": SCHEMA_VERSION, "mode": "synthetic",
           "scenario_id": scenario["scenario_id"], "input_revision": 0, "answers": {}}
assessment = assess_intake(payload, scenario=scenario)
# Supply only closed question IDs and answer IDs from the question catalogue.
# After a visitor accepts a displayed confirmation_required summary:
receipt = confirm_intake(payload, scenario=scenario)
confirmed = assess_intake(payload, scenario=scenario, confirmation=receipt)
```

The scenario contains its own edition, fixed narrative, structured concern, nullable service, structured prior clinician plan and known answers. A missing answer differs from an explicit unknown, a conflict and a negative. Narrative is for display. A scenario with an existing dialysis plan, MRI referral or assessed injury can produce an eligible request only for its corresponding service. The demo restricts ordinary search to adult, nonpregnant scenarios. These are fictional scenario rules. They provide no diagnosis or clinical validation.

| State | Meaning and next step |
| --- | --- |
| `invalid_input` | A malformed or incompatible input withheld the request. |
| `emergency_escalation` | Show N's primary warning message and end ordinary intake immediately. |
| `more_information_needed` | Ask the one listed question, or show the unresolved answers when none is listed. |
| `unsupported_care_need` | The population or concern falls outside the demo. |
| `clinician_assessment_needed` | The story lacks a validated simulated referral, treatment plan or assessment. |
| `confirmation_required` | Display the validated care summary. The visitor can now confirm this edition of it. |
| `ready` | A current in-process receipt and a fresh evaluation authorize P to use the request. |

Every state carries `request: null` except ready. Only the last two states have a care summary. Required and preferred capabilities and urgency come from O's validated plan. P supplies the date, candidates, travel inputs and existing ranker gates. A ready request may yield zero eligible campuses.

The first message ID is primary. Use M's `assessment_catalogue()` for state messages, M reasons, concern labels and the fictional-policy reference. N supplies warning messages/reasons, rules and clinical-reference entries through its catalogues. O supplies referral reasons and authority labels through `referral_catalogue()`. Q supplies questions and finite answer labels through `question_catalogue()`. Each concern identifies the reason and source of its demonstration rationale. The policy reference resolves to this document.

**Admitting an edition.** Before an eligible referral can produce a care summary, the engine checks the complete scenario against the [release manifest](reviewed_scenarios.json). The manifest is part of the reviewed application release and is loaded once at import. Visitor answers and receipts cannot add an entry. A missing, unreadable or invalid manifest withholds ordinary search. Reported structured warnings still escalate first.

To propose a new edition, supply its exact nine-field script with its ID and version. Compare the fixed story with each known warning and context answer, the concern category, the requested service and the clinician's plan. Leave unstated facts unanswered. Record who reviewed the script, its source revision and the comparison on the task issue. Revise the edition when changing its contents. From the reviewed script, compute the SHA-256 of `json.dumps(script, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")` and submit that pin for release review. Each ID/version pair has one digest. Review the script alongside the pin before accepting it. A matching digest proves the entire script equals the reviewed edition. The quality of the initial story-to-facts comparison depends on the reviewer.

The seven demo pins use R's published catalogue at `c852647`. The shipped CLI, UI builder and Python finder use the same approval check. Independent test releases can install a manifest for their own separately reviewed, frozen control scripts before starting the process. Record the test manifest and its provenance separately. Mutations run against those original pins. The engine has no per-call switch or automatic enrollment. A changed edition returns `invalid_input` with reason `intake_scenario_unreviewed` at the point it would otherwise become confirmable.

**Confirmation.** The fingerprint is SHA-256 of UTF-8 JSON for the array containing the policy version, complete payload and complete trusted scenario, in that order. Serialization uses sorted keys, compact separators and ASCII escaping. Source object order is immaterial. The policy version covers all three leaf policies and must change with a behavioral policy revision. A receipt is an opaque Python object associated with the fingerprint in its issuing process. A copied record, fingerprint, boolean or serialized assessment cannot confirm. Refusal to issue a receipt raises `ValueError`. An edited input retains its own assessment state and the supplied old receipt is stale. An unrecognized receipt is invalid. For invalid envelopes some identifying fields may be null.

**Offline rendering.** The build uses the visitor answer count as the revision and walks Q's finite choices. For each eligible summary it can issue a real receipt and generate ready and finder records for each P origin. The page pairs records by schema, policy, scenario ID and edition, revision, full fingerprint and care summary, and clears selection and previous results on every edit. A session that tracks edit history increments its revision even on an edit back to an earlier value. Re-evaluate failures from the current inputs. The bundle's measured state count, longest path and 5,000-state ceiling are checked by Q/R and Andrew.

**Verification.** From the repository root with the N/O/Q modules integrated, run `python3 -m unittest discover -s tests/intake -p test_assessment.py`. The engine has no provider, warehouse, routing or network dependency.
