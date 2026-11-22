# Patient runtime v1

Use `from patient_intake import PatientIntakeService, POLICY_VERSION` from a server with the deployed app/ on its import path. The policy edition is `patient-runtime.v1`. Each patient opens an O-owned encounter after local storage consent. Construct the service with a server-owned interview reducer, optional provider adapter, optional approved `provider_identity=(provider_id, provider_version)`, optional handoff callable, and an encounter turn limit (default 8, maximum 32). Keep any stateful provider adapter local to its encounter. The default configuration makes zero provider calls. An identity identifies a particular approved adapter and edition; operator review of intended use, terms and configuration precedes injecting it. If the clinical content edition is unknown, record that limitation with the release.

| Service operation | Effect |
| --- | --- |
| `view(handle)` | Return the current display record. O enforces ownership and expiry. |
| `edit(handle, expected_revision, *, description, context)` | Start a new interview from the current patient statement and context. Clear transmission consent, prior continuation, derived results and confirmation. Preserve used turns. |
| `consent(handle, expected_revision, *, granted)` | Record explicit transmission consent against the server's policy and provider identity, clearing prior results and continuation. Reset/delete the encounter via O to erase local storage. |
| `assess(handle, expected_revision)` | Explicitly submit the current interview. Reserve an in-progress revision and charge a turn before adapter invocation. On reply, commit only against that same revision. |
| `answer(handle, expected_revision, *, question_id, answers)` | Consume the current question's opaque `issuance_id` as question_id. Q validates choices, evidence review or text against the stored question. The next provider turn requires an explicit assess action. |
| `confirm(handle, expected_revision)` | Return an opaque in-process receipt for this completed result. The revision stays current. |
| `navigate(handle, expected_revision, *, confirmation)` | Verify current consent, completed state and receipt, call P with the server-owned handle, revision and assessment, then recheck revision. Absence of a destination integration yields `{"state":"no_reviewed_destination"}`. |

The view keys are `revision, policy_version, state, provider_id, provider_version, consent, reason, question, guidance, urgency, uncertainty, possible_causes, next_step`. States are draft, assessment_in_progress, awaiting_clarification, urgent, completed, unsupported and provider_unavailable. Urgent guidance is displayed immediately. Render plain text. Discard all previous display, confirmation and destination results on a stale/expired handle, an edit or a failed action. Only display the latest server revision. Never expose the full encounter snapshot, continuation, result secret or receipt to the browser. A provider suggestion and a navigation confirmation have separate provenance from a clinician order. Provider disclosure and vendor-side deletion require separate operational controls.

## Module interfaces

- O's opaque handle implements detached `read() -> (revision, dict)` and atomic `replace(expected_revision, dict) -> revision`. An empty dict means a new encounter. Server state holds `state`, `assessment` (current public view), `interview`, `calls_used`, `continuation`, `consent_identity`, `consent_policy` and `result_secret`. O enforces a hard session TTL. Discard a failed or superseded provider completion.
- Q implements `start(description, context)`, `prepare_question(provider_question, interview_data)`, `answer(interview_data, server_question, question_id, answers)` and `has_unresolved_evidence(interview_data) -> bool`. Data is JSON-safe and held server-side. Questions carry id, kind, prompt and options. Each option has id and label. Kinds are single, multiple, text and evidence_review. Evidence review includes the proposed concept_id, label, presence, temporality and source_ref. The patient's confirmation, uncertainty or disagreement remains distinct from what the provider extracted. M assigns a new issuance ID on every presentation, stores the prepared question privately and displays only Q's `question_view(server_question)` projection. Ordinary completion requires Q's explicit finding that evidence is resolved.
- N implements `assess(interview_data, *, continuation=None)`. Each reply has exact state, provider_id and provider_version. Awaiting clarification adds question and an optional bounded server-only continuation. Completed and urgent replies include plain-text guidance and uncertainty, possible_causes (a list of labels), a normalized urgency code and next_step. The disposition table below defines all accepted combinations. Unavailable or unsupported adds an optional bounded reason code. Adapter errors and uninterpretable payloads withhold prior output. N owns physical HTTP-call budgets, timeouts and concurrency. M owns the lifetime turn budget and performs no automatic retry. Consent revocation and edits invalidate outstanding replies via revision checks. Already dispatched work cannot be recalled.
- P receives `handoff(handle, expected_revision, assessment)`. It verifies current state and independent authority/destination evidence. No submitted patient checkbox, ready flag, origin, order or provider-proposed procedure enters this interface. A route or provider lookup can require separate consent, destination evidence and budget. Failure to find an eligible destination leaves the completed assessment available.

MGP's optional disabled adapter supports only its documented mappings. Free-text survey startup, correcting extracted evidence, approved patient populations and independently verified orders require their own integrations and reviews. When a requested function cannot be represented, return unsupported or provider_unavailable. Engineering tests use invented provider exchanges. A public deployment requires approved hosting, transport security, session isolation, secrets, vendor agreements, privacy controls and clinical review.


## Normalized provider dispositions

| Provider urgency | Required state | Required next_step |
| --- | --- | --- |
| `self_care` | completed | null |
| `consultation` | completed | `{"kind":"consultation","specialty_code":null}` or the same shape with a specialty code |
| `consultation_24` | urgent | null |
| `emergency` | urgent | null |
| `emergency_ambulance` | urgent | null |

The adapter maps its own structured disposition to these codes. The runtime checks the exact combination before persisting the assessment. An unknown code, a contradictory state or next step, or an extra clinical-stop field invalidates the reply and clears previous guidance and confirmation. Only completed dispositions can enter the separately authorized handoff.
