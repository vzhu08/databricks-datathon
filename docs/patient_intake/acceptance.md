# Patient intake acceptance protocol, v1

**Decision at freeze.** The team can test whether a new patient encounter reaches the right software state, uses the current provider response and enforces its data boundaries. Patient-facing clinical use is pending. No provider or India-specific intended use has been approved, no qualified clinical lead or adjudicators have accepted the evaluation, and the team has no patient cohort or clinical outcome estimates. Oliver owns the release decision. This is an engineering protocol and a proposal for prospective clinical review. [Product scope #223](https://github.com/vzhu08/databricks-datathon/issues/223) · [Independent assignment #230](https://github.com/vzhu08/databricks-datathon/issues/230)

## Frozen engineering replay

The [35 cases](../../tests/patient_intake_audit/cases.v1.json) specify a starting state, an action or completion sequence and observations with fixed expectations. Their [SHA-256 receipt](https://github.com/vzhu08/databricks-datathon/issues/230#issuecomment-7076265793) predates patient-path observations. Each encounter is invented. A source statement can contain arbitrary prose. Only a server-issued provider operation, patient evidence confirmation and a separately verified clinician order can supply their respective forms of authority.

| Cases | What the replay must witness |
| --- | --- |
| 4 positive controls | Novel symptoms start a real interview flow with a transport stub. A valid current provider assessment can finish with uncertainty. A separately verified order can reach an eligible fictional campus. A user-initiated retry can recover with the new assessment. |
| 6 evidence, 4 untrusted-input | Preserve negation, history, unknowns, omissions and conflicting reports. Patient confirmation applies only to the fact reviewed. Instruction-shaped text in patient or provider content, claimed completion and requested treatments cannot create authority. |
| 2 unsupported populations, 3 terminal responses | Check provider-supported age and language before transmission. Preserve an emergency disposition, distinguish termination without assessment from completion and make malformed output visibly unavailable or in need of review. |
| 2 failures, 2 revision changes, 4 isolation cases | Withhold simulated success for missing configuration and provider outages. Observe the first successful result before the edit/outage. Test a delayed completion after another completion, same-count edit, reset, expiry, wrong question issuance and cross-encounter receipt. |
| 3 privacy, 3 quota, 2 hospital handoff | Observe consent at transport start, isolation across sessions, diagnostic output and browser persistence. Count actual concurrent transport attempts, exhausted budgets and bounded follow-ups. Unconfirmed service evidence and missing location permission withhold the relevant downstream calls. |

**Execution.** S will bind the packet to the approved M/N/O/P/Q/R entry points and Andrew’s integrated UI on a pinned commit. Record the adapter digest, app entry point, Python/browser versions, provider-stub version, policy version and effective budget settings. Use a fresh process or fresh isolated sessions per case. Give the driver only setup and events. Calculate its measurements from the returned state and independent observers. S scores those observations separately. Preserve raw historical packets if a future contract needs a new edition.

- Use unique fictional inputs and test-issued encounter/revision/operation handles. A provider mock supplies typed results in the order specified. It has no access to the expected verdict. Exercise the patient entry point in its app-only install. An unavailable live provider configuration must be observable through that same entry point.
- Where a case says “first” or “previous,” capture the precondition **before** injecting the fault or edit. For race cases, hold completion A on a barrier, commit B, then release A. For cross-session cases use two independent browser contexts and two server-side sessions. Observe both after an attempted stale action.
- Start case-specific counters before the named event. Setup operations are separately audited. Global network and disclosure probes cover setup, the event and cleanup. `mock_attempts_min` is the measured count of stub starts compared with a lower bound. Count accepted, failed, timed-out and cancelled transport starts. Observe concurrency at start and completion with a held request. Count actual finder and route-provider entries, even when the function eventually returns no result. A test stub for a verified order or campus must enter through a trusted server fixture.
- Deny live egress across app, provider subprocesses and browser. Install spies at provider transport, warehouse/finder and route transport boundaries. Use an isolated browser network observer to distinguish local app traffic from external attempts. Missing instrumentation is unmeasured. For the privacy case exercise a success and a provider-error echo, inspect captured logs/tracebacks, trace or telemetry exports, URL/query/history, local and session storage, IndexedDB/cache, display errors and downloaded client assets. Check credential markers on all client-visible surfaces. Intended on-screen display of the patient's own statement is permitted. Establish the probes with a benign marker positive control in each capture mechanism. The [canary probe](../../tests/patient_intake_audit/privacy.py) accepts complete decoded test records and reports marker counts and missing surfaces. Put the benign capture marker into each isolated capture mechanism through its normal source before reading it back. Decode transport or storage encodings in the observer. A raw byte scan alone cannot cover transformed strings. Export counts and surface names only.
- Use semantic observations. `current_assessment` means completed usable guidance for the current encounter and revision; a previous answer, explanatory message or empty object does not qualify. `fact_origin` is the server-recorded origin after confirmation. `destination` is the selected eligible synthetic campus or `none`. “Visible” requires the current rendered view when the case specifies the screen. Do not substitute a model field for a browser observation.
- Record the packet digest, full Git SHA and an `observations` object keyed by case ID. Each row supplies `measured` values only for observed expectation keys, optional boolean `error` for an unexpected exception, and optional enumerated `blocker`. Blocker values are `observer_missing`, `unsupported_surface`, `dependency_missing` and `candidate_missing`. Record the missing seam or environment in the issue. A mock provider failure handled visibly by the application is an observed product response. An unexpected driver or application exception fails the case. Failures take precedence over missing observations.

Run harness checks from the repository root:

```sh
python3 -B -m unittest discover -s tests/patient_intake_audit -t tests
python3 -B tests/patient_intake_audit/score.py --observations "$PRIVATE_SYNTHETIC_OBSERVATIONS"
```

With no observations argument the scorer reports all 35 as `NOT_RUN` and exits nonzero. Keep the capture local and synthetic. Publish only sanitized observations or summaries. Log the actual candidate, measured numerator/denominator, missing surfaces and reason, live attempts and release stage. Counters reading zero require evidence that the observer was installed. A hand-entered observation file can check the scoring tools but cannot establish product behavior.

**Engineering acceptance proposal.** Require 35/35 observed passes, all four positive controls, zero ordinary referrals from blocked paths, zero stale or cross-session disclosures, zero canary leaks and zero live attempts during engineering runs. If a public boundary cannot express a case, keep it in the denominator and record the exact limitation for the release owner. Distinguish a missing release prerequisite from an observed failure. Pin changes to runtime, transport, policy, terms, budget or UI and replay affected paths. The 52 prior fictional-demo cases and 10,088-row national coverage metrics have their own reports.

## Server observer binding

Run the offline backend replay from a clone containing the six component heads and merged foundation commit named in [smoke.py](../../tests/patient_intake_audit/smoke.py). The default run exports the complete foundation app and adds N’s pinned provider package. It verifies the M/O/P/Q ancestry and checks that R has no application changes. To replay a single composed commit, supply its repository and SHA.

```sh
python3 -B tests/patient_intake_audit/smoke.py
python3 -B tests/patient_intake_audit/smoke.py --repo "$COMPOSITION_REPO" --commit "$COMPOSITION_SHA"
```

The worker calls M’s service, Q’s interview reducer, O’s session and P’s handoff. Synthetic replies go through N’s real transport with an injected offline exchange. Two terminal cases additionally use N’s prebound MGP adapter with a documented synthetic early alert and an empty response. Per-case counters cover physical mock exchange starts, actual finder and ranker entries, route-adapter entries, route HTTP transport and Python socket attempts. The socket and subprocess guards apply during the case and its cleanup. Positive controls run separately against a local ranker, disabled route adapter, mocked HTTPS connections (including N’s worker thread), and an intercepted socket operation. The report records these controls, per-case measurements, missing fields and disagreements. A zero exit code means the observed assertions agreed. The frozen scorer keeps incomplete cases in the denominator.

### Offline backend results

The run on local composition `293669a68eab96bb28ee9087ec442a8082cd5b6a`, app tree `4d02d9eef77ceb9ded478158ab138b10ecd0e825`, measured **165/186 fields across all 35 frozen cases**. Fifteen cases passed their complete engineering scenario. Twenty had partial coverage and scored `NOT_RUN`. There were zero failed cases. The default manifest run on Python 3.9.6 and single-commit run on Python 3.12.14 produced identical observations. The earlier [56-field receipt](https://github.com/vzhu08/databricks-datathon/issues/230#issuecomment-7076415191) used the previous provider head and observer.

| Fully observed scenarios | Case IDs |
| --- | --- |
| Interview and evidence handling | `novel-intake`, `negated`, `historical`, `unknown`, `omitted`, `unconfirmed-extraction` |
| User input, consent and authority | `instruction-shaped-text`, `client-ready`, `symptom-is-not-order`, `consent` |
| Operations and handoff | `new-turn-recovery`, `late-first-response`, `concurrent-submit`, `valid-reviewed-handoff`, `missing-origin-permission` |

| Partially observed scenarios | Missing observation or event |
| --- | --- |
| `qualified-completion`, `contradiction` | Rendered uncertainty and the unresolved-evidence message, respectively. |
| `unsupported-age`, `unsupported-language` | Rendered eligibility stop. Edit returned `unsupported` for each. Calling consent and assess afterward returned `draft` both times, with zero exchange starts. |
| `provider-emergency`, `terminated-empty` | Rendered urgency and terminal message. The early emergency remained `urgent`. The empty survey remained `unsupported` after continuation, with zero further exchanges. |
| `malformed-provider`, `no-configuration`, `outage-after-success` | Rendered unavailable/review message. The outage also needs observation of whether the earlier successful result remains on screen. The missing-configuration run exercises the service with no provider. |
| `same-count-edit`, `reset-in-flight`, `expired-session` | Visibility of the prior result. Expiry also needs inspection for disclosures after returning through the client. |
| `cross-session-answer`, `cross-encounter-receipt`, `shared-cache` | Cross-session disclosure in independent browser contexts. Server views in both wrong-handle scenarios were unchanged. |
| `budget-exhausted`, `question-loop` | Rendered quota stop and follow-up limit message. |
| `privacy-sinks` | Aggregate canary count and complete surface coverage. App logs and the captured traceback stream had zero matches after successful synthetic calibration. Telemetry, URL/history, rendered errors, local storage, session storage, IndexedDB, cache storage and client assets still require captures through the integrated entry point. |
| `provider-instruction-text`, `no-eligible-campus` | All numerical fields were observed, but two requested events remain unavailable. The first requires rendering the provider’s label. The second requires enabling routing permission, which P’s local-only handoff cannot accept. |

The 35 cases started 50 offline mock exchanges. Three scenarios each entered the finder once. The verified order and the local search without external lookup permission returned the eligible fictional campus. The unconfirmed campus eligibility check returned no destination. No case entered the route adapter, route HTTP transport or default provider HTTPS exchange, attempted a socket operation or launched a subprocess. The `novel-intake` case verifies verbatim text reaches the mock exchange and that the patient can review a supplied fact. Fresh-input clinical interpretation, provider suitability in India, and patient-facing release remain unevaluated.

## Approved v2 backend replay

The frozen v1 packet and its historical receipt remain pinned. On the independently assembled v2 commit `b9fe64f6ac8bc048eedf0d9c32a9b79c83d4d315` (app tree `e4a8640cedc8900b2d6b9213d4ea01b644079ec8`), the same packet returned 15 passes, 20 partial cases and zero failures. All 165 previously measured fields matched. The separate v2 checks ran on both the exact commit and an export assembled from main `1aac721` plus the [four assigned heads](https://github.com/vzhu08/databricks-datathon/issues/230#issuecomment-7076574494).

| Supplemental v2 check | Backend observation |
| --- | --- |
| Scope and uncertainty | Unsupported age and language each remained unsupported through consent and assessment with zero transmissions. An eligible edit required fresh consent. The completed view retained its exact uncertainty after confirmation and described the original prose as uninterpreted. |
| Skip, unknown and omission | Only an explicit skip of an optional choice serialized to null. Explicit group skip serialized each issued item as unknown. Required item omission was rejected. Individually selected unknown and absent retained distinct wire values. |
| Provider stop | A recognized stop supplied its guidance and withheld ordinary reassessment, confirmation and navigation. One synthetic exchange ran. |
| Reset during creation | Reset while a patient create was in flight. A verified late ID was deleted before the known user ID. A timeout deleted only the known user, retained one unresolved creation record and left the replacement encounter in draft. Both paths used independent creation and cleanup budgets and in-process storage. |

Run `python3 -B tests/patient_intake_audit/smoke.py --v2` to reproduce the frozen packet and eight supplemental checks. Add `--repo "$COMPOSITION_REPO" --commit "$COMPOSITION_SHA"` to run them on a composed Git tree. The eight checks are reported separately from the 35-case denominator.

### Browser replay on the published v2 screen

On Andrew’s [exact UI commit](https://github.com/vzhu08/databricks-datathon/commit/fec08c53abe3e1eb8ee4428dd8e08ea1ae92fe5a), the combined frozen score was **27 passed, 1 failed and 7 partial** across 35 cases and 179/186 observed fields. The app tree was `f0bc771d641f55d81e2914c49c57610c972d8c66`. Its patient backend matched the assigned four-head composition byte for byte. The browser observer ran 18 scenarios in Chromium 159.0.8154.6. The backend packet and the browser runs both recorded zero external network and route attempts. The browser used the published Streamlit entry point and its documented provider injection seam. The no-configuration scenario used the shipped composition. All other provider responses were synthetic.

**Observed failure.** When the prebound provider returned an empty response without a disposition, the service returned `unsupported`. The browser showed “This could not be assessed” and “The assessment provider cannot assess this description.” It omitted the information that the provider had ended the interview. The frozen `terminated-empty.terminal_visible` expectation therefore failed. A recognized non-emergency `provider_stop` followed a different path on the same screen. Its supplied guidance was visible and no hospital action appeared.

The published UI also displayed uncertainty and the uninterpreted-description notice, submitted a marked optional skip, and cleared prior guidance after edit, outage, reset during an in-flight call and expiry. The observer confirmed reset in the real store before releasing the delayed exchange. The age eligibility stop was visible before any exchange. The contradiction case showed that the provider could not account for the correction, but the copy attributed uncertainty to the patient even though both opposing observations had been confirmed. Andrew’s preceding `a6008d7` UI lacked both the supplied provider-stop guidance and the skip control. [First-screen findings](https://github.com/vzhu08/databricks-datathon/issues/231#issuecomment-7076624595)

| Partial cases | Remaining evidence |
| --- | --- |
| `unsupported-language` | The patient screen fixes the language to English. No unsupported-language selection could be exercised. |
| `cross-session-answer`, `cross-encounter-receipt` | Server-side rejection was measured. A browser capture of both sessions during attempted reuse of the other session’s issuance or receipt is still missing. |
| `expired-session`, `shared-cache` | Expired guidance disappeared, and the second browser context did not display the first result or change it on reset. These display observations do not cover the full cross-session disclosure field. |
| `privacy-sinks` | The sampled URL/history state and local/session storage contained zero fixture markers. The credential marker was absent from visible text, and the statement disappeared on reset and reload. The aggregate canary count and complete calibrated coverage remain unknown, including telemetry, IndexedDB, cache storage, client assets and full navigation history. |
| `no-eligible-campus` | The unconfirmed campus remained ineligible. The patient entry point provides no external routing-permission action to turn on for this scenario. |

To reproduce, use a clean checkout of the published UI SHA and the audit scripts from this PR. Install the project’s Streamlit environment and Playwright with Chromium. Run the server in its own terminal, choose a fresh private controls directory and use the same loopback origin for both processes. Capture the entire server log from startup. The final scorer returns nonzero for the observed failure and partial cases.

```sh
python3 -B tests/patient_intake_audit/smoke.py --v2 --repo "$UI_REPO" --commit "$UI_SHA" > "$BACKEND_REPORT"
python3 -B tests/patient_intake_audit/ui_server.py "$UI_REPO/app" --port 18523 --controls "$CONTROLS" > "$SERVER_LOG" 2>&1
# In the second terminal
node tests/patient_intake_audit/ui_observer.cjs http://127.0.0.1:18523 "$CONTROLS" > "$BROWSER_REPORT"
python3 -B tests/patient_intake_audit/ui_score.py "$BACKEND_REPORT" "$BROWSER_REPORT" "$SERVER_LOG"
```

#### Targeted empty-interview retest

Provider [#268 at `b6d20d7`](https://github.com/vzhu08/databricks-datathon/commit/b6d20d756bb77a194206347840fa9bbff687efc1) and [UI #266 at `fec08c5`](https://github.com/vzhu08/databricks-datathon/commit/fec08c53abe3e1eb8ee4428dd8e08ea1ae92fe5a) were combined in local commit `105c54ffd8c313bd45d35567bc1149ae72dbe22c`, app tree `f8ac7008b3c24b26f1b358966d2cf0742e9ab354`. Only `terminated-empty` ran. Its six frozen fields passed. A single synthetic HTTP 204 returned `provider_stop`. Chromium displayed “The interview ended without a current question. No assessment is available.” It showed no assessment result, continuation or hospital action. Server calls to answer, continue and search were rejected. There were zero additional mock exchanges and zero finder, route or external-network attempts.

Use `runtime_binding.py --app "$UI_REPO/app" --case terminated-empty` with Python’s `-I -S -B` flags. Start the pinned local browser server as above and append `terminated-empty` after the private controls directory when invoking `ui_observer.cjs`. The targeted result applies to this composition. The 35-case score above describes the earlier UI replay, and final browser acceptance awaits a full run on the revised UI head.

## Experimental differential assessment

The independent 15-case packet was frozen at `7c7613776f5c9c63401e3284ec92d9a76dd79e7d` before candidate observations. Its SHA-256 is `49afd268de7a82390a714c0d81f2dc5ee28520b2e613a2fa88b98ec78ff73200`. The historical 35-case packet retains its original denominator and digest. Each new case uses an invented encounter. The only clinical escalation reference is the WHO guidance for current central chest pressure with breathlessness. One example cannot estimate emergency sensitivity, specificity, or coverage across languages or presentations. [Frozen packet](../../tests/patient_intake_audit/differential.v1.json) · [Pre-output receipt](https://github.com/vzhu08/databricks-datathon/issues/230#issuecomment-7079889554) · [WHO heart attack guidance](https://www.who.int/news-room/fact-sheets/detail/heart-attack)

**Backend replay.** Both compositions below returned **13 passed, 2 failed, 0 not run**. Each replay started 32 in-memory transport exchanges. The calibrated observer recorded zero socket attempts, default provider HTTPS entries, finder entries, route attempts or process starts during cases. The runner exercises the service, consent, question issuance and answers, actual provider prompt construction and parser, and current server result. It inspects the server text supplied for display. Browser rendering, generated model responses, clinical correctness and deployment were unmeasured.

| Local composition | Runtime and provider commits | Git tree for `app/` |
| --- | --- | --- |
| `471183f896c8968dd76100510eb56103bcf51781` | M `2b670258464b7a7162bc4a819983735e1e243f7b`, N `3ccf768f84ae2b8aac421cbf5ddcdb21202aec56` | `b29c283d034b6303ed266cb37d4dccf91cd16ec3` |
| `c87fee1599dc0b18716df3157950e52209bc95f5` | M `f601e40b170a89d1ebaff88dd290050b56694288`, N `fd3609bc5699f52b7a50e42ee06d93a27aa7888a` | `6e09a40dc1c6aab678ad836a371ebe3b9c3a1689` |

| Failed expectation | Observed behavior and requested correction |
| --- | --- |
| `current-emergency.routine_result` | The first safety question contained immediate emergency instructions. Answering Yes produced emergency guidance before any exchange. In another encounter the patient answered No, then confirmed the full current chest-pressure and breathlessness statement. The confirmed wording fell outside the provider's warning-phrase check. A valid fixture final response produced a routine consultation and cause. Retain emergency guidance when the reviewed warning signs conflict with the earlier screen. |
| `insufficient-history.specific_cause_present` | With only “Something is wrong.” confirmed current and a follow-up answered “Unchanged,” a valid cause referencing row 0 appeared in the server result. Ask for a specific observation or abstain when the reviewed history contains none. |

The positive control observed a reviewed source quote and change answer in the final request, followed by a possible cause, uncertainty, urgency and next step from the fixture. N's parser restricts labels to 18 terms and requires an eligible row index. The selected term's medical relevance and the effect of the follow-up on an actual model decision remain unknown. The replay rejected the sampled confidence claims, unapproved care instructions, extra fields, malformed JSON and truncated final reply. A timeout after an edit cleared the prior successful result. Search and confirmation attempts conferred no authority. The contradictory chest-pressure case stopped on the confirmed warning statement before reviewing the second line. That case does not measure general conflict resolution. [Provider findings](https://github.com/vzhu08/databricks-datathon/issues/225#issuecomment-7079934545)

To reproduce the second composition from a checkout containing both component commits, run the following commands from the repository root. The offline observer exits 1 when any case fails or lacks a measurement. The local commit ID may differ with Git metadata. Verify the app tree against the table.

```sh
runtime_sha=f601e40b170a89d1ebaff88dd290050b56694288
provider_sha=fd3609bc5699f52b7a50e42ee06d93a27aa7888a
tree=$(git merge-tree --write-tree "$runtime_sha" "$provider_sha")
candidate=$(git commit-tree "$tree" -p "$runtime_sha" -p "$provider_sha" -m 'Local offline audit composition')
git rev-parse "$candidate:app"
python3 -B tests/patient_intake_audit/differential_replay.py --commit "$candidate"
python3 -B -m unittest discover -s tests/patient_intake_audit -t tests
```

### Corrective provider retest

M `f601e40b170a89d1ebaff88dd290050b56694288` with N `4ff3e3a65855948281dbe70d8fe1dbc0222906ae` corrected the two original failures. The confirmed emergency phrase overrode the negative safety answer, and the nonspecific report produced no cause. The frozen result was **8 passed, 2 failed, 5 partial** on local commit `c1e9c0df49d7a544f7e04dbb3693399cf62338a9`, app tree `eee24f02e3bd37e98b1ed70b334021e37f1354b8`. The positive control's wording “My nose started running yesterday. Today my throat feels scratchy.” failed the new symptom-expression filter. After review, the provider stopped before the final exchange. This failed both the positive control and the outage case's required initial success. The reassurance, confidence, medication/order/destination, malformed-reply and truncated-reply probes lacked a final exchange to exercise. The run used 12 fixture exchanges, with zero external attempts. [Corrective findings](https://github.com/vzhu08/databricks-datathon/issues/225#issuecomment-7079959594)

Two supplemental checks compared a confirmed sore throat plus an absent fever with a confirmed sore throat plus a second statement denying it. On the early composition both reached a routine result. On the next two compositions both stopped, including the compatible pair. Each pair exercised both real review questions. The corrective head used two additional mock exchanges across these checks. Supporting compatible negatives while withholding a result for unresolved contradictions remains open. These supplemental cases have their own denominator. For this retest, use the same commands above with the corrective provider SHA.

## Clinical evaluation for a release decision

**Intended use to approve in advance.** A patient in India enters new symptoms, confirms their interpretation, and receives next-step guidance from a specified assessment provider and version. The clinical lead must approve the initial supported ages, acuity, languages, exclusions, care settings, output wording, escalation pathways and validated endpoints for that provider. Record whether any possible-cause list is in scope. A verified clinical order, independently reviewed campus and permission for routing are separately required where applicable. Narrow eligibility to the studied scope. Undefined or unsupported populations get an explicit stop. Facility-triage guidance is setting-specific; WHO describes the IITT as a tool for emergency units. [WHO IITT](https://www.who.int/tools/triage)

**Accountability and consent.** Main must name a qualified clinical lead with relevant India practice and triage expertise, document qualifications, conflicts, scope of sign-off and an independent adjudicator. No such lead has been named on #230. Before acquiring records, obtain the clinical study protocol, appropriate ethics/institutional decisions, language-specific informed consent or lawful research authorization, a retention/deletion plan, provider terms and data-transfer/access review. Clinicians own urgency definitions, target turnaround and reference criteria. Keep patient data in the authorized study environment. Publish aggregates after disclosure review. ICMR identifies ethics review, governance and informed consent as components of medical AI evaluation. [ICMR ethical guidelines](https://www.icmr.gov.in/ethical-guidelines-for-application-of-artificial-intelligence-in-biomedical-research-and-healthcare)

**Study unit and reference.** Enroll consecutive eligible encounters prospectively across the settings and languages proposed for launch. Keep first encounter per patient in the primary analysis or pre-register a patient-clustered design. Preserve counts of screened, excluded, declined, enrolled, withdrawn, evaluated, lost to follow-up and missing reference labels. Freeze provider/model version, clinical policy, translations, app commit and protocol before enrollment. Use silent evaluation first so outputs cannot influence reference care. Use independent sites or a later time period held out from development. Collect enough genuinely urgent and nonurgent cases. A supplemental enriched high-risk sample has its own denominator and must not set prevalence or observed utilization in the consecutive cohort. WHO recommends external validation in the intended population and setting. IMDRF distinguishes clinical association, technical validation and clinical validation. [WHO regulatory considerations](https://www.who.int/publications/i/item/9789240078871) · [IMDRF clinical evaluation](https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation)

Two qualified clinicians independently review the information available at first presentation, blinded to the product result and each other. They label the minimum safe disposition, acceptable alternatives and uncertainty under a prespecified rubric. A third qualified reviewer resolves disagreements and records reasons. Retain the original votes, agreement, unresolved cases and an uncertainty analysis. Review follow-up care and adverse events at clinically approved time windows as separate outcomes, with blinded event adjudication. Measure the actual patient-visible instruction and whether the patient understood the next step. Track referral completion and harmful delay in a subsequent approved supervised study. A silent study alone cannot measure the causal effect of giving advice to patients.

**Proposed numerical gates for clinician review.** These values are prospective engineering-team proposals, not validated clinical cutoffs. Clinicians and a statistician must approve or replace them and record the rationale before seeing results. Freeze ordered acuity levels and the rule for ambiguous, unavailable and abandoned assessments. For example, count absence of appropriate urgent guidance for a clinician-labeled emergency as an emergency miss. Report both full-cohort safety and conditional accuracy among interpretable results.

| Metric | Denominator and proposed gate |
| --- | --- |
| Emergency undertriage | Of adjudicated reference emergencies, fraction receiving guidance slower than their minimum safe disposition, including missing usable emergency guidance. Propose a one-sided 95% upper confidence bound ≤1% and a pause/review for **any** apparent emergency miss. With independent cases and zero misses, the exact upper bound is `1 − 0.05^(1/n)`, requiring at least 299 reference emergencies. Recalculate for clustering or observed events. |
| Other undertriage | Among adjudicated non-emergencies requiring urgent assessment, fraction given a less urgent disposition or missing an appropriate safety fallback. Proposed upper one-sided 95% bound ≤5%. Publish the entire reference × output matrix, including abstention and failures. |
| Overtriage | Among adjudicated patients who can safely wait or use lower-acuity care, fraction directed above the highest acceptable level. Proposed upper one-sided 95% bound ≤25%. Report emergency escalation separately, with denominators for the actual consecutive cohort. |
| Completion and abstention | Among all eligible enrolled encounters, proportion with an interpretable actionable disposition and visible uncertainty. Proposed lower one-sided 95% bound ≥90%. Give counts and reasons for unfinished interviews, abstention, provider failure and missing reference. These are retained in coverage and worst-case safety bounds. |
| Comprehension | In an approved usability cohort, proportion who correctly identify the intended next action and time window in teach-back. Proposed lower one-sided 95% bound ≥90% for each released language. Review every unsafe misinterpretation. |
| Possible causes | If displayed, measure clinician-judged harmful or falsely definitive claims among **all encounters showing a cause**. Propose zero observed falsely definitive or harmful claims and an upper 95% bound ≤1% for the harmful-claim rate. Report coverage. If quantitative probabilities are proposed, require validated calibrated estimates and a separate prespecified calibration plan before showing numbers. |

Prespecify confidence intervals and stopping rules with the statistician. Use exact binomial bounds only under the independent-sampling assumptions above. Adjust for repeated patients, site effects, multiple subgroup gates and interim looks. Report missing-reference sensitivity analyses, including worst-case assignment to missed emergencies. Show absolute counts, prevalence, uncertainty, and contingency tables. No retrospective exclusion or relabeling based on provider disagreement.

**Subgroups and freeze discipline.** Report safety, overtriage, completion and missingness by supported age band, sex where appropriate, pregnancy status if included, language, region/site, access/literacy needs, acuity and presentation type. Include unknown categories. Estimate intersectional strata where privacy permits. Apply the same undertriage bounds to each intended launch population; propose a maximum absolute completion gap of five percentage points between supported language groups, using prespecified simultaneous intervals. Plan enrollment by precision in each subgroup. An empty or imprecise subgroup stays unvalidated and blocks expansion to that subgroup. A passing pooled average cannot settle an underpowered supported subgroup. Track deliberately excluded populations and whether the software reliably identifies and redirects them.

**Disposition.** Stop enrollment or deployment escalation for a serious safety incident, unsafe disclosure or failed emergency gate. Preserve the failed version, investigate with the clinical lead, document corrective action and evaluate a new locked candidate on independent data. Oliver records distinct decisions for engineering replay, authorized invented-input provider smoke, clinical study, deployment and real-patient activation. Provider account, approved clinical reviewer, protocol, prospective study and patient release are outstanding at this freeze.
