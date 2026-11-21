> This card records the completed matching implementation. The remaining live work is the full nationwide run in [#57](https://github.com/vzhu08/databricks-datathon/issues/57). The [national plan](../implementation/PLAN.md) governs current acceptance.

# ACQ-C01 · Developer C · Identity matching and geographic verification

Task issue: https://github.com/vzhu08/databricks-datathon/issues/5

Owner: Developer C, human; claim the task issue with handle/session. Branch `codex/acq-c-matching`. Own only `research/matching/`, `research/geography/`, `tests/research/matching/`, and `docs/handoffs/ACQ-C01.md`. Read the current board, contract, registry and synthetic fixture. Do not edit A/B collectors, D's ingestion, shared contracts or app ranking.

## Deliverables

1. A repeatable CLI `python -m research.matching.run --base <file> --external <batch> --output-dir <path>` accepting D's documented base adapter shape and contract batches. Start with the shared synthetic base; never infer the actual source column mapping.
2. Deterministic candidate generation using normalized name/alias, identifier namespace, address/phone where available, state/district/PIN and distance. Record rationale and candidate alternatives. Missing/bad coordinates must not eliminate all textual candidates. Document any candidate-search thresholds as retrieval heuristics, not identity probabilities.
3. Automatic confirmation only for an unambiguous same-namespace ID without campus conflicts. All other accepted pilot links require explicit review metadata and reasoning. Preserve unresolved, rejected, and conflicting candidates. Do not collapse same-name campuses or overwrite original base IDs/text.
4. Geographic checks for finite/range/country plausibility, inconsistent addresses/state/PIN, duplicate coordinate clusters and potential centroid/geocoding artifacts. Postal data must be aggregated by PIN with ambiguity retained before joining. Produce proposed corrections alongside original coordinates, never silent replacements.
5. A review workflow and ledger for up to 50 identity candidates (all if fewer), covering easy matches, aliases, ambiguous names, conflicting districts, missing geography, and non-hospital facility types. B supplies campus evidence; C records the final identity review. Report review sampling and match/unmatched/conflict rates with denominators.
6. After the core matches are usable, a bounded Overture building extract for 10 disputed coordinates and 10 clear controls, or all eligible cases if fewer. Use 500 m neighbourhoods of claimed and corroborated coordinates where different, pin the release, preserve source feature IDs and upstream lineage, record distance/containment with metre units and coordinate basis. Overture may reuse OSM/Google/Microsoft; do not double-count those. Null capture time remains unknown. No roof-size clinical score and no fraud inference from an absent footprint.
7. Emit matches, linked evidence, spatial evidence and review rows under v1.0.0. Preserve unlinked B evidence until a match is confirmed. Keep all real records/geometry outside Git; provide synthetic examples only.

## Required tests

Run `python3 -m unittest discover -s tests/research/matching -p 'test_*.py' -v`. Include same name/different campus, aliases, misleading acronym, shared phone/switchboard, conflicting same-source ID, namespace collision, name-only/proximity-only candidate, wrong district/PIN, missing/invalid/swapped coordinates, postal join fanout, stale footprint, no footprint, and OSM-derived building provenance. Ensure unknown remains unknown, and only confirmed coherent links can be attached to supporting evidence.

Verify deterministic reruns, stable IDs, untouched base count/IDs/text, and that a rejected/conflicted match cannot make a service claim verified. Distinguish retrieval coverage from reviewed match precision; report reviewed sample size and all observed false matches, not a confidence percentage from an uncalibrated heuristic.

## Dependencies and handoff

Fixture implementation starts now. Real matching waits for A/B batches and D's actual base mapping. Footprints are lower priority and must not block matching. Any unavailable artifact is named as a blocker while independent work continues.

Open a PR, no merge. Handoff SHA, commands/results, base adapter requirements, snapshot/input IDs, sample-selection rule, reviewed ledger counts, unresolved conflicts, footprint coverage/limitations, artifact paths and interface examples. D must be able to validate/import the outputs; B must be able to audit the recorded campus reasoning.
