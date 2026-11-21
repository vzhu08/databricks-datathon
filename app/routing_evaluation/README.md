# Offline comparison of routing preferences

The comparator tests destination acceptability as judged by the project reviewers. It uses the versioned urgency ranker to build one eligible campus pool per scenario. Nearest, fixed and learned methods all rank that same pool. The tool does not infer diagnoses, clinical outcomes, service eligibility or real-time vacancies.

Run from the repository root. Python's standard library is sufficient.

```sh
python3 -m app.routing_evaluation
python3 -m app.routing_evaluation --synthetic-smoke
python3 -m app.routing_evaluation --example-bundle
python3 -m app.routing_evaluation --bundle path/to/private-frozen-preferences.json
python3 -m unittest discover -s tests/routing_evaluation
```

With no bundle, the result is `pending_human_labels`, and the fixed policy stays selected. The smoke command runs a fully labeled synthetic interface check. Its output always has status `synthetic_smoke_only`. Keep real reviews and individual predictions in authorized private storage.

## Data collection and split

Freeze the input snapshots, scenarios, campus pools, split and leakage groups **before** collecting preferences or inspecting test results. Withhold all model ranks, scores and model-generated ordering from both reviewers. Present randomly ordered campus evidence plus the requested service, specified urgency, required/optional tools, travel estimates and as-of date. Two distinct people label independently. An untouched accreditation holdout remains reserved. Store an immutable hash for the reviewed bundle through the existing private evidence handoff.

Use `--example-bundle` for a complete invented example. The top-level fields are `schema_version: routing-preferences-v1`, an immutable `freeze_id`, `label_basis` (`human_blinded` or `synthetic`), optional boolean `geography_holdout`, and `scenarios`. The label-basis declaration must reflect how judgments were collected. Software cannot authenticate reviewer independence.

Each scenario supplies an ID, train/test split, geography, scenario group, independent cluster ID, request, candidates and reviews. The request and candidate evidence follow `app.ranking.urgency.rank_campuses`. Every candidate also supplies its canonical campus group and a list of upstream evidence/copy group IDs. These must identify the actual related records: use the same group for twins, repeated campuses, shared evidence or syndicated documents. Do not assign row-unique labels to duplicated material. Connected scenarios and sources, including ineligible candidates, must stay in one cluster and split. Declare `geography_holdout: true` to require disjoint train and test geographies. Freeze an as-of cutoff in the supplied snapshots.

A ballot includes a distinct `reviewer_id`, an explicit `acceptable_ids` list, and zero or more pair judgments of the form `{"left":"id-a","right":"id-b","choice":"left"}`. The alternatives for choice are `right`, `tie` and `abstain`. A reviewer can accept more than one destination. An empty acceptable list means none were judged acceptable. A null list records insufficient information. All judged destinations must belong to the common eligible pool. No clinical reviewer is assumed. Input bundles with partial reviews report incomplete coverage.

## Model and comparison

The learned model fits four nonnegative coefficients per urgency group. These cover normalized travel, assertion recency, independent corroboration and requested optional capabilities, reusing the ranker's factors. Training minimizes pairwise logistic loss with fixed L2 coefficient 0.1 toward the published fixed weights, normalized to fractions. Deterministic projected gradient descent uses 250 steps of 0.5. Ties have target 0.5; abstentions supply no target. At least two reviewers must contribute usable pair comparisons for a training scenario to count. Each scenario, and each contributing reviewer within it, receives equal total weight. The held-out acceptability labels and pair judgments never enter fitting. Scores concern preferences. They are not probabilities of treatment success.

The primary metric is average held-out first-choice acceptability, averaging reviewers within each scenario. Report the paired learned-minus-nearest and learned-minus-fixed differences. Use 2,000 bootstrap draws, seed 17, sampling whole independent test clusters with replacement. Fewer than two scorable clusters yields no interval. Report coverage, explicit review abstentions, no eligible destination, top-three acceptability and slices by geography, urgency and service. Top-one travel means retain their original units. The output includes all coefficients and aggregate source/split checks, as well as private per-case choices.

For selection, use blinded human labels with at least 20 reviewed scenarios per service, coverage of all three services and priorities on test, directional training data for every urgency, and at least ten scorable independent test clusters. The 95% lower bound for the paired gain must exceed zero against both comparators, with zero eligibility violations. Small pilots still return descriptive scores and the fixed default. A passing offline gate is a research comparison; it does not authorize deployment or a patient-facing claim.
