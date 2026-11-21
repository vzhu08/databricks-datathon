# Hospital routing and storm-surge demo

## Ownership and delivery

Oliver owns integration and model decisions. The user makes executive decisions in Oliver's main chat. Vincent runs data acquisition and refinement and distributes work in that lane. Andrew owns all UI and UX design and implementation. Ayush has one short, nonblocking replay check. Work and results are recorded on the [team board](OWNERSHIP.md) and [integration issue](https://github.com/vzhu08/databricks-datathon/issues/40). Oliver makes the final call on every merge, revert, branch retirement and release, including data changes. Each orchestrator has one five-minute board checker on their own account, through November 22, 2026 at 12:30 p.m. Eastern unless the user changes it.

| Owner | Deliverable |
| --- | --- |
| [Oliver](https://github.com/vzhu08/databricks-datathon/issues/87) | Eligibility, fixed weights, model evaluation, allocator, offline seeded replay and stable event fixture. Supply Andrew's first fixture before completing the learned-model comparison. |
| [Vincent](https://github.com/vzhu08/databricks-datathon/issues/88) | Versioned campus/service evidence, source coverage, resource units and uncertainty. Assign data work and recommend reviewed PRs to Oliver. |
| [Andrew](https://github.com/vzhu08/databricks-datathon/issues/89) | All product UI and UX, synchronized map comparison, replay controls, capacity display, decision explanations, accessibility and offline judging flow. |
| [Ayush](https://github.com/vzhu08/databricks-datathon/issues/90) | Watch one playable run and give one short clarity report on the detour, resource and simulated capacity. |

## Finder

A request specifies a service, origin, urgency, required capabilities and optional preferences. Begin with dialysis, MRI and trauma care. Preserve the [campus and evidence rules](SERVICE_STATUS.md). A reviewed onsite service at its named campus can qualify. External or cross-campus evidence needs a confirmed link. Missing, conflicting, expired and referral-only evidence cannot establish an affirmative onsite option. Show unresolved leads separately. Service and urgency come from the referral request.

| Urgency | Shorter travel | Recent service evidence | Independent corroboration | Preferred tools |
| --- | ---: | ---: | ---: | ---: |
| Routine | 45% | 25% | 15% | 15% |
| Time-sensitive | 65% | 15% | 10% | 10% |
| Highest | 80% | 10% | 5% | 5% |

Scale travel against the request's budget using one comparable metric per search. Prefer road time by mode when available, otherwise label straight-line kilometres. Use a 24-month half-life for the age of an applicable service observation and compare 12 and 36 months in sensitivity checks. Give credit for at most two additional independent source families. Copies of one statement count once. Required equipment is an eligibility condition. Score requested optional tools by the fraction documented and redistribute that weight when no optional tools are requested. Return up to three options with their travel, evidence date, availability and explanation. The weights are demo hypotheses.

## Data for ranking and capacity

The frozen 10,088 records have 9,970 with paired coordinates, 9,947 with capability text, 9,218 with procedure text, 7,683 with equipment text, 3,546 with a page-update value, 3,633 with a doctor count and 2,520 with reported facility-wide capacity. In the frozen screen 1,047 records mention dialysis, 947 MRI and 923 trauma care. Service-claim date, campus and source family carry more information than a repeated term or a webpage refresh. [Frozen input](https://github.com/vzhu08/databricks-datathon/issues/36#issuecomment-7069028113) · [Service screen](https://github.com/vzhu08/databricks-datathon/issues/58#issuecomment-7069189930)

Record campus, service, specific resource, unit, quantity, observation time, reporting period, capacity type, source, reuse basis and snapshot version. Distinguish installation, functional equipment, staffed slots, occupancy and availability. Prefer timestamped service-specific slots; use observed machines and throughput for scenario ranges. Where appropriate calibrate size-based ranges against known campuses, evaluate held-out error, and retain unknown where the range performs poorly. Preserve the nationwide data denominator. All operational inputs, origins and requests in the public demonstration are synthetic.

- Himachal Pradesh's centre-level dialysis report gives machines and delivered sessions in March 2024. [Public report](https://nhm.hp.gov.in/storage/app/media/uploaded-files/PMNDP%202023-24.pdf)
- Maharashtra's MRI inventory includes grouped institutions and reported zeros. [Public inventory](https://dmer.maharashtra.gov.in/english/list-of-hospitals-with-ct-mri-facilities/)
- Kerala's teaching-hospital records provide named campuses, beds and volumes. [Hospital statistics](https://spb.kerala.gov.in/economic-review/ER2025/appendix/6211.html)
- Delhi's ICU census provides dated occupancy and directs users to confirm occupancy before transfer. [Census](https://vmmc-sjh.mohfw.gov.in/status-of-icu-beds)

## Jaipur-area storm scenario

Use six fictional campuses, several synthetic origins and a seeded wave of already-triaged requests. Both policies receive identical arrivals, travel times and resource updates and see only information available at decision time. Compare nearest eligible first with urgency- and scarcity-aware assignment. A bounded detour limits extra travel versus the fastest feasible campus. Protect the last shared resource only when an eligible alternative has usable capacity within the current request's detour and time limits. High-urgency requests get zero added travel solely for capacity preservation. Distinct services compete only when they use the same staff, machine, bed or other modeled resource in the same time window.

Demonstrate an initial routine dialysis request that can use A in eight minutes or B in twelve. A owns the last reachable slot for the requested monitored service. B can take the routine request. Later, show an urgent request that needs A. Replay with no subsequent specialist request to show the four-minute cost when the reserve yields no benefit. Overload should leave requests visible with reasons. Replay a resource loss, unavailable capacity, reversed arrivals and configurable detour caps of 0, 5, 10 and 15 minutes. Travel times and capacities are scenario values.

Provide an offline fixture and CLI. Include a schema version, seed, synthetic-data label, campus and origin coordinates, requests, clock, policies, assignment events, metrics, resource usage before and after, estimated travel and decision reasons. Andrew consumes the replay outputs in a synchronized comparison with pause, step, replay, labels and an accessible table. The demo should explain who traveled farther, how much farther, the exact resource it freed, and whether the resource was used.

## Evaluation and release

1. With the same eligibility and frozen inputs, compare nearest eligible, fixed weights, and a transparent regularized pairwise preference model. Target 60 blinded scenarios, 20 per service, and two independent team judgments per scenario. Permit ties and insufficient evidence. Keep related campuses and source copies within a single split and hold out geography where feasible.
2. Keep fixed weights as the demo default unless learned weights improve held-out first-choice acceptability over both baselines with a positive paired 95% confidence interval and zero eligibility violations. Report top-three acceptability, abstention and travel burden by geography and urgency. Keep the independent national audit sealed.
3. Fix the scorer when comparing allocation policies. Report requests served, urgent requests within their windows, unassigned reasons, extra travel and capacity violations. Require zero overbooking, zero assignments to ineligible campuses and deterministic replay from a seed. Compare actual replay outputs without hand-authoring a favorable result.
4. Deliver the synthetic offline demo first. Report source acquisition, private warehouse rehearsal, live publication and organizer submission as distinct statuses. Oliver reviews exact PR revisions and retires released integrated branches after confirming current owners and remote tips.

